"""End-to-end launch against a real (but harmless) executable.

The engine executable is replaced with a copy of ``/usr/bin/true`` (or ``/bin/true``), so the
whole path is exercised for real: overlay preparation, command line building, ``Popen``, log
writing, exit code handling and playtime accounting.
"""

from __future__ import annotations

import os
import shutil

import pytest

from cordon import cli
from cordon.core import launch, util

TRUE_BINARY = shutil.which("true") or "/bin/true"


def _engine_as_true(fake_install) -> str:
    target = os.path.join(fake_install.game, "bin", "xr_3da")
    shutil.copy2(TRUE_BINARY, target)
    os.chmod(target, 0o755)
    return target


@pytest.fixture()
def true_engine(fake_install):
    if not os.path.isfile(TRUE_BINARY):  # pragma: no cover - non POSIX host
        pytest.skip("нет /bin/true")
    return _engine_as_true(fake_install)


def test_run_profile_starts_a_real_process(true_engine, fake_install, fake_profile):
    outcome = launch.run_profile(fake_profile, fake_install.store)
    assert outcome.returncode == 0
    assert not outcome.crashed
    assert os.path.isfile(outcome.session_log)
    log = util.read_text(outcome.session_log)
    assert "запуск профиля" in log
    assert "-fsltx" in log
    # the profile is marked as played even for a zero length session
    assert fake_profile.last_played_at is not None
    assert outcome.duration >= 0.0


def test_session_captures_output_and_unmounts(fake_install, fake_profile):
    """A tiny shell script instead of the engine, so stdout can be checked."""
    script = os.path.join(fake_install.game, "bin", "xr_3da")
    util.write_text_atomic(
        script,
        "#!/bin/sh\n"
        'echo "X-Ray 1.6 OpenXRay"\n'
        'echo "! cannot find texture: bug"\n'
        "exit 3\n",
    )
    os.chmod(script, 0o755)

    session = launch.start_session(fake_profile, fake_install.store)
    outcome = launch.finish_session(session, fake_install.store)
    assert outcome.returncode == 3
    assert outcome.crashed
    lines = session.lines()
    assert any("OpenXRay" in line for line in lines)
    assert any(line.startswith("!") for line in lines)
    assert os.path.isfile(session.log_path)
    assert "cannot find texture" in util.read_text(session.log_path)
    assert outcome.diagnostics is not None


def test_overlay_is_rebuilt_before_the_first_launch(true_engine, fake_install, fake_profile):
    workspace = launch.finish_session(
        launch.start_session(fake_profile, fake_install.store), fake_install.store
    )
    assert workspace.returncode == 0
    assert os.path.isfile(os.path.join(fake_install.store.profiles_root, "profile-p001", "fsgame.ltx"))


def test_launch_records_arguments_in_the_session_log(true_engine, fake_install, fake_profile):
    fake_profile.engine_flags = ["-nosplash"]
    fake_profile.launch_arguments = "-nointro"
    outcome = launch.run_profile(fake_profile, fake_install.store)
    log = util.read_text(outcome.session_log)
    assert "-nosplash -nointro" in log


