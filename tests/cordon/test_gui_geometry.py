"""Small-screen sizing: the interface must fit 1024x768 (real report from an Arch user)."""

from __future__ import annotations

import os

import pytest

from cordon.gui import geometry


# ------------------------------------------------------------------ pure helpers
def test_parse_screen_accepts_common_spellings():
    assert geometry.parse_screen("1024x768") == (1024, 768)
    assert geometry.parse_screen(" 1920X1080 ") == (1920, 1080)
    assert geometry.parse_screen("1280") is None
    assert geometry.parse_screen("abcxdef") is None
    assert geometry.parse_screen("10x10") is None, "слишком маленькое значение — не экран"


def test_screen_size_honours_the_override(monkeypatch):
    monkeypatch.setenv("CORDON_SCREEN", "1024x768")
    assert geometry.screen_size() == (1024, 768)
    monkeypatch.setenv("CORDON_SCREEN", "")
    assert geometry.screen_size()[0] >= 800, "без override используется реальный экран"


def test_fit_size_is_never_bigger_than_the_screen():
    assert geometry.fit_size((1280, 820), (1024, 768)) == (992, 696)
    assert geometry.fit_size((1280, 820), (1920, 1080)) == (1280, 820)
    assert geometry.fit_size((100, 100), (1024, 768)) == (100, 100)


def test_fit_size_keeps_a_usable_minimum_on_tiny_screens():
    width, height = geometry.fit_size((1280, 820), (600, 400))
    assert (width, height) == (600, 400), "на крошечном экране окно всё равно должно быть видимым"


def test_fit_width_for_dialogs():
    assert geometry.fit_width(720, (1024, 768)) == 720
    assert geometry.fit_width(900, (1024, 768)) == 900, "900 < 1024 - 48"
    assert geometry.fit_width(1200, (1024, 768)) == 976
    assert geometry.fit_width(400, (320, 240)) >= 320


def test_minimum_window_and_compact_mode():
    assert geometry.minimum_window((1024, 768)) == geometry.MIN_USABLE
    assert geometry.compact_mode((1024, 768)) is True
    assert geometry.compact_mode((1280, 720)) is True, "маленькая высота тоже повод для компактного режима"
    assert geometry.compact_mode((1920, 1080)) is False


def test_sidebar_and_splitter_widths_scale_with_the_screen():
    assert geometry.sidebar_width((1024, 768)) == 327, "треть ширины экрана"
    assert geometry.sidebar_width((1920, 1080)) == 340, "на большом экране — предпочтительная ширина"
    left, right = geometry.splitter_sizes((1024, 768))
    assert left == geometry.sidebar_width((1024, 768)) and left + right == 1024
    assert geometry.sidebar_width((640, 480)) >= 180


def test_clamp_rect_pulls_a_stale_geometry_back_on_screen():
    # geometry saved on a 1920x1080 monitor: window is off-screen on 1024x768
    x, y, width, height = geometry.clamp_rect(1300, 900, 1280, 820, (1024, 768))
    assert (width, height) == (992, 696)
    assert x + width <= 1024 and y + height <= 768, "окно обязано быть видно целиком"
    # a geometry that already fits is returned unchanged
    assert geometry.clamp_rect(10, 20, 800, 600, (1024, 768)) == (10, 20, 800, 600)
    # negative coordinates (second monitor on the left) are clamped too
    assert geometry.clamp_rect(-200, -100, 800, 600, (1024, 768)) == (0, 0, 800, 600)


# ------------------------------------------------------------------ Qt widgets
@pytest.fixture()
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_LOGGING_RULES", "qt.qpa.*=false")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/tmp")
    libs = os.environ.get("CORDON_TEST_LIBS", "")
    if libs:
        monkeypatch.setenv("LD_LIBRARY_PATH", libs)
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    return widgets.QApplication.instance() or widgets.QApplication([])


@pytest.fixture()
def gui_service(fake_install, fake_profile, tmp_path):
    service = __import__("cordon.core.service", fromlist=["CordonService"]).CordonService(fake_install.store)
    service.load()
    fake_profile.name = "CoP 1.6.02"
    service.settings.profiles = [fake_profile]
    service.settings.selected_profile_id = fake_profile.id
    service.save()
    return service


def test_main_window_fits_a_1024x768_screen(qt_app, gui_service, monkeypatch):
    monkeypatch.setenv("CORDON_SCREEN", "1024x768")
    try:
        from cordon.gui.main_window import MainWindow
    except ImportError as exc:  # pragma: no cover - no Qt libraries on this machine
        pytest.skip(f"PySide6 недоступен: {exc}")

    window = MainWindow(gui_service, profile_id=gui_service.settings.selected_profile_id)
    screen = geometry.screen_size()
    assert (window.width(), window.height()) == (992, 696)
    assert window.width() <= screen[0] and window.height() <= screen[1]
    assert window.minimumWidth() <= screen[0] and window.minimumHeight() <= screen[1]
    assert window._compact is True, "на 1024x768 включается компактный режим"
    # compact mode hides the duplicate text buttons but keeps the launch controls
    assert window.hint_label.isVisible() is False
    assert window.launch_button.isEnabled() and window.launch_action.shortcut().toString() == "F9"
    window.close()


def test_main_window_keeps_the_full_layout_on_a_big_screen(qt_app, gui_service, monkeypatch):
    monkeypatch.setenv("CORDON_SCREEN", "1920x1080")
    try:
        from cordon.gui.main_window import MainWindow
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"PySide6 недоступен: {exc}")

    window = MainWindow(gui_service, profile_id=gui_service.settings.selected_profile_id)
    assert (window.width(), window.height()) == (1280, 820)
    assert window._compact is False
    assert window.hint_label.isVisible() is False, "до показа окна виджет ещё не отрисован"
    assert window.hint_label.isHidden() is False
    window.close()


def test_dialogs_fit_a_1024x768_screen(qt_app, fake_install, monkeypatch):
    monkeypatch.setenv("CORDON_SCREEN", "1024x768")
    try:
        from cordon.core.models import Profile
        from cordon.gui import dialogs
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"PySide6 недоступен: {exc}")

    screen = geometry.screen_size()
    settings = __import__("cordon.core.settings", fromlist=["LauncherSettings"]).LauncherSettings()
    cases = [
        dialogs.ProfileDialog(Profile(id="p1", name="CoP", game_path=fake_install.game), fake_install.store,
                              creating=True),
        dialogs.LauncherSettingsDialog(settings),
        dialogs.Mo2Dialog(),
        dialogs.ReportDialog("Проверки", "текст отчёта\n" * 50),
        dialogs.AboutDialog(fake_install.store, upstream="https://example.invalid", version="0.1.0"),
    ]
    for dialog in cases:
        assert dialog.minimumWidth() <= screen[0], f"{type(dialog).__name__} шире экрана"
        hint = dialog.minimumSizeHint()
        assert hint.width() <= screen[0], f"{type(dialog).__name__} требует больше ширины, чем есть"
        dialog.close()
