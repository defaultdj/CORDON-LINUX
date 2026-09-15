"""Post-session log analysis: FATAL ERROR blocks, Lua errors, and the hints built from them."""

from __future__ import annotations

from cordon.core import diagnostics

FATAL_BLOCK = """
* Log file has been saved successfully!
FATAL ERROR

[error]Expression    : fatal error
[error]Function      : CScriptEngine::lua_error
[error]File          : script_engine.cpp
[error]Line          : 190
[error]Description   : <no expression>
[error]Arguments     : LUA error: ...gamedata\\scripts\\mod_reflection.script:55: attempt to call method 'SetName' (a nil value)


stack trace:
""".strip("\n").splitlines()

SCRIPT_RUNTIME = [
    "! [SCRIPT ERROR]: ...ata\\scripts\\bind_stalker.script:12: attempt to index a nil value",
    "* something normal",
    "! [SCRIPT ERROR]: ...ata\\scripts\\bind_stalker.script:12: attempt to index a nil value",
]


def test_fatal_block_is_summarised_with_arguments_and_location():
    problems = diagnostics.analyze_log(FATAL_BLOCK)
    assert len(problems) == 1
    text = problems[0]
    assert text.startswith("FATAL ERROR:")
    assert "mod_reflection.script:55" in text
    assert "script_engine.cpp:190" in text
    assert diagnostics.is_lua_problem(text)


def test_script_errors_are_deduplicated():
    problems = diagnostics.analyze_log(SCRIPT_RUNTIME)
    assert problems == ["Ошибка скрипта Lua: ...ata\\scripts\\bind_stalker.script:12: attempt to index a nil value"]


def test_generic_patterns_and_cap():
    lines = ["! No shaders found for OpenGL"] + [f"! Can't find texture 'tex_{i}'" for i in range(10)]
    problems = diagnostics.analyze_log(lines)
    assert problems[0] == "шейдеры рендера не найдены: OpenGL"
    assert problems[-1].startswith("… и ещё")
    assert len(problems) == diagnostics._MAX_PROBLEMS + 1


def test_clean_log_has_no_problems():
    assert diagnostics.analyze_log(["* Starting", "- game loaded", "* Log file has been saved successfully!"]) == []


def test_collect_fills_problems_and_text(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "xray_user.log").write_text("\n".join(FATAL_BLOCK), encoding="utf-8")
    diag = diagnostics.collect(str(tmp_path))
    assert diag.problems and diag.has_problems
    diag.hints = ["запустите через Proton"]
    text = diag.to_text()
    assert "Найденные ошибки:" in text
    assert "Подсказки:" in text


def test_session_hint_for_native_standalone_lua_crash():
    from cordon.core import launch
    from cordon.core.models import PROFILE_KIND_STANDALONE, LaunchPlan, Profile

    profile = Profile(id="p", name="p", kind=PROFILE_KIND_STANDALONE, game_path="/tmp/build")
    plan = LaunchPlan(profile_id="p", executable="/usr/bin/xr_3da", argv=["xr_3da"], cwd="/tmp", env={})
    outcome = launch.LaunchOutcome(plan=plan, returncode=1, started_at=1.0, finished_at=2.0)
    outcome.diagnostics = diagnostics.SessionDiagnostics(problems=diagnostics.analyze_log(FATAL_BLOCK))
    hints = launch.session_hints(profile, plan, outcome)
    assert hints and "Proton" in hints[0]

    plan_exe = LaunchPlan(profile_id="p", executable="/tmp/build/bin/xrEngine.exe", argv=["x"], cwd="/tmp", env={})
    assert launch.session_hints(profile, plan_exe, outcome) == []
