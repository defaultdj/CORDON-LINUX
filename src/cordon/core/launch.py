"""Launching a profile.

The command line built here is what makes the whole approach work on Linux:

* ``-fsltx <profile root>/fsgame.ltx`` turns the profile root into the engine's ``$fs_root$``
  (``CLocatorAPI::setup_fs_path`` resolves the *directory* of the given file);
* ``-overlaypath <profile root>/_appdata_`` moves ``$logs$`` and ``$app_data_root$`` to the
  profile, which is exactly what ``CLocatorAPI::_initialize`` does with that switch;
* ``-cs`` is added automatically for Clear Sky resources (CoP is the engine default);
* the working directory becomes the profile root, so every ``$fs_root$``-relative path the
  engine resolves by hand still lands inside the profile.
"""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import diagnostics, layers, preflight, util, winerun, xray
from . import engine as engine_mod
from .errors import LaunchError
from .layers import LayerPlan
from .models import BACKEND_FUSE, WINDOWS_RUNNER_LABELS, LaunchPlan, Profile
from .overlay import ProfileWorkspace
from .paths import AppPaths

LineCallback = Callable[[str], None] | None
ProgressCallback = Callable[[str], None] | None


@dataclass(slots=True)
class LaunchOutcome:
    plan: LaunchPlan
    returncode: int | None = None
    started_at: float = 0.0
    finished_at: float = 0.0
    session_log: str = ""
    diagnostics: diagnostics.SessionDiagnostics | None = None
    report: preflight.PreflightReport | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.finished_at - self.started_at) if self.finished_at else 0.0

    @property
    def crashed(self) -> bool:
        return bool(self.returncode not in (0, None))


