"""Screen-aware sizing for the Qt interface.

Old machines still run S.T.A.L.K.E.R. on 1024x768 screens, so the launcher must never assume a
"comfortable desktop" size: hardcoded 1280x820 windows and 720 px wide dialogs simply do not fit.
Every window asks this module for a size derived from the real available area instead.

``CORDON_SCREEN=1024x768`` replaces the detected screen size - handy for tests and for checking how
the interface looks on a smaller display than the one attached.
"""

from __future__ import annotations

import os

#: Fallback when Qt cannot tell us anything (headless runs, very early startup).
DEFAULT_SCREEN = (1280, 800)

#: A window smaller than this is unusable even on a tiny screen.
MIN_USABLE = (640, 420)

#: Space reserved for window decorations and panels; ``availableGeometry`` already excludes the
#: taskbar, this is the title bar plus a little breathing room.
MARGIN = (32, 72)

#: Below this width the interface switches to the compact layout (menus instead of text buttons).
COMPACT_WIDTH = 1150
COMPACT_HEIGHT = 800


def parse_screen(value: str) -> tuple[int, int] | None:
    """``"1024x768"`` -> ``(1024, 768)``; anything else is ignored."""
    text = (value or "").strip().lower().replace(" ", "")
    if "x" not in text:
        return None
    left, _, right = text.partition("x")
    try:
        width, height = int(left), int(right)
    except ValueError:
        return None
    if width < 320 or height < 240:
        return None
    return (width, height)


def screen_override() -> tuple[int, int] | None:
    return parse_screen(os.environ.get("CORDON_SCREEN", ""))


def available_rect() -> tuple[int, int, int, int]:
    """Available screen area as ``(x, y, width, height)``.

    ``availableGeometry`` already excludes panels/docks, which is what makes the launcher fit a
    small desktop: the window is sized from this rectangle, not from the physical resolution.
    """
    override = screen_override()
    if override is not None:
        return (0, 0, override[0], override[1])
    try:  # imported lazily: the pure helpers above stay importable without Qt
        from PySide6.QtGui import QGuiApplication
    except ImportError:  # pragma: no cover - CLI without Qt
        return (0, 0, *DEFAULT_SCREEN)
    screen = QGuiApplication.primaryScreen()
    if screen is None:  # pragma: no cover - no display at all
        return (0, 0, *DEFAULT_SCREEN)
    rect = screen.availableGeometry()
    if rect.width() <= 0 or rect.height() <= 0:  # pragma: no cover - odd platform plugins
        return (0, 0, *DEFAULT_SCREEN)
    return (rect.x(), rect.y(), rect.width(), rect.height())


def screen_size() -> tuple[int, int]:
    """Available screen area in device-independent pixels."""
    override = screen_override()
    if override is not None:
        return override
    x, y, width, height = available_rect()
    return (width, height)


def fit_size(
    preferred: tuple[int, int],
    available: tuple[int, int] | None = None,
    *,
    margin: tuple[int, int] = MARGIN,
    minimum: tuple[int, int] = MIN_USABLE,
) -> tuple[int, int]:
    """Largest size that still fits *available*, never bigger than *preferred*."""
    screen = available or screen_size()
    width = min(preferred[0], max(minimum[0], screen[0] - margin[0]))
    height = min(preferred[1], max(minimum[1], screen[1] - margin[1]))
    return (max(1, min(width, screen[0])), max(1, min(height, screen[1])))


def fit_width(preferred: int, available: tuple[int, int] | None = None, *, margin: int = 48) -> int:
    """Width for a dialog: *preferred* when there is room, otherwise the screen minus *margin*."""
    screen = available or screen_size()
    return max(320, min(preferred, screen[0] - margin))


def minimum_window(available: tuple[int, int] | None = None) -> tuple[int, int]:
    screen = available or screen_size()
    return (min(MIN_USABLE[0], screen[0]), min(MIN_USABLE[1], screen[1]))


def compact_mode(available: tuple[int, int] | None = None) -> bool:
    """True on small screens: fewer buttons, smaller paddings."""
    screen = available or screen_size()
    return screen[0] < COMPACT_WIDTH or screen[1] < COMPACT_HEIGHT


def sidebar_width(available: tuple[int, int] | None = None, *, preferred: int = 340, minimum: int = 200) -> int:
    """Width of the profile column: a third of the window, within sane bounds."""
    screen = available or screen_size()
    third = int(screen[0] * 0.32)
    return max(minimum, min(preferred, third, max(minimum, screen[0] // 2)))


def splitter_sizes(available: tuple[int, int] | None = None) -> list[int]:
    screen = available or screen_size()
    left = sidebar_width(screen)
    return [left, max(screen[0] - left, 320)]


def clamp_rect(
    x: int,
    y: int,
    width: int,
    height: int,
    available: tuple[int, int] | None = None,
) -> tuple[int, int, int, int]:
    """Keep a restored window on screen: shrink it and pull it back if needed."""
    screen_w, screen_h = available or screen_size()
    width, height = fit_size((width, height), (screen_w, screen_h))
    x = max(0, min(x, max(0, screen_w - width)))
    y = max(0, min(y, max(0, screen_h - height)))
    return (x, y, width, height)


def describe() -> str:
    """One-line summary for ``cordon tools`` and the launcher log."""
    rect = available_rect()
    size = (rect[2], rect[3])
    window = fit_size((1280, 820), size)
    compact = "да" if compact_mode(size) else "нет"
    return (
        f"Экран: доступно {size[0]}x{size[1]} (начало {rect[0]},{rect[1]}); "
        f"окно лаунчера {window[0]}x{window[1]}; компактный режим: {compact}"
    )
