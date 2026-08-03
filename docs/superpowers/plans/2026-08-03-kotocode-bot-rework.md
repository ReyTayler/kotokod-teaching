# Переработка kotocode-bot: из системы учёта в напоминалку — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот перестаёт быть вторым источником правды: у него исчезают собственная БД, роли, планировщик и ручной ввод событий. Остаются `/start`, `/help`, `/my` и передача журналу информации «этот chat_id — вот такой ник».

**Architecture:** Всё состояние живёт в PostgreSQL журнала. Бот ходит в журнал по двум служебным эндпоинтам с общим секретом в заголовке. Уведомления бот **не отправляет** — их шлёт журнал напрямую в Telegram Bot API. Порядка 300 строк вместо 3700.

**Tech Stack:** Python 3.11, python-telegram-bot 20.7, httpx, systemd. Уходят: APScheduler, sqlite3.

**Репозиторий:** `https://github.com/ReyTayler/kotocode-bot` — **не** этот. Клонировать отдельно.

**Спека:** `docs/superpowers/specs/2026-08-03-telegram-notifications-design.md`, раздел 8.

---

## Предусловия

Выполнять **только после** того, как план `2026-08-03-telegram-notifications.md` пройден и выкачен на прод, а админ убедился, что дайджесты приходят. Иначе на время работ школа останется и без старых напоминаний бота, и без новых.

Первым делом — Task 0: сверка данных. Не пропускать.

---

## Структура файлов после переработки

```
kotocode-bot/
├── main.py                     # сборка приложения, регистрация хендлеров
├── bot/
│   ├── config.py               # настройки из .env, логирование
│   ├── journal_api.py          # ЕДИНСТВЕННОЕ место, знающее про HTTP журнала
│   ├── handlers/
│   │   ├── common.py           # /start, /help, unknown_command
│   │   ├── my.py               # /my
│   │   └── identify.py         # на любое входящее — сообщить журналу chat_id
│   └── utils/
│       ├── formatters.py       # тексты ответов бота
│       └── commands.py         # меню команд в Telegram
├── tests/
│   ├── test_formatters.py
│   └── test_journal_api.py
├── requirements.txt
├── .env.example
└── systemd/kotocode-bot.service
```

**Удаляются целиком:** `bot/database.py`, `bot/scheduler.py`, `bot/services/role_service.py`, `bot/middlewares/role_check.py`, `bot/states/`, `bot/handlers/events_add.py`, `bot/handlers/events_edit.py`, `bot/handlers/events_list.py`, `bot/handlers/manager.py`, `bot/handlers/admin.py`, `bot/handlers/superadmin.py`, `bot/utils/parser.py`, `bot/utils/notifications.py`, `migrate_roles.py`.

---

## Task 0: Сверка данных перед выключением

**Files:** ничего не меняется — это проверка.

- [ ] **Step 1: Выгрузить активные события бота**

На сервере:

```bash
sqlite3 -header -csv /home/kotocode/kotocode-bot/data/kotocode.db \
  "SELECT id, type, teacher_username, group_name, lesson_number, scheduled_at, children, comment
   FROM events WHERE status = 'active' ORDER BY scheduled_at" > /tmp/active_events.csv
wc -l /tmp/active_events.csv
```

- [ ] **Step 2: Сверить с журналом**

Для каждой строки проверить в админке журнала, что соответствующий доп.урок или перенос там есть. Скорее всего есть — менеджер и так вводил их в оба места.

- [ ] **Step 3: Донести недостающее руками**

Всё, чего в журнале не оказалось, менеджер вносит через админку. Автоматический перенос здесь не нужен и опасен: строк единицы, а данные бота неструктурированы (`children` и `lesson_number` — свободный текст).

- [ ] **Step 4: Архивировать базу**

```bash
cp /home/kotocode/kotocode-bot/data/kotocode.db \
   /home/kotocode/kotocode.db.$(date +%Y%m%d).bak
```

Файл не удалять минимум месяц.

---

## Task 1: Клиент журнала

**Files:**
- Create: `bot/journal_api.py`, `tests/test_journal_api.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Написать падающий тест**

`tests/test_journal_api.py`:

```python
"""Клиент журнала: заголовок с секретом, обработка ответов."""
from unittest.mock import patch

import pytest