def build_launch_plan(
    profile: Profile,
    app: AppPaths,
    *,
    engine: engine_mod.EngineInfo | None = None,
    workspace: ProfileWorkspace | None = None,
    fsgame_path: str = "",
    appdata_path: str = "",
    portproton_path: str = "",
) -> LaunchPlan:
    info = engine or engine_mod.require_engine(profile)
    space = workspace or ProfileWorkspace(app, profile)
    root = space.root
    notes: list[str] = []
    is_windows = info.executable.lower().endswith(".exe")

    # Engine arguments (identical for native and Windows builds; paths are translated below).
    game_args: list[str] = []
    if profile.is_standalone:
        cwd = util.norm(profile.game_path) or info.engine_root
        if profile.isolate_appdata and os.path.isfile(space.fsgame_path):
            game_args += ["-fsltx", space.fsgame_path]
            if profile.use_overlay_path:
                game_args += ["-overlaypath", space.appdata]
                notes.append("данные профиля перенесены ключом -overlaypath")
    else:
        cwd = root
        prepared = fsgame_path or space.fsgame_path
        game_args += ["-fsltx", prepared]
        if profile.use_overlay_path:
            game_args += ["-overlaypath", appdata_path or space.appdata]
            notes.append("$app_data_root$ и $logs$ перенесены в профиль (-overlaypath)")

    game_switch = xray.engine_switch_for(profile.game_id) or info.game_switch
    if game_switch and game_switch not in game_args:
        game_args.append(game_switch)
        notes.append(f"режим игры движка: {game_switch}")

    for flag in profile.engine_flags:
        if flag and flag not in game_args:
            game_args.append(flag)
    try:
        extra = shlex.split(profile.launch_arguments)
    except ValueError as exc:
        raise LaunchError(f"не удалось разобрать дополнительные аргументы профиля: {exc}") from exc
    game_args += extra

    env = os.environ.copy()
    engine_dir = os.path.dirname(info.executable)

    if is_windows:
        # Wine sees the host filesystem as Z:\ — the engine gets Windows-style paths.
        game_args = [
            winerun.to_windows_path(arg) if os.path.isabs(arg) else arg for arg in game_args
        ]
        options = profile.wine_options
        compat_data = os.path.join(root, "proton-prefix")
        custom_prefix = str(options.get("prefix_name") or "").strip()
        if custom_prefix and os.path.isabs(os.path.expanduser(custom_prefix)):
            compat_data = util.norm(os.path.expanduser(custom_prefix))
        util.ensure_dir(compat_data)
        runner = None
        wine_version = str(options.get("wine_version") or "").strip()
        if wine_version and profile.windows_runner == winerun.RUNNER_KIND_PROTON:
            runner = winerun.proton_from_directory(wine_version, compat_data)
            if runner is None:
                notes.append(f"выбранная версия Proton не найдена ({wine_version}) — используется стандартная")
        if runner is None:
            runner = winerun.find_runner(
                preferred=profile.windows_runner, portproton_path=portproton_path, compat_data=compat_data
            )
        if runner is None:
            wanted = WINDOWS_RUNNER_LABELS.get(profile.windows_runner, profile.windows_runner)
            raise LaunchError(
                f"Windows-сборка ({os.path.basename(info.executable)}) требует Proton/Wine, "
                f"но «{wanted}» не найден. Установите PortProton, Proton (Steam) или Wine, "
                "либо укажите путь к PortProton в настройках лаунчера."
            )
        env.update(runner.env)
        env.update(winerun.option_env(options, runner.kind))
        if runner.args_via_ppdb:
            # PortProton ignores anything after the .exe on its command line:
            # arguments and PW_* settings live in <exe>.ppdb.
            ppdb = winerun.write_ppdb_launch_parameters(
                info.executable, game_args, winerun.ppdb_variables(options)
            )
            argv = list(runner.argv) + [info.executable]
            notes.append(f"запуск через {runner.label}; аргументы движка и настройки записаны в {ppdb}")
        else:
            wrappers, wrapper_notes = winerun.option_wrappers(options, runner.kind)
            notes += wrapper_notes
            argv = (
                wrappers
                + list(runner.argv)
                + winerun.wine_virtual_desktop_args(options, runner.kind)
                + [info.executable]
                + game_args
            )
            notes.append(f"запуск Windows-сборки через {runner.describe()}")
            if runner.kind == winerun.RUNNER_KIND_PROTON:
                notes.append(f"префикс Proton: {compat_data}")
            elif runner.kind == winerun.RUNNER_KIND_WINE and "WINEPREFIX" not in env:
                env["WINEPREFIX"] = compat_data
                notes.append(f"WINEPREFIX: {compat_data}")
        # the engine must start next to its DLLs; Wine resolves them relative to cwd/exe dir
        cwd = engine_dir if os.path.isdir(engine_dir) else cwd
    else:
        argv = [info.executable] + game_args
        if info.libraries:
            current = env.get("LD_LIBRARY_PATH", "")
            if engine_dir not in current.split(":"):
                env["LD_LIBRARY_PATH"] = f"{engine_dir}:{current}" if current else engine_dir
                notes.append("LD_LIBRARY_PATH дополнен каталогом движка (portable-сборка)")
    env.setdefault("SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR", "0")

    return LaunchPlan(
        profile_id=profile.id,
        executable=info.executable,
        argv=argv,
        cwd=cwd,
        env=env,
        fsgame_path=fsgame_path or space.fsgame_path,
        root_path=root,
        appdata_path=appdata_path or space.appdata,
        backend=profile.backend,
        notes=notes,
    )


