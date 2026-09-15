#!/usr/bin/env bash
# CORDON-LINUX — дымовой тест на живой системе (Arch/Linux).
#
#   bash cordon-smoke-test.sh                     # фаза A: самопроверка без игры
#   bash cordon-smoke-test.sh "Моя сборка"         # фазы A + B (проверки реального профиля)
#
# Фаза A ничего не устанавливает и не меняет вне временного каталога /tmp:
# создаёт fake-игру, fake-движок (/usr/bin/true) и прогоняет весь конвейер
# (профиль -> моды -> сборка оверлея -> конфликты -> аудит -> doctor -> dry-run).
# Так проверяется, что лаунчер работает на твоём Python и в твоём дистрибутиве,
# ещё до того, как в дело вступит настоящий движок.
set -uo pipefail

PASS=0
FAIL=0
WARN=0
TMP=""

ok()   { printf '  \033[32m[OK]\033[0m   %s\n' "$*"; PASS=$((PASS + 1)); }
bad()  { printf '  \033[31m[СБОЙ]\033[0m %s\n' "$*"; FAIL=$((FAIL + 1)); }
warn() { printf '  \033[33m[!]\033[0m    %s\n' "$*"; WARN=$((WARN + 1)); }
info() { printf '  ...    %s\n' "$*"; }
head_() { printf '\n=== %s ===\n' "$*"; }

cleanup() {
  if [[ -n "${TMP}" && -d "${TMP}" ]]; then rm -rf "${TMP}"; fi
}
trap cleanup EXIT

# --- 0. Что за система и где лаунчер --------------------------------------
head_ "0. Система"
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  printf '  ОС:      %s\n' "$(. /etc/os-release && echo "${PRETTY_NAME:-?}")"
fi
printf '  ядро:    %s\n' "$(uname -sr)"
printf '  арх.:    %s\n' "$(uname -m)"
printf '  python3: %s (%s)\n' "$(python3 -V 2>&1)" "$(command -v python3 || echo 'нет')"

CORDON_BIN="${CORDON_BIN:-}"
if [[ -z "${CORDON_BIN}" ]]; then
  if command -v cordon >/dev/null 2>&1; then
    CORDON_BIN="$(command -v cordon)"
  elif [[ -x "${HOME}/.local/bin/cordon" ]]; then
    CORDON_BIN="${HOME}/.local/bin/cordon"
  fi
fi
if [[ -z "${CORDON_BIN}" ]]; then
  bad "cordon не найден в PATH — сначала выполните ./install.sh"
  echo
  echo "  Затем:  export PATH=\"\$HOME/.local/bin:\$PATH\"  и запустите тест заново."
  exit 1
fi
ok "cordon: ${CORDON_BIN}"
printf '  версия:  %s\n' "$("${CORDON_BIN}" --version 2>&1)"

head_ "0б. Системные утилиты"
if "${CORDON_BIN}" tools 2>&1 | sed 's/^/  /'; then :; else warn "'cordon tools' завершился с ошибкой"; fi

# --- 1. GUI ---------------------------------------------------------------
head_ "1. Графический интерфейс"
GUI_SUFFIX=""
if command -v cordon-gui >/dev/null 2>&1; then
  ok "cordon-gui найден: $(command -v cordon-gui)"
else
  warn "cordon-gui нет в PATH (CLI всё равно работает)"
fi
VENV_PY="${HOME}/.local/lib/cordon-linux/venv/bin/python"
if [[ -x "${VENV_PY}" ]]; then
  if "${VENV_PY}" -c 'import PySide6, PySide6.QtWidgets' >/dev/null 2>&1; then
    ok "PySide6 импортируется в venv лаунчера: $("${VENV_PY}" -c 'import PySide6;print(PySide6.__version__)')"
  else
    bad "в venv нет PySide6 — GUI не запустится (поставьте pyside6 или переустановите с GUI)"
  fi
  if QT_QPA_PLATFORM=offscreen "${VENV_PY}" -c '
import sys
from PySide6.QtWidgets import QApplication, QLabel
app = QApplication([])
w = QLabel("test"); w.resize(120, 40); w.show()
sys.exit(0 if w.grab().save("/dev/null") or True else 1)
' >/dev/null 2>&1; then
    ok "Qt создаёт окно в offscreen-режиме (библиотеки Qt на месте)"
  else
    warn "Qt не смог создать окно в offscreen — проверьте видеодрайверы/библиотеки Qt"
  fi
else
  warn "venv лаунчера не найден (${VENV_PY}) — проверка GUI пропущена"
fi

# --- 2. Фаза A: конвейер на fake-игре -------------------------------------
head_ "2. Конвейер без игры (fake-профиль)"
TMP="$(mktemp -d /tmp/cordon-selftest.XXXXXX)"
export CORDON_CONFIG_DIR="${TMP}/config"
export CORDON_DATA_DIR="${TMP}/data"
export CORDON_CACHE_DIR="${TMP}/cache"
info "временный каталог: ${TMP}"

