"""Running Windows builds (``.exe``) through PortProton, Proton or Wine.

CordonIX prefers a native OpenXRay, but most standalone S.T.A.L.K.E.R. builds ship their own
patched ``xrEngine.exe`` plus DLLs and simply cannot run natively. For those the launcher hands
the executable to a Windows compatibility layer:

* **PortProton** (linux-gaming.ru) — the most common choice on Russian-speaking Linux desktops;
  it manages its own prefixes, DXVK, runtime and per-``.exe`` settings (``<exe>.ppdb``).
  Engine arguments must go through ``LAUNCH_PARAMETERS`` inside that ``.ppdb`` file: the
  command line of ``start.sh`` accepts the ``.exe`` path only, everything after it is ignored.
* **Proton** (Steam / Proton GE) — needs ``STEAM_COMPAT_DATA_PATH`` (the prefix) and
  ``STEAM_COMPAT_CLIENT_INSTALL_PATH`` (the Steam root) or the ``proton`` script refuses to
  start. Arguments are passed on the command line after the ``.exe``.
* **Wine** — plain ``wine <exe> <args>``; ``WINEPREFIX`` is left to the environment.

Paths handed to the Windows process (``-fsltx``, ``-overlaypath``) are Unix paths, so they are
translated to ``Z:\\...`` – Wine's default drive mapping for the host root.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
from dataclasses import dataclass, field

from . import util

RUNNER_KIND_PORTPROTON = "portproton"
RUNNER_KIND_PROTON = "proton"
RUNNER_KIND_WINE = "wine"

#: Where PortProton keeps its ``start.sh`` when installed by the official script or a package.
PORTPROTON_ROOTS = (
    "~/PortProton",
    "~/.local/share/PortWINE/PortProton",
    "~/.var/app/ru.linux_gaming.PortProton/data/PortProton",
)
PORTPROTON_FLATPAK_ID = "ru.linux_gaming.PortProton"

STEAM_ROOTS = (
    "~/.steam/root",
    "~/.steam/steam",
    "~/.local/share/Steam",
    "~/.var/app/com.valvesoftware.Steam/data/Steam",
)


@dataclass(slots=True)
class WindowsRunner:
    kind: str
    path: str
    argv: list[str] = field(default_factory=list)
    label: str = ""
    #: extra environment the runner needs (Proton: STEAM_COMPAT_* variables)
    env: dict[str, str] = field(default_factory=dict)
    #: True when arguments cannot be appended to the command line (PortProton → .ppdb)
    args_via_ppdb: bool = False

    def describe(self) -> str:
        return f"{self.label or self.kind}: {self.path}"


# ---------------------------------------------------------------------------- paths
def to_windows_path(path: str) -> str:
    """Translate an absolute Unix path into Wine's ``Z:`` drive notation."""
    if not os.path.isabs(path):
        return path
    return "Z:" + util.norm(path).replace("/", "\\")


def _executable(candidate: str) -> bool:
    return bool(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK)


# ---------------------------------------------------------------------------- discovery
def find_portproton(preferred: str = "") -> WindowsRunner | None:
    """Locate PortProton: an explicit path, ``portproton`` in ``$PATH``, the usual roots or Flatpak."""
    candidates: list[str] = []
    if preferred:
        expanded = os.path.expanduser(preferred)
        if os.path.isdir(expanded):
            candidates += [
                os.path.join(expanded, "data", "scripts", "start.sh"),
                os.path.join(expanded, "PortProton"),
            ]
        else:
            candidates.append(expanded)
    which = shutil.which("portproton")
    if which:
        candidates.append(which)
    for root in PORTPROTON_ROOTS:
        base = os.path.expanduser(root)
        candidates.append(os.path.join(base, "data", "scripts", "start.sh"))
    for candidate in candidates:
        if _executable(candidate):
            return WindowsRunner(
                kind=RUNNER_KIND_PORTPROTON,
                path=util.norm(candidate),
                argv=[util.norm(candidate), "cli", "--launch"],
                label="PortProton",
                args_via_ppdb=True,
            )
    flatpak = shutil.which("flatpak")
    if flatpak and _flatpak_has(flatpak, PORTPROTON_FLATPAK_ID):
        return WindowsRunner(
            kind=RUNNER_KIND_PORTPROTON,
            path=flatpak,
            argv=[flatpak, "run", PORTPROTON_FLATPAK_ID, "cli", "--launch"],
            label="PortProton (Flatpak)",
            args_via_ppdb=True,
        )
    return None


