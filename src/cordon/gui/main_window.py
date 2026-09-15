"""The main window: profiles on the left, the mod/priority list and reports on the right."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core import diagnostics, layers, preflight, util, winerun, xray
from ..core import engine as engine_mod
from ..core import mods as mods_mod
from ..core.errors import CordonError
from ..core.models import Profile
from ..core.service import CordonService
from . import geometry as geometry_mod
from . import theme as theme_mod
from .dialogs import (
    AboutDialog,
    ArchiveScannerDialog,
    InstallBuildDialog,
    LauncherSettingsDialog,
    LeftoversDialog,
    Mo2Dialog,
    ProfileDialog,
    ReportDialog,
)
from .screenshots import ScreenshotsPane
from .widgets import ModTable, ProfileList, ReportPane, StatusStrip, make_button, make_menu_button, summary_line
from .workers import SessionThread, Task

UPSTREAM = "https://github.com/ITzSYUK/CORDON"


class MainWindow(QMainWindow):
    def __init__(self, service: CordonService, *, profile_id: str = "") -> None:
        super().__init__()
        self.service = service
        self.settings = service.settings
        self._task: Task | None = None
        self._session_thread: SessionThread | None = None
        self._presence = None
        self._status = None
        self.actions_map: dict[str, QAction] = {}

        self.setWindowTitle(f"CordonIX {__version__}")
        icon_path = util.norm(os.path.join(os.path.dirname(__file__), "..", "..", "..", "packaging", "cordonix.svg"))
        if os.path.isfile(icon_path):
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(icon_path))
        # Small screens (1024x768 is still common for S.T.A.L.K.E.R.) must not get a window
        # bigger than their display: everything derives from the available area.
        self._screen_rect = geometry_mod.available_rect()
        self._screen = (self._screen_rect[2], self._screen_rect[3])
        self._compact = geometry_mod.compact_mode(self._screen)
        self._geometry_checked = False

        self._header = self._build_header()
        # The status bar must exist before the central widget: it hosts the progress indicator and
        # the priority hint, and both are added while building the tabs.
        self.setStatusBar(QStatusBar())
        self._build_central()
        # Sizes are applied after the widgets exist: the layout minimum tells how much room the
        # content really needs, which is the only reliable way to avoid clipping.
        self._apply_startup_size()
        self._apply_theme()

        if profile_id:
            profile = self.settings.profile(profile_id)
            if profile:
                self.settings.selected_profile_id = profile.id
        self.refresh_profiles(select=self.settings.selected_profile_id)
        self._restore_geometry()

    def _mod_hint(self, standalone: bool) -> str:
        """Text for the status bar: the full sentence only when there is room for it."""
        if standalone:
            return "Профиль-сборка: моды не подключаются, запускается только игра."
        if self._compact:
            return "Ниже в списке — выше приоритет"
        return "Чем ниже мод в списке, тем выше его приоритет (его файлы побеждают)."

    def _apply_startup_size(self) -> None:
        """Pick window bounds from the screen on one side and the content on the other.

        * minimum - never smaller than the layout needs (otherwise buttons are cut off),
          but capped by the screen so a small display still shows a complete window;
        * maximum - the available area, so nothing can be pushed off the screen;
        * start size - the preferred 1280x820, widened when the non-compact header needs more,
          then trimmed to the screen.
        """
        rect = self._screen_rect
        content = self.minimumSizeHint()
        # +32: Qt refines font-dependent metrics on the first layout pass, so the hint measured now
        # is a little smaller than the final requirement.
        slack = 32
        floor_width, floor_height = geometry_mod.minimum_window(self._screen)
        minimum_width = min(max(floor_width, content.width() + slack), rect[2])
        minimum_height = min(max(floor_height, content.height()), rect[3])
        self.setMinimumSize(minimum_width, minimum_height)
        self.setMaximumSize(rect[2], rect[3])
        preferred = (max(1280, minimum_width), 820)
        self.resize(*geometry_mod.fit_size(preferred, self._screen))
        logger = getattr(self.service, "logger", None)
        if logger is not None:
            logger.info(
                "экран: доступно %sx%s; окно %sx%s (минимум %sx%s); компактный режим: %s",
                self._screen[0], self._screen[1], self.width(), self.height(),
                minimum_width, minimum_height, "да" if self._compact else "нет",
            )

    # ------------------------------------------------------------------ ui setup
    def _build_header(self) -> QWidget:
        """Compact top bar: the few actions used often, the rest behind menus.

        A plain ``QToolBar`` was too wide for 1280 px windows, so the launch buttons ended up in
        the overflow menu; here the buttons are placed explicitly instead.
        """
        header = QWidget()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)

        brand = QLabel("☢ CordonIX")
        brand.setObjectName("brand")
        brand.setToolTip("CordonIX — S.T.A.L.K.E.R. Profile & Mod Manager")
        layout.addWidget(brand)

        sep = QLabel("│")
        sep.setObjectName("dim")
        layout.addWidget(sep)

        def action(text: str, slot, shortcut: str = "", tip: str = "") -> QAction:
            item = QAction(text, self)
            item.triggered.connect(slot)
            if shortcut:
                item.setShortcut(QKeySequence(shortcut))
            if tip:
                item.setToolTip(tip)
            self.addAction(item)
            self.actions_map[text] = item
            return item

        def button(text: str, slot=None, tip: str = "", primary: bool = False):
            widget = make_button(text, primary=primary)
            if slot is not None:
                widget.clicked.connect(slot)
            if tip:
                widget.setToolTip(tip)
            layout.addWidget(widget)
            return widget

        def menu_button(text: str, entries: list[QAction], tip: str = ""):
            from PySide6.QtWidgets import QMenu, QToolButton

            tool = QToolButton()
            tool.setText(text + "  ▾")
            tool.setObjectName("menuButton")
            tool.setPopupMode(QToolButton.InstantPopup)
            menu = QMenu(tool)
            for entry in entries:
                if entry is None:  # разделитель между группами пунктов
                    menu.addSeparator()
                else:
                    menu.addAction(entry)
            tool.setMenu(menu)
            if tip:
                tool.setToolTip(tip)
            layout.addWidget(tool)
            return tool

        # --- actions first: they carry the shortcuts and are shared by buttons and menus,
        # so every one of them has to exist before the header is laid out
        action("Новый профиль", self.new_profile, "Ctrl+N", "Создать профиль")
        action(
            "Настройки профиля",
            self.edit_profile,
            "Ctrl+E",
            "Движок, исполняемый файл, аргументы запуска, каталоги профиля",
        )
        action("Установить сборку", self.install_build, "Ctrl+Shift+I",
               "Распаковать архив или запустить setup.exe сборки и создать для неё профиль")
        action("Дублировать", self.duplicate_profile, "", "Копия профиля вместе с модами")
        action("Удалить", self.delete_profile, "Ctrl+Delete", "Удалить профиль")
        action("Добавить моды", self.add_mods, "Ctrl+O", "Добавить папки модов")
        action("Найти моды", self.scan_mods, "Ctrl+F", "Найти моды в каталоге")
        action("Поиск архивов", self.scan_archives_dialog, "", "Сканировать каталог на наличие архивов модов")
        action("Установить архив", self.install_archive, "Ctrl+I", "Установить мод из архива")
        action("Импорт MO2", self.import_mo2, "", "Импортировать порядок модов из Mod Organizer 2")
        action(
            "Запустить через Proton/Wine",
            lambda: self.launch_profile(runner=engine_mod.RUNNER_PROTON),
            "Shift+F9",
            "Принудительно запустить Windows .exe сборки через Proton/Wine, минуя нативный OpenXRay",
        )
        action(
            "Запустить только нативно",
            lambda: self.launch_profile(runner=engine_mod.RUNNER_NATIVE),
            "Ctrl+F9",
            "Запустить только нативный OpenXRay без автоматического переключения на Proton/Wine",
        )
        action("Собрать", self.prepare_profile, "F5", "Собрать оверлей профиля")
        action("Проверить", self.run_checks, "F6", "Предполётные проверки")
        action("Конфликты", self.show_conflicts, "Ctrl+K", "Показать конфликты файлов")
        action("Аудит регистра", self.run_audit, "Ctrl+R", "Проверить регистр путей (Linux-специфика)")
        action("Отчёт", self.save_report, "Ctrl+P", "Сохранить отчёт о профиле")
        action("Настройки лаунчера", self.launcher_settings, "Ctrl+,",
               "Тема, Discord-статус, размер журнала")
        action("О программе", self.show_about, "F1", "Версия и каталоги лаунчера")

        # --- профиль и моды
        profile_entries: list[QAction | None] = []
        if not self._compact:
            button("Новый профиль", self.new_profile, "Ctrl+N")
            button("Настройки", self.edit_profile, "Ctrl+E — движок, аргументы запуска, каталоги")
        else:
            # На узком экране в шапке остаются только три меню, а кнопки скрываются. Всё, что
            # раньше было кнопкой, обязано быть в меню: иначе «Настройки профиля» (движок,
            # аргументы запуска, каталоги) и «Собрать» с «Проверить» исчезают из интерфейса.
            profile_entries += [
                self.actions_map["Новый профиль"],
                self.actions_map["Настройки профиля"],
                None,
                self.actions_map["Собрать"],
                self.actions_map["Проверить"],
                None,
            ]
        profile_entries += [
            self.actions_map["Запустить через Proton/Wine"],
            self.actions_map["Запустить только нативно"],
            None,
            self.actions_map["Установить сборку"],
            self.actions_map["Дублировать"],
            self.actions_map["Удалить"],
        ]
        menu_button(
            "Профиль",
            profile_entries,
            "Создать, настроить, собрать, проверить, дублировать или удалить профиль",
        )
        menu_button(
            "Моды",
            [
                self.actions_map["Добавить моды"],
                self.actions_map["Найти моды"],
                self.actions_map["Поиск архивов"],
                self.actions_map["Установить архив"],
                self.actions_map["Импорт MO2"],
            ],
            "Добавление, поиск и установка модов",
        )

        # --- обслуживание профиля
        if not self._compact:
            button("Собрать", self.prepare_profile, "F5 — собрать оверлей профиля")
            button("Проверить", self.run_checks, "F6 — предполётные проверки")
        menu_button(
            "Инструменты",
            [
                self.actions_map["Конфликты"],
                self.actions_map["Аудит регистра"],
                self.actions_map["Отчёт"],
                self.actions_map["Настройки лаунчера"],
                self.actions_map["О программе"],
            ],
            "Конфликты, аудит регистра, отчёт",
        )

        layout.addStretch(1)

        self.launch_button = make_button("▶  Запустить", primary=True)
        self.launch_button.setToolTip("Запустить игру с выбранным профилем (F9)")
        self.launch_button.clicked.connect(self.launch_profile)
        self.launch_action = QAction("▶  Запустить", self)
        self.launch_action.setShortcut(QKeySequence("F9"))
        self.launch_action.triggered.connect(self.launch_profile)
        self.addAction(self.launch_action)
        layout.addWidget(self.launch_button)

        self.launch_menu = make_menu_button(
            "▾",
            [self.actions_map["Запустить через Proton/Wine"], self.actions_map["Запустить только нативно"]],
            tooltip="Другие способы запуска: принудительно через Proton/Wine или только нативный OpenXRay",
        )
        self.launch_menu.setObjectName("primary")
        layout.addWidget(self.launch_menu)

        self.stop_button = make_button("◼  Остановить")
        self.stop_button.setEnabled(False)
        self.stop_button.setToolTip("Завершить запущенную игру")
        self.stop_button.clicked.connect(self.stop_game)
        layout.addWidget(self.stop_button)

        return header

    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left.setMinimumWidth(geometry_mod.sidebar_width(self._screen, preferred=300, minimum=180))
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 4, 8)
        header = QLabel("Профили")
        header.setObjectName("headline")
        left_layout.addWidget(header)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Фильтр по названию…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        left_layout.addWidget(self.filter_edit)
        self.profile_list = ProfileList()
        self.profile_list.currentItemChanged.connect(self._profile_changed)
        self.profile_list.profile_activated.connect(self._activate_profile)
        left_layout.addWidget(self.profile_list, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 8, 8, 8)
        self.status_strip = StatusStrip()
        right_layout.addWidget(self.status_strip)

        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)          # иначе суммарная ширина вкладок задаёт минимум окна
        self.tabs.tabBar().setElideMode(Qt.ElideRight)
        right_layout.addWidget(self.tabs, 1)

        # --- mods tab
        mods_tab = QWidget()
        mods_layout = QVBoxLayout(mods_tab)
        mods_layout.setContentsMargins(6, 6, 6, 6)
        self.mod_table = ModTable()
        self.mod_table.toggled.connect(self._mod_toggled)
        self.mod_table.order_changed.connect(self._mods_reordered)
        self.mod_table.selection_changed.connect(lambda _mod_id: self._sync_mod_buttons())
        self.mod_table.files_dropped.connect(self.handle_files_dropped)
        mods_layout.addWidget(self.mod_table, 1)

        mod_buttons = QHBoxLayout()
        mod_buttons.setSpacing(4 if self._compact else 6)
        for text, short, slot, tip in (
            ("Вверх", "Вверх", lambda: self._move_selected(-1), "Выше в списке — ниже приоритет"),
            ("Вниз", "Вниз", lambda: self._move_selected(1), "Ниже в списке — выше приоритет"),
        ):
            button = make_button(short if self._compact else text)
            button.clicked.connect(slot)
            button.setToolTip(tip)
            mod_buttons.addWidget(button)
        bulk = (
            ("Включить все", lambda: self._set_all(True)),
            ("Отключить все", lambda: self._set_all(False)),
            ("Убрать из профиля", self.remove_mod),
            ("Удалить файлы", self.delete_mod_files),
        )
        self._mod_menu = None
        if self._compact:
            # six buttons need ~570 px; on a small screen they collapse into one menu
            self._mod_menu = make_menu_button("Ещё ▾", bulk, tooltip="Действия с модами профиля")
            mod_buttons.addWidget(self._mod_menu)
        else:
            for text, slot in bulk:
                button = make_button(text)
                button.clicked.connect(slot)
                mod_buttons.addWidget(button)
        mod_buttons.addStretch(1)
        # A QLabel with plain text demands its full width from the layout, which alone pushed the
        # window minimum past a 1024 px screen; the status bar elides instead.
        self.hint_label = QLabel(self._mod_hint(False))
        self.hint_label.setObjectName("dim")
        self.hint_label.setToolTip("Чем ниже мод в списке, тем выше его приоритет (его файлы побеждают).")
        self.mod_table.setToolTip(self.hint_label.toolTip())
        self.statusBar().addPermanentWidget(self.hint_label)
        mods_layout.addLayout(mod_buttons)
        self.tabs.addTab(mods_tab, "📁 Моды и приоритет")

        # --- reports tab
        self.report_pane = ReportPane()
        self.tabs.addTab(self.report_pane, "🩺 Проверки и конфликты")

        # --- screenshots tab
        self.screenshots_pane = ScreenshotsPane()
        self.tabs.addTab(self.screenshots_pane, "🖼️ Скриншоты")

        # --- diagnostics tab
        diag_tab = QWidget()
        diag_layout = QVBoxLayout(diag_tab)
        diag_buttons = QHBoxLayout()
        diag_actions = (
            ("Игровой лог", self.open_game_log),
            ("user.ltx", self.open_user_ltx),
            ("Дампы", self.open_dumps),
            ("Каталог профиля", lambda: self.open_path("root")),
            ("Данные профиля", lambda: self.open_path("appdata")),
            ("Папка модов", lambda: self.open_path("mods")),
            ("Журнал лаунчера", self.open_launcher_log),
        )
        self._diag_menu = None
        if self._compact:
            # this row alone wants ~830 px - impossible on a 1024 px screen
            self._diag_menu = make_menu_button(
                "Открыть ▾", diag_actions, tooltip="Открыть каталоги профиля и логи"
            )
            diag_buttons.addWidget(self._diag_menu)
        else:
            for text, slot in diag_actions:
                button = make_button(text)
                button.clicked.connect(slot)
                diag_buttons.addWidget(button)
        diag_buttons.addStretch(1)
        diag_layout.addLayout(diag_buttons)
        self.diag_view = QPlainTextEdit()
        self.diag_view.setReadOnly(True)
        self.diag_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        diag_layout.addWidget(self.diag_view, 1)
        self.tabs.addTab(diag_tab, "📄 Диагностика")

        # --- log tab
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_buttons = QHBoxLayout()
        clear_button = make_button("Очистить")
        clear_button.clicked.connect(lambda: self.log_view.clear())
        follow_check = QCheckBox("Прокручивать за выводом")
        follow_check.setChecked(True)
        self.follow_check = follow_check
        log_buttons.addWidget(clear_button)
        log_buttons.addWidget(follow_check)
        log_buttons.addStretch(1)
        log_layout.addLayout(log_buttons)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_view.setFont(theme_mod.monospace(11))
        log_layout.addWidget(self.log_view, 1)
        self.tabs.addTab(log_tab, "📟 Вывод игры")

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes(geometry_mod.splitter_sizes(self._screen))
        self.splitter = splitter

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._header)
        central_layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setMaximumWidth(180)
        self.statusBar().addPermanentWidget(self.progress)

    def _apply_theme(self) -> None:
        palette = theme_mod.palettes().get(self.settings.theme, theme_mod.PDA)
        self.setPalette(theme_mod.qpalette(palette))
        self.setStyleSheet(theme_mod.stylesheet(palette, compact=self._compact))
        self._palette = palette

    # ------------------------------------------------------------------ profiles
    def refresh_profiles(self, *, select: str = "") -> None:
        profiles = self.settings.profiles
        target = select or self.settings.selected_profile_id
        self.profile_list.set_profiles(profiles, target)
        self._apply_filter(self.filter_edit.text())
        if not profiles:
            self.status_strip.headline.setText("Профилей нет")
            self.status_strip.detail.setText("Нажмите «Новый профиль», чтобы начать")
            self.mod_table.setRowCount(0)
            self.launch_button.setEnabled(False)
            self.launch_menu.setEnabled(False)
            return
        if not self.profile_list.current_profile_id():
            self.profile_list.setCurrentRow(0)
        self._profile_changed()

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self.profile_list.count()):
            item = self.profile_list.item(row)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def current_profile(self) -> Profile | None:
        profile_id = self.profile_list.current_profile_id()
        if not profile_id and self.settings.profiles:
            profile_id = self.settings.profiles[0].id
        return self.settings.profile(profile_id) if profile_id else None

    def _update_mod_table(self, profile: Profile | None = None) -> None:
        if profile is None:
            profile = self.current_profile()
        if profile is None:
            self.mod_table.set_mods(Profile(id="", name=""))
            return
        statuses = {}
        try:
            report = self.service.conflict_report(profile)
            statuses = report.per_mod
        except Exception:  # noqa: BLE001
            statuses = {}
        self.mod_table.set_mods(profile, statuses=statuses)
        self.status_strip.detail.setText(summary_line(profile))

    def _profile_changed(self, *_args) -> None:
        profile = self.current_profile()
        if profile is None:
            self.launch_button.setEnabled(False)
            self.launch_menu.setEnabled(False)
            return
        self.settings.selected_profile_id = profile.id
        self.service.save()
        self.launch_button.setEnabled(self._session_thread is None)
        self.launch_menu.setEnabled(self._session_thread is None)
        self._update_mod_table(profile)
        self.hint_label.setText(
            self._mod_hint(profile.is_standalone)
        )
        self.status_strip.headline.setText(profile.name)
        self.status_strip.detail.setText(summary_line(profile))
        workspace = self.service.workspace_for(profile)
        self.screenshots_pane.set_appdata(workspace.appdata)

        # Automatically populate "Проверки и конфликты" tab with preflight readiness report
        try:
            plan = self.service.plan_for(profile)
            report = preflight.run(profile, self.service.app, plan=plan, workspace=workspace)
            lines = [(check.level, self._format_check(check)) for check in report.checks]
            self.report_pane.set_lines([("plain", report.headline), ("plain", "")] + lines)
            self._status = report
        except Exception as exc:  # noqa: BLE001
            self.report_pane.set_text(f"Ошибка проверки профиля: {exc}", "error")

        self._sync_mod_buttons()
        self._refresh_status_light()

    def _activate_profile(self, profile_id: str) -> None:
        self.launch_profile()

    def new_profile(self) -> None:
        profile = Profile(id=util.new_id(), name="Новый профиль")
        dialog = ProfileDialog(profile, self.service.app, creating=True, parent=self)
        if dialog.exec() == ProfileDialog.Accepted:
            created = dialog.result_profile()
            self.settings.profiles.append(created)
            self.settings.selected_profile_id = created.id
            self.service.save()
            self.refresh_profiles(select=created.id)
            self._log(f"Создан профиль «{created.name}»")

    def edit_profile(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        dialog = ProfileDialog(profile, self.service.app, parent=self)
        if dialog.exec() == ProfileDialog.Accepted:
            updated = dialog.result_profile()
            index = self.settings.profiles.index(profile)
            self.settings.profiles[index] = updated
            self.service.save()
            self.refresh_profiles(select=updated.id)
            self._log(f"Профиль «{updated.name}» обновлён")

    def duplicate_profile(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        try:
            clone = self.service.duplicate_profile(profile.id)
        except CordonError as exc:
            self._error(str(exc))
            return
        self.refresh_profiles(select=clone.id)
        self._log(f"Создана копия: «{clone.name}»")

    def install_build(self) -> None:
        dialog = InstallBuildDialog(self.service.app, parent=self)
        if dialog.exec() != InstallBuildDialog.Accepted:
            return
        source, destination, name, runner = dialog.values()
        is_installer = source.lower().endswith((".exe", ".msi"))
        if is_installer:
            self._log(
                "Запускается установщик. Укажите в нём каталог "
                + winerun.to_windows_path(destination)
            )

        def work(progress):
            return self.service.install_build(source, destination, name=name, runner_preference=runner, progress=progress)

        def done(result):
            profile, outcome = result
            self.refresh_profiles(select=profile.id)
            self._log(f"Сборка установлена в {outcome.game_root}; создан профиль «{profile.name}»")
            for note in outcome.notes:
                self._log("  " + note)
            text = f"Профиль «{profile.name}» создан.\n\nКаталог: {outcome.game_root}"
            if outcome.notes:
                text += "\n\n" + "\n".join(outcome.notes)
            self._info("Сборка установлена", text)

        self._run_task("Установка сборки…" if not is_installer else "Ожидание завершения установщика…", work, done)

    def delete_profile(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        answer = QMessageBox.question(
            self,
            "Удаление профиля",
            f"Удалить профиль «{profile.name}»?\n\n"
            "Каталог профиля и распакованные моды будут удалены, папки самих модов — нет.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        name = profile.name
        try:
            report = self.service.leftovers_for(profile)
        except OSError as exc:
            self._log(f"Не удалось проверить остатки: {exc}")
            report = None
        self.service.delete_profile(profile.id)
        self.refresh_profiles()
        self._log(f"Профиль «{name}» удалён")
        if report is None:
            return
        report.items = [item for item in report.items if os.path.lexists(item.path)]
        if not report.items:
            self._log("На диске от профиля ничего не осталось")
            return
        dialog = LeftoversDialog(name, report, parent=self)
        if dialog.exec() != QDialog.Accepted:
            self._log("Остатки профиля оставлены: " + "; ".join(item.path for item in report.items))
            return
        selected = dialog.selected()
        if not selected:
            return
        answer = QMessageBox.warning(
            self,
            "Подтверждение",
            "Безвозвратно удалить:\n\n" + "\n".join(item.path for item in selected),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        errors = self.service.remove_leftovers(selected, report)
        self._log(f"Удалено остатков: {len(selected) - len(errors)}")
        if errors:
            self._error("Часть остатков удалить не удалось:\n" + "\n".join(errors))

    # ------------------------------------------------------------------ mods
    def _sync_mod_buttons(self) -> None:
        has_selection = bool(self.mod_table.selected_mod_ids())
        for button in self.findChildren(type(self.stop_button)):
            if button.text() in ("Вверх", "Вниз", "Убрать из профиля", "Удалить файлы", "Убрать выбранные", "Удалить выбранные"):
                button.setEnabled(has_selection)

    def _mod_toggled(self, mod_id: str, enabled: bool) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        mod = profile.mod_by_id(mod_id)
        if mod is None:
            return
        mod.enabled = enabled
        self.service.save()
        self._update_mod_table(profile)
        self.status_strip.detail.setText(summary_line(profile))
        self._log(("Включён" if enabled else "Отключён") + f" мод «{mod.name}»")

    def _mods_reordered(self, order: list[str]) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        layers.reorder_mods(profile, order)
        self.service.save()
        self._update_mod_table(profile)
        self._log("Порядок модов изменён: " + ", ".join(mod.name for mod in profile.mods[:5]) + "…")
        self._refresh_status_light()

    def _move_selected(self, delta: int) -> None:
        profile = self.current_profile()
        mod_id = self.mod_table.selected_mod_id()
        if profile is None or not mod_id:
            return
        index = next((i for i, mod in enumerate(profile.mods) if mod.id == mod_id), None)
        if index is None:
            return
        target = max(0, min(len(profile.mods) - 1, index + delta))
        if target == index:
            return
        mod = profile.mods.pop(index)
        profile.mods.insert(target, mod)
        self.service.save()
        self._update_mod_table(profile)
        self.mod_table.selectRow(target)
        self._refresh_status_light()

    def _set_all(self, enabled: bool) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        for mod in profile.mods:
            mod.enabled = enabled
        self.service.save()
        self._update_mod_table(profile)
        self.status_strip.detail.setText(summary_line(profile))

    def add_mods(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        directories = QFileDialog.getExistingDirectory(
            self, "Каталог с модами", os.path.expanduser("~"), QFileDialog.ShowDirsOnly
        )
        if not directories:
            return
        self._run_task(
            "Поиск модов…",
            lambda progress: self.service.add_mods_from_folders(profile, [directories]),
            self._mods_added,
        )

    def scan_mods(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        directory = QFileDialog.getExistingDirectory(self, "Каталог для поиска модов", os.path.expanduser("~"))
        if not directory:
            return

        def work(progress):
            result = self.service.scan_folder(profile, directory)
            return result

        def done(result):
            if not result.found:
                self._info("Моды не найдены", "В выбранном каталоге не найдено папок, похожих на моды S.T.A.L.K.E.R.")
                return
            answer = QMessageBox.question(
                self,
                "Найдены моды",
                f"Найдено модов: {len(result.found)}.\n\nДобавить их в профиль «{profile.name}»?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                return
            added = self.service.add_mods_from_folders(profile, [entry.path for entry in result.found])
            self._mods_added(added)

        self._run_task("Сканирование…", work, done)

    def _mods_added(self, added: int) -> None:
        profile = self.current_profile()
        self.service.save()
        if profile is not None:
            self._update_mod_table(profile)
            self.status_strip.detail.setText(summary_line(profile))
            for mod in profile.mods:
                if os.path.isdir(mod.path):
                    indicators = xray.detect_standalone_mod_indicators(mod.path)
                    if indicators:
                        self._log(
                            f"⚠ ВНИМАНИЕ: Мод «{mod.name}» содержит {', '.join(indicators)} — "
                            "это похоже на готовую сборку! Рекомендуется использовать профиль «standalone»."
                        )
        self._log(f"Добавлено модов: {added}")

    def install_archive(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        pattern = "Архивы модов (" + " ".join(f"*{suffix}" for suffix in mods_mod.ARCHIVE_SUFFIXES) + ");;Все файлы (*)"
        archives, _filter = QFileDialog.getOpenFileNames(self, "Установить моды из архивов", os.path.expanduser("~"), pattern)
        if not archives:
            return

        def work(progress):
            installed = []
            for archive in archives:
                outcome = self.service.install_archive(profile, archive, progress=progress)
                installed.append(outcome.mod.name)
            return installed

        def done(names):
            self.service.save()
            self._update_mod_table(profile)
            self._log("Установлены моды: " + ", ".join(names))
            QMessageBox.information(self, "Готово", "Установлено модов: " + str(len(names)))

        self._run_task("Распаковка архивов…", work, done)

    def scan_archives_dialog(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        dialog = ArchiveScannerDialog(os.path.expanduser("~"), self)
        if dialog.exec() == ArchiveScannerDialog.Accepted:
            archives = dialog.selected_archives()
            if not archives:
                return

            def work(progress):
                installed = []
                for archive in archives:
                    outcome = self.service.install_archive(profile, archive, progress=progress)
                    installed.append(outcome.mod.name)
                return installed

            def done(names):
                self.service.save()
                self._update_mod_table(profile)
                self._log("Установлены моды из архивов: " + ", ".join(names))
                QMessageBox.information(self, "Готово", "Установлено модов: " + str(len(names)))

            self._run_task("Распаковка архивов…", work, done)

    def handle_files_dropped(self, paths: list[str]) -> None:
        profile = self.current_profile()
        if profile is None or not paths:
            return
        archives = [p for p in paths if mods_mod.is_archive(p)]
        folders = [p for p in paths if os.path.isdir(p)]

        if not archives and not folders:
            return

        def work(progress):
            installed_archives = []
            for archive in archives:
                outcome = self.service.install_archive(profile, archive, progress=progress)
                installed_archives.append(outcome.mod.name)
            added_folders = 0
            if folders:
                added_folders = self.service.add_mods_from_folders(profile, folders)
            return installed_archives, added_folders

        def done(result):
            installed_names, added_count = result
            self.service.save()
            self._update_mod_table(profile)
            msg_parts = []
            if installed_names:
                msg_parts.append(f"распаковано архивов: {len(installed_names)}")
            if added_count:
                msg_parts.append(f"добавлено папок: {added_count}")
            summary = " · ".join(msg_parts) or "Готово"
            self._log(f"Drag & Drop: {summary}")
            self.statusBar().showMessage(f"Импорт завершён: {summary}")

        self._run_task("Обработка перетащенных файлов…", work, done)

    def remove_mod(self) -> None:
        profile = self.current_profile()
        mod_ids = self.mod_table.selected_mod_ids()
        if profile is None or not mod_ids:
            return
        removed_names = []
        for mod_id in mod_ids:
            mod = profile.mod_by_id(mod_id)
            if mod is not None:
                removed_names.append(mod.name)
                self.service.remove_mod(profile, mod_id, delete_files=False)
        self.service.save()
        self._update_mod_table(profile)
        self.status_strip.detail.setText(summary_line(profile))
        self._log(f"Моды убраны из профиля ({len(removed_names)}): " + ", ".join(removed_names))

    def delete_mod_files(self) -> None:
        profile = self.current_profile()
        mod_ids = self.mod_table.selected_mod_ids()
        if profile is None or not mod_ids:
            return
        mods_to_delete = [m for m in [profile.mod_by_id(mid) for mid in mod_ids] if m is not None]
        if not mods_to_delete:
            return
        names_str = "\n".join(f"• {m.name}" for m in mods_to_delete[:10])
        if len(mods_to_delete) > 10:
            names_str += f"\n… и ещё {len(mods_to_delete) - 10} модов"
        answer = QMessageBox.question(
            self,
            "Удаление модов",
            f"Убрать и удалить с диска выбранные моды ({len(mods_to_delete)})?\n\n{names_str}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        deleted_names = []
        for mod in mods_to_delete:
            deleted_names.append(mod.name)
            self.service.remove_mod(profile, mod.id, delete_files=True)
        self.service.save()
        self._update_mod_table(profile)
        self.status_strip.detail.setText(summary_line(profile))
        self._log(f"Моды удалены с диска ({len(deleted_names)}): " + ", ".join(deleted_names))

    def import_mo2(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        dialog = Mo2Dialog(self)
        if dialog.exec() != Mo2Dialog.Accepted:
            return
        path, modlist_only, no_overwrite = dialog.values()
        if not path:
            return
        from ..core.mo2 import apply_modlist_only, apply_preview, build_preview

        try:
            preview = build_preview(path)
        except Exception as exc:  # noqa: BLE001
            self._error(f"Не удалось прочитать MO2: {exc}")
            return
        if modlist_only:
            count = apply_modlist_only(profile, preview)
        else:
            count = apply_preview(profile, preview, use_overwrite=not no_overwrite)
        self.service.save()
        self._update_mod_table(profile)
        self._log(f"Импорт MO2: применено записей — {count}")

    # ------------------------------------------------------------------ checks
    def prepare_profile(self, *, force: bool = True) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        if profile.is_standalone:
            self.service.workspace_for(profile).ensure_root()
            self._log("Профиль-сборка: оверлей не нужен")
            return

        def work(progress):
            return self.service.prepare(profile, force=force, progress=progress)

        def done(result):
            plan, workspace, overlay = result
            stats = plan.stats()
            self.report_pane.set_text(
                f"{overlay.summary}\n"
                f"Файлов: {stats.total_files}, пересечений: {stats.overlapping_files}, "
                f"объём: {util.human_size(stats.total_bytes)}\n"
                f"fsgame.ltx: {workspace.fsgame_path}",
                "ok",
            )
            self.tabs.setCurrentWidget(self.report_pane)
            self._log(overlay.summary)
            self._refresh_status_light()

        self._run_task("Сборка оверлея…", work, done)

    def run_checks(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return

        def work(progress):
            plan = self.service.plan_for(profile, progress=progress)
            report = preflight.run(profile, self.service.app, plan=plan, workspace=self.service.workspace_for(profile))
            return report

        def done(report):
            lines = [(check.level, self._format_check(check)) for check in report.checks]
            self.report_pane.set_lines([("plain", report.headline), ("plain", "")] + lines)
            self.tabs.setCurrentWidget(self.report_pane)
            self._status = report
            self._refresh_status_light()

        self._run_task("Проверка профиля…", work, done)

    @staticmethod
    def _format_check(check) -> str:
        hint = f"\n     → {check.hint}" if getattr(check, "hint", "") else ""
        return f"[{check.badge}] {check.title}\n     {check.detail}{hint}"

    def show_conflicts(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return

        def work(progress):
            plan = self.service.plan_for(profile, progress=progress)
            return self.service.conflict_report(profile, plan=plan)

        def done(report):
            text = report.to_text()
            if report.redundant:
                text += "\n\nПолностью перекрытые моды:\n" + "\n".join(
                    f"  • {item.name}" for item in report.redundant
                )
            dialog = ReportDialog(f"Конфликты — {profile.name}", text, self)
            dialog.exec()

        self._run_task("Анализ конфликтов…", work, done)

    def run_audit(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return

        def work(progress):
            plan = self.service.plan_for(profile, progress=progress)
            return self.service.audit_case(profile, plan=plan, fix=False)

        def done(result):
            text = result.to_text()
            if result.issues:
                answer = QMessageBox.question(
                    self,
                    "Аудит регистра",
                    f"Найдено проблем с регистром: {len(result.issues)}.\n\n"
                    "Создать ссылки-алиасы, чтобы движок нашёл файлы?\n"
                    "Это безопасно: файлы модов не изменяются.",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if answer == QMessageBox.Yes:
                    self._audit_fix(profile)
                    return
            dialog = ReportDialog(f"Аудит регистра — {profile.name}", text, self)
            dialog.exec()

        self._run_task("Аудит чувствительности к регистру…", work, done)

    def _audit_fix(self, profile) -> None:
        def work(progress):
            return self.service.audit_case(profile, fix=True)

        def done(result):
            self._log(f"Создано алиасов: {len(result.created)}")
            QMessageBox.information(
                self,
                "Аудит регистра",
                "Создано ссылок-алиасов: "
                + str(len(result.created))
                + "\nОни будут восстанавливаться при каждой пересборке профиля.",
            )

        self._run_task("Создание алиасов…", work, done)

    def save_report(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        try:
            path = self.service.report(profile)
        except CordonError as exc:
            self._error(str(exc))
            return
        self._log(f"Отчёт сохранён: {path}")
        QMessageBox.information(self, "Отчёт", f"Отчёт сохранён:\n{path}")

    # ------------------------------------------------------------------ launch
    def launch_profile(self, *, runner: str = engine_mod.RUNNER_AUTO) -> None:
        profile = self.current_profile()
        if profile is None or self._session_thread is not None:
            return
        if runner != engine_mod.RUNNER_AUTO:
            active, _fallback = engine_mod.select_engines(profile, runner)
            if active is None:
                self._error(
                    f"Режим «{engine_mod.RUNNER_LABELS[runner]}»: подходящий исполняемый файл не найден.\n"
                    "Проверьте каталог игры/движка в настройках профиля."
                )
                return
        if profile.is_standalone:
            self._start_session(profile, force=False, runner=runner)
            return

        def work(progress):
            plan = self.service.plan_for(profile, progress=progress)
            report = preflight.run(profile, self.service.app, plan=plan, workspace=self.service.workspace_for(profile))
            return report

        def done(report):
            self._status = report
            if not report.ok:
                lines = [(check.level, self._format_check(check)) for check in report.checks]
                self.report_pane.set_lines([("plain", report.headline), ("plain", "")] + lines)
                self.tabs.setCurrentWidget(self.report_pane)
                answer = QMessageBox.question(
                    self,
                    "Есть проблемы",
                    f"{report.headline}\n\nВсё равно запустить игру?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return
            self._start_session(profile, force=False, runner=runner)

        self._run_task("Подготовка запуска…", work, done)

    def _start_session(self, profile: Profile, *, force: bool, runner: str = engine_mod.RUNNER_AUTO) -> None:
        self.log_view.clear()
        self.tabs.setCurrentWidget(self.log_view.parentWidget().parentWidget())
        self.progress.setVisible(True)
        self.launch_button.setEnabled(False)
        self.launch_menu.setEnabled(False)
        self.stop_button.setEnabled(True)

        thread = SessionThread(
            profile, self.service.app, service=self.service, force_rebuild=force, runner=runner, parent=self
        )
        thread.line.connect(self._append_game_line)
        thread.started.connect(self._on_game_started)
        thread.finished.connect(self._on_game_finished)
        thread.failed.connect(self._on_game_failed)
        self._session_thread = thread
        thread.start()

    def _on_game_started(self, command_line: str) -> None:
        self._log(f"Запуск: {command_line}")
        self.statusBar().showMessage("Игра запущена")
        self._start_presence()

    # ------------------------------------------------------------------ discord
    def _start_presence(self) -> None:
        profile = self.current_profile()
        if profile is None or not self.settings.discord_presence:
            return
        from ..core.discord import announce_launch

        self._presence = announce_launch(self.settings.discord_client_id, profile.name, game_id=profile.game_id)
        if self._presence is None:
            self._log("Discord не найден — статус не публикуется")
        else:
            self._log("Статус Discord включён")

    def _stop_presence(self) -> None:
        if self._presence is None:
            return
        try:
            self._presence.clear()
            self._presence.close()
        except Exception:  # noqa: BLE001 - presence must never break the UI
            pass
        self._presence = None

    def _append_game_line(self, line: str) -> None:
        self.log_view.appendPlainText(line)
        if self.follow_check.isChecked():
            self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def _on_game_finished(self, code: int, duration: float) -> None:
        self._session_thread = None
        self._stop_presence()
        self.progress.setVisible(False)
        self.launch_button.setEnabled(True)
        self.launch_menu.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.statusBar().showMessage(f"Игра завершилась с кодом {code} за {util.human_duration(duration)}")
        self._log(f"Процесс завершён: код {code}, время сессии {util.human_duration(duration)}")
        profile = self.current_profile()
        if profile is not None:
            self.status_strip.detail.setText(summary_line(profile))
            self.service.save()
        self._load_diagnostics(profile)

    def _on_game_failed(self, message: str) -> None:
        self._session_thread = None
        self._stop_presence()
        self.progress.setVisible(False)
        self.launch_button.setEnabled(True)
        self.launch_menu.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._error(f"Не удалось запустить игру: {message}")

    def stop_game(self) -> None:
        if self._session_thread is None:
            return
        answer = QMessageBox.question(
            self,
            "Остановить игру",
            "Завершить запущенную игру? Несохранённый прогресс будет потерян.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._log("Запрошено завершение игры…")
            self._session_thread.stop()

    # ------------------------------------------------------------------ diagnostics
    def _load_diagnostics(self, profile: Profile | None) -> None:
        if profile is None:
            return
        workspace = self.service.workspace_for(profile)
        diag = diagnostics.collect(workspace.appdata)
        lines = [diag.to_text(), ""]
        overlay_result = workspace.verify()
        lines.append("Проверка оверлея:")
        lines.extend(f"  {line}" for line in overlay_result)
        self.diag_view.setPlainText("\n".join(lines))

    def open_game_log(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        workspace = self.service.workspace_for(profile)
        diag = diagnostics.collect(workspace.appdata)
        if diag.log_path:
            self._open_file(diag.log_path)
        else:
            self._info("Лог не найден", "Игровой лог ещё не создан — сначала запустите игру.")

    def open_user_ltx(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        user_ltx = os.path.join(self.service.workspace_for(profile).appdata, "user.ltx")
        if os.path.isfile(user_ltx):
            self._open_file(user_ltx)
        else:
            self._info("Файл не найден", f"Файл user.ltx ещё не создан:\n{user_ltx}")

    def open_dumps(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        dumps = os.path.join(self.service.workspace_for(profile).appdata, "dumps")
        if os.path.isdir(dumps):
            self._open_file(dumps)
        else:
            self._info("Дампов нет", "Каталог дампов пока не создан.")

    def open_path(self, what: str) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        workspace = self.service.workspace_for(profile)
        mapping = {
            "root": workspace.root,
            "appdata": workspace.appdata,
            "mods": self.service.app.mod_storage(profile.id, profile.mod_storage_path),
        }
        path = mapping[what]
        util.ensure_dir(path)
        self._open_file(path)

    def open_launcher_log(self) -> None:
        path = self.service.app.launcher_log
        if os.path.isfile(path):
            self._open_file(path)
        else:
            self._info("Журнал пуст", "Журнал лаунчера ещё не создан.")

    def _open_file(self, path: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if not os.path.exists(path):
            self._info("Не найдено", path)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _refresh_status_light(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        try:
            plan = self.service.plan_for(profile)
            stats = plan.stats()
            detail = f"{stats.total_files} файлов · {util.human_size(stats.total_bytes)}"
            if stats.overlapping_files:
                detail += f" · пересечений {stats.overlapping_files}"
            self.statusBar().showMessage(detail)
        except Exception:  # noqa: BLE001 - the status bar is cosmetic
            self.statusBar().showMessage("готово")

    # ------------------------------------------------------------------ misc ui
    def _run_task(self, message: str, work, done) -> None:
        if self._task is not None:
            return
        self.progress.setVisible(True)
        self.statusBar().showMessage(message)
        task = Task(work, self)

        def finished(result) -> None:
            self._finish_task()
            try:
                done(result)
            except Exception as exc:  # noqa: BLE001
                self._error(str(exc))

        def failed(text: str) -> None:
            self._finish_task()
            self._error(text)

        task.finished_ok.connect(finished)
        task.failed.connect(failed)
        task.progressed.connect(lambda text: self.statusBar().showMessage(text))
        self._task = task
        task.start()

    def _finish_task(self) -> None:
        self._task = None
        self.progress.setVisible(False)
        self.statusBar().clearMessage()

    def _log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        self.service.logger.info("%s", text)

    def _info(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)

    def _error(self, text: str) -> None:
        self._log("Ошибка: " + text)
        QMessageBox.critical(self, "Ошибка", text)

    def launcher_settings(self) -> None:
        dialog = LauncherSettingsDialog(self.settings, self)
        if dialog.exec() == LauncherSettingsDialog.Accepted:
            dialog.apply_to(self.settings)
            self.service.save()
            self._apply_theme()
            self._log("Настройки лаунчера обновлены")

    def show_about(self) -> None:
        AboutDialog(self.service.app, upstream=UPSTREAM, version=__version__, parent=self).exec()

    # ------------------------------------------------------------------ persistence
    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if not getattr(self, "_sizes_applied", False):
            self.splitter.setSizes([360, max(320, self.width() - 380)])
            self._sizes_applied = True
        if not self._geometry_checked:
            # The window manager may add a title bar or a border: check the real frame on the first
            # paint, once, and pull the window back if it hangs over an edge.
            self._geometry_checked = True
            QTimer.singleShot(0, self._ensure_on_screen)

    def _ensure_on_screen(self) -> None:
        """Keep the *decorated* window inside the available area.

        A window manager adds a title bar and may ignore our preferred size; after the first paint
        the real frame is known, so the window is trimmed and pulled back if needed.
        """
        for _ in range(3):
            rect = geometry_mod.available_rect()
            right, bottom = rect[0] + rect[2], rect[1] + rect[3]
            frame = self.frameGeometry()
            over_width = max(0, frame.width() - rect[2])
            over_height = max(0, frame.height() - rect[3])
            outside_x = max(0, rect[0] - frame.x()) + max(0, frame.x() + frame.width() - right)
            outside_y = max(0, rect[1] - frame.y()) + max(0, frame.y() + frame.height() - bottom)
            if not (over_width or over_height or outside_x or outside_y):
                return
            if over_width or over_height:
                self.resize(
                    max(1, self.width() - over_width),
                    max(1, self.height() - over_height),
                )
            frame = self.frameGeometry()
            dx = self.x() - frame.x()
            dy = self.y() - frame.y()
            x = min(max(frame.x(), rect[0]), max(rect[0], right - frame.width()))
            y = min(max(frame.y(), rect[1]), max(rect[1], bottom - frame.height()))
            self.move(x + dx, y + dy)
        logger = getattr(self.service, "logger", None)
        if logger is not None:
            logger.info("окно подогнано под экран: %sx%s", self.width(), self.height())

    def _restore_geometry(self) -> None:
        geometry = getattr(self.settings, "window_geometry", "")
        if geometry:
            try:
                self.restoreGeometry(bytes.fromhex(geometry))
            except ValueError:  # pragma: no cover - corrupt value in settings
                pass
        # A geometry saved on a bigger monitor would push the window off a small screen.
        x, y, width, height = geometry_mod.clamp_rect(
            self.x(), self.y(), self.width(), self.height(), self._screen
        )
        self.resize(width, height)
        self.move(x, y)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._session_thread is not None:
            answer = QMessageBox.question(
                self,
                "Игра запущена",
                "Игра всё ещё работает. Закрыть лаунчер? Игра продолжит работу.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self._stop_presence()
        try:
            self.settings.window_geometry = bytes(self.saveGeometry().toHex()).decode("ascii")
            self.service.save()
        except Exception:  # noqa: BLE001 - never block closing
            pass
        event.accept()


def start_timer_update(window: MainWindow) -> None:
    """Periodically refresh the played-time of an active profile (cheap, once a minute)."""
    timer = QTimer(window)
    timer.setInterval(60_000)
    timer.timeout.connect(lambda: window.refresh_profiles(select=window.settings.selected_profile_id))
    timer.start()