mkdir -p "${TMP}/game/gamedata/textures/cars" "${TMP}/game/bin" "${TMP}/mods/HD"
printf '\0' > "${TMP}/game/gamedata/textures/cars/volga.dds"
cp /usr/bin/true "${TMP}/game/bin/xr_3da"
cat > "${TMP}/game/fsgame.ltx" <<'LTX'
[gamedata]
$game_data$ = true| false| $fs_root$| gamedata\
LTX
printf '\0' > "${TMP}/mods/HD/gamedata/textures/cars/volga.dds"

run() {  # run "описание" cmd...
  local desc="$1"; shift
  local out
  if out="$("$@" 2>&1)"; then
    ok "${desc}"
    printf '%s\n' "${out}" | sed 's/^/         /'
    return 0
  fi
  bad "${desc}"
  printf '%s\n' "${out}" | sed 's/^/         /'
  return 1
}

run "cordon new — создание профиля" "${CORDON_BIN}" new "selftest" --game "${TMP}/game"
run "cordon list" "${CORDON_BIN}" list
run "cordon mod-add — добавление модов" "${CORDON_BIN}" mod-add "selftest" "${TMP}/mods"
run "cordon mods" "${CORDON_BIN}" mods "selftest"
run "cordon prepare — сборка оверлея" "${CORDON_BIN}" prepare "selftest"
run "cordon conflicts --tree" "${CORDON_BIN}" conflicts "selftest" --tree
run "cordon audit" "${CORDON_BIN}" audit "selftest"
run "cordon doctor" "${CORDON_BIN}" doctor "selftest"
run "cordon launch --dry-run" "${CORDON_BIN}" launch "selftest" --dry-run

PROFILE_DIR="$(find "${CORDON_DATA_DIR}/profiles" -maxdepth 1 -mindepth 1 -type d | head -1)"
if [[ -n "${PROFILE_DIR}" ]]; then
  [[ -f "${PROFILE_DIR}/fsgame.ltx" ]] \
    && ok "fsgame.ltx подготовлен в профиле" \
    || bad "fsgame.ltx не создан в профиле"
  if [[ -L "${PROFILE_DIR}/bin" ]]; then
    ok "каталог движка подключён ссылкой: bin -> $(readlink "${PROFILE_DIR}/bin")"
  elif [[ -L "${PROFILE_DIR}/bin/xr_3da" ]]; then
    ok "движок подключён символической ссылкой: $(readlink "${PROFILE_DIR}/bin/xr_3da")"
  elif [[ -e "${PROFILE_DIR}/bin/xr_3da" ]]; then
    warn "bin/xr_3da на месте, но это копия, а не ссылка (проверьте backend профиля)"
  else
    bad "bin/xr_3da недоступен в профиле — движок не подключился"
  fi
  [[ -d "${PROFILE_DIR}/_appdata_" ]] \
    && ok "_appdata_ создан (каталог данных профиля)" \
    || warn "_appdata_ не создан"
  info "структура профиля:"
  find "${PROFILE_DIR}" -maxdepth 2 -printf '         %y %p -> %l\n' 2>/dev/null | head -20
fi

# --- 3. Фаза B: реальный профиль (если передан) ---------------------------
head_ "3. Реальный профиль"
if [[ $# -ge 1 && -n "${1:-}" ]]; then
  unset CORDON_CONFIG_DIR CORDON_DATA_DIR CORDON_CACHE_DIR
  PROFILE="$1"
  if "${CORDON_BIN}" list --json 2>/dev/null | grep -qF "\"name\": \"${PROFILE}\""; then
    run "cordon doctor \"${PROFILE}\"" "${CORDON_BIN}" doctor "${PROFILE}"
    run "cordon audit \"${PROFILE}\"" "${CORDON_BIN}" audit "${PROFILE}" || true
    run "cordon conflicts \"${PROFILE}\"" "${CORDON_BIN}" conflicts "${PROFILE}" || true
    info "итоговая команда запуска:"
    "${CORDON_BIN}" launch "${PROFILE}" --dry-run 2>&1 | sed 's/^/         /'
  else
    warn "профиля «${PROFILE}» нет в ~/.local/share/cordon — создайте его и запустите тест снова:"
    echo "         cordon new \"${PROFILE}\" --game /путь/к/игре"
    info "сейчас в лаунчере такие профили:"
    "${CORDON_BIN}" list 2>&1 | sed 's/^/         /'
  fi
else
  info "профиль не передан: запустите 'bash cordon-smoke-test.sh \"Имя профиля\"' для проверки реальной сборки"
fi

# --- 4. Итог --------------------------------------------------------------
head_ "Итог"
printf '  успешно: %d, сбоев: %d, замечаний: %d\n' "${PASS}" "${FAIL}" "${WARN}"
if [[ ${FAIL} -eq 0 ]]; then
  echo "  Лаунчер на этой системе работает. Дальше — тест с настоящим движком (см. гайд)."
  exit 0
fi
echo "  Есть сбои — пришлите весь вывод этого скрипта, разберём."
exit 1