from bot import journal_api


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_identify_sends_secret_header():
    with patch('bot.journal_api.httpx.post', return_value=_Resp(204)) as post:
        journal_api.identify(telegram_id=1, username='anna', full_name='Анна')
    _args, kwargs = post.call_args
    assert kwargs['headers']['X-Bot-Token'] == journal_api.SERVICE_TOKEN


def test_identify_never_raises_on_failure():
    """Журнал недоступен — бот обязан продолжать отвечать человеку."""
    import httpx
    with patch('bot.journal_api.httpx.post', side_effect=httpx.ConnectError('down')):
        assert journal_api.identify(telegram_id=1, username=None, full_name='Аноним') is False


def test_my_returns_none_when_not_linked():
    with patch('bot.journal_api.httpx.get', return_value=_Resp(404)):
        assert journal_api.my_events(telegram_id=1) is None


def test_my_returns_payload():
    payload = {'teacher_name': 'Анна', 'events': [{'date': '2026-08-05'}]}
    with patch('bot.journal_api.httpx.get', return_value=_Resp(200, payload)):
        assert journal_api.my_events(telegram_id=1) == payload
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest tests/test_journal_api.py -v`
Expected: FAIL — `ModuleNotFoundError: bot.journal_api`

- [ ] **Step 3: Реализовать клиент**

`bot/journal_api.py`:

```python
"""
Единственное место в боте, знающее про HTTP журнала.

Бот и журнал живут на одной машине, поэтому адрес — localhost, а эндпоинты
дополнительно закрыты в nginx правилом allow 127.0.0.1.

Все функции при ошибке возвращают False/None и НИКОГДА не бросают: если журнал
недоступен, бот обязан продолжать отвечать человеку, а не молчать.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get('JOURNAL_API_URL', 'http://127.0.0.1:8000').rstrip('/')
SERVICE_TOKEN = os.environ.get('BOT_SERVICE_TOKEN', '')
TIMEOUT = 5.0

_HEADERS = {'X-Bot-Token': SERVICE_TOKEN}


def identify(*, telegram_id: int, username: str | None, full_name: str) -> bool:
    """Сообщить журналу, какому нику соответствует chat_id."""
    try:
        response = httpx.post(
            f'{BASE_URL}/api/integrations/telegram/identify',
            json={'telegram_id': telegram_id, 'username': username,
                  'full_name': full_name},
            headers=_HEADERS, timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.warning('identify не дошёл до журнала: %s', exc)
        return False
    return response.status_code == 204


def my_events(*, telegram_id: int) -> dict | None:
    """Ближайшие события преподавателя. None — аккаунт не привязан или журнал молчит."""
    try:
        response = httpx.get(
            f'{BASE_URL}/api/integrations/telegram/my',
            params={'telegram_id': telegram_id},
            headers=_HEADERS, timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.warning('my не дошёл до журнала: %s', exc)
        return None
    if response.status_code != 200:
        return None
    return response.json()
```

- [ ] **Step 4: Обновить зависимости**

`requirements.txt` целиком:

```
python-telegram-bot==20.7
httpx==0.27.2
python-dotenv==1.0.1
pytest==8.3.3
```

APScheduler удалён — планированием занимается Celery в журнале.

- [ ] **Step 5: Запустить тесты**

Run: `pytest tests/test_journal_api.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add bot/journal_api.py tests/test_journal_api.py requirements.txt
git commit -m "feat: клиент API журнала, вместо собственной БД"
```

---

## Task 2: Хендлеры /start, /help, /my и identify

**Files:**
- Rewrite: `bot/handlers/common.py`
- Create: `bot/handlers/my.py`, `bot/handlers/identify.py`
- Rewrite: `bot/utils/formatters.py`
- Test: `tests/test_formatters.py`

- [ ] **Step 1: Написать падающий тест**

`tests/test_formatters.py`:

```python
"""Тексты ответов бота."""
from bot.utils import formatters


def test_my_events_formats_list():
    text = formatters.my_events({
        'teacher_name': 'Анна Петрова',
        'events': [
            {'date': '2026-08-05', 'time': '12:00', 'group': 'СИ1027',
             'direction': 'Scratch', 'seq': 1, 'is_substitute': False},
            {'date': '2026-08-06', 'time': '13:00', 'group': 'ПИ1062',
             'direction': 'Python', 'seq': 9, 'is_substitute': True},
        ],
    })
    assert '05.08' in text
    assert 'СИ1027' in text
    assert 'замена' in text


def test_my_events_handles_empty_list():
    text = formatters.my_events({'teacher_name': 'Анна', 'events': []})
    assert 'нет' in text.lower()


def test_not_linked_message_explains_what_to_do():
    text = formatters.not_linked()
    assert 'администратор' in text.lower()
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest tests/test_formatters.py -v`
Expected: FAIL — функций нет.

- [ ] **Step 3: Переписать форматтеры**

`bot/utils/formatters.py`:

```python
"""Тексты ответов бота. Чистые функции, без сети."""
from __future__ import annotations

import datetime


def _day(iso: str) -> str:
    return datetime.date.fromisoformat(iso).strftime('%d.%m')


def start(full_name: str) -> str:
    return (
        f'Привет, {full_name}!\n\n'
        'Я присылаю напоминания о занятиях: утром — расписание на день, '
        'вечером — что осталось заполнить, и отдельно — когда назначают '
        'доп.урок, перенос или замену.\n\n'
        'Команда /my покажет ближайшие занятия.'
    )


def help_text() -> str:
    return (
        'Доступные команды:\n\n'
        '/my — мои ближайшие занятия\n'
        '/help — эта справка'
    )


def my_events(payload: dict) -> str:
    events = payload.get('events') or []
    if not events:
        return 'На ближайшую неделю занятий нет.'

    lines = []
    for event in events:
        mark = ' (замена)' if event.get('is_substitute') else ''
        number = f" — урок №{event['seq']}" if event.get('seq') is not None else ''
        lines.append(
            f"• {_day(event['date'])}, {event.get('time') or '—'} — "
            f"{event['group']} ({event['direction']}){number}{mark}"
        )
    return 'Ваши ближайшие занятия:\n\n' + '\n'.join(lines)


def not_linked() -> str:
    return (
        'Ваш аккаунт ещё не привязан к преподавателю.\n\n'
        'Обратитесь к администратору — он привяжет вас в журнале, '
        'после этого начнут приходить напоминания.'
    )


def journal_unavailable() -> str:
    return 'Журнал сейчас недоступен, попробуйте через пару минут.'
```

- [ ] **Step 4: Написать хендлеры**

`bot/handlers/identify.py`:

```python
"""
На любое входящее сообщение сообщаем журналу, какому нику соответствует chat_id.

