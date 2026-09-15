"""Screenshot collection and management for game profiles."""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass

from . import util

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".dds")


@dataclass(slots=True)
class ScreenshotItem:
    path: str
    filename: str
    size: int
    size_display: str
    mtime: float
    date_display: str


def list_screenshots(appdata_path: str) -> list[ScreenshotItem]:
    """Scan *appdata_path/screenshots* for game screenshot images."""
    screenshots_dir = os.path.join(util.norm(appdata_path), "screenshots")
    if not os.path.isdir(screenshots_dir):
        return []

    items: list[ScreenshotItem] = []
    try:
        entries = os.listdir(screenshots_dir)
    except OSError:
        return []

    for name in entries:
        lowered = name.lower()
        if not any(lowered.endswith(ext) for ext in IMAGE_EXTENSIONS):
            continue
        full_path = os.path.join(screenshots_dir, name)
        try:
            stat_info = os.stat(full_path)
            size = stat_info.st_size
            mtime = stat_info.st_mtime
        except OSError:
            continue

        dt = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        items.append(
            ScreenshotItem(
                path=full_path,
                filename=name,
                size=size,
                size_display=util.human_size(size),
                mtime=mtime,
                date_display=date_str,
            )
        )

    return sorted(items, key=lambda x: x.mtime, reverse=True)


def delete_screenshot(path: str) -> bool:
    """Delete a screenshot file safely."""
    path = util.norm(path)
    if os.path.isfile(path):
        try:
            os.remove(path)
            return True
        except OSError:
            return False
    return False