@dataclass(slots=True)
class Session:
    """A running (or completed) game process with live output."""

    plan: LaunchPlan
    process: subprocess.Popen
    log_path: str
    profile: Profile
    workspace: ProfileWorkspace
    started_at: float = field(default_factory=time.time)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _lines: list[str] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _callbacks: list[LineCallback] = field(default_factory=list, repr=False)

    def add_line_callback(self, callback: Callable[[str], None]) -> None:
        self._callbacks.append(callback)

    def start_reader(self) -> None:
        def reader() -> None:
            stream = self.process.stdout
            if stream is None:  # pragma: no cover
                return
            try:
                with open(self.log_path, "a", encoding="utf-8", errors="replace") as handle:
                    for line in stream:
                        text = line.rstrip("\n")
                        with self._lock:
                            self._lines.append(text)
                        handle.write(text + "\n")
                        handle.flush()
                        for callback in list(self._callbacks):
                            try:
                                callback(text)
                            except Exception:  # noqa: BLE001 - UI callbacks must not kill the reader
                                pass
            except (OSError, ValueError):  # pragma: no cover - stream closed on exit
                pass

        self._thread = threading.Thread(target=reader, name="cordon-session-reader", daemon=True)
        self._thread.start()

    def lines(self, count: int = 400) -> list[str]:
        with self._lock:
            return self._lines[-count:]

    def wait_for_reader(self, timeout: float = 5.0) -> None:
        """Wait for the output reader to drain the pipe after the process has exited."""
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def running(self) -> bool:
        return self.process.poll() is None

    def stop(self, *, timeout: float = 10.0) -> int:
        """Terminate the whole session.

        The engine may sit behind wrappers (PortProton's ``start.sh``, ``gamemoderun``,
        ``systemd-inhibit``); the session runs in its own process group, so the signal goes to
        the group and the game itself receives it too, not just the outer script.
        """
        if self.process.poll() is None:
            self._signal_group(signal.SIGTERM)
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:  # pragma: no cover
                self._signal_group(signal.SIGKILL)
        return int(self.process.wait())

    def _signal_group(self, sig: int) -> None:
        try:
            os.killpg(os.getpgid(self.process.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                self.process.send_signal(sig)
            except OSError:  # pragma: no cover
                pass


def prepare_launch(
    profile: Profile,
    app: AppPaths,
    *,
    force_rebuild: bool = False,
    progress: ProgressCallback = None,
    logger=None,
    engine: engine_mod.EngineInfo | None = None,
    plan: LayerPlan | None = None,
) -> tuple[LaunchPlan, ProfileWorkspace, engine_mod.EngineInfo]:
    """Build the overlay (if needed) and return the exact command line that *would* be run."""
    info = engine or engine_mod.require_engine(profile)
    workspace = ProfileWorkspace(app, profile, logger=logger)
    if not profile.is_standalone:
        layer_plan = plan or layers.build_plan(profile, engine_data_path=info.data_root)
        if not layer_plan.entries:
            layer_plan.index(progress)
        workspace.prepare(layer_plan, engine_executable=info.executable, force=force_rebuild, progress=progress)
        try:
            from . import audit as audit_mod

            created = audit_mod.apply_aliases(workspace.root, logger=logger)
            if created and logger:
                logger.info("восстановлено алиасов регистра: %d", created)
        except Exception as exc:  # noqa: BLE001 - aliases are best effort
            if logger:
                logger.warning("не удалось применить алиасы регистра: %s", exc)
    else:
        workspace.ensure_root()
    launch_plan = build_launch_plan(profile, app, engine=info, workspace=workspace)
    return launch_plan, workspace, info


def spawn(launch_plan: LaunchPlan, workspace: ProfileWorkspace, profile: Profile, *, logger=None) -> Session:
    """Start a previously prepared launch plan."""
    log_path = os.path.join(workspace.root, "logs", "cordon-session.log")
    util.ensure_dir(os.path.dirname(log_path))
    if logger:
        logger.info("запуск: %s", launch_plan.command_line)
        logger.info("рабочий каталог: %s", launch_plan.cwd)
    header = (f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} запуск профиля «{profile.name}» =====\n"
              f"$ {launch_plan.command_line}\n")
    with open(log_path, "a", encoding="utf-8", errors="replace") as handle:
        handle.write(header)
    try:
        process = subprocess.Popen(
            launch_plan.argv,
            cwd=launch_plan.cwd,
            env=launch_plan.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
    except OSError as exc:
        raise LaunchError(f"не удалось запустить {launch_plan.executable}: {exc}") from exc
    session = Session(plan=launch_plan, process=process, log_path=log_path, profile=profile, workspace=workspace)
    session.start_reader()
    return session


def start_session(
    profile: Profile,
    app: AppPaths,
    *,
    prepare: bool = True,
    force_rebuild: bool = False,
    progress: ProgressCallback = None,
    logger=None,
    engine: engine_mod.EngineInfo | None = None,
    plan: LayerPlan | None = None,
) -> Session:
    """Prepare the overlay if needed and start the engine."""
    if not prepare:
        info = engine or engine_mod.require_engine(profile)
        workspace = ProfileWorkspace(app, profile, logger=logger)
        workspace.ensure_root()
        launch_plan = build_launch_plan(profile, app, engine=info, workspace=workspace)
        return spawn(launch_plan, workspace, profile, logger=logger)
    launch_plan, workspace, _info = prepare_launch(
        profile, app, force_rebuild=force_rebuild, progress=progress, logger=logger, engine=engine, plan=plan
    )
    return spawn(launch_plan, workspace, profile, logger=logger)


def finish_session(
    session: Session,
    app: AppPaths,
    *,
    logger=None,
    unmount: bool = True,
) -> LaunchOutcome:
    """Collect statistics and diagnostics after the game exited."""
    returncode = session.process.wait()
    session.wait_for_reader()
    finished = time.time()
    started = session.started_at
    duration = max(0.0, finished - started)
    session.profile.mark_played(duration)
    outcome = LaunchOutcome(
        plan=session.plan,
        returncode=returncode,
        started_at=started,
        finished_at=finished,
        session_log=session.log_path,
    )
    try:
        outcome.diagnostics = diagnostics.collect(session.workspace.appdata, since=started)
    except Exception as exc:  # noqa: BLE001 - diagnostics are best effort
        if logger:
            logger.warning("не удалось собрать диагностику: %s", exc)
    if unmount and session.profile.backend == BACKEND_FUSE:
        try:
            session.workspace.unmount()
        except Exception as exc:  # noqa: BLE001
            if logger:
                logger.warning("не удалось отмонтировать оверлей: %s", exc)
    if logger:
        logger.info(
            "процесс завершён с кодом %s, время сессии %s",
            returncode,
            util.human_duration(duration),
        )
    return outcome


def run_profile(
    profile: Profile,
    app: AppPaths,
    *,
    dry_run: bool = False,
    force_rebuild: bool = False,
    progress: ProgressCallback = None,
    line_callback: LineCallback = None,
    logger=None,
    runner: str = engine_mod.RUNNER_AUTO,
) -> LaunchOutcome | LaunchPlan:
    """Blocking convenience wrapper used by the CLI and the tests."""
    active_engine, fallback_engine = engine_mod.select_engines(profile, runner)
    if runner != engine_mod.RUNNER_AUTO and active_engine is None:
        raise LaunchError(f"режим «{engine_mod.RUNNER_LABELS[runner]}»: подходящий исполняемый файл не найден")

    if dry_run:
        launch_plan, _workspace, _info = prepare_launch(
            profile, app, force_rebuild=force_rebuild, progress=progress, logger=logger, engine=active_engine
        )
        return launch_plan

    if fallback_engine is not None and logger:
        logger.info("🚀 [Нативный запуск] Попытка запуска через системный OpenXRay (%s)...", active_engine.executable)

    session = start_session(
        profile,
        app,
        force_rebuild=force_rebuild,
        progress=progress,
        logger=logger,
        engine=active_engine,
    )
    if line_callback:
        session.add_line_callback(line_callback)
    outcome = finish_session(session, app, logger=logger)

    if outcome.crashed and fallback_engine is not None and getattr(profile, "auto_proton_fallback", True):
        if logger:
            logger.warning(
                "⚠️ Нативный OpenXRay завершился с ошибкой (код %s). Запуск .exe через Proton/Wine (%s)...",
                outcome.returncode,
                fallback_engine.executable,
            )
        if line_callback:
            line_callback(
                f"⚠️ Нативный OpenXRay завершился с ошибкой (код {outcome.returncode}). "
                f"Переключение на запуск .exe через Proton/Wine ({fallback_engine.executable})..."
            )
        session = start_session(
            profile,
            app,
            force_rebuild=False,
            logger=logger,
            engine=fallback_engine,
        )
        if line_callback:
            line_callback(session.plan.command_line)
        return finish_session(session, app, logger=logger)

    return outcome


def engine_for(profile: Profile) -> engine_mod.EngineInfo | None:
    return engine_mod.find_engine(profile)


def open_in_file_manager(path: str) -> bool:
    """Open a directory in the desktop file manager (used by the GUI and CLI)."""
    for tool in ("xdg-open", "gio", "nautilus", "dolphin", "thunar", "pcmanfm"):
        if shutil.which(tool):
            command = [tool, "open", path] if tool == "gio" else [tool, path]
            try:
                subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:  # pragma: no cover
                continue
    return False


def describe_launch(plan: LaunchPlan) -> str:
    lines = [
        f"Исполняемый файл: {plan.executable}",
        f"Рабочий каталог:   {plan.cwd}",
        f"Команда:           {plan.command_line}",
        f"Каталог профиля:   {plan.root_path}",
        f"Данные профиля:    {plan.appdata_path}",
    ]
    if plan.notes:
        lines.append("Примечания:")
        lines.extend(f"  • {note}" for note in plan.notes)
    return "\n".join(lines)
