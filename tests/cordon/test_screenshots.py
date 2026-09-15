"""Tests for screenshots management."""

from __future__ import annotations

import os

from cordon.core import screenshots


def test_list_and_delete_screenshots(tmp_path):
    appdata = tmp_path / "appdata"
    ss_dir = appdata / "screenshots"
    ss_dir.mkdir(parents=True)

    img1 = ss_dir / "ss_01.png"
    img1.write_bytes(b"\x89PNG\r\n\x1a\nfake_image_data")
    img2 = ss_dir / "ss_02.jpg"
    img2.write_bytes(b"\xff\xd8\xfffake_jpg_data")
    txt = ss_dir / "readme.txt"
    txt.write_text("not an image")

    items = screenshots.list_screenshots(str(appdata))
    assert len(items) == 2
    filenames = [item.filename for item in items]
    assert "ss_01.png" in filenames
    assert "ss_02.jpg" in filenames
    assert "readme.txt" not in filenames

    assert screenshots.delete_screenshot(str(img1)) is True
    assert not img1.exists()

    items_after = screenshots.list_screenshots(str(appdata))
    assert len(items_after) == 1
    assert items_after[0].filename == "ss_02.jpg"
