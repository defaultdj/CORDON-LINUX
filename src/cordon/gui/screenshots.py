"""Gallery widget and preview dialog for game screenshots."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import screenshots as ss_mod
from ..core import util
from .widgets import make_button


class ScreenshotViewerDialog(QDialog):
    """Full-size image preview dialog for screenshots."""

    def __init__(self, item: ss_mod.ScreenshotItem, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Скриншот — {item.filename}")
        self.resize(1000, 700)

        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(item.path)
        if not pixmap.isNull():
            self.image_label.setPixmap(pixmap)
        else:
            self.image_label.setText("Не удалось загрузить изображение")
        scroll.setWidget(self.image_label)
        layout.addWidget(scroll, 1)

        info = QLabel(f"{item.filename}  ·  {item.size_display}  ·  {item.date_display}")
        info.setObjectName("dim")
        layout.addWidget(info)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class ScreenshotsPane(QWidget):
    """Gallery grid/list of profile screenshots with preview and actions."""

    screenshot_deleted = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._appdata_path = ""
        self._items: list[ss_mod.ScreenshotItem] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        toolbar = QHBoxLayout()
        refresh_btn = make_button("Обновить")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        open_folder_btn = make_button("Открыть папку")
        open_folder_btn.clicked.connect(self._open_folder)
        toolbar.addWidget(open_folder_btn)

        copy_btn = make_button("Скопировать изображение")
        copy_btn.clicked.connect(self._copy_image)
        toolbar.addWidget(copy_btn)

        delete_btn = make_button("Удалить")
        delete_btn.clicked.connect(self._delete_selected)
        toolbar.addWidget(delete_btn)

        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(180, 120))
        self.list_widget.setViewMode(QListWidget.IconMode)
        self.list_widget.setResizeMode(QListWidget.Adjust)
        self.list_widget.setMovement(QListWidget.Static)
        self.list_widget.setSpacing(10)
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_widget.itemDoubleClicked.connect(self._open_viewer)
        layout.addWidget(self.list_widget, 1)

        self.summary_label = QLabel("Скриншоты не найдены")
        self.summary_label.setObjectName("dim")
        layout.addWidget(self.summary_label)

    def set_appdata(self, appdata_path: str) -> None:
        self._appdata_path = appdata_path
        self.refresh()

    def refresh(self) -> None:
        self.list_widget.clear()
        if not self._appdata_path:
            self.summary_label.setText("Профиль не выбран")
            return

        self._items = ss_mod.list_screenshots(self._appdata_path)
        if not self._items:
            self.summary_label.setText("В этом профиле пока нет скриншотов")
            return

        for item in self._items:
            pixmap = QPixmap(item.path)
            if not pixmap.isNull():
                thumb = pixmap.scaled(180, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon = QIcon(thumb)
            else:
                icon = QIcon()

            list_item = QListWidgetItem(icon, f"{item.filename}\n{item.size_display}")
            list_item.setData(Qt.UserRole, item)
            list_item.setToolTip(f"{item.filename}\nРазмер: {item.size_display}\nДата: {item.date_display}")
            self.list_widget.addItem(list_item)

        self.summary_label.setText(f"Скриншотов в профиле: {len(self._items)}")

    def _selected_item(self) -> ss_mod.ScreenshotItem | None:
        curr = self.list_widget.currentItem()
        if curr:
            return curr.data(Qt.UserRole)
        return None

    def _open_viewer(self, item: QListWidgetItem) -> None:
        data: ss_mod.ScreenshotItem = item.data(Qt.UserRole)
        if data:
            dialog = ScreenshotViewerDialog(data, self)
            dialog.exec()

    def _open_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        folder = os.path.join(util.norm(self._appdata_path), "screenshots")
        util.ensure_dir(folder)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _copy_image(self) -> None:
        from PySide6.QtWidgets import QApplication

        item = self._selected_item()
        if item is None:
            QMessageBox.warning(self, "Выбор скриншота", "Выберите скриншот для копирования.")
            return
        pixmap = QPixmap(item.path)
        if not pixmap.isNull():
            QApplication.clipboard().setPixmap(pixmap)
            QMessageBox.information(self, "Скопировано", f"Скриншот «{item.filename}» скопирован в буфер обмена.")
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось прочитать изображение.")

    def _delete_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            QMessageBox.warning(self, "Выбор скриншота", "Выберите скриншот для удаления.")
            return
        answer = QMessageBox.question(
            self,
            "Удаление скриншота",
            f"Удалить скриншот «{item.filename}»?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            if ss_mod.delete_screenshot(item.path):
                self.refresh()
                self.screenshot_deleted.emit()
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось удалить файл скриншота.")
