"""CordonIX - a UNIX/Linux port of the CORDON S.T.A.L.K.E.R. mod launcher.

The package is split into three layers:

* :mod:`cordon.core` - pure Python domain logic (profiles, layered file overlay, engine
  discovery, launching). No GUI imports, fully unit-testable and usable on a headless box.
* :mod:`cordon.cli` - the ``cordon`` command line front end.
* :mod:`cordon.gui` - the optional PySide6 desktop front end.

Upstream CORDON (Windows/WPF) writes its own profile workspace by hard-linking the game
tree and by rewriting ``fsgame.ltx``.  This port does the same job with POSIX primitives
(symlinks, optional FUSE overlays) and uses the switches that the OpenXRay engine actually
provides on Linux (``-fsltx``, ``-overlaypath``, ``-cs``) plus automatic Proton/Wine fallback.
"""

from __future__ import annotations

__all__ = ["__version__", "APP_NAME", "UPSTREAM_VERSION"]

__version__ = "0.2.0"

APP_NAME = "CordonIX"
UPSTREAM_VERSION = "1.4.5"
