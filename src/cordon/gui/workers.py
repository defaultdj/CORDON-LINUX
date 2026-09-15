"""Threading helpers: long tasks (overlay build, archive install, launching) run off the GUI
thread and report back through Qt signals."""

from __future__ import annotations

import traceback
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal


class Task(QThread):
    """Run ``work`` in a worker thread; ``work`` receives a ``progress(str)`` callback."""

    progressed = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, work: Callable[[Callable[[str], None]], object], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._work = work

    def run(self) -> None:  # pragma: no cover - exercised through the GUI
        try:
            result = self._work(lambda text: self.progressed.emit(text))
        except Exception as exc:  # noqa: BLE001 - report any failure to the UI
            details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.failed.emit(details)
            return
        self.finished_ok.emit(result)


class SessionThread(QThread):
    """A running game process; emits output lines and the final exit code."""

    line = Signal(str)
    started = Signal(str)
    finished = Signal(int, float)
    failed = Signal(str)

    def __init__(self, profile, app, *, service, force_rebuild: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._profile = profile
        self._app = app
        self._service = service
        self._force = force_rebuild
        self._session = None
        self._stop_requested = False

    def run(self) -> None:  # pragma: no cover - needs a real game process
        from ..core import engine as engine_mod
        from ..core.launch import finish_session, start_session

        target_engine = engine_mod.find_engine(self._profile)
        native_engine = (
            engine_mod.find_native_fallback_engine(self._profile)
            if getattr(self._profile, "prefer_native_openxray", True)
            else None
        )

        use_native_first = (
            native_engine is not None
            and target_engine is not None
            and target_engine.executable.lower().endswith(".exe")
            and getattr(self._profile, "auto_proton_fallback", True)
        )

        active_engine = native_engine if use_native_first else target_engine

        try:
            if use_native_first:
                self.line.emit(f"… 🚀 Попытка нативного запуска через OpenXRay ({active_engine.executable})")
            self._session = start_session(
                self._profile,
                self._app,
                force_rebuild=self._force,
                progress=lambda text: self.line.emit(f"… {text}"),
                logger=self._service.logger,
                engine=active_engine,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return

        self.started.emit(self._session.plan.command_line)
        self._session.add_line_callback(self.line.emit)
        while self._session.running() and not self._stop_requested:
            self.msleep(200)

        outcome = finish_session(self._session, self._app, logger=self._service.logger)

        fallback_engine = None
        if outcome.crashed and not self._stop_requested and getattr(self._profile, "auto_proton_fallback", True):
            if use_native_first and target_engine and target_engine.executable.lower().endswith(".exe"):
                fallback_engine = target_engine
            elif active_engine and not active_engine.executable.lower().endswith(".exe"):
                fallback_engine = engine_mod.find_windows_fallback_engine(self._profile)

        if fallback_engine is not None and not self._stop_requested:
            self.line.emit(
                f"⚠️ Запуск нативного OpenXRay завершился с ошибкой (код {outcome.returncode}). "
                f"Автоматический переключатель на Proton/Wine ({fallback_engine.executable})..."
            )
            try:
                self._session = start_session(
                    self._profile,
                    self._app,
                    force_rebuild=False,
                    logger=self._service.logger,
                    engine=fallback_engine,
                )
                self.started.emit(self._session.plan.command_line)
                self._session.add_line_callback(self.line.emit)
                while self._session.running() and not self._stop_requested:
                    self.msleep(200)
                outcome = finish_session(self._session, self._app, logger=self._service.logger)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(str(exc))
                return

        self.finished.emit(int(outcome.returncode or 0), outcome.duration)

    def stop(self) -> None:
        self._stop_requested = True
        if self._session is not None:
            self._session.stop()

    @property
    def session(self):
        return self._session
