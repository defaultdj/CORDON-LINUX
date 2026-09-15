"""Post-session diagnostics: game log, crash dumps, and the report the Status window shows."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import util, xray
from .paths import AppPaths

LOG_DIRS = ("logs",)
DUMP_DIRS = ("dumps", "reports")
DUMP_SUFFIXES = (".dmp", ".mdmp", ".core", ".crash")


@dataclass(slots=True)
class SessionDiagnostics:
    log_path: str = ""
    log_tail: list[str] = field(default_factory=list)
    dumps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    @property
    def has_problems(self) -> bool:
        return bool(self.dumps or self.problems) or any(
            "! " in line or "FATAL" in line.upper() for line in self.log_tail
        )

    def to_text(self) -> str:
        lines: list[str] = []
        if self.log_path:
            lines.append(f"Последний игровой лог: {self.log_path}")
        if self.dumps:
            lines.append("Дампы/отчёты:")
            lines.extend(f"  • {item}" for item in self.dumps)
        if self.problems:
            lines.append("Найденные ошибки:")
            lines.extend(f"  • {item}" for item in self.problems)
        if self.hints:
            lines.append("Подсказки:")
            lines.extend(f"  • {item}" for item in self.hints)
        if self.notes:
            lines.append("Заметки:")
            lines.extend(f"  • {item}" for item in self.notes)
        if self.log_tail:
            lines.append("")
            lines.append("Хвост лога:")
            lines.extend(self.log_tail[-25:])
        return "\n".join(lines) or "Диагностика пуста."


def collect(appdata: str, *, since: float = 0.0, tail_lines: int = 40) -> SessionDiagnostics:
    """Look for logs and dumps inside a profile data directory."""
    result = SessionDiagnostics()
    if not os.path.isdir(appdata):
        result.notes.append(f"каталог данных не найден: {appdata}")
        return result

    candidates: list[tuple[float, str]] = []
    for directory in LOG_DIRS:
        root = os.path.join(appdata, directory)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in util.iter_tree(root):
            for name in filenames:
                path = os.path.join(dirpath, name)
                if not name.lower().endswith((".log", ".txt")):
                    continue
                try:
                    mtime = os.lstat(path).st_mtime
                except OSError:  # pragma: no cover
                    continue
                if mtime + 1 >= since:
                    candidates.append((mtime, path))
    if candidates:
        candidates.sort()
        result.log_path = candidates[-1][1]
        result.log_tail = util.tail_lines(result.log_path, tail_lines)
        result.problems = analyze_log(util.tail_lines(result.log_path, ANALYZE_LINES))
    else:
        result.notes.append("новый игровой лог не найден — возможно, движок не успел его создать")

    for directory in DUMP_DIRS:
        root = os.path.join(appdata, directory)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in util.iter_tree(root):
            for name in filenames:
                lower = name.lower()
                path = os.path.join(dirpath, name)
                if not (lower.endswith(DUMP_SUFFIXES) or lower.startswith("crash")):
                    continue
                try:
                    mtime = os.lstat(path).st_mtime
                except OSError:  # pragma: no cover
                    continue
                if mtime + 1 >= since:
                    result.dumps.append(path)
    return result


ANALYZE_LINES = 600
_MAX_PROBLEMS = 6
_FATAL_FIELDS = ("expression", "function", "file", "line", "description", "arguments")
_SCRIPT_ERROR_RE = re.compile(r"SCRIPT (?:RUNTIME )?ERROR\]?[:\s]*(.*)", re.IGNORECASE)
_LUA_ERROR_RE = re.compile(r"LUA error[:\s]*(.*)", re.IGNORECASE)
_GENERIC_PATTERNS = (
    (re.compile(r"No shaders found for (\w+)", re.IGNORECASE), "шейдеры рендера не найдены: {0}"),
    (re.compile(r"Can't find (?:any )?(?:file|texture|model|sound)[^\n]*", re.IGNORECASE), "{0}"),
    (re.compile(r"Can't open section '([^']+)'", re.IGNORECASE), "не найдена секция конфига '{0}'"),
    (re.compile(r"Out of memory", re.IGNORECASE), "движку не хватило памяти (Out of memory)"),
    (re.compile(r"(?:Segmentation fault|SIGSEGV)", re.IGNORECASE), "падение движка (SIGSEGV)"),
)


def _strip_prefix(line: str) -> str:
    """Drop the ``[timestamp]`` / ``! `` / ``* `` decorations X-Ray adds to log lines."""
    text = line.strip()
    if text.startswith("[") and "]" in text:
        text = text[text.index("]") + 1 :].strip()
    while text[:1] in ("!", "*", "-", "~") and text[1:2] == " ":
        text = text[2:].strip()
    return text


def analyze_log(lines: list[str]) -> list[str]:
    """Pull human-readable problem statements out of an X-Ray log.

    Recognised: ``FATAL ERROR`` blocks (with their Expression/Function/File/Line/Description/
    Arguments fields), Lua ``SCRIPT RUNTIME ERROR`` lines, and a handful of well-known one-line
    failures (missing shaders, missing files/sections, OOM, SIGSEGV).
    """
    problems: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        text = " ".join(text.split())
        if text and text not in seen:
            seen.add(text)
            problems.append(text)

    index = 0
    while index < len(lines):
        text = _strip_prefix(lines[index])
        upper = text.upper()
        if upper.startswith("FATAL ERROR"):
            fields: dict[str, str] = {}
            cursor = index + 1
            while cursor < len(lines) and cursor - index < 12:
                candidate = _strip_prefix(lines[cursor])
                if not candidate:
                    cursor += 1
                    continue
                key, sep, value = candidate.partition(":")
                key = key.strip().lower()
                if key.startswith("["):
                    key = key.strip("[] ")
                if sep and key in _FATAL_FIELDS:
                    fields[key] = value.strip()
                    cursor += 1
                    continue
                if key == "stack trace":
                    break
                if fields:
                    break
                cursor += 1
            summary = fields.get("description") or fields.get("expression") or text
            details: list[str] = []
            if fields.get("arguments"):
                details.append(fields["arguments"])
            if fields.get("file"):
                location = fields["file"]
                if fields.get("line"):
                    location += f":{fields['line']}"
                details.append(location)
            if fields.get("function") and not summary.startswith(fields["function"]):
                details.append(fields["function"])
            add("FATAL ERROR: " + summary + (f" ({'; '.join(details)})" if details else ""))
            index = max(cursor, index + 1)
            continue
        match = _SCRIPT_ERROR_RE.search(text) or _LUA_ERROR_RE.search(text)
        if match:
            detail = match.group(1).strip()
            if not detail and index + 1 < len(lines):
                detail = _strip_prefix(lines[index + 1])
            add("Ошибка скрипта Lua: " + (detail or text))
            index += 1
            continue
        for pattern, template in _GENERIC_PATTERNS:
            found = pattern.search(text)
            if found:
                add(template.format(*(found.groups() or (found.group(0),))))
                break
        index += 1
    if len(problems) > _MAX_PROBLEMS:
        problems = problems[:_MAX_PROBLEMS] + [f"… и ещё {len(problems) - _MAX_PROBLEMS}"]
    return problems


def is_lua_problem(problem: str) -> bool:
    return problem.startswith("Ошибка скрипта Lua") or "LUA" in problem.upper() or ".script" in problem


def standalone_data_dirs(build_root: str) -> list[str]:
    return xray.find_appdata_roots(build_root)


def build_report_text(
    *,
    profile_name: str,
    engine_summary: str,
    executable: str,
    root_path: str,
    overlay_summary: str,
    preflight_text: str,
    diag: SessionDiagnostics | None = None,
    extra_notes: list[str] | None = None,
) -> str:
    lines = [
        "CordonIX — отчёт о состоянии профиля",
        "=" * 46,
        f"Профиль:        {profile_name}",
        f"Движок:         {engine_summary or '—'}",
        f"Исполняемый:    {executable or '—'}",
        f"Каталог профиля:{root_path or '—'}",
        f"Оверлей:        {overlay_summary or '—'}",
        "",
        "Проверки:",
        preflight_text or "—",
    ]
    if extra_notes:
        lines += ["", "Дополнительно:"]
        lines += [f"  • {note}" for note in extra_notes]
    if diag is not None:
        lines += ["", diag.to_text()]
    return "\n".join(lines)


def write_report(app: AppPaths, name: str, text: str) -> str:
    util.ensure_dir(app.reports_dir)
    stamp = util.short_hash(name + text, 8)
    target = os.path.join(app.reports_dir, f"{name}-{stamp}.txt")
    util.write_text_atomic(target, text)
    return target