Так журнал накапливает справочник аккаунтов, из которого админ выбирает при
привязке, — и админу не приходится набирать ник руками.

Группа хендлеров отдельная (group=-1), чтобы это срабатывало ДО обработки
команды и не мешало ей.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import journal_api


async def identify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.effective_chat.type != 'private':
        return
    journal_api.identify(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name,
    )
```

`bot/handlers/my.py`:

```python
"""/my — ближайшие занятия преподавателя из журнала."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import journal_api
from bot.utils import formatters


async def my(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != 'private':
        return  # в группах бот команды игнорирует
    payload = journal_api.my_events(telegram_id=update.effective_user.id)
    if payload is None:
        await update.message.reply_text(formatters.not_linked())
        return
    await update.message.reply_text(formatters.my_events(payload))
```

`bot/handlers/common.py`:

```python
"""/start, /help и ответ на неизвестную команду."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.utils import formatters


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != 'private':
        return
    await update.message.reply_text(formatters.start(update.effective_user.full_name))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != 'private':
        return
    await update.message.reply_text(formatters.help_text())


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != 'private':
        return
    await update.message.reply_text(formatters.help_text())
```

- [ ] **Step 5: Запустить тесты**

Run: `pytest tests/ -v`
Expected: все passed.

- [ ] **Step 6: Commit**

```bash
git add bot tests
git commit -m "feat: /start, /help, /my поверх API журнала"
```

---

## Task 3: Удаление старого кода

**Files:** удаление, см. список ниже.

- [ ] **Step 1: Удалить файлы**

```bash
git rm bot/database.py bot/scheduler.py migrate_roles.py
git rm bot/services/role_service.py
git rm bot/middlewares/role_check.py bot/middlewares/__init__.py
git rm -r bot/states
git rm bot/handlers/events_add.py bot/handlers/events_edit.py bot/handlers/events_list.py
git rm bot/handlers/manager.py bot/handlers/admin.py bot/handlers/superadmin.py
git rm bot/utils/parser.py bot/utils/notifications.py
```

- [ ] **Step 2: Переписать main.py**

```python
"""
Точка входа. Бот только отвечает на три команды и сообщает журналу о контактах;
напоминания рассылает журнал напрямую через Telegram Bot API.
"""
from __future__ import annotations

