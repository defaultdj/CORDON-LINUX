"""Dialogs: profile editor, Mod Organizer 2 import, about box and simple reports."""

from __future__ import annotations

import copy
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import engine as engine_mod
from ..core import preflight, util, winerun, xray
from ..core.models import (
    BACKEND_DIRECT,
    BACKEND_FUSE,
    BACKEND_LINK,
    ENGINE_FLAG_LABELS,
    GAME_IDS,
    PROFILE_KIND_MODS,
    PROFILE_KIND_STANDALONE,
    WINDOWS_RUNNER_LABELS,
    WINE_OPTION_DEFAULTS,
    WINE_OPTION_LABELS,
    Profile,
)
from ..core.paths import AppPaths
from . import geometry as geometry_mod

BACKEND_LABELS = {
    BACKEND_LINK: "Символические ссылки (без прав root)",
    BACKEND_FUSE: "fuse-overlayfs (настоящий оверлей, только для чтения игры)",
    BACKEND_DIRECT: "Напрямую из папок модов (ничего не собирается)",
}

BACKEND_HINTS = {
    BACKEND_LINK: "Самый совместимый вариант: файлы модов объединяются ссылками внутри каталога профиля.",
    BACKEND_FUSE: "Нужен пакет fuse-overlayfs. Оверлей монтируется при запуске и отключается после выхода.",
    BACKEND_DIRECT: "Файлы модов подключаются напрямую; конфликты разрешает движок по порядку.",
}


def _path_row(edit: QLineEdit, callback, label: str = "…") -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(edit, 1)
    button = QPushButton(label)
    button.setFixedWidth(34)
    button.clicked.connect(callback)
    layout.addWidget(button)
    return widget


