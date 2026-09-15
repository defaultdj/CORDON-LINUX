#!/usr/bin/env bash
# CORDON-LINUX installer (user level, no root required).
#
#   ./install.sh              # install into ~/.local (recommended)
#   ./install.sh --system     # install into /usr/local (needs sudo)
#   ./install.sh --portable DIR   # also create the portable launcher next to the app data
#
# The script only touches:
#   <prefix>/lib/cordon-linux        the application (a private venv)
#   <prefix>/bin/cordon, cordon-gui  launcher entry points
#   <prefix>/share/applications      desktop entry
#   <prefix>/share/icons/hicolor     icon
set -euo pipefail

PREFIX="${HOME}/.local"
SYSTEM=0
PORTABLE=""
GUI=1
PYTHON_BIN="${PYTHON_BIN:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --system) SYSTEM=1; PREFIX="/usr/local"; shift ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --portable) PORTABLE="$2"; shift 2 ;;
    --no-gui) GUI=0; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Неизвестный параметр: $1" >&2; exit 1 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${PREFIX}/lib/cordon-linux"
VENV="${APP_DIR}/venv"

# Guard against the most common mistake: running the script from a checkout of `main`, which
# only carries the original Windows launcher (no pyproject.toml, no src/cordon).
if [[ ! -f "${ROOT}/pyproject.toml" || ! -d "${ROOT}/src/cordon" ]]; then
  # note the "|| true": with `set -o pipefail` a failing git call would abort the script
  # before it can explain what went wrong
  BRANCH="$(git -C "${ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [[ -z "${BRANCH}" || "${BRANCH}" == "HEAD" ]]; then
    BRANCH="не определена"
  fi
  cat >&2 <<MSG
Ошибка: это дерево не содержит Linux-порта CORDON.
  каталог: ${ROOT}
  ветка:   ${BRANCH}
  ожидалось: pyproject.toml и src/cordon

Похоже, рабочая копия устарела (порт влит в основную ветку). Обновите её:

  git -C "${ROOT}" pull            # если ветка уже есть
  # или склонируйте заново:
  git clone https://github.com/defaultdj/CORDON-LINUX.git
  cd CORDON-LINUX && ./install.sh
MSG
  exit 1
fi

echo "==> CORDON-LINUX: установка в ${PREFIX}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Ошибка: не найден ${PYTHON_BIN}. Установите Python 3.11 или новее." >&2
  exit 1
fi

version="$("${PYTHON_BIN}" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
major="${version%%.*}"; minor="${version##*.}"
if (( major < 3 || (major == 3 && minor < 10) )); then
  echo "Ошибка: нужен Python 3.10 или новее (найден ${version})." >&2
  exit 1
fi
if (( major == 3 && minor < 11 )) && [[ ${GUI} -eq 1 ]]; then
  echo "Предупреждение: найден Python ${version}; для PySide6 лучше 3.11+." >&2
fi

need_sudo=""
if [[ ${SYSTEM} -eq 1 && ! -w "${PREFIX}" ]]; then
  need_sudo="sudo"
fi

${need_sudo} mkdir -p "${APP_DIR}" "${PREFIX}/bin" "${PREFIX}/share/applications" \
  "${PREFIX}/share/icons/hicolor/scalable/apps"

echo "==> Python: создание виртуального окружения (${version})"
${need_sudo} "${PYTHON_BIN}" -m venv --system-site-packages "${VENV}"

# pip may be missing inside the venv (Arch: the python package has no bundled pip)
if ! ${need_sudo} "${VENV}/bin/python" -m pip --version >/dev/null 2>&1; then
  echo "==> В venv нет pip, включаю его через ensurepip"
  ${need_sudo} "${VENV}/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
fi

# A system PySide6 (Arch: `pacman -S pyside6`) is already visible thanks to
# --system-site-packages, so do not download a second copy of Qt from PyPI (~100 MB).
NEEDS_PYSIDE6=${GUI}
if [[ ${GUI} -eq 1 ]] && "${VENV}/bin/python" -c 'import PySide6' >/dev/null 2>&1; then
  echo "==> PySide6 найден в системе, использую его (в PyPI не обращаемся)"
  NEEDS_PYSIDE6=0
fi

# Without build isolation pip must find setuptools>=70 (it ships bdist_wheel itself);
# with Arch's python-setuptools the package build then needs no network at all.
PIP_BUILD_ARGS=()
if "${VENV}/bin/python" -c 'import setuptools,sys; v=[int(p) for p in setuptools.__version__.split(".")[:2] if p.isdigit()]; sys.exit(0 if v>=[70,1] else 1)' >/dev/null 2>&1; then
  PIP_BUILD_ARGS=(--no-build-isolation)
fi

pip_install() {
  # $1: requirement spec. Retries without the extra flags, e.g. when the system
  # setuptools is too old for --no-build-isolation.
  if ! ${need_sudo} "${VENV}/bin/python" -m pip install "${PIP_BUILD_ARGS[@]}" "$1"; then
    ${need_sudo} "${VENV}/bin/python" -m pip install "$1"
  fi
}

if [[ ${GUI} -eq 1 && ${NEEDS_PYSIDE6} -eq 1 ]]; then
  echo "==> Установка пакета (это может занять минуту: PySide6 ~100 МБ)"
else
  echo "==> Установка пакета"
fi
${need_sudo} "${VENV}/bin/python" -m pip install --upgrade pip >/dev/null 2>&1 || true

if [[ ${GUI} -eq 1 && ${NEEDS_PYSIDE6} -eq 1 ]]; then
  if ! pip_install "${ROOT}[gui]"; then
    echo "Предупреждение: не удалось поставить PySide6, ставлю ядро без графического интерфейса." >&2
    pip_install "${ROOT}" || { echo "Ошибка: не удалось установить пакет." >&2; exit 1; }
    GUI=0
  fi
else
  pip_install "${ROOT}" || { echo "Ошибка: не удалось установить пакет." >&2; exit 1; }
fi

echo "==> Точки входа"
for tool in cordon; do
  ${need_sudo} ln -sf "../lib/cordon-linux/venv/bin/${tool}" "${PREFIX}/bin/${tool}"
done
if [[ ${GUI} -eq 1 ]]; then
  ${need_sudo} ln -sf "../lib/cordon-linux/venv/bin/cordon-gui" "${PREFIX}/bin/cordon-gui"
fi

echo "==> Значок и пункт меню (раздел «Игры»)"
DESKTOP_DIR="${PREFIX}/share/applications"
ICON_DIR="${PREFIX}/share/icons/hicolor/scalable/apps"
${need_sudo} mkdir -p "${DESKTOP_DIR}" "${ICON_DIR}"

${need_sudo} cp "${ROOT}/packaging/cordon-linux.svg" "${ICON_DIR}/cordon-linux.svg"

# The desktop entry is what puts the launcher into the applications menu: the packages that
# build the menu take «Игры» from Categories=Game, and the icon from Icon=<name> resolved
# through the hicolor theme. Exec/TryExec must hold the absolute path of this installation.
desktop_tmp="$(mktemp)"
sed "s|^Exec=.*|Exec=${PREFIX}/bin/cordon-gui %u|; s|^TryExec=.*|TryExec=${PREFIX}/bin/cordon-gui|" \
  "${ROOT}/packaging/cordon-linux.desktop" > "${desktop_tmp}"
# 'install', not a shell redirect: with --system the target lives in /usr/local, and a redirect
# would either fail or leave the file owned by the current user.
${need_sudo} install -m 644 "${desktop_tmp}" "${DESKTOP_DIR}/cordon-linux.desktop"
rm -f "${desktop_tmp}"

if [[ ${GUI} -eq 0 ]]; then
  echo "  [i] GUI не установлен: TryExec указывает на отсутствующий ${PREFIX}/bin/cordon-gui,"
  echo "      поэтому в меню пункт пока скрыт — он появится после установки PySide6."
fi
if [[ "${PREFIX}" != "${HOME}/.local" && "${PREFIX}" != "/usr" && "${PREFIX}" != "/usr/local" ]]; then
  echo "  [i] ${PREFIX}/share не входит в стандартные пути меню:"
  echo "      добавьте export XDG_DATA_DIRS=\"${PREFIX}/share:\${XDG_DATA_DIRS:-/usr/local/share:/usr/share}\""
fi

if command -v desktop-file-validate >/dev/null 2>&1; then
  if desktop-file-validate "${DESKTOP_DIR}/cordon-linux.desktop"; then
    echo "  [OK] пункт меню прошёл проверку (desktop-file-validate)"
  fi
else
  echo "  [i] desktop-file-validate не найден — проверку пункта меню пропускаю"
  echo "      Arch: sudo pacman -S desktop-file-utils"
fi

# The menu has to be told that the directory changed, otherwise the new item appears only after
# a re-login. Every tool is optional: a missing one is only worth a note.
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${DESKTOP_DIR}" >/dev/null 2>&1 || true
  echo "  [OK] база пунктов меню обновлена"
else
  echo "  [i] update-desktop-database не найден — в меню пункт появится после перезахода"
  echo "      Arch: sudo pacman -S desktop-file-utils"
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -f -t "${PREFIX}/share/icons/hicolor" >/dev/null 2>&1 || true
fi
# KDE keeps its own cache; the command name differs between Plasma 5 and 6.
for sycoca in kbuildsycoca6 kbuildsycoca5; do
  if command -v "${sycoca}" >/dev/null 2>&1; then
    "${sycoca}" >/dev/null 2>&1 || true
    break
  fi
done
echo "  Пункт меню: ${DESKTOP_DIR}/cordon-linux.desktop"

echo
echo "Готово."
echo "  CLI : ${PREFIX}/bin/cordon --help"
if [[ ${GUI} -eq 1 ]]; then
  echo "  GUI : ${PREFIX}/bin/cordon-gui"
  echo "        или значок CORDON-LINUX в меню приложений, раздел «Игры»"
else
  echo "  GUI : не установлен (нет PySide6). Поставьте вручную: ${VENV}/bin/pip install PySide6-Essentials"
fi
if [[ -n "${PORTABLE}" ]]; then
  echo "  Портативный режим: ${PREFIX}/bin/cordon --portable \"${PORTABLE}\""
fi
echo
echo "Проверка окружения:  ${PREFIX}/bin/cordon tools"
echo "Создание профиля:    ${PREFIX}/bin/cordon new \"Моя сборка\" --game ~/games/anomaly"
cat <<'HINT'

Полезно поставить системные утилиты (по возможности):
  Arch:          sudo pacman -S fuse3 fuse-overlayfs 7zip unrar pyside6
  Debian/Ubuntu: sudo apt install fuse3 fuse-overlayfs p7zip-full libarchive-tools unrar python3-pyside6.qtwidgets
  Fedora:        sudo dnf install fuse3 fuse-overlayfs p7zip p7zip-plugins unrar python3-pyside6
HINT