import logging

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from bot.config import BOT_TOKEN, setup_logging
from bot.handlers.common import help_command, start, unknown
from bot.handlers.identify import identify
from bot.handlers.my import my
from bot.utils.commands import set_commands

logger = logging.getLogger(__name__)


def build_application():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(set_commands).build()

    # group=-1: срабатывает раньше команд и им не мешает.
    app.add_handler(MessageHandler(filters.ALL, identify), group=-1)

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('my', my))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    return app


def main() -> None:
    setup_logging()
    logger.info('Бот запускается')
    build_application().run_polling()


if __name__ == '__main__':
    main()
```

- [ ] **Step 3: Упростить config.py и commands.py**

Из `bot/config.py` убрать `DB_PATH`, `GENERAL_CHAT_ID`, `SUPERADMIN_ID`. Оставить `BOT_TOKEN`, `TIMEZONE`, `LOG_LEVEL`, настройку логирования и добавить чтение `JOURNAL_API_URL`, `BOT_SERVICE_TOKEN` (они читаются в `journal_api.py`, здесь достаточно загрузки `.env`).

В `bot/utils/commands.py` оставить единое меню из трёх команд — ролевых меню больше нет.

- [ ] **Step 4: Обновить .env.example**

```env
BOT_TOKEN=токен_от_BotFather
JOURNAL_API_URL=http://127.0.0.1:8000
BOT_SERVICE_TOKEN=общий_секрет_с_журналом
TIMEZONE=Europe/Moscow
LOG_LEVEL=INFO
```

`GENERAL_CHAT_ID` переехал в настройки журнала — теперь в общий чат пишет он. `SUPERADMIN_ID` не нужен: ролей у бота больше нет.

- [ ] **Step 5: Проверить, что ничего не осталось**

Run: `grep -rn "database\|sqlite\|apscheduler\|role_service\|ROLE_" --include="*.py" . | grep -v "^./tests"`
Expected: пусто.

Run: `python -c "import main; main.build_application"`
Expected: без ошибок импорта.

- [ ] **Step 6: Запустить тесты**

Run: `pytest tests/ -v`
Expected: все passed.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: убраны собственная БД, роли, планировщик и ручной ввод событий"
```

---

## Task 4: Обновить README и выкатить

**Files:**
- Rewrite: `README.md`

- [ ] **Step 1: Переписать README**

Убрать разделы про роли, команды менеджера и админа, таблицы БД, схему напоминаний APScheduler, `migrate_roles.py`. Добавить: бот — канал доставки, источник правды — журнал; три команды; две переменные окружения для связи с журналом; ссылка на спеку.

- [ ] **Step 2: Выкатить**

```bash
cd /home/kotocode/kotocode-bot
git pull
source venv/bin/activate
pip install -r requirements.txt
nano .env          # добавить JOURNAL_API_URL и BOT_SERVICE_TOKEN
systemctl restart kotocode-bot
journalctl -u kotocode-bot -f
```

- [ ] **Step 3: Проверить живьём**

- Написать боту `/start` — приходит новое приветствие.
- В журнале открыть карточку преподавателя — аккаунт появился в списке для привязки.
- Привязать и выполнить `/my` — приходит список занятий.
- Выполнить `/my` с непривязанного аккаунта — приходит объяснение, что делать.
- Проверить `journalctl`, что нет исключений.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README под новую роль бота"
```

---

## Self-review плана

| Требование спеки §8 | Задача |
|---|---|
| Удалить ручной ввод, роли, SQLite, APScheduler | 3 |
| Оставить `/start`, `/help`, `/my` | 2 |
| Сообщать журналу chat_id при контакте | 2 |
| Новый `.env`, `GENERAL_CHAT_ID` переезжает в журнал | 3 |
| Systemd-юнит не меняется | 4 |
| Сверка данных перед выключением (§12, фаза 0) | 0 |
| Минимальные тесты (§11) | 1, 2 |