def test_cli_detach_returns_immediately(true_engine, fake_install, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CORDON_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("CORDON_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CORDON_CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["new", "Detach", "--game", fake_install.game]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["launch", "Detach", "--detach"]) == cli.EXIT_OK
    output = capsys.readouterr().out
    assert "Игра запущена (pid" in output
    assert "не будет ждать" in output


def test_cli_launch_reports_the_exit_code(true_engine, fake_install, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CORDON_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("CORDON_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CORDON_CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["new", "True", "--game", fake_install.game]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["launch", "True"]) == cli.EXIT_OK
    assert "кодом 0" in capsys.readouterr().out


def test_cli_launch_blocks_on_broken_profile(fake_install, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CORDON_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("CORDON_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CORDON_CACHE_DIR", str(tmp_path / "cache"))
    assert cli.main(["new", "Пустой"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["launch", "Пустой"]) == cli.EXIT_BLOCKED
    assert "заблокирован" in capsys.readouterr().err


def test_unmount_is_safe_without_a_mount(fake_install, fake_profile):
    workspace = launch.prepare_launch(fake_profile, fake_install.store)[1]
    workspace.unmount()  # must not raise: nothing is mounted


def _fake_exe_info(fake_install):
    from cordon.core import elf
    from cordon.core.engine import EngineInfo

    exe_path = os.path.join(fake_install.game, "bin", "xrEngine.exe")
    util.write_text_atomic(exe_path, "MZ_fake_pe")
    return EngineInfo(
        executable=exe_path,
        binary=elf.BinaryInfo(path=exe_path, kind="pe", bits=64, machine="x86_64"),
        engine_root=os.path.join(fake_install.game, "bin"),
        game_root=fake_install.game,
        data_root=fake_install.game,
    )


def _isolated_runners(monkeypatch, tmp_path):
    """No PortProton/Proton/Wine leaks in from the developer's machine."""
    from cordon.core import winerun

    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(winerun, "PORTPROTON_ROOTS", ())
    monkeypatch.setattr(winerun, "STEAM_ROOTS", ())
    monkeypatch.setattr(winerun, "_flatpak_has", lambda *_args: False)
    return winerun


def _fake_tool(directory, name):
    path = os.path.join(directory, name)
    util.write_text_atomic(path, "#!/bin/sh\nexit 0\n")
    os.chmod(path, 0o755)
    return path


def test_exe_via_wine_gets_windows_paths(fake_install, fake_profile, monkeypatch, tmp_path):
    winerun = _isolated_runners(monkeypatch, tmp_path)
    wine = _fake_tool(str(tmp_path / "bin"), "wine")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))

    plan = launch.build_launch_plan(fake_profile, fake_install.store, engine=_fake_exe_info(fake_install))
    assert plan.argv[0] == wine
    assert plan.argv[1].endswith("xrEngine.exe")
    fsltx = plan.argv[plan.argv.index("-fsltx") + 1]
    assert fsltx.startswith("Z:\\") and "/" not in fsltx, fsltx
    assert fsltx == winerun.to_windows_path(plan.fsgame_path)
    assert plan.cwd == os.path.join(fake_install.game, "bin")


def test_exe_via_proton_sets_compat_env(fake_install, fake_profile, monkeypatch, tmp_path):
    _isolated_runners(monkeypatch, tmp_path)
    proton = _fake_tool(str(tmp_path / "bin"), "proton")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))

    plan = launch.build_launch_plan(fake_profile, fake_install.store, engine=_fake_exe_info(fake_install))
    assert plan.argv[:2] == [proton, "run"]
    assert plan.env["STEAM_COMPAT_DATA_PATH"] == os.path.join(plan.root_path, "proton-prefix")
    assert os.path.isdir(plan.env["STEAM_COMPAT_DATA_PATH"])
    assert plan.env["STEAM_COMPAT_CLIENT_INSTALL_PATH"]


def test_exe_via_portproton_writes_ppdb(fake_install, fake_profile, monkeypatch, tmp_path):
    winerun = _isolated_runners(monkeypatch, tmp_path)
    portproton = _fake_tool(str(tmp_path / "bin"), "portproton")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    info = _fake_exe_info(fake_install)
    # PortProton's own settings in the .ppdb must survive
    util.write_text_atomic(info.executable + ".ppdb", '#!/usr/bin/env bash\nexport PW_PREFIX_NAME="STALKER"\n')

    plan = launch.build_launch_plan(fake_profile, fake_install.store, engine=info)
    assert plan.argv == [portproton, "cli", "--launch", info.executable], plan.argv
    ppdb = util.read_text(info.executable + ".ppdb")
    assert 'export PW_PREFIX_NAME="STALKER"' in ppdb
    assert "export LAUNCH_PARAMETERS=" in ppdb
    assert "-fsltx" in ppdb and "Z:\\\\" in ppdb, ppdb  # backslashes doubled for bash
    assert winerun.PPDB_BLOCK_BEGIN in ppdb
    # rewriting keeps exactly one LAUNCH_PARAMETERS line
    launch.build_launch_plan(fake_profile, fake_install.store, engine=info)
    assert util.read_text(info.executable + ".ppdb").count("export LAUNCH_PARAMETERS=") == 1


def test_exe_without_any_runner_is_a_clear_error(fake_install, fake_profile, monkeypatch, tmp_path):
    _isolated_runners(monkeypatch, tmp_path)
    with pytest.raises(launch.LaunchError, match="PortProton"):
        launch.build_launch_plan(fake_profile, fake_install.store, engine=_fake_exe_info(fake_install))


def test_profile_can_pin_the_windows_runner(fake_install, fake_profile, monkeypatch, tmp_path):
    _isolated_runners(monkeypatch, tmp_path)
    _fake_tool(str(tmp_path / "bin"), "portproton")
    wine = _fake_tool(str(tmp_path / "bin"), "wine")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    fake_profile.windows_runner = "wine"

    plan = launch.build_launch_plan(fake_profile, fake_install.store, engine=_fake_exe_info(fake_install))
    assert plan.argv[0] == wine


def test_portproton_found_through_explicit_path(fake_install, fake_profile, monkeypatch, tmp_path):
    winerun = _isolated_runners(monkeypatch, tmp_path)
    root = tmp_path / "PortProton"
    start = _fake_tool(str(root / "data" / "scripts"), "start.sh")
    runner = winerun.find_portproton(str(root))
    assert runner is not None and runner.path == start
    assert winerun.find_portproton("") is None


def test_to_windows_path():
    from cordon.core import winerun

    assert winerun.to_windows_path("/home/u/game/fsgame.ltx") == "Z:\\home\\u\\game\\fsgame.ltx"
    assert winerun.to_windows_path("-nointro") == "-nointro"


def test_automatic_proton_fallback_on_crash(fake_install, fake_profile, monkeypatch):
    fake_profile.executable_relative = "bin/xrEngine.exe"
    exe_file = os.path.join(fake_install.game, "bin", "xrEngine.exe")
    util.write_text_atomic(exe_file, "MZ_fake_pe")
    os.chmod(exe_file, 0o755)

    fake_proton = os.path.join(fake_install.game, "bin", "proton")
    util.write_text_atomic(fake_proton, "#!/bin/sh\nexit 0\n")
    os.chmod(fake_proton, 0o755)
    monkeypatch.setenv("PATH", f"{os.path.dirname(fake_proton)}:{os.environ.get('PATH', '')}")

    outcome = launch.run_profile(fake_profile, fake_install.store)
    assert outcome.returncode == 0
    assert not outcome.crashed
    log_content = util.read_text(outcome.session_log).lower()
    assert "proton" in log_content or "wine" in log_content


# --------------------------------------------------------------------------- wine options
def test_wine_options_reach_the_ppdb(fake_install, fake_profile, monkeypatch, tmp_path):
    winerun = _isolated_runners(monkeypatch, tmp_path)
    _fake_tool(str(tmp_path / "bin"), "portproton")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    info = _fake_exe_info(fake_install)
    fake_profile.wine_options.update(
        {"esync": False, "gamemode": True, "wine_version": "WINE_LG", "prefix_name": "STALKER",
         "dll_overrides": "dinput8=n", "extra_env": "PW_VKBASALT=1\n# comment\nbad line"}
    )
    # a stale single-line record from an older CordonIX plus PortProton's own value
    util.write_text_atomic(
        info.executable + ".ppdb",
        f'#!/usr/bin/env bash\nexport PW_MANGOHUD="1"\n{winerun.PPDB_MARKER}\nexport LAUNCH_PARAMETERS="-old"\n',
    )

    launch.build_launch_plan(fake_profile, fake_install.store, engine=info)
    ppdb = util.read_text(info.executable + ".ppdb")
    assert 'export PW_USE_ESYNC="0"' in ppdb
    assert 'export PW_USE_GAMEMODE="1"' in ppdb
    assert 'export PW_WINE_USE="WINE_LG"' in ppdb
    assert 'export PW_PREFIX_NAME="STALKER"' in ppdb
    assert 'export WINEDLLOVERRIDES="dinput8=n"' in ppdb
    assert 'export PW_VKBASALT="1"' in ppdb
    assert "bad line" not in ppdb and "-old" not in ppdb
    # PortProton's own line survives, but our block (later in the file) wins
    lines = ppdb.splitlines()
    assert lines.index('export PW_MANGOHUD="1"') < lines.index('export PW_MANGOHUD="0"')
    # idempotent
    launch.build_launch_plan(fake_profile, fake_install.store, engine=info)
    assert util.read_text(info.executable + ".ppdb").count(winerun.PPDB_BLOCK_BEGIN) == 1


def test_wine_options_become_env_for_proton_and_wine(fake_install, fake_profile, monkeypatch, tmp_path):
    _isolated_runners(monkeypatch, tmp_path)
    _fake_tool(str(tmp_path / "bin"), "proton")
    gamemoderun = _fake_tool(str(tmp_path / "bin"), "gamemoderun")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    fake_profile.wine_options.update({"esync": False, "ntsync": True, "gamemode": True, "mangohud": True,
                                      "inhibit_sleep": False, "dll_overrides": "d3d9=n,b"})
    plan = launch.build_launch_plan(fake_profile, fake_install.store, engine=_fake_exe_info(fake_install))
    assert plan.argv[0] == gamemoderun
    assert plan.env["PROTON_NO_ESYNC"] == "1" and plan.env["PROTON_USE_NTSYNC"] == "1"
    assert "PROTON_NO_FSYNC" not in plan.env
    assert plan.env["MANGOHUD"] == "1" and plan.env["WINEDLLOVERRIDES"] == "d3d9=n,b"

    fake_profile.windows_runner = "wine"
    _fake_tool(str(tmp_path / "bin"), "wine")
    plan = launch.build_launch_plan(fake_profile, fake_install.store, engine=_fake_exe_info(fake_install))
    assert plan.env["WINEESYNC"] == "0" and plan.env["WINEFSYNC"] == "1" and plan.env["WINENTSYNC"] == "1"
    assert plan.env["WINEPREFIX"] == os.path.join(plan.root_path, "proton-prefix")


def test_profile_can_pin_a_proton_install_dir(fake_install, fake_profile, monkeypatch, tmp_path):
    _isolated_runners(monkeypatch, tmp_path)
    _fake_tool(str(tmp_path / "bin"), "proton")
    ge = _fake_tool(str(tmp_path / "GE-Proton9-20"), "proton")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    fake_profile.windows_runner = "proton"
    fake_profile.wine_options["wine_version"] = str(tmp_path / "GE-Proton9-20")
    fake_profile.wine_options["prefix_name"] = str(tmp_path / "shared-prefix")
    plan = launch.build_launch_plan(fake_profile, fake_install.store, engine=_fake_exe_info(fake_install))
    assert plan.argv[:2] == [ge, "run"]
    assert plan.env["STEAM_COMPAT_DATA_PATH"] == str(tmp_path / "shared-prefix")


def test_wine_options_survive_round_trip_and_drop_junk():
    from cordon.core.models import Profile

    profile = Profile.from_dict({"id": "x", "name": "n", "wine_options": {"esync": 0, "bogus": 1, "windows_version": 7}})
    assert profile.wine_options["esync"] is False
    assert profile.wine_options["fsync"] is True
    assert profile.wine_options["windows_version"] == "7"
    assert "bogus" not in profile.wine_options
    assert Profile.from_dict(profile.to_dict()).wine_options == profile.wine_options


# --------------------------------------------------------------------------- standalone + native
def test_standalone_native_run_merges_engine_data(fake_install, tmp_path, monkeypatch):
    """A standalone build on the system OpenXRay needs /usr/share/openxray shaders: overlay + -fsltx."""
    from cordon.core import elf, layers
    from cordon.core.engine import EngineInfo
    from cordon.core.models import Profile

    _isolated_runners(monkeypatch, tmp_path)
    profile = Profile(id="s1", name="Сборка", kind="standalone", game_path=fake_install.game)
    profile.normalize()
    native = EngineInfo(
        executable=os.path.join(fake_install.game, "bin", "xr_3da"),
        binary=elf.BinaryInfo(path=os.path.join(fake_install.game, "bin", "xr_3da"), kind="elf", bits=64, machine="x86_64"),
        engine_root=os.path.join(fake_install.game, "bin"),
        game_root=fake_install.game,
        data_root=fake_install.engine_data,
    )
    plan = layers.build_plan(profile, engine_data_path=fake_install.engine_data)
    assert [layer.kind for layer in plan.layers] == ["engine", "game"]
    assert layers.needs_overlay(profile, plan)

    launch_plan, workspace, _ = launch.prepare_launch(profile, fake_install.store, engine=native)
    assert os.path.isfile(workspace.fsgame_path)
    assert "-fsltx" in launch_plan.argv
    assert launch_plan.cwd == workspace.root
    assert os.path.exists(os.path.join(workspace.root, "gamedata", "shaders", "gl", "common.h"))

    # the same profile through its own .exe runs in place again and the merged overlay is dropped
    exe = _fake_exe_info(fake_install)
    exe.data_root = fake_install.game
    plan_exe = layers.build_plan(profile, engine_data_path=exe.data_root)
    assert not layers.needs_overlay(profile, plan_exe)
    workspace.ensure_root()
    assert os.path.isfile(workspace.manifest_path)
    with pytest.raises(launch.LaunchError):  # no Wine in the isolated PATH — but the overlay reset happens first
        launch.prepare_launch(profile, fake_install.store, engine=exe)
    assert not os.path.isfile(workspace.manifest_path) and not os.path.isfile(workspace.fsgame_path)


def test_standalone_exe_never_gets_engine_overlay(fake_install, tmp_path, monkeypatch):
    """Regression: an .exe engine whose EngineInfo carries the system data root must still run in place.

    Otherwise the launcher builds a merged overlay and passes ``-fsltx Z:\\...\\fsgame.ltx`` to
    xrEngine.exe, which fails with «Cannot open file fsgame.ltx».
    """
    import os

    from cordon.core import launch, layers
    from cordon.core.models import Profile

    _isolated_runners(monkeypatch, tmp_path)
    profile = Profile(id="s2", name="Сборка", kind="standalone", game_path=fake_install.game)
    exe = _fake_exe_info(fake_install)
    exe.data_root = fake_install.engine_data  # what find_engine() may report on a system with openxray installed
    workspace = launch.ProfileWorkspace(fake_install.store, profile)
    with pytest.raises(launch.LaunchError):  # no Wine in PATH; the overlay decision happens before that
        launch.prepare_launch(profile, fake_install.store, engine=exe)
    assert not os.path.isfile(workspace.manifest_path)
    assert not os.path.isfile(workspace.fsgame_path)
    assert not os.path.exists(os.path.join(workspace.root, "gamedata", "shaders"))
    assert layers.needs_overlay(profile, layers.build_plan(profile, engine_data_path=fake_install.engine_data))
