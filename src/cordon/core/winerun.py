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


# ---------------------------------------------------------------------------- PortProton .ppdb
PPDB_MARKER = "# managed by CordonIX: LAUNCH_PARAMETERS is rewritten before every launch"


def write_ppdb_launch_parameters(exe_path: str, arguments: list[str]) -> str:
    """Store engine arguments in ``<exe>.ppdb`` so PortProton passes them to the game.

    Only ``LAUNCH_PARAMETERS`` is touched: PortProton keeps its own settings (prefix, DXVK,
    MangoHud, …) in the same file and those must survive. Returns the ``.ppdb`` path.
    """
    ppdb = exe_path + ".ppdb"
    value = " ".join(_ppdb_quote(argument) for argument in arguments)
    lines: list[str] = []
    if os.path.isfile(ppdb):
        lines = util.read_text(ppdb, errors="replace").splitlines()
    kept = [line for line in lines if not line.startswith("export LAUNCH_PARAMETERS=") and line != PPDB_MARKER]
    if kept and not kept[0].startswith("#!"):
        kept.insert(0, "#!/usr/bin/env bash")
    elif not kept:
        kept = ["#!/usr/bin/env bash", f"#{os.path.basename(exe_path)}"]
    kept += [PPDB_MARKER, f'export LAUNCH_PARAMETERS="{value}"']
    util.write_text_atomic(ppdb, "\n".join(kept) + "\n")
    return ppdb


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
