# Third-Party Notices

CordonIX includes or uses the following third-party components. Their original licenses remain in effect.

## Python & GUI Libraries

- **PySide6 / Qt 6** ([Qt Project](https://www.qt.io/)) — GNU LGPL v3 / GPL v3.
- **Python Standard Library** ([Python Software Foundation](https://www.python.org/)) — PSF License.

## Linux Overlay & Engine Integration

- **fuse-overlayfs** ([containers/fuse-overlayfs](https://github.com/containers/fuse-overlayfs)) — GNU General Public License v2.0 or later. Provides user-space overlay filesystem support on Linux.
- **OpenXRay** ([OpenXRay/xray-16](https://github.com/OpenXRay/xray-16)) — GNU General Public License v3.0 / BSD License. Native Linux port of the X-Ray engine.
- **Valve Proton / Wine** ([ValveSoftware/Proton](https://github.com/ValveSoftware/Proton)) — Wine License (LGPL v2.1+) / BSD / MIT. Windows executable runner compatibility layer on Linux.

## Interface & Typography Assets

- **Symbols Nerd Font / JetBrains Mono** ([Nerd Fonts](https://www.nerdfonts.com/)) — SIL Open Font License 1.1 / Apache 2.0. Not bundled: the Qt theme references these font families if they are installed on the system, for PDA-style status and conflict indicators (`☢`, `⏱`, etc.).
- **Application Icon** (`packaging/cordonix.svg`) — Project asset (GPLv3, same as the code).

The PDA UI atlases, icon packs and sounds inherited from the Windows launcher are not part of CordonIX.

## Legacy & Replaced Components

- **Mod Organizer 2 USVFS (Windows)** — USVFS C++ binaries and Windows hooks are not used in CordonIX for Linux. Virtual filesystem management is handled natively via Linux symbolic/hard links or FUSE overlay layers.
- **C# / .NET Managed Libraries** — AngleSharp, NAudio, SharpCompress, and .NET runtime dependencies from the original C# Windows build have been replaced with Python native modules (`zipfile`, `tarfile`, `urllib`, `hashlib`, `socket`).
- **AP-PRO Catalog Browser** — The AP-PRO online browser feature was removed in CordonIX v0.2.0.

## Game Names and Trademarks

S.T.A.L.K.E.R., X-Ray Engine, and related names, artwork, and trademarks belong to GSC Game World and their respective rights holders. CordonIX is an independent community open-source project and is not affiliated with or endorsed by GSC Game World, Valve, or Mod Organizer 2.
