<h1 align="center">CordonIX</h1>

<p align="center"><strong>Лаунчер профилей и модов S.T.A.L.K.E.R. для UNIX/Linux (OpenXRay / Proton / Wine)</strong></p>

<p align="center">
  <img src="docs/screenshots/mods.png" alt="Главное окно CordonIX: профили и список модов" width="1000">
</p>

<p align="center">
  <strong>Форк лаунчера CORDON для UNIX-систем: нативный запуск OpenXRay, автопереключение на Proton/Wine, стилизация под S.T.A.L.K.E.R. PDA с Nerd Fonts и цветовая индикация конфликтов.</strong>
</p>

<p align="center">
  <a href="#установка"><strong>Установка</strong></a>
  ·
  <a href="docs/USER_GUIDE_LINUX_RU.md">Руководство пользователя</a>
  ·
  <a href="#возможности">Возможности</a>
  ·
  <a href="#english">English</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Linux_%2F_UNIX-x86__64-1793d1?logo=linux&logoColor=white" alt="Linux / UNIX x86_64">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776ab?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/%D0%B4%D0%B2%D0%B8%D0%B6%D0%BE%D0%BA-OpenXRay%20%2F%20Proton-ff6f00" alt="OpenXRay / Proton">
  <a href="LICENSE.md"><img src="https://img.shields.io/badge/%D0%BB%D0%B8%D1%86%D0%B5%D0%BD%D0%B7%D0%B8%D1%8F-GPLv3-blue" alt="GPLv3"></a>
</p>

---

## Что это

**CordonIX** — нативный порт и развитие лаунчера CORDON на Python + Qt (PySide6) для UNIX/Linux. Приложение предназначено для удобного управления профилями и модами S.T.A.L.K.E.R., объединяя возможности нативного движка **OpenXRay** и запуск классических Windows-сборок через **Proton / Wine**.

| Архитектурный подход | Реализация в CordonIX |
| --- | --- |
| Изоляция и виртуализация файлов | Backend `link` (символические ссылки) или `fuse-overlayfs` (настоящие слои) |
| Конфликты модов | Приоритеты модов + значки радиации `☢` (Зелёный/Красный/Жёлтый/Янтарный/Серый) |
| Запуск игры | Нативный OpenXRay (`xr_3da`); Windows-сборки — через PortProton / Proton / Wine |
| Хранение данных | Стандарты XDG (`~/.config/cordon`, `~/.local/share/cordon`, `~/.cache/cordon`) |
| Без root-прав | Безопасная установка в `~/.local` без прав администратора |

## Возможности

| Раздел | Описание |
| --- | --- |
| **Оформление PDA и Nerd Fonts** | Стилизованный интерфейс в стиле ПДА из S.T.A.L.K.E.R. с поддержкой Nerd Fonts (`Symbols Nerd Font`, `JetBrains Mono`), янтарной подсветкой и компактным режимом (1024x768) |
| **Цветовой анализ конфликтов** | Подсветка статуса модов цветными символами радиации `☢`: Зелёный (перекрывает другие), Красный (перекрыт), Жёлтый (избыточен), Янтарный (смешанный) и Серый |
| **Запуск OpenXRay + Proton/Wine** | Автоматическая попытка нативного запуска через Linux OpenXRay. Если мод требует оригинальные DLL или завершается с ошибкой — CordonIX автоматически перезапускает его через Proton/Wine |
| **Мультивыделение модов** | Поддержка выбора нескольких модов клавишами `Ctrl` и `Shift` для массового удаления из профиля или с диска |
| **Профили** | Создание, дублирование и настройка; режим «игра + моды» и автономная «готовая сборка» (standalone); независимые сохранения, `user.ltx`, логи и скриншоты для каждого профиля |
| **Моды** | Добавление папок, сканирование каталогов, установка из архивов (`zip`, `7z`, `rar`, `tar.*`), драг-н-дроп импорт, учет наигранного времени (`⏱ 0 мин`) |
| **Предупреждение о сборках** | Автоматическое обнаружение `fsgame.ltx`, `bin/` или `levels/` при добавлении папки мода с рекомендацией использовать режим сборки |
| **Аудит регистра путей** | Автоматический поиск несовпадений регистра в файлах модов с созданием симлинков-алиасов для регистрозависимой VFS Linux |
| **Импорт из MO2** | Импорт порядка, включённости и групп из `modlist.txt` Mod Organizer 2 (папка `overwrite` — отдельным слоем) |
| **Интерфейс** | Полный CLI (`cordon`) и GUI (`cordonix` / `cordon-gui`); тёмная тема PDA; Discord Rich Presence |

## Установка

### 1. Установка через скрипт `install.sh` (рекомендуется)

```bash
git clone https://github.com/defaultdj/CordonIX.git
cd CordonIX
./install.sh
```

`install.sh` создаёт виртуальное окружение в `~/.local/lib/cordonix`, устанавливает пакет, добавляет бинарники `cordon` и `cordonix` в `~/.local/bin` и создаёт ярлык в меню приложений (**Категория: Игры**).

Опции установщика:
* `./install.sh --system` — установка в `/usr/local` (требует root).
* `./install.sh --no-gui` — установка только консольной версии без PySide6.
* `./install.sh --portable /path/to/dir` — портативная установка.