def _flatpak_has(flatpak: str, app_id: str) -> bool:
    for base in ("~/.local/share/flatpak", "/var/lib/flatpak"):
        if os.path.isdir(os.path.join(os.path.expanduser(base), "app", app_id)):
            return True
    return False


def _natural_key(name: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _steam_root() -> str:
    for root in STEAM_ROOTS:
        base = os.path.expanduser(root)
        if os.path.isdir(os.path.join(base, "steamapps")) or os.path.isfile(os.path.join(base, "steam.sh")):
            return util.norm(os.path.realpath(base))
    return ""


def find_proton(compat_data: str) -> WindowsRunner | None:
    """Locate Proton (``$PATH``, Steam library, compatibilitytools.d) and set up its environment."""
    candidates: list[str] = []
    for cmd in ("proton", "proton-ge", "proton-ge-custom"):
        found = shutil.which(cmd)
        if found:
            candidates.append(found)
    steam_root = _steam_root()
    search_dirs = []
    if steam_root:
        search_dirs += [
            os.path.join(steam_root, "compatibilitytools.d"),
            os.path.join(steam_root, "steamapps", "common"),
        ]
    search_dirs += ["/usr/share/steam/compatibilitytools.d", os.path.expanduser("~/.local/share/Steam/compatibilitytools.d")]
    for directory in search_dirs:
        if not os.path.isdir(directory):
            continue
        # newest first: "Proton 9.0" > "Proton 8.0", "GE-Proton9-20" > "GE-Proton9-5"
        for name in sorted(util.entry_names(directory), key=_natural_key, reverse=True):
            if "proton" in name.lower():
                candidates.append(os.path.join(directory, name, "proton"))
    for candidate in candidates:
        if not _executable(candidate):
            continue
        env = {
            "STEAM_COMPAT_DATA_PATH": compat_data,
            "STEAM_COMPAT_CLIENT_INSTALL_PATH": steam_root or os.path.expanduser("~/.local/share/Steam"),
        }
        return WindowsRunner(
            kind=RUNNER_KIND_PROTON,
            path=util.norm(candidate),
            argv=[util.norm(candidate), "run"],
            label="Proton",
            env=env,
        )
    return None


def find_wine() -> WindowsRunner | None:
    for cmd in ("wine64", "wine"):
        found = shutil.which(cmd)
        if found:
            return WindowsRunner(kind=RUNNER_KIND_WINE, path=found, argv=[found], label="Wine")
    return None


def find_runner(*, preferred: str = "auto", portproton_path: str = "", compat_data: str = "") -> WindowsRunner | None:
    """Pick the runner for a Windows build.

    ``preferred`` is ``auto`` (PortProton → Proton → Wine), ``portproton``, ``proton`` or ``wine``.
    ``compat_data`` is the per-profile Proton prefix directory (created by the caller).
    """
    finders = {
        RUNNER_KIND_PORTPROTON: lambda: find_portproton(portproton_path),
        RUNNER_KIND_PROTON: lambda: find_proton(compat_data),
        RUNNER_KIND_WINE: find_wine,
    }
    if preferred in finders:
        return finders[preferred]()
    for kind in (RUNNER_KIND_PORTPROTON, RUNNER_KIND_PROTON, RUNNER_KIND_WINE):
        runner = finders[kind]()
        if runner is not None:
            return runner
    return None


def available_runners(*, portproton_path: str = "") -> list[WindowsRunner]:
    """Everything ``cordon tools`` / preflight can report."""
    found = []
    for runner in (find_portproton(portproton_path), find_proton(""), find_wine()):
        if runner is not None:
            found.append(runner)
    return found


# ---------------------------------------------------------------------------- tuning options
#: Windows version names accepted by ``winecfg -v`` / ``PW_WINDOWS_VER``.
WINDOWS_VERSIONS = ("7", "8.1", "10", "11")

#: Wine/Proton dists PortProton ships or downloads into ``data/dist``; the two aliases resolve to
#: the versions pinned in PortProton's ``var`` file.
PORTPROTON_WINE_ALIASES = ("PROTON_LG", "WINE_LG")


def option_env(options: dict[str, object], kind: str) -> dict[str, str]:
    """Environment for Proton/Wine derived from ``Profile.wine_options``.

    PortProton reads the same switches from ``.ppdb`` (see :func:`ppdb_variables`) — only the
    free-form ``extra_env``/``dll_overrides`` are exported for it, everything else would be
    overridden by its own ``var`` defaults anyway.
    """
    env: dict[str, str] = {}
    if kind != RUNNER_KIND_PORTPROTON:
        esync = bool(options.get("esync", True))
        fsync = bool(options.get("fsync", True))
        ntsync = bool(options.get("ntsync", False))
        if kind == RUNNER_KIND_PROTON:
            if not esync:
                env["PROTON_NO_ESYNC"] = "1"
            if not fsync:
                env["PROTON_NO_FSYNC"] = "1"
            if ntsync:
                env["PROTON_USE_NTSYNC"] = "1"
            if options.get("fsr"):
                env["WINE_FULLSCREEN_FSR"] = "1"
        else:
            env["WINEESYNC"] = "1" if esync else "0"
            env["WINEFSYNC"] = "1" if fsync else "0"
            if ntsync:
                env["WINENTSYNC"] = "1"
        if options.get("large_address_aware", True):
            env["WINE_LARGE_ADDRESS_AWARE"] = "1"
        if options.get("mangohud"):
            env["MANGOHUD"] = "1"
    overrides = str(options.get("dll_overrides") or "").strip()
    if overrides:
        env["WINEDLLOVERRIDES"] = overrides
    env.update(parse_extra_env(str(options.get("extra_env") or "")))
    return env


def parse_extra_env(text: str) -> dict[str, str]:
    """``KEY=VALUE`` per line; blank lines and ``#`` comments are ignored, bad lines skipped."""
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            result[key] = value.strip().strip('"')
    return result


def option_wrappers(options: dict[str, object], kind: str) -> tuple[list[str], list[str]]:
    """Commands to prepend to the Proton/Wine command line, plus notes about what was skipped.

    PortProton applies GameMode / MangoHud / sleep inhibition itself from the ``.ppdb``.
    """
    if kind == RUNNER_KIND_PORTPROTON:
        return [], []
    wrappers: list[str] = []
    notes: list[str] = []
    if options.get("gamemode"):
        gamemoderun = shutil.which("gamemoderun")
        if gamemoderun:
            wrappers += [gamemoderun]
        else:
            notes.append("GameMode включён в профиле, но gamemoderun не найден — пропущено")
    if options.get("inhibit_sleep", True):
        inhibit = shutil.which("systemd-inhibit")
        # without the system bus systemd-inhibit refuses to start (and would take the game with it)
        if inhibit and os.path.exists("/run/dbus/system_bus_socket"):
            wrappers += [inhibit, "--what=idle:sleep", "--who=CordonIX", "--why=Игра запущена", "--mode=block"]
    if options.get("mangohud") and kind == RUNNER_KIND_WINE:
        mangohud = shutil.which("mangohud")
        if mangohud:
            wrappers += [mangohud]
        else:
            notes.append("MangoHud включён в профиле, но не установлен — пропущено")
    return wrappers, notes


def wine_virtual_desktop_args(options: dict[str, object], kind: str) -> list[str]:
    """``explorer /desktop=...`` prefix for plain Wine (Proton/PortProton have their own switch)."""
    if kind == RUNNER_KIND_WINE and options.get("virtual_desktop"):
        return ["explorer", "/desktop=CordonIX,1920x1080"]
    return []


def _flag(value: object) -> str:
    return "1" if value else "0"


def ppdb_variables(options: dict[str, object]) -> dict[str, str]:
    """``PW_*`` variables PortProton reads from ``<exe>.ppdb`` for the given profile options."""
    variables = {
        "PW_USE_ESYNC": _flag(options.get("esync", True)),
        "PW_USE_FSYNC": _flag(options.get("fsync", True)),
        "PW_USE_NTSYNC": _flag(options.get("ntsync", False)),
        "PW_USE_GAMEMODE": _flag(options.get("gamemode", False)),
        "PW_MANGOHUD": _flag(options.get("mangohud", False)),
        "PW_USE_INHIBIT_SLEEP": _flag(options.get("inhibit_sleep", True)),
        "PW_WINE_FULLSCREEN_FSR": _flag(options.get("fsr", False)),
        "PW_VIRTUAL_DESKTOP": _flag(options.get("virtual_desktop", False)),
    }
    if options.get("large_address_aware", True):
        variables["WINE_LARGE_ADDRESS_AWARE"] = "1"
    windows_version = str(options.get("windows_version") or "").strip()
    if windows_version in WINDOWS_VERSIONS:
        variables["PW_WINDOWS_VER"] = windows_version
    wine_version = str(options.get("wine_version") or "").strip()
    if wine_version:
        variables["PW_WINE_USE"] = wine_version
    prefix_name = str(options.get("prefix_name") or "").strip()
    if prefix_name:
        variables["PW_PREFIX_NAME"] = prefix_name
    overrides = str(options.get("dll_overrides") or "").strip()
    if overrides:
        variables["WINEDLLOVERRIDES"] = overrides
    variables.update(parse_extra_env(str(options.get("extra_env") or "")))
    return variables


def portproton_root(runner_path: str) -> str:
    """``~/PortProton`` for ``~/PortProton/data/scripts/start.sh``; empty for Flatpak/unknown."""
    path = util.norm(os.path.realpath(runner_path)) if runner_path else ""
    marker = "/data/scripts/start.sh"
    if path.endswith(marker):
        return path[: -len(marker)]
    for root in PORTPROTON_ROOTS:
        base = os.path.expanduser(root)
        if os.path.isfile(os.path.join(base, "data", "scripts", "start.sh")):
            return util.norm(base)
    return ""


def list_portproton_dists(root: str) -> list[str]:
    """Wine/Proton builds available to PortProton (``data/dist/*``) — for the version combo box."""
    names: list[str] = []
    dist = os.path.join(root, "data", "dist") if root else ""
    if dist and os.path.isdir(dist):
        for name in util.entry_names(dist):
            if os.path.isdir(os.path.join(dist, name)):
                names.append(name)
    names.sort(key=_natural_key, reverse=True)
    return list(PORTPROTON_WINE_ALIASES) + names


def list_portproton_prefixes(root: str) -> list[str]:
    prefixes = os.path.join(root, "data", "prefixes") if root else ""
    if not prefixes or not os.path.isdir(prefixes):
        return []
    return sorted(name for name in util.entry_names(prefixes) if os.path.isdir(os.path.join(prefixes, name)))


def portproton_prefix_dir(root: str, prefix_name: str) -> str:
    return os.path.join(root, "data", "prefixes", prefix_name or "DEFAULT") if root else ""


def list_proton_versions() -> list[str]:
    """Absolute directories of every Proton install (newest first) — for the version combo box."""
    found: list[str] = []
    steam_root = _steam_root()
    search_dirs: list[str] = []
    if steam_root:
        search_dirs += [
            os.path.join(steam_root, "compatibilitytools.d"),
            os.path.join(steam_root, "steamapps", "common"),
        ]
    search_dirs += ["/usr/share/steam/compatibilitytools.d", os.path.expanduser("~/.local/share/Steam/compatibilitytools.d")]
    for directory in search_dirs:
        if not os.path.isdir(directory):
            continue
        for name in sorted(util.entry_names(directory), key=_natural_key, reverse=True):
            candidate = os.path.join(directory, name)
            if "proton" in name.lower() and _executable(os.path.join(candidate, "proton")):
                found.append(util.norm(candidate))
    return found


def proton_from_directory(directory: str, compat_data: str) -> WindowsRunner | None:
    """Runner for an explicitly chosen Proton install directory (``wine_options['wine_version']``)."""
    script = os.path.join(os.path.expanduser(directory), "proton")
    if not _executable(script):
        return None
    steam_root = _steam_root()
    return WindowsRunner(
        kind=RUNNER_KIND_PROTON,
        path=util.norm(script),
        argv=[util.norm(script), "run"],
        label=f"Proton ({os.path.basename(os.path.normpath(directory))})",
        env={
            "STEAM_COMPAT_DATA_PATH": compat_data,
            "STEAM_COMPAT_CLIENT_INSTALL_PATH": steam_root or os.path.expanduser("~/.local/share/Steam"),
        },
    )


# ---------------------------------------------------------------------------- PortProton .ppdb
PPDB_MARKER = "# managed by CordonIX: LAUNCH_PARAMETERS is rewritten before every launch"
PPDB_BLOCK_BEGIN = "# >>> CordonIX (rewritten before every launch; edit these settings in the profile) >>>"
PPDB_BLOCK_END = "# <<< CordonIX <<<"


def write_ppdb_launch_parameters(
    exe_path: str, arguments: list[str], variables: dict[str, str] | None = None
) -> str:
    """Store engine arguments and ``PW_*`` settings in ``<exe>.ppdb`` for PortProton.

    Only the CordonIX block at the end of the file is rewritten: PortProton keeps its own
    settings in the same file and lines outside the block survive. Because the block comes
    last, its values win over anything PortProton's GUI wrote earlier. Returns the path.
    """
    ppdb = exe_path + ".ppdb"
    kept = _ppdb_lines_outside_block(util.read_text(ppdb, errors="replace") if os.path.isfile(ppdb) else "")
    if not kept:
        kept = ["#!/usr/bin/env bash", f"#{os.path.basename(exe_path)}"]
    elif not kept[0].startswith("#!"):
        kept.insert(0, "#!/usr/bin/env bash")
    value = " ".join(_ppdb_quote(argument) for argument in arguments)
    block = [PPDB_BLOCK_BEGIN]
    for key, val in (variables or {}).items():
        block.append(f'export {key}="{_ppdb_quote(val)}"')
    block += [f'export LAUNCH_PARAMETERS="{value}"', PPDB_BLOCK_END]
    util.write_text_atomic(ppdb, "\n".join(kept + block) + "\n")
    return ppdb


def _ppdb_lines_outside_block(text: str) -> list[str]:
    kept: list[str] = []
    inside = False
    for line in text.splitlines():
        if line == PPDB_BLOCK_BEGIN:
            inside = True
            continue
        if line == PPDB_BLOCK_END:
            inside = False
            continue
        if inside or line == PPDB_MARKER or line.startswith("export LAUNCH_PARAMETERS="):
            continue  # old single-line format from earlier CordonIX versions is dropped too
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    return kept


def _ppdb_quote(argument: str) -> str:
    """Quote for a double-quoted bash string that PortProton later word-splits (no ``eval``).

    Values are expanded unquoted (``${proxy_launch_parameters}``), so an argument with spaces
    cannot be preserved as one word — the X-Ray engine does not need that anyway, its flags are
    single tokens and ``Z:\\...`` paths without spaces. Backslashes are doubled because PortProton
    collapses ``\\\\`` back to ``\\`` when building the command line.
    """
    escaped = argument.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    return escaped


def shell_preview(argv: list[str], env: dict[str, str]) -> str:
    """Human-readable command line including the runner-specific environment."""
    prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in sorted(env.items()))
    body = " ".join(shlex.quote(part) for part in argv)
    return f"{prefix} {body}".strip()
