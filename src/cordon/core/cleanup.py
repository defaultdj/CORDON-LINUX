"""What a profile leaves behind and how to remove it.

Deleting a profile removes the workspace root and mod storage. Windows builds started through
PortProton/Proton/Wine scatter more: a Proton prefix inside the profile root, ``<exe>.ppdb``
next to the executable, a PortProton prefix in ``~/PortProton/data/prefixes/<NAME>`` and the
shortcuts PortProton may have created. Builds installed *by* CordonIX (``setup.exe`` or an
archive unpacked into a directory of the user's choice) carry :data:`BUILD_MARKER`, so the
build directory itself can be offered for removal too.

The scan never deletes anything; :func:`remove` deletes only items the caller selected, and only
after re-checking that the path is still one of the scanned leftovers.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

from . import engine as engine_mod
from . import util, winerun
from .models import Profile
from .paths import PROFILE_MARKER, AppPaths

#: Written into a build directory CordonIX created itself (see ``install``).
BUILD_MARKER = ".cordonix-build"

KIND_BUILD = "build"
KIND_PROFILE_ROOT = "profile_root"
KIND_MOD_STORAGE = "mod_storage"
KIND_PROTON_PREFIX = "proton_prefix"
KIND_PPDB = "ppdb"
KIND_PORTPROTON_PREFIX = "portproton_prefix"
KIND_PORTPROTON_SHORTCUT = "portproton_shortcut"
KIND_SAVES = "saves"

KIND_LABELS = {
    KIND_BUILD: "Каталог сборки (установлен лаунчером)",
    KIND_PROFILE_ROOT: "Каталог профиля",
    KIND_MOD_STORAGE: "Распакованные моды профиля",
    KIND_PROTON_PREFIX: "Префикс Proton/Wine профиля",
    KIND_PPDB: "Настройки PortProton для .exe (.ppdb)",
    KIND_PORTPROTON_PREFIX: "Префикс PortProton",
    KIND_PORTPROTON_SHORTCUT: "Ярлык PortProton",
    KIND_SAVES: "Сохранения и логи игры",
}


@dataclass(slots=True)
class Leftover:
    kind: str
    path: str
    size: int = -1
    #: shared with other profiles/games — never selected by default
    shared: bool = False
    note: str = ""

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    def describe(self) -> str:
        size = f" ({util.human_size(self.size)})" if self.size >= 0 else ""
        note = f" — {self.note}" if self.note else ""
        return f"{self.label}: {self.path}{size}{note}"


@dataclass(slots=True)
class LeftoverReport:
    items: list[Leftover] = field(default_factory=list)

    def default_selection(self) -> list[Leftover]:
        return [item for item in self.items if not item.shared]

    def to_text(self) -> str:
        if not self.items:
            return "После удаления профиля ничего не осталось."
        return "\n".join(item.describe() for item in self.items)


def tree_size(path: str) -> int:
    total = 0
    if os.path.isfile(path):
        try:
            return os.lstat(path).st_size
        except OSError:
            return -1
    for dirpath, _dirnames, filenames in os.walk(path, onerror=lambda _e: None):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
    return total


def is_managed_build(directory: str) -> bool:
    return bool(directory) and os.path.isfile(os.path.join(directory, BUILD_MARKER))


# --------------------------------------------------------------------------- scan
def scan(profile: Profile, app: AppPaths, *, other_profiles: list[Profile] = (), portproton_path: str = "") -> LeftoverReport:
    """Everything on disk that belongs (or may belong) to *profile*."""
    report = LeftoverReport()
    seen: set[str] = set()

    def add(kind: str, path: str, *, shared: bool = False, note: str = "") -> None:
        if not path:
            return
        path = util.norm(path)
        if path in seen or not os.path.lexists(path):
            return
        seen.add(path)
        report.items.append(Leftover(kind, path, tree_size(path), shared=shared, note=note))

    others = [p for p in other_profiles if p.id != profile.id]
    root = app.profile_root(profile.id, profile.root_path)
    add(KIND_PROTON_PREFIX, os.path.join(root, "proton-prefix"))
    options = profile.wine_options or {}
    custom_prefix = os.path.expanduser(str(options.get("prefix_name") or ""))
    if custom_prefix and os.path.isabs(custom_prefix):
        shared_prefix = any(os.path.expanduser(str((p.wine_options or {}).get("prefix_name") or "")) == custom_prefix for p in others)
        add(KIND_PROTON_PREFIX, custom_prefix, shared=shared_prefix, note="указан в настройках профиля" + (", используется другим профилем" if shared_prefix else ""))
    if os.path.isfile(os.path.join(root, PROFILE_MARKER)):
        add(KIND_PROFILE_ROOT, root)
    elif os.path.isdir(root):
        add(KIND_PROFILE_ROOT, root, shared=True, note="нет маркера CordonIX — каталог не наш, удалять вручную")
    storage = app.mod_storage(profile.id, profile.mod_storage_path)
    if os.path.isdir(storage) and os.path.isfile(os.path.join(storage, ".cordon-mod-storage")):
        add(KIND_MOD_STORAGE, storage)

    game = util.norm(profile.game_path) if profile.game_path else ""
    engine_root = util.norm(profile.engine_path) if profile.engine_path else ""
    for exe in engine_mod.candidate_windows_executables(game, engine_root):
        add(KIND_PPDB, exe + ".ppdb")

    pp = winerun.find_portproton(portproton_path)
    pp_root = winerun.portproton_root(pp.path if pp else "")
    if pp_root:
        _scan_portproton(report, add, profile, others, pp_root, game, engine_root)

    for directory in (game, engine_root):
        if directory and is_managed_build(directory) and not _used_by(others, directory):
            add(KIND_BUILD, directory, note="создан лаунчером при установке сборки")
        elif directory and is_managed_build(directory):
            add(KIND_BUILD, directory, shared=True, note="используется другим профилем")
    return report


def _used_by(profiles: list[Profile], directory: str) -> bool:
    return any(util.norm(p.game_path or "") == directory or util.norm(p.engine_path or "") == directory for p in profiles)


def _scan_portproton(report, add, profile: Profile, others: list[Profile], pp_root: str, game: str, engine_root: str) -> None:
    options = profile.wine_options or {}
    prefix_name = str(options.get("prefix_name") or "").strip() or "DEFAULT"
    prefix_dir = winerun.portproton_prefix_dir(pp_root, prefix_name)
    others_prefixes = {str((p.wine_options or {}).get("prefix_name") or "").strip() or "DEFAULT" for p in others}
    if prefix_name == "DEFAULT":
        add(KIND_PORTPROTON_PREFIX, prefix_dir, shared=True, note="общий префикс DEFAULT всех игр PortProton — лучше не трогать")
    else:
        shared = prefix_name in others_prefixes
        add(KIND_PORTPROTON_PREFIX, prefix_dir, shared=shared, note="используется другим профилем" if shared else "")
    # saves the engine writes inside the prefix (Documents) — only when it is not the shared one
    if prefix_name != "DEFAULT" and os.path.isdir(prefix_dir):
        for docs in _prefix_documents(prefix_dir):
            add(KIND_SAVES, docs, shared=True, note="внутри префикса; удалится вместе с ним")

    # shortcuts: PortProton names them after the game directory / exe stem
    exes = engine_mod.candidate_windows_executables(game, engine_root)
    names = {os.path.splitext(os.path.basename(exe))[0] for exe in exes}
    if game:
        names.add(os.path.basename(game.rstrip("/")))
    for name in sorted(names):
        for candidate in (
            os.path.join(pp_root, f"{name}.desktop"),
            os.path.expanduser(f"~/.local/share/applications/{name}.desktop"),
        ):
            if os.path.isfile(candidate) and _desktop_points_to(candidate, exes):
                add(KIND_PORTPROTON_SHORTCUT, candidate)
        icon = os.path.join(pp_root, "data", "img", f"{name}.png")
        if os.path.isfile(icon):
            add(KIND_PORTPROTON_SHORTCUT, icon, note="иконка ярлыка")


def _prefix_documents(prefix_dir: str) -> list[str]:
    found = []
    users = os.path.join(prefix_dir, "drive_c", "users")
    for user in util.entry_names(users):
        for sub in ("Documents", "My Documents"):
            for game_dir in ("S.T.A.L.K.E.R. - Call of Pripyat", "S.T.A.L.K.E.R. - Clear Sky", "stalker-shoc", "S.T.A.L.K.E.R. - Shadow of Chernobyl"):
                path = os.path.join(users, user, sub, game_dir)
                if os.path.isdir(path):
                    found.append(path)
    return found


def _desktop_points_to(desktop: str, exes: list[str]) -> bool:
    if not exes:
        return False
    text = util.read_text(desktop, errors="replace")
    return any(exe in text for exe in exes)


# --------------------------------------------------------------------------- remove
def remove(items: list[Leftover], report: LeftoverReport) -> list[str]:
    """Delete the selected leftovers; returns human-readable errors (empty on success)."""
    allowed = {item.path for item in report.items}
    errors: list[str] = []
    # longest paths first so nested entries (Documents inside a prefix) go before their parent
    for item in sorted(items, key=lambda entry: len(entry.path), reverse=True):
        if item.path not in allowed:
            errors.append(f"{item.path}: не входит в список найденных остатков — пропущено")
            continue
        if not os.path.lexists(item.path):
            continue
        try:
            if os.path.isdir(item.path) and not os.path.islink(item.path):
                shutil.rmtree(item.path)
            else:
                os.remove(item.path)
        except OSError as exc:
            errors.append(f"{item.path}: {exc.strerror or exc}")
    return errors