class ProfileDialog(QDialog):
    """Create or edit a profile. Mutates ``profile`` only when accepted."""

    def __init__(self, profile: Profile, app: AppPaths, *, creating: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._profile = profile
        self._app = app
        self._creating = creating
        self.setWindowTitle("Новый профиль" if creating else f"Профиль «{profile.name}»")
        screen = geometry_mod.screen_size()
        self.setMinimumWidth(geometry_mod.fit_width(720, screen))
        self.resize(*geometry_mod.fit_size((760, 700), screen))

        # The form is long (paths, backend, engine keys): on a 1024x768 screen it is scrolled
        # instead of being cut off, while the buttons stay pinned to the bottom.
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.name_edit = QLineEdit(profile.name)
        form.addRow("Название", self.name_edit)

        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Игра + моды (оверлей профиля)", PROFILE_KIND_MODS)
        self.kind_combo.addItem("Готовая сборка (без оверлея)", PROFILE_KIND_STANDALONE)
        self.kind_combo.setCurrentIndex(1 if profile.is_standalone else 0)
        self.kind_combo.currentIndexChanged.connect(self._sync_enabled)
        form.addRow("Тип профиля", self.kind_combo)

        self.game_edit = QLineEdit(profile.game_path)
        self.game_edit.setPlaceholderText("каталог с gamedata/ и fsgame.ltx")
        form.addRow("Каталог игры", _path_row(self.game_edit, self._pick_game))

        self.engine_edit = QLineEdit(profile.engine_path)
        self.engine_edit.setPlaceholderText("оставьте пустым — движок будет найден автоматически")
        form.addRow("Движок (OpenXRay)", _path_row(self.engine_edit, self._pick_engine))

        self.engine_data_edit = QLineEdit(profile.engine_data_path)
        self.engine_data_edit.setPlaceholderText("например /usr/share/openxray")
        form.addRow("Данные движка", _path_row(self.engine_data_edit, self._pick_engine_data))

        self.executable_edit = QLineEdit(profile.executable_relative)
        self.executable_edit.setPlaceholderText("bin/xr_3da")
        self.executable_edit.setToolTip(
            "Путь к исполняемому файлу относительно каталога движка.\n"
            "В deb-сборке OpenXRay это /usr/games/xr_3da, в portable — bin/xr_3da."
        )
        find_button = QPushButton("Найти")
        find_button.clicked.connect(self._detect)
        executable_row = QWidget()
        executable_layout = QHBoxLayout(executable_row)
        executable_layout.setContentsMargins(0, 0, 0, 0)
        executable_layout.addWidget(self.executable_edit, 1)
        executable_layout.addWidget(find_button)
        form.addRow("Исполняемый файл", executable_row)

        self.backend_combo = QComboBox()
        for backend, label in BACKEND_LABELS.items():
            self.backend_combo.addItem(label, backend)
        index = self.backend_combo.findData(profile.backend)
        self.backend_combo.setCurrentIndex(max(0, index))
        self.backend_combo.currentIndexChanged.connect(self._sync_backend_hint)
        form.addRow("Способ сборки", self.backend_combo)

        self.backend_hint = QLabel("")
        self.backend_hint.setWordWrap(True)
        self.backend_hint.setObjectName("dim")
        form.addRow("", self.backend_hint)

        self.game_id_combo = QComboBox()
        for game_id in GAME_IDS:
            self.game_id_combo.addItem(xray.describe_game_id(game_id), game_id)
        index = self.game_id_combo.findData(profile.game_id)
        self.game_id_combo.setCurrentIndex(max(0, index))
        form.addRow("Тип игры", self.game_id_combo)

        self.appdata_combo = QComboBox()
        self.appdata_combo.addItem("Внутри профиля (-overlaypath)", "profile")
        self.appdata_combo.addItem("Общая папка игры", "shared")
        self.appdata_combo.setCurrentIndex(0 if profile.appdata_mode != "shared" else 1)
        form.addRow("Данные игры", self.appdata_combo)

        self.root_edit = QLineEdit(profile.root_path)
        self.root_edit.setPlaceholderText(app.profiles_root)
        form.addRow("Каталог профиля", _path_row(self.root_edit, self._pick_root))

        self.arguments_edit = QLineEdit(profile.launch_arguments)
        self.arguments_edit.setPlaceholderText("дополнительные аргументы, например: -nointro")
        form.addRow("Аргументы запуска", self.arguments_edit)

        self.description_edit = QPlainTextEdit(profile.description)
        self.description_edit.setFixedHeight(48)
        form.addRow("Описание", self.description_edit)

        layout.addLayout(form)

        flags_box = QGroupBox("Ключи движка")
        flags_layout = QVBoxLayout(flags_box)
        self.flag_checks: dict[str, QCheckBox] = {}
        for flag, (label, tooltip) in ENGINE_FLAG_LABELS.items():
            check = QCheckBox(f"{label}  ({flag})")
            check.setToolTip(tooltip)
            check.setChecked(flag in profile.engine_flags)
            self.flag_checks[flag] = check
            flags_layout.addWidget(check)
        self.overlay_path_check = QCheckBox("Переносить данные профиля ключом -overlaypath")
        self.overlay_path_check.setChecked(profile.use_overlay_path)
        flags_layout.addWidget(self.overlay_path_check)
        self.isolate_check = QCheckBox("Свои логи, сохранения и скриншоты у каждого профиля")
        self.isolate_check.setChecked(profile.isolate_appdata)
        flags_layout.addWidget(self.isolate_check)
        self.prefer_openxray_check = QCheckBox("Сначала пробовать нативный OpenXRay (для сборок с .exe)")
        self.prefer_openxray_check.setToolTip(
            "Если в каталоге игры лежат .exe файлы, лаунчер сначала попробует запустить нативный OpenXRay для максимального FPS."
        )
        self.prefer_openxray_check.setChecked(getattr(profile, "prefer_native_openxray", True))
        flags_layout.addWidget(self.prefer_openxray_check)
        self.auto_fallback_check = QCheckBox("Автопереключение на Proton/Wine при ошибке OpenXRay")
        self.auto_fallback_check.setToolTip(
            "Если нативный OpenXRay завершится с ошибкой, лаунчер автоматически перезапустит игру через Proton/Wine."
        )
        self.auto_fallback_check.setChecked(getattr(profile, "auto_proton_fallback", True))
        flags_layout.addWidget(self.auto_fallback_check)
        runner_row = QHBoxLayout()
        runner_row.addWidget(QLabel("Запуск Windows-сборок (.exe) через"))
        self.windows_runner_combo = QComboBox()
        for runner_id, label in WINDOWS_RUNNER_LABELS.items():
            self.windows_runner_combo.addItem(label, runner_id)
        index = self.windows_runner_combo.findData(getattr(profile, "windows_runner", "auto"))
        self.windows_runner_combo.setCurrentIndex(max(0, index))
        self.windows_runner_combo.setToolTip(
            "PortProton (linux-gaming.ru) берёт на себя префикс, DXVK и настройки; аргументы движка "
            "записываются в <exe>.ppdb. Proton из Steam получает свой префикс в каталоге профиля. "
            "Wine использует WINEPREFIX из окружения."
        )
        runner_row.addWidget(self.windows_runner_combo, 1)
        flags_layout.addLayout(runner_row)
        layout.addWidget(flags_box)
        layout.addWidget(self._build_wine_box(profile))
        self.windows_runner_combo.currentIndexChanged.connect(self._sync_wine_versions)
        self._sync_wine_versions()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.check_button = buttons.addButton("Проверить", QDialogButtonBox.ActionRole)
        self.check_button.clicked.connect(self._run_checks)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(scroll, 1)
        outer.addWidget(buttons)

        self._sync_backend_hint()
        self._sync_enabled()

    # ------------------------------------------------------------------ Proton/Wine tuning
    def _build_wine_box(self, profile: Profile) -> QGroupBox:
        options = dict(WINE_OPTION_DEFAULTS)
        options.update(getattr(profile, "wine_options", {}) or {})
        box = QGroupBox("Proton / Wine: дополнительно (только для Windows-сборок)")
        body = QVBoxLayout(box)
        hint = QLabel(
            "Для PortProton эти значения записываются в <exe>.ppdb (PW_*) перед каждым запуском и "
            "перекрывают настройки из его меню. Для Proton/Wine превращаются в переменные окружения."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        body.addWidget(hint)

        self.wine_checks: dict[str, QCheckBox] = {}
        for key, label in WINE_OPTION_LABELS.items():
            check = QCheckBox(label)
            check.setChecked(bool(options.get(key)))
            self.wine_checks[key] = check
            body.addWidget(check)
        self.wine_checks["ntsync"].setToolTip("Требует модуль ntsync в ядре; при включении esync/fsync отключаются самим Wine.")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.windows_version_combo = QComboBox()
        for version in winerun.WINDOWS_VERSIONS:
            self.windows_version_combo.addItem(f"Windows {version}", version)
        index = self.windows_version_combo.findData(str(options.get("windows_version") or "10"))
        self.windows_version_combo.setCurrentIndex(max(0, index))
        form.addRow("Версия Windows в префиксе", self.windows_version_combo)

        self.wine_version_combo = QComboBox()
        self.wine_version_combo.setEditable(True)
        self.wine_version_combo.setToolTip(
            "PortProton: имя сборки из data/dist (PROTON_LG / WINE_LG — версии по умолчанию). "
            "Proton: каталог с установленным Proton (compatibilitytools.d/...). Пусто — как у раннера."
        )
        self._wine_version_initial = str(options.get("wine_version") or "")
        form.addRow("Версия Wine / Proton", self.wine_version_combo)

        self.prefix_name_combo = QComboBox()
        self.prefix_name_combo.setEditable(True)
        self.prefix_name_combo.setToolTip(
            "PortProton: имя префикса в data/prefixes (пусто — DEFAULT). "
            "Proton/Wine: абсолютный путь к префиксу; пусто — <каталог профиля>/proton-prefix."
        )
        self._prefix_name_initial = str(options.get("prefix_name") or "")
        form.addRow("Префикс", self.prefix_name_combo)

        self.dll_overrides_edit = QLineEdit(str(options.get("dll_overrides") or ""))
        self.dll_overrides_edit.setPlaceholderText("d3d9=n,b;dinput8=n")
        form.addRow("WINEDLLOVERRIDES", self.dll_overrides_edit)
        body.addLayout(form)

        body.addWidget(QLabel("Дополнительные переменные окружения (KEY=VALUE, по одной на строку):"))
        self.extra_env_edit = QPlainTextEdit(str(options.get("extra_env") or ""))
        self.extra_env_edit.setPlaceholderText("DXVK_HUD=fps\nPW_VKBASALT=1")
        self.extra_env_edit.setMaximumHeight(80)
        body.addWidget(self.extra_env_edit)
        return box

    def _sync_wine_versions(self) -> None:
        """Fill the version/prefix combos for the selected runner, keeping the typed value."""
        runner = self.windows_runner_combo.currentData() or "auto"
        current_version = self.wine_version_combo.currentText().strip() or self._wine_version_initial
        current_prefix = self.prefix_name_combo.currentText().strip() or self._prefix_name_initial
        versions: list[str] = []
        prefixes: list[str] = []
        try:
            if runner in ("auto", winerun.RUNNER_KIND_PORTPROTON):
                pp = winerun.find_portproton(str(getattr(self._app, "extra", {}).get("portproton_path", "") or ""))
                root = winerun.portproton_root(pp.path if pp else "")
                versions = winerun.list_portproton_dists(root)
                prefixes = winerun.list_portproton_prefixes(root)
            if runner in ("auto", winerun.RUNNER_KIND_PROTON):
                versions += winerun.list_proton_versions()
        except OSError:
            pass
        for combo, values, current in (
            (self.wine_version_combo, versions, current_version),
            (self.prefix_name_combo, prefixes, current_prefix),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("")
            for value in values:
                combo.addItem(value)
            combo.setCurrentText(current)
            combo.blockSignals(False)

    def _wine_options(self) -> dict[str, object]:
        options: dict[str, object] = {key: check.isChecked() for key, check in self.wine_checks.items()}
        options["windows_version"] = self.windows_version_combo.currentData() or "10"
        options["wine_version"] = self.wine_version_combo.currentText().strip()
        options["prefix_name"] = self.prefix_name_combo.currentText().strip()
        options["dll_overrides"] = self.dll_overrides_edit.text().strip()
        options["extra_env"] = self.extra_env_edit.toPlainText().strip()
        return options

    # ------------------------------------------------------------------ helpers
    def _pick_game(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Каталог игры", self.game_edit.text() or os.path.expanduser("~"))
        if path:
            self.game_edit.setText(path)
            self._autofill_from_game(path)

    def _pick_engine(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Каталог движка", self.engine_edit.text() or "/usr")
        if path:
            self.engine_edit.setText(path)

    def _pick_engine_data(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Каталог данных движка", self.engine_data_edit.text() or "/usr/share/openxray"
        )
        if path:
            self.engine_data_edit.setText(path)

    def _pick_root(self) -> None:
        start = self.root_edit.text() or self._app.profiles_root
        path = QFileDialog.getExistingDirectory(self, "Каталог профиля", start)
        if path:
            self.root_edit.setText(path)

    def _autofill_from_game(self, path: str) -> None:
        game_id = xray.detect_game_id(path, declared="auto")
        index = self.game_id_combo.findData(game_id)
        if index >= 0:
            self.game_id_combo.setCurrentIndex(index)
        if not self.engine_edit.text() and engine_mod.find_engine(self._scratch()) is None:
            self.engine_edit.setText(path)

    def _detect(self) -> None:
        scratch = self._scratch()
        info = engine_mod.find_engine(scratch)
        if info is None:
            QMessageBox.warning(
                self,
                "Движок не найден",
                "Не удалось найти исполняемый файл OpenXRay.\n\n"
                "Укажите каталог движка вручную или путь к файлу xr_3da.",
            )
            return
        self.engine_edit.setText(info.engine_root)
        if info.data_root and info.data_root != util.norm(self.game_edit.text()):
            self.engine_data_edit.setText(info.data_root)
        if info.executable.startswith(info.engine_root + os.sep):
            self.executable_edit.setText(os.path.relpath(info.executable, info.engine_root))
        else:
            self.executable_edit.setText(info.executable)
        QMessageBox.information(self, "Движок найден", info.describe())

    def _sync_backend_hint(self) -> None:
        backend = self.backend_combo.currentData()
        self.backend_hint.setText(BACKEND_HINTS.get(backend, ""))
        standalone = self.kind_combo.currentData() == PROFILE_KIND_STANDALONE
        self.backend_combo.setEnabled(not standalone)
        self.overlay_path_check.setEnabled(not standalone or True)

    def _sync_enabled(self) -> None:
        standalone = self.kind_combo.currentData() == PROFILE_KIND_STANDALONE
        self.backend_combo.setEnabled(not standalone)
        self._sync_backend_hint()

    def _scratch(self) -> Profile:
        profile = copy.deepcopy(self._profile)
        profile.name = self.name_edit.text().strip() or profile.name
        profile.kind = self.kind_combo.currentData()
        profile.game_path = util.norm(self.game_edit.text().strip()) if self.game_edit.text().strip() else ""
        profile.engine_path = util.norm(self.engine_edit.text().strip()) if self.engine_edit.text().strip() else ""
        profile.engine_data_path = (
            util.norm(self.engine_data_edit.text().strip()) if self.engine_data_edit.text().strip() else ""
        )
        profile.executable_relative = self.executable_edit.text().strip() or "bin/xr_3da"
        profile.backend = self.backend_combo.currentData()
        profile.game_id = self.game_id_combo.currentData()
        profile.appdata_mode = self.appdata_combo.currentData()
        profile.root_path = util.norm(self.root_edit.text().strip()) if self.root_edit.text().strip() else ""
        profile.launch_arguments = self.arguments_edit.text().strip()
        profile.engine_flags = [flag for flag, check in self.flag_checks.items() if check.isChecked()]
        profile.use_overlay_path = self.overlay_path_check.isChecked()
        profile.isolate_appdata = self.isolate_check.isChecked()
        profile.prefer_native_openxray = self.prefer_openxray_check.isChecked()
        profile.auto_proton_fallback = self.auto_fallback_check.isChecked()
        profile.windows_runner = self.windows_runner_combo.currentData() or "auto"
        profile.wine_options = self._wine_options()
        profile.description = self.description_edit.toPlainText().strip()
        return profile

    def _run_checks(self) -> None:
        scratch = self._scratch()
        try:
            report = preflight.run(scratch, self._app)
        except Exception as exc:  # noqa: BLE001 - the dialog must stay usable
            QMessageBox.critical(self, "Проверка не удалась", str(exc))
            return
        box = QMessageBox(self)
        box.setWindowTitle("Проверка профиля")
        box.setText(report.headline)
        box.setDetailedText(report.to_text())
        box.setIcon(QMessageBox.Information if report.ok else QMessageBox.Warning)
        box.exec()

    def _accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Проверьте данные", "Укажите название профиля.")
            return
        game = self.game_edit.text().strip()
        if game and not os.path.isdir(game):
            QMessageBox.warning(self, "Проверьте данные", f"Каталог игры не найден:\n{game}")
            return
        engine_path = self.engine_edit.text().strip()
        if engine_path and not os.path.isdir(engine_path):
            QMessageBox.warning(self, "Проверьте данные", f"Каталог движка не найден:\n{engine_path}")
            return
        self.accept()

    def result_profile(self) -> Profile:
        return self._scratch()


class LauncherSettingsDialog(QDialog):
    """Launcher-wide preferences (theme, presence, log size)."""

    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки лаунчера")
        self.setMinimumWidth(geometry_mod.fit_width(560))
        self._settings = settings
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("PDA (тёмная, янтарные акценты)", "pda")
        self.theme_combo.addItem("Классическая (светлая)", "classic")
        index = self.theme_combo.findData(getattr(settings, "theme", "pda"))
        self.theme_combo.setCurrentIndex(max(0, index))
        form.addRow("Оформление", self.theme_combo)

        self.discord_check = QCheckBox("Показывать статус в Discord во время игры")
        self.discord_check.setChecked(bool(getattr(settings, "discord_presence", False)))
        form.addRow("", self.discord_check)

        self.discord_id_edit = QLineEdit(str(getattr(settings, "discord_client_id", "")))
        self.discord_id_edit.setPlaceholderText("Application ID приложения Discord")
        form.addRow("Discord Application ID", self.discord_id_edit)

        self.log_lines_edit = QLineEdit(str(getattr(settings, "keep_launcher_log_lines", 4000)))
        self.log_lines_edit.setPlaceholderText("сколько строк вывода игры хранить в окне")
        form.addRow("Строк вывода в окне", self.log_lines_edit)

        self.portproton_edit = QLineEdit(str(getattr(settings, "portproton_path", "")))
        self.portproton_edit.setPlaceholderText("пусто — искать автоматически (portproton в PATH, ~/PortProton, Flatpak)")
        form.addRow("Каталог PortProton", _path_row(self.portproton_edit, self._pick_portproton))

        layout.addLayout(form)

        hint = QLabel(
            "Статус в Discord работает через локальный сокет Discord (нужен запущенный клиент).\n"
            "Настройки профилей находятся в диалоге «Настройки» на главной панели."
        )
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick_portproton(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Каталог PortProton", self.portproton_edit.text() or os.path.expanduser("~")
        )
        if path:
            self.portproton_edit.setText(path)

    def apply_to(self, settings) -> None:
        settings.portproton_path = self.portproton_edit.text().strip()
        settings.theme = self.theme_combo.currentData()
        settings.discord_presence = self.discord_check.isChecked()
        client_id = self.discord_id_edit.text().strip()
        if client_id:
            settings.discord_client_id = client_id
        try:
            lines = int(self.log_lines_edit.text().strip() or 4000)
        except ValueError:
            lines = 4000
        settings.keep_launcher_log_lines = max(200, min(200_000, lines))


class Mo2Dialog(QDialog):
    """Import ``modlist.txt`` from a Mod Organizer 2 instance."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Импорт из Mod Organizer 2")
        self.setMinimumWidth(geometry_mod.fit_width(760))

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("каталог MO2, каталог профиля или путь к modlist.txt")
        form.addRow("Путь MO2", _path_row(self.path_edit, self._pick))
        layout.addLayout(form)

        self.modlist_only_check = QCheckBox("Только порядок и включённость (моды уже добавлены в профиль)")
        self.no_overwrite_check = QCheckBox("Не подключать папку overwrite")
        layout.addWidget(self.modlist_only_check)
        layout.addWidget(self.no_overwrite_check)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(_mono())
        layout.addWidget(self.preview, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.scan_button = buttons.addButton("Предпросмотр", QDialogButtonBox.ActionRole)
        self.scan_button.clicked.connect(self.scan)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Каталог Mod Organizer 2", os.path.expanduser("~"))
        if path:
            self.path_edit.setText(path)
            self.scan()

    def scan(self) -> None:
        from ..core.mo2 import build_preview

        path = self.path_edit.text().strip()
        if not path:
            return
        try:
            self.preview.setPlainText(build_preview(path).to_text())
        except Exception as exc:  # noqa: BLE001 - show the problem in the dialog
            self.preview.setPlainText(f"Не удалось прочитать MO2: {exc}")

    def values(self) -> tuple[str, bool, bool]:
        return self.path_edit.text().strip(), self.modlist_only_check.isChecked(), self.no_overwrite_check.isChecked()


class ReportDialog(QDialog):
    """Plain text report with copy and save buttons (used for conflicts, audits and diagnostics)."""

    def __init__(self, title: str, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(*geometry_mod.fit_size((900, 620)))
        layout = QVBoxLayout(self)
        self.view = QPlainTextEdit(text)
        self.view.setReadOnly(True)
        self.view.setFont(_mono())
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        save_button = buttons.addButton("Сохранить в файл...", QDialogButtonBox.ActionRole)
        save_button.clicked.connect(self._save)
        copy_button = buttons.addButton("Копировать", QDialogButtonBox.ActionRole)
        copy_button.clicked.connect(self._copy)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.view.toPlainText())

    def _save(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Сохранить отчёт",
            os.path.expanduser("~/report.txt"),
            "Текстовый файл (*.txt);;Markdown (*.md);;Все файлы (*)",
        )
        if path:
            util.write_text_atomic(path, self.view.toPlainText())


class ArchiveScannerDialog(QDialog):
    """Dialog to scan a directory recursively for mod archives and select ones for installation."""

    def __init__(self, start_dir: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Поиск архивов с модами")
        self.setMinimumWidth(geometry_mod.fit_width(760))
        self.resize(*geometry_mod.fit_size((800, 500)))

        self._selected_archives: list[str] = []
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.path_edit = QLineEdit(start_dir or os.path.expanduser("~"))
        self.path_edit.setPlaceholderText("выберите папку для поиска архивов модов")
        form.addRow("Каталог поиска", _path_row(self.path_edit, self._pick_directory, "…"))
        layout.addLayout(form)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Установить", "Имя файла", "Имя мода", "Размер"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.summary_label = QLabel("Укажите каталог и нажмите «Сканировать».")
        self.summary_label.setObjectName("dim")
        layout.addWidget(self.summary_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.scan_button = buttons.addButton("Сканировать", QDialogButtonBox.ActionRole)
        self.scan_button.clicked.connect(self.scan)
        self.install_button = buttons.addButton("Установить выбранные", QDialogButtonBox.AcceptRole)
        self.install_button.setEnabled(False)
        buttons.accepted.connect(self._accept_install)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if start_dir and os.path.isdir(start_dir):
            self.scan()

    def _pick_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Выберите папку для поиска архивов", self.path_edit.text() or os.path.expanduser("~")
        )
        if path:
            self.path_edit.setText(path)
            self.scan()

    def scan(self) -> None:
        from ..core.mods import scan_archives_detailed

        path = self.path_edit.text().strip()
        if not path or not os.path.isdir(path):
            QMessageBox.warning(self, "Каталог не найден", f"Указанный каталог не существует:\n{path}")
            return
        items = scan_archives_detailed(path)
        self.table.setRowCount(0)
        for item in items:
            row = self.table.rowCount()
            self.table.insertRow(row)

            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            check.setCheckState(Qt.Checked)
            check.setData(Qt.UserRole, item.path)
            self.table.setItem(row, 0, check)

            name_item = QTableWidgetItem(item.name)
            name_item.setToolTip(item.path)
            self.table.setItem(row, 1, name_item)

            stem_item = QTableWidgetItem(item.stem)
            self.table.setItem(row, 2, stem_item)

            size_item = QTableWidgetItem(item.size_display)
            self.table.setItem(row, 3, size_item)

        self.summary_label.setText(f"Найдено архивов: {len(items)}")
        self.install_button.setEnabled(len(items) > 0)

    def _accept_install(self) -> None:
        self._selected_archives = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                path = item.data(Qt.UserRole)
                if path:
                    self._selected_archives.append(str(path))
        if not self._selected_archives:
            QMessageBox.warning(self, "Архивы не выбраны", "Отметьте галочками архивы для установки.")
            return
        self.accept()

    def selected_archives(self) -> list[str]:
        return self._selected_archives


def _mono():
    from .theme import monospace

    return monospace(12)


class AboutDialog(QDialog):
    def __init__(self, app: AppPaths, *, upstream: str, version: str, parent=None) -> None:
        super().__init__(parent)
        from .. import UPSTREAM_VERSION

        self.setWindowTitle("О программе")
        self.setMinimumWidth(geometry_mod.fit_width(560))
        layout = QVBoxLayout(self)

        title = QLabel("CordonIX")
        title.setObjectName("headline")
        font = title.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        text = QLabel(
            f"Версия {version} · Форк CORDON {UPSTREAM_VERSION} для UNIX/Linux.\n"
            "Лаунчер профилей и модов S.T.A.L.K.E.R. с поддержкой OpenXRay и Proton/Wine.\n\n"
            f"Оригинал: {upstream}\n"
            "Лицензия: GPL-3.0 (как и у оригинального проекта).\n\n"
            f"Настройки: {app.config_dir}\n"
            f"Профили и моды: {app.data_dir}\n"
            f"Кэш: {app.cache_dir}\n"
            f"Журнал: {app.launcher_log}"
        )
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(text)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class LeftoversDialog(QDialog):
    """After a profile is deleted: what is still on disk, with checkboxes for what to remove."""

    def __init__(self, profile_name: str, report, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Остатки профиля «{profile_name}»")
        screen = geometry_mod.screen_size()
        self.resize(*geometry_mod.fit_size((760, 460), screen))
        self._report = report
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Профиль удалён. Ниже — каталоги и файлы, которые с ним связаны. Отметьте, что удалить. "
            "Общие с другими профилями или играми элементы по умолчанию не отмечены."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.table = QTableWidget(len(report.items), 3)
        self.table.setHorizontalHeaderLabels(["Удалить", "Что это", "Путь / размер"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self._checks: list[tuple[QCheckBox, object]] = []
        for row, item in enumerate(report.items):
            check = QCheckBox()
            check.setChecked(not item.shared)
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(6, 0, 6, 0)
            hl.setAlignment(Qt.AlignCenter)
            hl.addWidget(check)
            self.table.setCellWidget(row, 0, holder)
            self.table.setItem(row, 1, QTableWidgetItem(item.label + ("  [общее]" if item.shared else "")))
            size = f"  ({util.human_size(item.size)})" if item.size >= 0 else ""
            cell = QTableWidgetItem(f"{item.path}{size}")
            if item.note:
                cell.setToolTip(item.note)
            self.table.setItem(row, 2, cell)
            self._checks.append((check, item))
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox()
        remove = buttons.addButton("Удалить отмеченное", QDialogButtonBox.AcceptRole)
        remove.setDefault(False)
        keep = buttons.addButton("Оставить всё", QDialogButtonBox.RejectRole)
        keep.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self) -> list:
        return [item for check, item in self._checks if check.isChecked()]


class InstallBuildDialog(QDialog):
    """Pick a build source (archive or setup.exe) and the directory to install it into."""

    def __init__(self, app: AppPaths, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Установить сборку")
        screen = geometry_mod.screen_size()
        self.setMinimumWidth(geometry_mod.fit_width(640, screen))
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Архив распаковывается в выбранный каталог; установщик .exe запускается через PortProton/"
            "Proton/Wine — в нём укажите тот же каталог (он будет показан как Z:\\…). Каталог должен быть "
            "пустым или новым: лаунчер помечает его своим и предложит удалить вместе с профилем."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.source_edit = QLineEdit()
        form.addRow("Архив или установщик", _path_row(self.source_edit, self._pick_source))
        self.dest_edit = QLineEdit(os.path.join(app.data_dir, "builds"))
        form.addRow("Каталог установки", _path_row(self.dest_edit, self._pick_destination))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("по умолчанию — имя каталога сборки")
        form.addRow("Название профиля", self.name_edit)
        self.runner_combo = QComboBox()
        for runner_id, label in WINDOWS_RUNNER_LABELS.items():
            self.runner_combo.addItem(label, runner_id)
        form.addRow("Установщик .exe запускать через", self.runner_combo)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Установить")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.source_edit.textChanged.connect(self._suggest_destination)

    def _pick_source(self) -> None:
        pattern = "Сборки (*.exe *.msi *.zip *.7z *.rar *.tar *.tar.gz *.tgz *.tar.xz *.tar.bz2 *.tar.zst);;Все файлы (*)"
        path, _f = QFileDialog.getOpenFileName(self, "Архив или установщик сборки", os.path.expanduser("~"), pattern)
        if path:
            self.source_edit.setText(path)

    def _pick_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Каталог установки", self.dest_edit.text() or os.path.expanduser("~"))
        if path:
            self.dest_edit.setText(path)

    def _suggest_destination(self, source: str) -> None:
        base = self.dest_edit.text().strip()
        if not source or not base:
            return
        from ..core import mods as mods_mod

        stem = mods_mod.archive_stem(source) if not source.lower().endswith((".exe", ".msi")) else os.path.splitext(os.path.basename(source))[0]
        stem = mods_mod.slugify(stem, fallback="build")
        parent = os.path.dirname(base) if os.path.basename(base) == getattr(self, "_last_stem", None) else base
        self._last_stem = stem
        self.dest_edit.setText(os.path.join(parent, stem))

    def _accept(self) -> None:
        source = self.source_edit.text().strip()
        if not os.path.isfile(source):
            QMessageBox.warning(self, "Проверьте данные", "Укажите существующий архив или установщик.")
            return
        if not self.dest_edit.text().strip():
            QMessageBox.warning(self, "Проверьте данные", "Укажите каталог установки.")
            return
        self.accept()

    def values(self) -> tuple[str, str, str, str]:
        return (
            self.source_edit.text().strip(),
            self.dest_edit.text().strip(),
            self.name_edit.text().strip(),
            self.runner_combo.currentData() or "auto",
        )
