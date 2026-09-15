"""Installing a standalone build through the launcher.

Two sources are supported:

* **an archive** (zip/7z/rar/tar) — unpacked into a directory the user chose; a single
  top-level folder is collapsed so the game root ends up directly in the destination;
* **a Windows installer** (``setup.exe`` / ``*.exe``) — started through the same runner the game
  would use (PortProton/Proton/Wine). The installer shows its own destination page: the user
  points it to the chosen directory, which Wine sees as ``Z:\\...``. CordonIX waits for the
  installer to exit and then looks for the game tree in the destination.

Either way the destination receives :data:`cleanup.BUILD_MARKER` so a later profile deletion
can offer to remove the build too. The marker is written only into directories CordonIX
created or that were empty — an existing game folder is never claimed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import cleanup, util, winerun, xray
from . import engine as engine_mod
from . import mods as mods_mod
from .errors import CordonError
from .paths import write_marker

ProgressCallback = Callable[[str], None] | None


class InstallError(CordonError):
    pass


@dataclass(slots=True)
class BuildInstallResult:
    #: directory to use as ``Profile.game_path``
    game_root: str
    #: where files were written (== game_root unless the tree is nested)
    destination: str
    source: str
    kind: str  # archive | installer
    executables: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def windows_only(self) -> bool:
        return bool(self.executables) and not any(
            os.path.isfile(os.path.join(self.game_root, sub, "xr_3da")) for sub in engine_mod.BINARY_SUBDIRS
        )


def is_installer(path: str) -> bool:
    return path.lower().endswith((".exe", ".msi"))


def is_build_source(path: str) -> bool:
    return os.path.isfile(path) and (is_installer(path) or mods_mod.is_archive(path))


def prepare_destination(destination: str) -> str:
    """Create *destination* (or accept an empty/marked one) and claim it with the marker."""
    destination = util.norm(os.path.expanduser(destination))
    if not destination or destination == "/" or destination == util.norm(os.path.expanduser("~")):
        raise InstallError("укажите отдельный каталог для сборки (не домашний каталог и не корень)")
    if os.path.isfile(destination):
        raise InstallError(f"это файл, а не каталог: {destination}")
    if os.path.isdir(destination):
        entries = [name for name in util.entry_names(destination) if name != cleanup.BUILD_MARKER]
        if entries and not cleanup.is_managed_build(destination):
            raise InstallError(
                f"каталог не пуст и не создавался лаунчером: {destination}\n"
                "Выберите пустой или новый каталог, чтобы лаунчер мог безопасно им управлять."
            )
    util.ensure_dir(destination)
    write_marker(destination, cleanup.BUILD_MARKER, f"cordonix build\ncreated={int(time.time())}\n")
    return destination


# --------------------------------------------------------------------------- archive
def install_from_archive(archive: str, destination: str, *, progress: ProgressCallback = None) -> BuildInstallResult:
    archive = util.norm(archive)
    if not mods_mod.is_archive(archive):
        raise InstallError(f"не архив: {archive}")
    destination = prepare_destination(destination)
    mods_mod.extract_archive(archive, destination, progress=progress)
    _collapse_single_root(destination)
    game_root = locate_game_root(destination)
    result = BuildInstallResult(game_root=game_root, destination=destination, source=archive, kind="archive")
    _finish(result, progress)
    return result


def _collapse_single_root(destination: str) -> None:
    """``Build.zip`` → ``Build/…``: move that one folder's content up (the marker is ignored)."""
    entries = [name for name in util.entry_names(destination) if name != cleanup.BUILD_MARKER]
    if len(entries) != 1:
        return
    single = os.path.join(destination, entries[0])
    if not os.path.isdir(single) or os.path.islink(single):
        return
    if any(os.path.exists(os.path.join(destination, name)) for name in util.entry_names(single)):
        return
    for name in util.entry_names(single):
        shutil.move(os.path.join(single, name), os.path.join(destination, name))
    os.rmdir(single)


# --------------------------------------------------------------------------- installer
def install_from_installer(
    installer: str,
    destination: str,
    *,
    runner_preference: str = "auto",
    portproton_path: str = "",
    progress: ProgressCallback = None,
    runner_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> BuildInstallResult:
    """Run a Windows installer through PortProton/Proton/Wine and wait for it to finish."""
    installer = util.norm(installer)
    if not os.path.isfile(installer):
        raise InstallError(f"установщик не найден: {installer}")
    destination = prepare_destination(destination)
    compat_data = os.path.join(destination, ".cordonix-installer-prefix")
    util.ensure_dir(compat_data)
    runner = winerun.find_runner(preferred=runner_preference, portproton_path=portproton_path, compat_data=compat_data)
    if runner is None:
        raise InstallError(
            "для запуска установщика нужен PortProton, Proton или Wine — ни один не найден. "
            "Распакуйте сборку вручную или установите PortProton."
        )
    env = os.environ.copy()
    env.update(runner.env)
    if runner.kind == winerun.RUNNER_KIND_WINE:
        env.setdefault("WINEPREFIX", compat_data)
    argv = list(runner.argv) + [installer]
    if runner.args_via_ppdb:
        # PortProton reads settings from <exe>.ppdb; make sure a stale one does not inject flags
        winerun.write_ppdb_launch_parameters(installer, [], {})
    windows_dest = winerun.to_windows_path(destination)
    if progress:
        progress(f"Запуск установщика через {runner.label}. В установщике укажите каталог: {windows_dest}")
    try:
        process = runner_factory(argv, cwd=os.path.dirname(installer), env=env)
        code = process.wait()
    except OSError as exc:
        raise InstallError(f"не удалось запустить установщик: {exc}") from exc
    if runner.args_via_ppdb and os.path.isfile(installer + ".ppdb"):
        try:
            os.remove(installer + ".ppdb")
        except OSError:
            pass
    notes = [f"установщик завершился с кодом {code}"]
    try:
        game_root = locate_game_root(destination)
    except InstallError as exc:
        raise InstallError(
            f"{exc}\nУстановщик работал через {runner.label}; каталог назначения в нём должен быть {windows_dest}. "
            "Если игра установлена в другое место, создайте профиль вручную, указав тот каталог."
        ) from exc
    result = BuildInstallResult(game_root=game_root, destination=destination, source=installer, kind="installer", notes=notes)
    _finish(result, progress)
    return result


# --------------------------------------------------------------------------- shared
def locate_game_root(destination: str, *, max_depth: int = 3) -> str:
    """Find the directory holding ``gamedata``/``fsgame.ltx``/archives/engine below *destination*."""
    best = ""
    for dirpath, dirnames, _filenames in os.walk(destination):
        depth = os.path.relpath(dirpath, destination).count(os.sep) + (0 if dirpath == destination else 1)
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if depth > max_depth:
            dirnames[:] = []
            continue
        if xray.is_xray_tree(dirpath) or engine_mod.candidate_windows_executables(dirpath):
            best = dirpath
            break
    if not best:
        raise InstallError(f"в {destination} не найдено игровое дерево (gamedata, fsgame.ltx или xrEngine.exe)")
    return util.norm(best)


def _finish(result: BuildInstallResult, progress: ProgressCallback) -> None:
    result.executables = engine_mod.candidate_windows_executables(result.game_root)
    if not result.executables and not any(
        os.path.isfile(os.path.join(result.game_root, sub, "xr_3da")) for sub in engine_mod.BINARY_SUBDIRS
    ):
        result.notes.append("движок в сборке не найден — потребуется системный OpenXRay или указание каталога движка")
    if progress:
        progress(f"Сборка установлена: {result.game_root}")
