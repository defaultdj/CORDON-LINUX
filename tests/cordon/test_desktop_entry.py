"""Пункт меню приложений: после install.sh лаунчер обязан попасть в раздел «Игры».

Здесь проверяется сам файл packaging/cordon-linux.desktop и то, что установщик кладёт его
в <prefix>/share/applications с абсолютными путями этой установки.
"""

from __future__ import annotations

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DESKTOP = os.path.join(ROOT, "packaging", "cordon-linux.desktop")
ICON = os.path.join(ROOT, "packaging", "cordon-linux.svg")
INSTALL = os.path.join(ROOT, "install.sh")


def parse_desktop(path: str) -> dict[str, list[str]]:
    """Минимальный разбор desktop-файла: ключ → значения (с учётом локализованных ключей)."""
    entries: dict[str, list[str]] = {}
    section = ""
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            entries.setdefault(f"{section}.{key.strip()}", []).append(value.strip())
    return entries


@pytest.fixture(scope="module")
def desktop() -> dict[str, list[str]]:
    assert os.path.isfile(DESKTOP), f"нет файла {DESKTOP}"
    return parse_desktop(DESKTOP)


def test_desktop_entry_is_a_launchable_application(desktop):
    assert desktop["Desktop Entry.Type"] == ["Application"]
    assert desktop["Desktop Entry.Name"][0]
    assert desktop["Desktop Entry.Exec"][0].split()[0] == "cordon-gui", "Exec должен запускать GUI"
    assert desktop["Desktop Entry.TryExec"][0].endswith("cordon-gui")
    assert desktop["Desktop Entry.Terminal"] == ["false"]
    assert desktop["Desktop Entry.StartupNotify"] == ["true"]


def test_desktop_entry_lands_in_the_games_section(desktop):
    """Раздел меню определяется категориями: «Игры» — это ровно Game."""
    categories = [item for item in desktop["Desktop Entry.Categories"][0].split(";") if item]
    assert "Game" in categories, "без категории Game пункт не попадёт в «Игры»"
    # Utility уводил бы пункт ещё и в «Утилиты», а в некоторых меню заменял собой «Игры»
    assert "Utility" not in categories, "лишняя категория уводит значок из раздела «Игры»"
    assert desktop["Desktop Entry.Categories"][0].endswith(";"), "список категорий кончается на ';'"


def test_locale_strings_are_present(desktop):
    for key in ("Name", "GenericName", "Comment", "Keywords"):
        assert f"Desktop Entry.{key}[ru]" in desktop, f"нет русского варианта {key}"
    assert "S.T.A.L.K.E.R." in desktop["Desktop Entry.Name[ru]"][0]


def test_icon_matches_the_installed_file_name(desktop):
    icon = desktop["Desktop Entry.Icon"][0]
    assert os.path.isfile(ICON), "нет файла значка"
    assert os.path.basename(ICON) == f"{icon}.svg", "Icon= должен совпадать с именем установленного значка"
    with open(ICON, encoding="utf-8") as handle:
        svg = handle.read()
    assert svg.lstrip().startswith("<"), "значок должен быть валидным SVG"


def test_install_script_installs_the_menu_entry_into_the_prefix():
    with open(INSTALL, encoding="utf-8") as handle:
        script = handle.read()

    assert 'DESKTOP_DIR="${PREFIX}/share/applications"' in script
    assert 'ICON_DIR="${PREFIX}/share/icons/hicolor/scalable/apps"' in script
    # Exec/TryExec обязаны указывать на эту установку, а не на команду из PATH
    assert "Exec=${PREFIX}/bin/cordonix" in script
    assert "TryExec=${PREFIX}/bin/cordonix" in script
    # файл попадает на место через install и с нормальными правами
    assert re.search(r"install -m 644 .*cordon.*\.desktop", script)
    # меню и кэш значков обновляются, если инструменты есть
    assert "update-desktop-database" in script
    assert "gtk-update-icon-cache" in script
    assert "kbuildsycoca" in script, "в KDE кэш обновляется своей утилитой"
    # и результат проверяется, когда есть чем
    assert "desktop-file-validate" in script