### 2. Сборка пакета Arch Linux (PKGBUILD / AUR)

```bash
cd packaging/arch
makepkg -si
```

### 3. Установка через pipx

```bash
pipx install "cordonix[gui] @ git+https://github.com/defaultdj/CordonIX.git"
```

## Быстрый старт

### Использование CLI

```bash
cordon tools                                        # Проверка доступных системных утилит (Proton, Wine, FUSE)
cordon new "Anomaly 1.5.2" --game ~/games/anomaly   # Создание профиля
cordon mod-add "Anomaly 1.5.2" ~/Downloads/Mods     # Добавление папок или архивов модов
cordon mods "Anomaly 1.5.2"                         # Просмотр списка и конфликтов модов
cordon doctor "Anomaly 1.5.2"                       # Предполётная проверка профиля
cordon prepare "Anomaly 1.5.2"                      # Сборка оверлея
cordon launch "Anomaly 1.5.2"                       # Запуск игры
```

### Использование GUI

Запустите **CordonIX** из меню приложений или выполните команду `cordonix`.

![Главный экран](docs/screenshots/mods.png)

1. Создайте профиль (**Профиль ▾** → **Новый профиль**) и укажите каталог игры.
2. Добавьте моды (**Моды ▾** → **Добавить моды** / **Установить архив**).
3. Настройте порядок и включенность модов — значки `☢` сразу покажут статус конфликтов.
4. Нажмите **Собрать** (F5) и **Запустить** (F9).

## Автоматический выбор движка и Proton

CordonIX автоматически определяет тип бинарников в каталоге игры:
* **Нативный ELF (`xr_3da`)**: Запускается напрямую в Linux через OpenXRay.
* **Windows PE (`xrEngine.exe`)**: CordonIX ищет **PortProton**, **Proton** (Steam / Proton GE) или **Wine** и запускает игру в нём; ключи `-fsltx`/`-overlaypath` переводятся в `Z:\…`, для PortProton записываются в `<exe>.ppdb`.
* **Авто-фолбэк**: При наличии системного OpenXRay лаунчер сначала запускает мод нативно. В случае ошибки скриптов или DLL игра автоматически перезапускается через Proton/Wine.
* **Ручной выбор**: Меню **▾** рядом с «Запустить» (или `cordon launch --runner proton|native`) принудительно запускает сборку через Proton/Wine либо только нативно — на случай, если автоопределение сбоя не сработало.

## Способы сборки оверлея (Backends)

| Backend | Как работает | Преимущества |
| --- | --- | --- |
| **`link`** *(по умолчанию)* | Строит дерево символических ссылок в каталоге профиля | Не требует root или FUSE; работает на любых ФС (ext4, btrfs, xfs, tmpfs) |
| **`fuse-overlayfs`** | Настоящее слоистое монтирование точек `gamedata` | Мгновенная сборка без создания множества симлинков |
| **`direct`** | Без оверлея — параметры передаются движку напрямую | Для простых сборок без конфликтующих модов |

## Разработка и тестирование

```bash
# Настройка окружения разработки
python3 -m venv .venv
.venv/bin/pip install -e ".[gui,dev]" build wheel

# Запуск тестов
.venv/bin/pytest tests/cordon -v

# Запуск дымового теста
PATH="$PWD/.venv/bin:$PATH" bash cordon-smoke-test.sh
```

## Документация

* 📖 [Руководство пользователя (RU)](docs/USER_GUIDE_LINUX_RU.md)
* 🛠️ [Техническое описание архитектуры (EN)](docs/TECHNICAL_LINUX_EN.md)
* 📦 Импорт из Mod Organizer 2 — раздел 13 руководства пользователя

## Лицензия

Код распространяется по лицензии [GNU GPLv3](LICENSE.md).  
Сторонние компоненты: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).  
Узнать больше о движке: <https://github.com/OpenXRay/xray-16>.

---

<a id="english"></a>

## English

**CordonIX** is a native UNIX/Linux profile & mod manager for S.T.A.L.K.E.R., tailored for [OpenXRay](https://github.com/OpenXRay/xray-16) and Proton/Wine compatibility.

### Key Features

* **S.T.A.L.K.E.R. PDA Theme & Nerd Fonts**: Custom high-tech PDA styling with Nerd Fonts support (`Symbols Nerd Font`, `JetBrains Mono`).
* **Colored Radiation Conflict Symbol Icons (`☢`)**: Visual conflict status column (Green = overwrites, Red = overwritten, Yellow = redundant, Amber = mixed, Gray = conflict-free).
* **Native OpenXRay + Automatic Proton/Wine Fallback**: Tries native OpenXRay first for max performance, falling back to Proton/Wine if Windows `.exe` dependencies fail.
* **Isolated Profiles & Multi-Select**: Multi-selection (`Ctrl`/`Shift`) for mod removal and deletion, isolated saves, logs, and `user.ltx`.
* **Case-Sensitivity Audit**: Automated scan for Linux case mismatches in `.ltx`/`.script` files with automatic symlink alias generation.
* **Dual Interface**: Full CLI (`cordon`) and PySide6 Qt GUI (`cordonix` / `cordon-gui`).

### Quick Install

```bash
git clone https://github.com/defaultdj/CordonIX.git
cd CordonIX && ./install.sh
```

Or start `cordonix` from your application menu.
