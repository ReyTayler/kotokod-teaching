# Telegram-уведомления: сторона журнала — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Журнал становится единственным источником правды по доп.урокам, переносам и заменам и сам рассылает преподавателям Telegram-уведомления: два дайджеста (расписание в 8:00, незаполненные отчёты в 21:00) и точечные сообщения об изменениях.

**Architecture:** Новое приложение `apps/notifications/` — единственное место, знающее про Telegram. Доменные сервисы (`scheduling`, `extra_lessons`) кладут готовое сообщение в очередь в PostgreSQL (transactional outbox) в той же транзакции, что и сама операция. Celery-beat раз в минуту разгребает очередь и отправляет через Telegram Bot API; дайджесты — отдельные beat-задачи. Идемпотентность обеспечивает уникальный `dedup_key` на уровне БД. Бот в доставке не участвует.

**Tech Stack:** Django 5 + DRF, PostgreSQL, Celery + Redis (beat уже работает в проде), `requests` для Telegram API, pytest, React 19 + TanStack Query v5 (Admin SPA).

**Спека:** `docs/superpowers/specs/2026-08-03-telegram-notifications-design.md` — читать перед началом.

**Отдельный план:** переработка самого бота — `docs/superpowers/plans/2026-08-03-kotocode-bot-rework.md` (другой репозиторий). Этот план от него не зависит: всё проверяется pytest'ом без живого бота.

---

## Правила проекта, которые нарушать нельзя

Прочитать до первой строчки кода — иначе задачи будут переделываться:

1. **RBAC.** DRF по умолчанию `AllowAny`. Каждая новая вьюха ОБЯЗАНА задать `permission_classes`. Забыл → эндпоинт открыт всему интернету.
2. **Тесты гонять полным `pytest -q` из `journal_django/`,** а не по приложениям. Часть приложений no-op'ит `django_db_setup` (общая persistent `journal_test`), часть даёт pytest-django создать свежую `test_journal_test`. Прогон по частям даёт ложнозелёный результат. Приложение `notifications` создаёт новые таблицы ⇒ его тесты **не** переопределяют `django_db_setup`.
3. **pghistory.** Новые доменные модели обязаны получить `@pghistory.track(...)` + запись в `apps/changelog/registry.py`, иначе упадёт `test_registry_covers_all_tracked_models`.
4. **Даты.** «Сейчас» — `apps.core.utils.dates.msk_now()`. DATE приходит из БД строкой `YYYY-MM-DD`.
5. **Admin SPA.** Нативные `<select>`, `<input type=date>`, `<input type=checkbox>` запрещены — только `SelectInput`, `DateInput`, `Checkbox`, `Combobox` из `components/form/`. Подписи enum-значений — только из `lib/labels.ts`. Цвета/радиусы/отступы — только токены из `styles/tokens.css`.
6. **Серверная пагинация.** `placeholderData: keepPreviousData` обязателен в хуках. `ErrorBoundary` — `key={location.pathname}`.
7. **Коммиты.** Коммитить по шагам плана можно (шаги «Commit» ниже). Пушить — только по явной просьбе пользователя.
8. **Секреты** только из окружения, в git не попадают.

---

## Структура файлов

### Создаются

| Файл | Ответственность |
|---|---|
| `apps/notifications/__init__.py`, `apps.py` | регистрация приложения |
| `apps/notifications/models.py` | `TelegramUser`, `TelegramRecipient`, `NotificationMessage` |
| `apps/notifications/migrations/0001_initial.py` | создание трёх таблиц |
| `apps/notifications/constants.py` | значения `kind` / `channel` / `status` в одном месте |
| `apps/notifications/messages.py` | чистые функции «данные → текст сообщения»; ни БД, ни сети |
| `apps/notifications/services.py` | постановка в очередь, идемпотентность, выбор адресатов |
| `apps/notifications/telegram.py` | транспорт: один HTTP-вызов `sendMessage` + разбор ответа |
| `apps/notifications/digests.py` | сборка данных для утреннего и вечернего дайджестов |
| `apps/notifications/dispatcher.py` | разгребание очереди, ретраи, подрезка хвоста |
| `apps/notifications/tasks.py` | три Celery-задачи, делегируют в модули выше |
| `apps/notifications/repository.py` | запросы к очереди для админского раздела |
| `apps/notifications/serializers.py` | сериализаторы раздела «Уведомления» |
| `apps/notifications/views.py` | админские вьюхи раздела |
| `apps/notifications/urls.py` | маршруты `/api/admin/notifications` |
| `apps/notifications/integration_views.py` | служебные вьюхи для бота |
| `apps/notifications/integration_urls.py` | маршруты `/api/integrations/telegram` |
| `apps/notifications/authentication.py` | аутентификация бота по общему секрету |
| `apps/notifications/tests/` | тесты (см. задачи) |
| `frontend/admin-src/src/pages/notifications/NotificationsPage.tsx` | страница раздела |
| `frontend/admin-src/src/pages/notifications/NotificationDetailModal.tsx` | модалка сообщения |
| `frontend/admin-src/src/pages/notifications/SchedulePanel.tsx` | вкладка «Расписание» |
| `frontend/admin-src/src/hooks/useNotifications.ts` | хуки TanStack Query |

### Изменяются

| Файл | Что меняется |
|---|---|
| `config/settings/base.py` | `INSTALLED_APPS`, настройки Telegram, `CELERY_BEAT_SCHEDULE` |
| `config/urls.py` | монтирование двух роутеров |
| `apps/changelog/registry.py` | регистрация `TelegramRecipient` |
| `apps/changelog/labels.py` | правила для новых мутирующих URL |
| `apps/dashboard/fill_service.py` | добавить `teacher_id` в возвращаемые словари |
| `apps/extra_lessons/repository.py` | новая функция `scheduled_on(date)` |
| `apps/extra_lessons/services.py` | вызовы уведомлений в назначении/изменении/отмене |
| `apps/scheduling/services.py` | вызовы уведомлений в переносе/отмене/замене |
| `apps/teachers/serializers.py`, `views.py` | привязка Telegram в карточке преподавателя |
| `frontend/admin-src/src/components/shell/Sidebar.tsx` | пункт «Уведомления» в группе «Система» |
| `frontend/admin-src/src/lib/labels.ts` | подписи `kind`, `channel`, `status` |
| `frontend/admin-src/src/App.tsx` (или файл роутов) | маршрут `/admin/notifications` |
| `deploy/nginx/journal-kotokod.conf` | закрыть `/api/integrations/` на `127.0.0.1` |

---

## Task 1: Каркас приложения и модели

**Files:**
- Create: `apps/notifications/__init__.py`, `apps/notifications/apps.py`, `apps/notifications/constants.py`, `apps/notifications/models.py`
- Create: `apps/notifications/tests/__init__.py`, `apps/notifications/tests/test_models.py`
- Modify: `config/settings/base.py:89` (INSTALLED_APPS)

- [ ] **Step 1: Написать падающий тест**

Создать `apps/notifications/tests/test_models.py`:

```python
"""Тесты моделей notifications: формы данных и защита от дублей."""
from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.notifications.constants import CHANNEL_DM, KIND_MORNING_DIGEST, STATUS_QUEUED
from apps.notifications.models import NotificationMessage, TelegramRecipient, TelegramUser
from apps.teachers.models import Teacher


@pytest.mark.django_db
def test_telegram_user_chat_id_unique():
    TelegramUser.objects.create(chat_id=111, username='ivanov', full_name='Иван')
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TelegramUser.objects.create(chat_id=111, username='other', full_name='Другой')


@pytest.mark.django_db
def test_recipient_is_one_per_teacher():
    teacher = Teacher.objects.create(name='Анна Петрова', created_at='2026-08-01T00:00:00Z')
    tg1 = TelegramUser.objects.create(chat_id=201, username='anna', full_name='Анна')
    tg2 = TelegramUser.objects.create(chat_id=202, username='anna2', full_name='Анна 2')
    TelegramRecipient.objects.create(teacher=teacher, telegram_user=tg1)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TelegramRecipient.objects.create(teacher=teacher, telegram_user=tg2)


@pytest.mark.django_db
def test_dedup_key_is_unique():
    NotificationMessage.objects.create(
        kind=KIND_MORNING_DIGEST, channel=CHANNEL_DM, chat_id=111,
        text='первое', dedup_key='morning:1:2026-08-03', status=STATUS_QUEUED,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            NotificationMessage.objects.create(
                kind=KIND_MORNING_DIGEST, channel=CHANNEL_DM, chat_id=111,
                text='второе', dedup_key='morning:1:2026-08-03', status=STATUS_QUEUED,
            )
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `pytest apps/notifications/tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.notifications'`

- [ ] **Step 3: Создать каркас приложения**

`apps/notifications/__init__.py` — пустой файл.

`apps/notifications/apps.py`:

```python
from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = 'apps.notifications'
    verbose_name = 'Уведомления'
```

`apps/notifications/constants.py`:

```python
"""
Значения enum-полей очереди уведомлений — единый источник.

Строки НЕ дублируются по коду: и модели (CheckConstraint), и сервисы, и тесты
берут их отсюда. Подписи для фронта — во frontend/admin-src/src/lib/labels.ts.
"""
from __future__ import annotations

# --- Типы сообщений --------------------------------------------------------
KIND_MORNING_DIGEST = 'morning_digest'
KIND_FILL_DIGEST = 'fill_digest'
KIND_MAKEUP_ASSIGNED = 'makeup_assigned'
KIND_MAKEUP_CHANGED = 'makeup_changed'
KIND_MAKEUP_CANCELLED = 'makeup_cancelled'
KIND_LESSON_MOVED = 'lesson_moved'
KIND_LESSON_CANCELLED = 'lesson_cancelled'
KIND_SUBSTITUTE_ASSIGNED = 'substitute_assigned'
KIND_SUBSTITUTE_REMOVED = 'substitute_removed'

KIND_CHOICES = [
    KIND_MORNING_DIGEST, KIND_FILL_DIGEST,
    KIND_MAKEUP_ASSIGNED, KIND_MAKEUP_CHANGED, KIND_MAKEUP_CANCELLED,
    KIND_LESSON_MOVED, KIND_LESSON_CANCELLED,
    KIND_SUBSTITUTE_ASSIGNED, KIND_SUBSTITUTE_REMOVED,
]

# --- Каналы ----------------------------------------------------------------
CHANNEL_DM = 'dm'                # личка преподавателя
CHANNEL_GROUP = 'group_chat'     # общий чат сотрудников
CHANNEL_CHOICES = [CHANNEL_DM, CHANNEL_GROUP]

# --- Статусы доставки ------------------------------------------------------
STATUS_QUEUED = 'queued'
STATUS_SENT = 'sent'
STATUS_FAILED = 'failed'
STATUS_CHOICES = [STATUS_QUEUED, STATUS_SENT, STATUS_FAILED]

# Терминальные статусы — только они подлежат подрезке хвоста.
TERMINAL_STATUSES = (STATUS_SENT, STATUS_FAILED)

# Сколько попыток отправки делаем до перевода в failed.
MAX_ATTEMPTS = 5
```

`apps/notifications/models.py`:

```python
"""
Модели уведомлений.

TelegramUser       — справочник аккаунтов, которых бот когда-либо видел. Ещё не
                     привязка: нужен, чтобы админ выбирал из списка, а не набирал
                     ник руками, и чтобы взять числовой chat_id (по @нику Bot API
                     писать в личку не умеет).
TelegramRecipient  — собственно привязка «преподаватель ↔ аккаунт».
NotificationMessage— очередь исходящих, она же журнал доставки (transactional outbox).

См. docs/superpowers/specs/2026-08-03-telegram-notifications-design.md
"""
from __future__ import annotations

import pghistory
from django.db import models

from apps.notifications.constants import (
    CHANNEL_CHOICES, KIND_CHOICES, STATUS_CHOICES, STATUS_QUEUED,
)


class TelegramUser(models.Model):
    """Аккаунт Telegram, известный боту."""

    id = models.AutoField(primary_key=True)
    chat_id = models.BigIntegerField(unique=True)
    # @ник без собаки. В Telegram необязателен и может меняться — опираться на него
    # как на идентификатор нельзя, он только для глаз человека.
    username = models.TextField(null=True, blank=True)
    full_name = models.TextField()
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = 'telegram_users'
        indexes = [models.Index(fields=['username'], name='telegram_users_username_idx')]

    def __str__(self) -> str:
        return f'@{self.username}' if self.username else self.full_name


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
)
class TelegramRecipient(models.Model):
    """Привязка преподавателя к аккаунту Telegram."""

    id = models.AutoField(primary_key=True)
    teacher = models.OneToOneField(
        'teachers.Teacher', on_delete=models.CASCADE,
        related_name='telegram_recipient',
    )
    telegram_user = models.ForeignKey(
        TelegramUser, on_delete=models.PROTECT, related_name='recipients',
    )
    # Снимается автоматически, когда Telegram отвечает «заблокирован» / «чат не найден».
    # Единственный внятный способ узнать, почему человек перестал получать сообщения.
    is_active = models.BooleanField(default=True)
    blocked_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = 'telegram_recipients'


class NotificationMessage(models.Model):
    """
    Одна строка = одно сообщение в один чат.

    Дубль в общий чат — просто вторая строка с другим chat_id, никакой особой
    логики. Под pghistory СОЗНАТЕЛЬНО не ставится: техническая таблица с высокой
    оборачиваемостью, журналировать её изменения — чистый шум.
    """

    id = models.AutoField(primary_key=True)
    kind = models.TextField()
    channel = models.TextField()
    chat_id = models.BigIntegerField()
    # Для отображения в админке. Null для сообщений в общий чат.
    recipient_teacher = models.ForeignKey(
        'teachers.Teacher', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notification_messages',
    )
    text = models.TextField()
    # Ключ идемпотентности: повторная постановка того же сообщения молча ничего
    # не делает (ON CONFLICT DO NOTHING). Защита на уровне БД, а не кода.
    dedup_key = models.TextField(unique=True)
    # След для разбора: 'absence_resolution' + 42.
    source_kind = models.TextField(null=True, blank=True)
    source_id = models.IntegerField(null=True, blank=True)
    status = models.TextField(default=STATUS_QUEUED)
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = 'notification_messages'
        indexes = [
            # Рабочий индекс диспетчера: частичный, только по строкам в очереди.
            models.Index(
                fields=['created_at'], name='notif_queued_idx',
                condition=models.Q(status=STATUS_QUEUED),
            ),
            # Под фильтры и сортировку раздела «Уведомления».
            models.Index(fields=['kind', '-created_at'], name='notif_kind_created_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                name='notification_messages_kind_check',
                condition=models.Q(kind__in=KIND_CHOICES),
            ),
            models.CheckConstraint(
                name='notification_messages_channel_check',
                condition=models.Q(channel__in=CHANNEL_CHOICES),
            ),
            models.CheckConstraint(
                name='notification_messages_status_check',
                condition=models.Q(status__in=STATUS_CHOICES),
            ),
        ]
```

- [ ] **Step 4: Зарегистрировать приложение**

В `config/settings/base.py` в `INSTALLED_APPS` после `'apps.reports',` добавить строку:

```python
    'apps.notifications',
```

- [ ] **Step 5: Создать миграцию**

Run: `python manage.py makemigrations notifications`
Expected: `Create model TelegramUser`, `Create model TelegramRecipient`, `Create model NotificationMessage` + триггеры pghistory.

- [ ] **Step 6: Запустить тесты**

Run: `pytest apps/notifications/tests/test_models.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add apps/notifications config/settings/base.py
git commit -m "feat(notifications): модели очереди уведомлений и привязки Telegram"
```

---

## Task 2: Регистрация в журнале изменений

**Files:**
- Modify: `apps/changelog/registry.py`
- Test: существующий `apps/changelog/tests/` (тест реестра уже есть)

- [ ] **Step 1: Убедиться, что тест реестра падает**

Run: `pytest apps/changelog -k registry_covers -v`
Expected: FAIL — `TelegramRecipient` трекается pghistory, но отсутствует в `TRACKED`.

- [ ] **Step 2: Добавить модель в реестр**

В `apps/changelog/registry.py` в словарь `TRACKED` добавить (topo=15 — после справочников, рядом с `accounts.Account`, поскольку зависит от `teachers.Teacher`):

```python
    'notifications.TelegramRecipient': TrackedModel('telegram_recipient', False, 15),
```

`revertable=False`: откат привязки Telegram смысла не имеет — это не доменные данные, а канал связи, и восстановление удалённой строки не вернёт согласие человека получать сообщения.

- [ ] **Step 3: Добавить правила меток операций**

В `apps/changelog/labels.py` добавить правила для новых мутирующих URL по образцу соседних записей в файле: `POST /api/admin/teachers/<id>/telegram` → «Привязка Telegram», `DELETE /api/admin/teachers/<id>/telegram` → «Отвязка Telegram». Точный формат правил взять из существующих строк того же файла.

- [ ] **Step 4: Запустить тесты**

Run: `pytest apps/changelog -v`
Expected: все passed.

- [ ] **Step 5: Commit**

```bash
git add apps/changelog
git commit -m "feat(changelog): TelegramRecipient в реестре журнала изменений"
```

---

## Task 3: Тексты сообщений

**Files:**
- Create: `apps/notifications/messages.py`
- Test: `apps/notifications/tests/test_messages.py`

Чистые функции «данные → строка». Ни БД, ни сети — поэтому тесты не требуют `django_db` и выполняются мгновенно.

- [ ] **Step 1: Написать падающие тесты**

`apps/notifications/tests/test_messages.py`:

```python
"""Тесты форматирования текстов. Без БД: функции чистые."""
from __future__ import annotations

import datetime

from apps.notifications import messages


def test_morning_digest_marks_substitute_and_extra():
    text = messages.morning_digest(
        teacher_name='Анна Петрова',
        day=datetime.date(2026, 8, 3),
        items=[
            {'time': '12:00', 'group': 'СИ1027', 'direction': 'Scratch',
             'seq': 1, 'is_substitute': False, 'is_extra': False},
            {'time': '13:00', 'group': 'ПИ1062', 'direction': 'Python',
             'seq': 9, 'is_substitute': True, 'is_extra': False},
            {'time': '14:30', 'group': 'ПИ1062', 'direction': 'Python',
             'seq': None, 'is_substitute': False, 'is_extra': True},
        ],
    )
    assert 'Доброе утро, Анна Петрова!' in text
    assert 'Ваши уроки на сегодня (03.08):' in text
    assert '• 12:00 — СИ1027 (Scratch) — урок №1' in text
    assert '• 13:00 — ПИ1062 (Python) — урок №9 (замена)' in text
    assert '• 14:30 — ПИ1062 (Python) — доп.урок' in text
    assert 'Хорошего дня! 🚀' in text


def test_fill_digest_always_has_the_required_footer():
    text = messages.fill_digest(items=[
        {'date': datetime.date(2026, 8, 2), 'time': '16:00', 'group': 'ПИ1054',
         'direction': 'Python', 'seq': 11},
    ])
    assert '• 02.08, 16:00 — ПИ1054 (Python) — урок №11' in text
    assert 'Если уроков не было, сообщите менеджеру или администратору.' in text


def test_makeup_assigned_states_who_what_when():
    text = messages.makeup_assigned(
        teacher_name='Анна Петрова',
        group='ПИ1062', direction='Python',
        day=datetime.date(2026, 8, 10), time='14:30',
        student_name='Пётр Иванов', is_beyond_course=False,
    )
    assert 'доп.урок' in text.lower()
    assert '10.08' in text
    assert '14:30' in text
    assert 'ПИ1062' in text
    assert 'Пётр Иванов' in text


def test_lesson_moved_shows_both_dates():
    text = messages.lesson_moved(
        group='СИ1027', direction='Scratch', seq=4,
        from_day=datetime.date(2026, 8, 5), to_day=datetime.date(2026, 8, 12),
        time='12:00',
    )
    assert '05.08' in text
    assert '12.08' in text
    assert 'СИ1027' in text
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest apps/notifications/tests/test_messages.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.notifications.messages`

- [ ] **Step 3: Реализовать модуль**

`apps/notifications/messages.py`:

```python
"""
Тексты сообщений. Чистые функции: данные на входе, готовая строка на выходе.

Формат — HTML (parse_mode=HTML в Telegram API), поэтому пользовательские данные
экранируются: имя группы или ученика с символом «&» иначе сломает разбор
сообщения на стороне Telegram и оно не доставится.

Номер урока — ПОРЯДКОВЫЙ (PlannedLesson.seq). На 45-минутных курсах в БД лежит
lesson_number = seq × 0.5 — это внутренний вес для расчёта денег и прогресса,
преподавателю он не показывается.
"""
from __future__ import annotations

import datetime
from html import escape


def _d(day: datetime.date) -> str:
    """Дата в человеческом виде: 03.08."""
    return day.strftime('%d.%m')


def _lesson_line(item: dict) -> str:
    """Одна строка списка занятий."""
    head = f"• {item['time']} — {escape(item['group'])} ({escape(item['direction'])})"
    if item.get('is_extra'):
        return f'{head} — доп.урок'
    line = f"{head} — урок №{item['seq']}"
    if item.get('is_substitute'):
        line += ' (замена)'
    return line


def morning_digest(*, teacher_name: str, day: datetime.date, items: list[dict]) -> str:
    """Утренний список занятий. Вызывается только когда items непуст."""
    lines = '\n'.join(_lesson_line(i) for i in items)
    return (
        f'Доброе утро, {escape(teacher_name)}!\n\n'
        f'Ваши уроки на сегодня ({_d(day)}):\n\n'
        f'{lines}\n\n'
        'Хорошего дня! 🚀'
    )


def fill_digest(*, items: list[dict]) -> str:
    """Вечерний список незаполненных отчётов. Последняя строка обязательна."""
    lines = '\n'.join(
        f"• {_d(i['date'])}, {i['time']} — {escape(i['group'])} "
        f"({escape(i['direction'])}) — урок №{i['seq']}"
        if i.get('seq') is not None else
        f"• {_d(i['date'])}, {i['time']} — {escape(i['group'])} "
        f"({escape(i['direction'])}) — доп.урок"
        for i in items
    )
    return (
        'Не заполнены отчёты:\n\n'
        f'{lines}\n\n'
        'Если уроков не было, сообщите менеджеру или администратору.'
    )


def makeup_assigned(*, teacher_name: str, group: str, direction: str,
                    day: datetime.date, time: str, student_name: str,
                    is_beyond_course: bool) -> str:
    what = 'Доп.урок сверх курса' if is_beyond_course else 'Доп.урок (отработка)'
    return (
        f'{what} назначен.\n\n'
        f'{escape(group)} ({escape(direction)})\n'
        f'{_d(day)} в {time}\n'
        f'Ученик: {escape(student_name)}\n'
        f'Преподаватель: {escape(teacher_name)}'
    )


def makeup_changed(*, teacher_name: str, group: str, direction: str,
                   day: datetime.date, time: str, student_name: str) -> str:
    return (
        'Доп.урок изменён.\n\n'
        f'{escape(group)} ({escape(direction)})\n'
        f'Новое время: {_d(day)} в {time}\n'
        f'Ученик: {escape(student_name)}\n'
        f'Преподаватель: {escape(teacher_name)}'
    )


def makeup_cancelled(*, teacher_name: str, group: str, direction: str,
                     day: datetime.date, time: str, student_name: str) -> str:
    return (
        'Доп.урок отменён.\n\n'
        f'{escape(group)} ({escape(direction)})\n'
        f'Было: {_d(day)} в {time}\n'
        f'Ученик: {escape(student_name)}\n'
        f'Преподаватель: {escape(teacher_name)}'
    )


def lesson_moved(*, group: str, direction: str, seq: int | None,
                 from_day: datetime.date, to_day: datetime.date, time: str) -> str:
    number = f' — урок №{seq}' if seq is not None else ''
    return (
        'Занятие перенесено.\n\n'
        f'{escape(group)} ({escape(direction)}){number}\n'
        f'Было: {_d(from_day)}\n'
        f'Стало: {_d(to_day)} в {time}'
    )


def lesson_cancelled(*, group: str, direction: str, seq: int | None,
                     day: datetime.date, time: str) -> str:
    number = f' — урок №{seq}' if seq is not None else ''
    return (
        'Занятие отменено.\n\n'
        f'{escape(group)} ({escape(direction)}){number}\n'
        f'Было: {_d(day)} в {time}'
    )


def substitute_assigned(*, group: str, direction: str, day: datetime.date,
                        time: str, substitute_name: str, for_substitute: bool) -> str:
    if for_substitute:
        head = 'Вас назначили заменой.'
    else:
        head = f'На ваше занятие назначена замена: {escape(substitute_name)}.'
    return (
        f'{head}\n\n'
        f'{escape(group)} ({escape(direction)})\n'
        f'{_d(day)} в {time}'
    )


def substitute_removed(*, group: str, direction: str, day: datetime.date,
                       time: str, for_substitute: bool) -> str:
    head = 'Замена снята — занятие ведёт основной преподаватель.' if for_substitute \
        else 'Замена снята — занятие снова за вами.'
    return (
        f'{head}\n\n'
        f'{escape(group)} ({escape(direction)})\n'
        f'{_d(day)} в {time}'
    )
```

- [ ] **Step 4: Запустить тесты**

Run: `pytest apps/notifications/tests/test_messages.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/notifications/messages.py apps/notifications/tests/test_messages.py
git commit -m "feat(notifications): тексты сообщений"
```

---

## Task 4: Постановка в очередь

**Files:**
- Create: `apps/notifications/services.py`
- Test: `apps/notifications/tests/test_enqueue.py`
- Modify: `config/settings/base.py` (настройки Telegram)

- [ ] **Step 1: Добавить настройки**

В `config/settings/base.py` после блока `CELERY_*` добавить:

```python
# ---------------------------------------------------------------------------
# Telegram-уведомления (спека 2026-08-03)
# ---------------------------------------------------------------------------
# Токен того же бота, что крутится в kotocode-bot. Отправлять с одним токеном
# может несколько процессов — ограничение Telegram касается только getUpdates.
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
# Общий чат сотрудников: сюда дублируются точечные уведомления об изменениях.
# Дайджесты сюда НЕ идут (см. спеку, п. 2.5).
TELEGRAM_GENERAL_CHAT_ID = int(os.environ.get('TELEGRAM_GENERAL_CHAT_ID', '0') or 0)
# Общий секрет журнал ↔ бот для служебных эндпоинтов /api/integrations/telegram.
BOT_SERVICE_TOKEN = os.environ.get('BOT_SERVICE_TOKEN', '')
# Сколько ЗАВЕРШЁННЫХ записей очереди храним. Строки в очереди не удаляются никогда.
NOTIFICATIONS_HISTORY_LIMIT = int(os.environ.get('NOTIFICATIONS_HISTORY_LIMIT', '200'))
```

- [ ] **Step 2: Написать падающие тесты**

`apps/notifications/tests/test_enqueue.py`:

```python
"""Тесты постановки в очередь: идемпотентность и выбор адресатов."""
from __future__ import annotations

import pytest
from django.test import override_settings

from apps.notifications import services
from apps.notifications.constants import (
    CHANNEL_DM, CHANNEL_GROUP, KIND_MAKEUP_ASSIGNED, STATUS_QUEUED,
)
from apps.notifications.models import NotificationMessage, TelegramRecipient, TelegramUser
from apps.teachers.models import Teacher


@pytest.fixture
def teacher(db):
    return Teacher.objects.create(name='Анна Петрова', created_at='2026-08-01T00:00:00Z')


@pytest.fixture
def linked_teacher(teacher):
    tg = TelegramUser.objects.create(chat_id=555, username='anna', full_name='Анна')
    TelegramRecipient.objects.create(teacher=teacher, telegram_user=tg)
    return teacher


@pytest.mark.django_db
def test_enqueue_is_idempotent(linked_teacher):
    for _ in range(3):
        services.enqueue(
            kind=KIND_MAKEUP_ASSIGNED, channel=CHANNEL_DM, chat_id=555,
            text='текст', dedup_key='makeup_assigned:42:dm',
        )
    assert NotificationMessage.objects.filter(dedup_key='makeup_assigned:42:dm').count() == 1


@pytest.mark.django_db
@override_settings(TELEGRAM_GENERAL_CHAT_ID=-100500)
def test_notify_teacher_creates_dm_and_group_rows(linked_teacher):
    services.notify_teacher(
        kind=KIND_MAKEUP_ASSIGNED,
        teacher_id=linked_teacher.id,
        text='Доп.урок назначен.',
        dedup_prefix='makeup_assigned:42',
        source_kind='absence_resolution', source_id=42,
        also_to_group_chat=True,
    )
    rows = NotificationMessage.objects.order_by('channel')
    assert [r.channel for r in rows] == [CHANNEL_DM, CHANNEL_GROUP]
    assert {r.chat_id for r in rows} == {555, -100500}
    assert all(r.status == STATUS_QUEUED for r in rows)


@pytest.mark.django_db
@override_settings(TELEGRAM_GENERAL_CHAT_ID=-100500)
def test_unlinked_teacher_still_gets_group_chat_copy(teacher):
    """Привязки нет — личка не создаётся, но чат получает сообщение.

    Система деградирует мягко: молчать нельзя, иначе перенос потеряется.
    """
    services.notify_teacher(
        kind=KIND_MAKEUP_ASSIGNED, teacher_id=teacher.id, text='Доп.урок назначен.',
        dedup_prefix='makeup_assigned:43',
        source_kind='absence_resolution', source_id=43,
        also_to_group_chat=True,
    )
    rows = list(NotificationMessage.objects.all())
    assert len(rows) == 1
    assert rows[0].channel == CHANNEL_GROUP


@pytest.mark.django_db
@override_settings(TELEGRAM_GENERAL_CHAT_ID=-100500)
def test_inactive_recipient_gets_no_dm(linked_teacher):
    TelegramRecipient.objects.filter(teacher=linked_teacher).update(
        is_active=False, blocked_reason='bot was blocked by the user')
    services.notify_teacher(
        kind=KIND_MAKEUP_ASSIGNED, teacher_id=linked_teacher.id, text='т',
        dedup_prefix='makeup_assigned:44',
        source_kind='absence_resolution', source_id=44,
        also_to_group_chat=True,
    )
    assert not NotificationMessage.objects.filter(channel=CHANNEL_DM).exists()


@pytest.mark.django_db
@override_settings(TELEGRAM_GENERAL_CHAT_ID=0)
def test_group_chat_not_configured_is_not_an_error(linked_teacher):
    """Пустой TELEGRAM_GENERAL_CHAT_ID (локальная разработка) не должен ронять запись урока."""
    services.notify_teacher(
        kind=KIND_MAKEUP_ASSIGNED, teacher_id=linked_teacher.id, text='т',
        dedup_prefix='makeup_assigned:45',
        source_kind='absence_resolution', source_id=45,
        also_to_group_chat=True,
    )
    assert NotificationMessage.objects.filter(channel=CHANNEL_GROUP).count() == 0
    assert NotificationMessage.objects.filter(channel=CHANNEL_DM).count() == 1
```

- [ ] **Step 3: Запустить и убедиться, что падает**

Run: `pytest apps/notifications/tests/test_enqueue.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.notifications.services`

- [ ] **Step 4: Реализовать сервис**

`apps/notifications/services.py`:

```python
"""
Постановка сообщений в очередь.

Вызывается ИЗ ТОЙ ЖЕ ТРАНЗАКЦИИ, что и доменная операция (transactional outbox):
либо доп.урок назначен и сообщение поставлено, либо не произошло ни то, ни другое.
Состояния «назначили, а сказать забыли» не существует.

Отправку инициирует НЕ транзакция: после коммита (transaction.on_commit) дёргается
диспетчер, чтобы точечные уведомления уходили сразу. Прямой .delay() внутри
транзакции недопустим — задача стартует раньше коммита и не находит данных.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction

from apps.notifications.constants import CHANNEL_DM, CHANNEL_GROUP
from apps.notifications.models import NotificationMessage, TelegramRecipient

logger = logging.getLogger(__name__)


def enqueue(*, kind: str, channel: str, chat_id: int, text: str, dedup_key: str,
            recipient_teacher_id: int | None = None,
            source_kind: str | None = None, source_id: int | None = None) -> bool:
    """
    Поставить одно сообщение в очередь. Возвращает True, если строка создана.

    Повторная постановка того же dedup_key молча ничего не делает: защита от
    двойного клика, повторного запуска задачи и гонки воркеров — на уровне БД,
    а не на уровне «мы аккуратно написали код».
    """
    # get_or_create, а НЕ bulk_create(ignore_conflicts=True): на PostgreSQL второй
    # не проставляет pk в возвращаемый объект даже при успешной вставке, поэтому
    # по нему нельзя понять, была ли строка создана. get_or_create честно отдаёт
    # флаг created и сам оборачивает вставку в savepoint — безопасно внутри
    # внешней транзакции доменной операции.
    _row, created = NotificationMessage.objects.get_or_create(
        dedup_key=dedup_key,
        defaults={
            'kind': kind, 'channel': channel, 'chat_id': chat_id, 'text': text,
            'recipient_teacher_id': recipient_teacher_id,
            'source_kind': source_kind, 'source_id': source_id,
        },
    )
    return created


def active_chat_id(teacher_id: int) -> int | None:
    """chat_id активной привязки преподавателя либо None."""
    row = (TelegramRecipient.objects
           .filter(teacher_id=teacher_id, is_active=True)
           .values_list('telegram_user__chat_id', flat=True)
           .first())
    return row


def notify_teacher(*, kind: str, teacher_id: int, text: str, dedup_prefix: str,
                   source_kind: str, source_id: int,
                   also_to_group_chat: bool) -> None:
    """
    Уведомить преподавателя: личка и, если нужно, дубль в общий чат.

    Дубль — просто вторая строка очереди с другим chat_id, никакой особой логики.
    Нет привязки → личка не создаётся, но общий чат сообщение получает.
    """
    chat_id = active_chat_id(teacher_id)
    if chat_id is not None:
        enqueue(kind=kind, channel=CHANNEL_DM, chat_id=chat_id, text=text,
                dedup_key=f'{dedup_prefix}:dm', recipient_teacher_id=teacher_id,
                source_kind=source_kind, source_id=source_id)

    general = getattr(settings, 'TELEGRAM_GENERAL_CHAT_ID', 0)
    if also_to_group_chat and general:
        enqueue(kind=kind, channel=CHANNEL_GROUP, chat_id=general, text=text,
                dedup_key=f'{dedup_prefix}:group', recipient_teacher_id=None,
                source_kind=source_kind, source_id=source_id)

    _request_dispatch()


def _request_dispatch() -> None:
    """
    После коммита попросить воркер разгрести очередь — чтобы точечные уведомления
    уходили сразу, а не ждали минутного тика beat.

    Celery локально не установлен (штатный режим, см. config/celery.py): тогда
    ничего не происходит, сообщение остаётся в очереди. Ничего не падает и
    ничего не теряется.
    """
    def _kick() -> None:
        try:
            from apps.notifications.tasks import dispatch_outbox
            dispatch_outbox.delay()
        except Exception:  # noqa: BLE001 — Celery/Redis недоступны: это не ошибка
            logger.debug('dispatch_outbox не запущен: Celery недоступен')

    transaction.on_commit(_kick)
```

- [ ] **Step 5: Запустить тесты**

Run: `pytest apps/notifications/tests/test_enqueue.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/notifications config/settings/base.py
git commit -m "feat(notifications): постановка сообщений в очередь с идемпотентностью"
```

---

## Task 5: Транспорт Telegram

**Files:**
- Create: `apps/notifications/telegram.py`
- Test: `apps/notifications/tests/test_telegram_transport.py`

- [ ] **Step 1: Написать падающие тесты**

`apps/notifications/tests/test_telegram_transport.py`:

```python
"""Тесты транспорта: разбор ответов Telegram. Сеть замокана."""
from __future__ import annotations

from unittest.mock import patch

from django.test import override_settings

from apps.notifications import telegram


class _Resp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@override_settings(TELEGRAM_BOT_TOKEN='tkn')
def test_ok_response():
    with patch('apps.notifications.telegram.requests.post',
               return_value=_Resp(200, {'ok': True})):
        result = telegram.send_message(chat_id=1, text='привет')
    assert result.ok is True
    assert result.blocked is False


@override_settings(TELEGRAM_BOT_TOKEN='tkn')
def test_blocked_by_user_is_permanent():
    payload = {'ok': False, 'error_code': 403,
               'description': 'Forbidden: bot was blocked by the user'}
    with patch('apps.notifications.telegram.requests.post',
               return_value=_Resp(403, payload)):
        result = telegram.send_message(chat_id=1, text='привет')
    assert result.ok is False
    assert result.blocked is True
    assert result.retry_after is None


@override_settings(TELEGRAM_BOT_TOKEN='tkn')
def test_chat_not_found_is_permanent():
    payload = {'ok': False, 'error_code': 400, 'description': 'Bad Request: chat not found'}
    with patch('apps.notifications.telegram.requests.post',
               return_value=_Resp(400, payload)):
        result = telegram.send_message(chat_id=1, text='привет')
    assert result.blocked is True


@override_settings(TELEGRAM_BOT_TOKEN='tkn')
def test_rate_limit_reports_retry_after():
    payload = {'ok': False, 'error_code': 429, 'description': 'Too Many Requests',
               'parameters': {'retry_after': 7}}
    with patch('apps.notifications.telegram.requests.post',
               return_value=_Resp(429, payload)):
        result = telegram.send_message(chat_id=1, text='привет')
    assert result.ok is False
    assert result.blocked is False
    assert result.retry_after == 7


@override_settings(TELEGRAM_BOT_TOKEN='tkn')
def test_network_error_is_temporary():
    import requests as rq
    with patch('apps.notifications.telegram.requests.post',
               side_effect=rq.ConnectionError('boom')):
        result = telegram.send_message(chat_id=1, text='привет')
    assert result.ok is False
    assert result.blocked is False
    assert result.retry_after is None
    assert 'boom' in result.error


@override_settings(TELEGRAM_BOT_TOKEN='')
def test_missing_token_does_not_call_network():
    with patch('apps.notifications.telegram.requests.post') as post:
        result = telegram.send_message(chat_id=1, text='привет')
    post.assert_not_called()
    assert result.ok is False
    assert result.blocked is False
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest apps/notifications/tests/test_telegram_transport.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.notifications.telegram`

- [ ] **Step 3: Реализовать транспорт**

`apps/notifications/telegram.py`:

```python
"""
Транспорт Telegram: один HTTP-вызов sendMessage и осмысленный разбор ответа.

Здесь нет ни бизнес-логики, ни работы с БД — только «отправь строку в чат и
скажи, что ответил Telegram». Решение, что делать с ответом, принимает диспетчер.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

API_URL = 'https://api.telegram.org/bot{token}/sendMessage'
TIMEOUT_SECONDS = 10

# Описания, означающие «этому адресату писать бесполезно, пока он сам не вернётся».
_PERMANENT_MARKERS = (
    'bot was blocked by the user',
    'chat not found',
    'user is deactivated',
    'bot was kicked',
)


@dataclass(frozen=True)
class SendResult:
    ok: bool
    # Постоянный отказ: адресат недоступен, повторять бессмысленно —
    # привязку надо деактивировать.
    blocked: bool = False
    # Telegram просит подождать столько секунд (код 429).
    retry_after: int | None = None
    error: str = ''


def send_message(*, chat_id: int, text: str) -> SendResult:
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not token:
        # Локальная разработка без токена: не ходим в сеть, честно сообщаем.
        return SendResult(ok=False, error='TELEGRAM_BOT_TOKEN не задан')

    try:
        response = requests.post(
            API_URL.format(token=token),
            json={
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
            },
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return SendResult(ok=False, error=str(exc))

    try:
        payload = response.json()
    except ValueError:
        return SendResult(ok=False, error=f'HTTP {response.status_code}: не JSON')

    if payload.get('ok'):
        return SendResult(ok=True)

    description = str(payload.get('description', ''))
    retry_after = (payload.get('parameters') or {}).get('retry_after')
    if retry_after:
        return SendResult(ok=False, retry_after=int(retry_after), error=description)

    lowered = description.lower()
    blocked = any(marker in lowered for marker in _PERMANENT_MARKERS)
    return SendResult(ok=False, blocked=blocked, error=description)
```

- [ ] **Step 4: Добавить зависимость**

Проверить, что `requests` уже в `requirements.txt`:

Run: `grep -i "^requests" requirements.txt`
Если строки нет — добавить `requests==2.32.3` и выполнить `pip install -r requirements.txt`.

- [ ] **Step 5: Запустить тесты**

Run: `pytest apps/notifications/tests/test_telegram_transport.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/notifications requirements.txt
git commit -m "feat(notifications): транспорт Telegram с разбором ответов API"
```

---

## Task 6: Диспетчер очереди

**Files:**
- Create: `apps/notifications/dispatcher.py`
- Test: `apps/notifications/tests/test_dispatcher.py`

- [ ] **Step 1: Написать падающие тесты**

`apps/notifications/tests/test_dispatcher.py`:

```python
"""Тесты диспетчера: успех, отказы, ретраи, подрезка хвоста."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.notifications import dispatcher
from apps.notifications.constants import (
    CHANNEL_DM, KIND_MAKEUP_ASSIGNED, MAX_ATTEMPTS,
    STATUS_FAILED, STATUS_QUEUED, STATUS_SENT,
)
from apps.notifications.models import NotificationMessage, TelegramRecipient, TelegramUser
from apps.notifications.telegram import SendResult
from apps.teachers.models import Teacher


@pytest.fixture
def linked(db):
    teacher = Teacher.objects.create(name='Анна', created_at='2026-08-01T00:00:00Z')
    tg = TelegramUser.objects.create(chat_id=555, username='anna', full_name='Анна')
    TelegramRecipient.objects.create(teacher=teacher, telegram_user=tg)
    return teacher


def _msg(dedup: str, teacher=None, chat_id: int = 555) -> NotificationMessage:
    return NotificationMessage.objects.create(
        kind=KIND_MAKEUP_ASSIGNED, channel=CHANNEL_DM, chat_id=chat_id,
        text='текст', dedup_key=dedup, status=STATUS_QUEUED,
        recipient_teacher=teacher,
    )


@pytest.mark.django_db
def test_successful_send_marks_sent(linked):
    row = _msg('a', linked)
    with patch('apps.notifications.dispatcher.telegram.send_message',
               return_value=SendResult(ok=True)):
        dispatcher.dispatch()
    row.refresh_from_db()
    assert row.status == STATUS_SENT
    assert row.sent_at is not None


@pytest.mark.django_db
def test_blocked_deactivates_recipient(linked):
    row = _msg('b', linked)
    with patch('apps.notifications.dispatcher.telegram.send_message',
               return_value=SendResult(ok=False, blocked=True,
                                       error='bot was blocked by the user')):
        dispatcher.dispatch()
    row.refresh_from_db()
    assert row.status == STATUS_FAILED
    recipient = TelegramRecipient.objects.get(teacher=linked)
    assert recipient.is_active is False
    assert 'blocked' in recipient.blocked_reason


@pytest.mark.django_db
def test_rate_limit_leaves_message_queued(linked):
    row = _msg('c', linked)
    with patch('apps.notifications.dispatcher.telegram.send_message',
               return_value=SendResult(ok=False, retry_after=5, error='Too Many Requests')):
        dispatcher.dispatch()
    row.refresh_from_db()
    assert row.status == STATUS_QUEUED
    assert row.attempts == 1


@pytest.mark.django_db
def test_temporary_error_fails_only_after_max_attempts(linked):
    row = _msg('d', linked)
    with patch('apps.notifications.dispatcher.telegram.send_message',
               return_value=SendResult(ok=False, error='timeout')):
        for _ in range(MAX_ATTEMPTS - 1):
            dispatcher.dispatch()
        row.refresh_from_db()
        assert row.status == STATUS_QUEUED

        dispatcher.dispatch()
    row.refresh_from_db()
    assert row.status == STATUS_FAILED
    assert row.attempts == MAX_ATTEMPTS
    assert 'timeout' in row.last_error


@pytest.mark.django_db
@override_settings(NOTIFICATIONS_HISTORY_LIMIT=3)
def test_trim_keeps_limit_and_never_touches_queued(linked):
    for i in range(6):
        m = _msg(f'sent-{i}', linked)
        m.status = STATUS_SENT
        m.save(update_fields=['status'])
    pending = _msg('still-queued', linked)

    dispatcher.trim_history()

    assert NotificationMessage.objects.filter(status=STATUS_SENT).count() == 3
    assert NotificationMessage.objects.filter(pk=pending.pk).exists()


@pytest.mark.django_db
def test_dispatch_is_batched(linked):
    for i in range(dispatcher.BATCH_SIZE + 5):
        _msg(f'batch-{i}', linked)
    with patch('apps.notifications.dispatcher.telegram.send_message',
               return_value=SendResult(ok=True)) as send:
        dispatcher.dispatch()
    assert send.call_count == dispatcher.BATCH_SIZE
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest apps/notifications/tests/test_dispatcher.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.notifications.dispatcher`

- [ ] **Step 3: Реализовать диспетчер**

`apps/notifications/dispatcher.py`:

```python
"""
Диспетчер очереди: берёт сообщения, отправляет, разбирается с ответами,
подрезает хвост истории.

Блокировка строк — SELECT ... FOR UPDATE SKIP LOCKED: два воркера никогда не
возьмут одну строку и не пришлют человеку дубль.
"""
from __future__ import annotations

import logging
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.notifications import telegram
from apps.notifications.constants import (
    MAX_ATTEMPTS, STATUS_FAILED, STATUS_QUEUED, STATUS_SENT, TERMINAL_STATUSES,
)
from apps.notifications.models import NotificationMessage, TelegramRecipient

logger = logging.getLogger(__name__)

# Лимит Telegram — порядка 30 сообщений в секунду. 100 сообщений с паузой 40 мс
# уходят примерно за 4 секунды: утренний дайджест на 100 преподавателей
# укладывается в один прогон.
BATCH_SIZE = 100
PAUSE_BETWEEN_SENDS = 0.04


def dispatch() -> int:
    """
    Один прогон: отправить до BATCH_SIZE сообщений. Возвращает число отправленных.

    Строки берутся по одной в отдельной транзакции с блокировкой: длинная
    транзакция на весь батч держала бы блокировки все 4 секунды.
    """
    sent = 0
    for _ in range(BATCH_SIZE):
        message_id = _claim_next()
        if message_id is None:
            break
        outcome = _send_one(message_id)
        if outcome == 'sent':
            sent += 1
        elif outcome == 'rate_limited':
            # Telegram просит притормозить — заканчиваем прогон, остальное
            # уедет следующим тиком beat через минуту.
            break
        time.sleep(PAUSE_BETWEEN_SENDS)
    trim_history()
    return sent


def _claim_next() -> int | None:
    """Взять id следующего сообщения в очереди, заблокировав строку."""
    with transaction.atomic():
        row = (NotificationMessage.objects
               .select_for_update(skip_locked=True)
               .filter(status=STATUS_QUEUED)
               .order_by('created_at')
               .values_list('id', flat=True)
               .first())
        return row


def _send_one(message_id: int) -> str:
    """Отправить одно сообщение и записать исход. Возвращает 'sent'|'retry'|'rate_limited'|'failed'."""
    with transaction.atomic():
        message = (NotificationMessage.objects
                   .select_for_update()
                   .filter(id=message_id, status=STATUS_QUEUED)
                   .first())
        if message is None:
            return 'retry'

        result = telegram.send_message(chat_id=message.chat_id, text=message.text)

        if result.ok:
            message.status = STATUS_SENT
            message.sent_at = timezone.now()
            message.attempts += 1
            message.last_error = None
            message.save(update_fields=['status', 'sent_at', 'attempts', 'last_error'])
            return 'sent'

        message.attempts += 1
        message.last_error = result.error[:2000]

        if result.blocked:
            # Адресат недоступен — повторять бессмысленно. Гасим сообщение и
            # деактивируем привязку, чтобы это было видно админу в карточке.
            message.status = STATUS_FAILED
            message.save(update_fields=['status', 'attempts', 'last_error'])
            _deactivate_recipient(message)
            return 'failed'

        if result.retry_after:
            message.save(update_fields=['attempts', 'last_error'])
            return 'rate_limited'

        if message.attempts >= MAX_ATTEMPTS:
            message.status = STATUS_FAILED
        message.save(update_fields=['status', 'attempts', 'last_error'])
        return 'failed' if message.status == STATUS_FAILED else 'retry'


def _deactivate_recipient(message: NotificationMessage) -> None:
    if message.recipient_teacher_id is None:
        return
    TelegramRecipient.objects.filter(teacher_id=message.recipient_teacher_id).update(
        is_active=False, blocked_reason=message.last_error,
    )
    logger.warning('Привязка Telegram деактивирована: teacher_id=%s, причина=%s',
                   message.recipient_teacher_id, message.last_error)


def trim_history() -> int:
    """
    Оставить не более NOTIFICATIONS_HISTORY_LIMIT завершённых записей.

    Строки в очереди НЕ удаляются никогда — иначе однажды подрезка съест
    неотправленное сообщение.
    """
    limit = getattr(settings, 'NOTIFICATIONS_HISTORY_LIMIT', 200)
    stale_ids = list(
        NotificationMessage.objects
        .filter(status__in=TERMINAL_STATUSES)
        .order_by('-created_at', '-id')
        .values_list('id', flat=True)[limit:]
    )
    if not stale_ids:
        return 0
    deleted, _ = NotificationMessage.objects.filter(id__in=stale_ids).delete()
    return deleted
```

- [ ] **Step 4: Запустить тесты**

Run: `pytest apps/notifications/tests/test_dispatcher.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/notifications
git commit -m "feat(notifications): диспетчер очереди с ретраями и подрезкой истории"
```

---

## Task 7: Источники данных для дайджестов

**Files:**
- Modify: `apps/dashboard/fill_service.py`
- Modify: `apps/extra_lessons/repository.py`
- Test: `apps/notifications/tests/test_digest_sources.py`

- [ ] **Step 1: Написать падающие тесты**

`apps/notifications/tests/test_digest_sources.py`:

```python
"""Источники данных дайджестов: teacher_id в fill_service и доп.уроки на дату."""
from __future__ import annotations

import datetime

import pytest

from apps.dashboard import fill_service


@pytest.mark.django_db
def test_unfilled_lessons_expose_teacher_id():
    """Вечернему дайджесту нужен id для группировки, а не только имя.

    Раньше fill_service отдавал только teacher_name — по имени группировать нельзя,
    полные тёзки в школе встречаются.
    """
    rows = fill_service.unfilled_lessons(
        now=datetime.datetime(2026, 8, 3, 22, 0, tzinfo=fill_service.MSK))
    for row in rows:
        assert 'teacher_id' in row


@pytest.mark.django_db
def test_scheduled_extra_lessons_on_date_returns_empty_for_far_future():
    from apps.extra_lessons import repository as extra_repo
    assert extra_repo.scheduled_on(datetime.date(2099, 1, 1)) == []
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest apps/notifications/tests/test_digest_sources.py -v`
Expected: FAIL — `KeyError: 'teacher_id'` и `AttributeError: module has no attribute 'scheduled_on'`

- [ ] **Step 3: Добавить teacher_id в fill_service**

В `apps/dashboard/fill_service.py` в словарь, собираемый для плановых занятий, добавить ключ рядом с `teacher_name`:

```python
            'teacher_id': effective,
```

и аналогично в ветке доп.уроков — id эффективного преподавателя доп.урока. Добавление поля обратно совместимо: существующий фронт вкладки «Заполнить» читает по именам ключей и лишнее поле игнорирует.

- [ ] **Step 4: Добавить функцию репозитория доп.уроков**

В `apps/extra_lessons/repository.py` добавить:

```python
def scheduled_on(target_date) -> list[dict]:
    """
    Назначенные доп.уроки на конкретную дату — по всей школе, одним запросом.

    Источник утреннего дайджеста. Фильтр по статусу: только назначенные и ещё не
    проведённые (makeup_scheduled); проведённые в списке дня уже не нужны.
    """
    return list(
        AbsenceResolution.objects
        .filter(status=MAKEUP_SCHEDULED, scheduled_date=target_date)
        .values(
            'id', 'assigned_teacher_id', 'scheduled_date', 'scheduled_time',
            'student_id', 'kind',
            student_name=F('student__full_name'),
            group_pk=Coalesce('group_id', 'missed_lesson__group_id'),
        )
    )
```

Импорты `F` и `Coalesce` добавить в шапку файла, если их там ещё нет:

```python
from django.db.models import F
from django.db.models.functions import Coalesce
```

Имена группы и направления к строкам подтягивает вызывающий (`digests.py`) батч-справочником — так же, как это делает `scheduling/services.py`: одним запросом на все группы, без N+1.

- [ ] **Step 5: Запустить тесты**

Run: `pytest apps/notifications/tests/test_digest_sources.py apps/dashboard -v`
Expected: все passed (тесты dashboard не должны сломаться от нового поля).

- [ ] **Step 6: Commit**

```bash
git add apps/dashboard/fill_service.py apps/extra_lessons/repository.py apps/notifications/tests
git commit -m "feat(notifications): источники данных для дайджестов"
```

---

## Task 8: Утренний дайджест

**Files:**
- Create: `apps/notifications/digests.py`
- Test: `apps/notifications/tests/test_morning_digest.py`

- [ ] **Step 1: Написать падающие тесты**

`apps/notifications/tests/test_morning_digest.py`:

```python
"""Утренний дайджест: состав, адресаты, отсутствие пустых сообщений."""
from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.notifications import digests
from apps.notifications.constants import CHANNEL_DM, CHANNEL_GROUP, KIND_MORNING_DIGEST
from apps.notifications.models import NotificationMessage, TelegramRecipient, TelegramUser
from apps.teachers.models import Teacher

TODAY = datetime.date(2026, 8, 3)


@pytest.fixture
def linked(db):
    teacher = Teacher.objects.create(name='Анна Петрова', created_at='2026-08-01T00:00:00Z')
    tg = TelegramUser.objects.create(chat_id=555, username='anna', full_name='Анна')
    TelegramRecipient.objects.create(teacher=teacher, telegram_user=tg)
    return teacher


@pytest.mark.django_db
def test_teacher_without_lessons_gets_no_message(linked):
    """Будить человека в 8 утра ради «сегодня уроков нет» смысла нет."""
    with patch('apps.notifications.digests._collect_day', return_value={}):
        digests.send_morning_digest(day=TODAY)
    assert NotificationMessage.objects.count() == 0


@pytest.mark.django_db
@override_settings(TELEGRAM_GENERAL_CHAT_ID=-100500)
def test_morning_digest_goes_only_to_dm(linked):
    """Персональный список в общий чат не дублируется: 100 сообщений каждое утро
    сделали бы чат нечитаемым (спека, п. 2.5)."""
    day_map = {linked.id: [
        {'time': '12:00', 'group': 'СИ1027', 'direction': 'Scratch',
         'seq': 1, 'is_substitute': False, 'is_extra': False},
    ]}
    with patch('apps.notifications.digests._collect_day', return_value=day_map):
        digests.send_morning_digest(day=TODAY)

    rows = list(NotificationMessage.objects.all())
    assert len(rows) == 1
    assert rows[0].channel == CHANNEL_DM
    assert rows[0].kind == KIND_MORNING_DIGEST
    assert not NotificationMessage.objects.filter(channel=CHANNEL_GROUP).exists()


@pytest.mark.django_db
def test_morning_digest_is_idempotent_within_a_day(linked):
    day_map = {linked.id: [
        {'time': '12:00', 'group': 'СИ1027', 'direction': 'Scratch',
         'seq': 1, 'is_substitute': False, 'is_extra': False},
    ]}
    with patch('apps.notifications.digests._collect_day', return_value=day_map):
        digests.send_morning_digest(day=TODAY)
        digests.send_morning_digest(day=TODAY)
    assert NotificationMessage.objects.filter(kind=KIND_MORNING_DIGEST).count() == 1


@pytest.mark.django_db
def test_unlinked_teacher_is_skipped(db):
    teacher = Teacher.objects.create(name='Без телеги', created_at='2026-08-01T00:00:00Z')
    day_map = {teacher.id: [
        {'time': '12:00', 'group': 'СИ1027', 'direction': 'Scratch',
         'seq': 1, 'is_substitute': False, 'is_extra': False},
    ]}
    with patch('apps.notifications.digests._collect_day', return_value=day_map):
        digests.send_morning_digest(day=TODAY)
    assert NotificationMessage.objects.count() == 0
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest apps/notifications/tests/test_morning_digest.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.notifications.digests`

- [ ] **Step 3: Реализовать сборку и рассылку**

`apps/notifications/digests.py`:

```python
"""
Сборка и рассылка дайджестов.

Оба дайджеста — только в личку (спека, п. 2.5). Данные собираются ОДНИМ запросом
на всю школу и группируются в памяти: сто преподавателей — это два запроса,
а не двести. VPS 2 CPU / 2 ГБ, запрос на преподавателя здесь недопустим.
"""
from __future__ import annotations

import datetime
import logging

from django.db.models import F

from apps.core.utils.dates import msk_now
from apps.dashboard import fill_service
from apps.extra_lessons import repository as extra_repo
from apps.groups.models import Group
from apps.notifications import messages, services
from apps.notifications.constants import CHANNEL_DM, KIND_FILL_DIGEST, KIND_MORNING_DIGEST
from apps.notifications.models import TelegramRecipient
from apps.scheduling import repository as scheduling_repo
from apps.scheduling.occurrences import CANCELLED, MOVED

logger = logging.getLogger(__name__)


def _active_recipients() -> dict[int, tuple[int, str]]:
    """teacher_id → (chat_id, ФИО). Только активные привязки."""
    rows = (TelegramRecipient.objects
            .filter(is_active=True)
            .values_list('teacher_id', 'telegram_user__chat_id', 'teacher__name'))
    return {teacher_id: (chat_id, name) for teacher_id, chat_id, name in rows}


def _collect_day(day: datetime.date) -> dict[int, list[dict]]:
    """
    Занятия дня по всей школе, сгруппированные по эффективному преподавателю.

    Плановые занятия: planned_lessons_in_window уже фильтрует активные группы и
    учитывает замену — занятие попадает в день заменяющего, а не основного.
    Отменённые и перенесённые строки исключаются.
    """
    result: dict[int, list[dict]] = {}

    for row in scheduling_repo.planned_lessons_in_window(day, day, teacher_id=None):
        if row['status'] in (CANCELLED, MOVED):
            continue
        substitute_id = row['substitute_teacher_id']
        effective = substitute_id or row['teacher_id']
        if effective is None:
            continue
        result.setdefault(effective, []).append({
            'time': row['scheduled_time'].strftime('%H:%M') if row['scheduled_time'] else '—',
            'group': row['group_name'],
            'direction': row['direction_name'],
            'seq': row['seq'],
            'is_substitute': substitute_id is not None,
            'is_extra': False,
        })

    extra_rows = extra_repo.scheduled_on(day)
    if extra_rows:
        group_ids = {r['group_pk'] for r in extra_rows if r['group_pk']}
        groups = {
            g['id']: g for g in Group.objects
            .filter(id__in=group_ids)
            .values('id', 'name', direction_name=F('direction__name'))
        }
        for row in extra_rows:
            teacher_id = row['assigned_teacher_id']
            if teacher_id is None:
                continue
            group = groups.get(row['group_pk']) or {}
            result.setdefault(teacher_id, []).append({
                'time': row['scheduled_time'].strftime('%H:%M') if row['scheduled_time'] else '—',
                'group': group.get('name', '—'),
                'direction': group.get('direction_name', '—'),
                'seq': None,
                'is_substitute': False,
                'is_extra': True,
            })

    for items in result.values():
        items.sort(key=lambda i: i['time'])
    return result


def send_morning_digest(day: datetime.date | None = None) -> int:
    """Разослать утренний список занятий. Возвращает число поставленных сообщений."""
    day = day or msk_now().date()
    recipients = _active_recipients()
    if not recipients:
        return 0

    queued = 0
    for teacher_id, items in _collect_day(day).items():
        if not items:
            continue
        target = recipients.get(teacher_id)
        if target is None:
            continue
        chat_id, teacher_name = target
        text = messages.morning_digest(teacher_name=teacher_name, day=day, items=items)
        created = services.enqueue(
            kind=KIND_MORNING_DIGEST, channel=CHANNEL_DM, chat_id=chat_id, text=text,
            dedup_key=f'morning:{teacher_id}:{day.isoformat()}',
            recipient_teacher_id=teacher_id,
        )
        queued += int(created)
    return queued


def send_fill_digest(day: datetime.date | None = None) -> int:
    """
    Разослать список незаполненных отчётов.

    Логика «что считается незаполненным» НЕ переписывается: берём тот же расчёт,
    что питает вкладку «Заполнить» дашборда, иначе через полгода два места разъедутся.
    """
    day = day or msk_now().date()
    recipients = _active_recipients()
    if not recipients:
        return 0

    by_teacher: dict[int, list[dict]] = {}
    for row in fill_service.unfilled_lessons(sort_dir='asc'):
        teacher_id = row.get('teacher_id')
        if teacher_id is None:
            continue
        by_teacher.setdefault(teacher_id, []).append({
            'date': datetime.date.fromisoformat(row['date']),
            'time': row['time'] or '—',
            'group': row['group_name'],
            'direction': row['direction_name'],
            'seq': int(row['lesson_number']) if row.get('lesson_number') else None,
        })

    queued = 0
    for teacher_id, items in by_teacher.items():
        target = recipients.get(teacher_id)
        if target is None:
            continue
        chat_id, _name = target
        text = messages.fill_digest(items=items)
        created = services.enqueue(
            kind=KIND_FILL_DIGEST, channel=CHANNEL_DM, chat_id=chat_id, text=text,
            dedup_key=f'fill:{teacher_id}:{day.isoformat()}',
            recipient_teacher_id=teacher_id,
        )
        queued += int(created)
    return queued
```

- [ ] **Step 4: Запустить тесты**

Run: `pytest apps/notifications/tests/test_morning_digest.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/notifications
git commit -m "feat(notifications): утренний дайджест расписания"
```

---

## Task 9: Вечерний дайджест и Celery-задачи

**Files:**
- Create: `apps/notifications/tasks.py`
- Test: `apps/notifications/tests/test_fill_digest.py`
- Modify: `config/settings/base.py:230` (CELERY_BEAT_SCHEDULE)

- [ ] **Step 1: Написать падающие тесты**

`apps/notifications/tests/test_fill_digest.py`:

```python
"""Вечерний дайджест: только личка, обязательная приписка, идемпотентность."""
from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.notifications import digests
from apps.notifications.constants import CHANNEL_DM, KIND_FILL_DIGEST
from apps.notifications.models import NotificationMessage, TelegramRecipient, TelegramUser
from apps.teachers.models import Teacher

TODAY = datetime.date(2026, 8, 3)


@pytest.fixture
def linked(db):
    teacher = Teacher.objects.create(name='Анна Петрова', created_at='2026-08-01T00:00:00Z')
    tg = TelegramUser.objects.create(chat_id=555, username='anna', full_name='Анна')
    TelegramRecipient.objects.create(teacher=teacher, telegram_user=tg)
    return teacher


def _unfilled(teacher_id: int) -> list[dict]:
    return [{
        'kind': 'planned', 'id': 1, 'group_id': 7, 'group_name': 'ПИ1054',
        'teacher_id': teacher_id, 'teacher_name': 'Анна Петрова',
        'direction_name': 'Python', 'direction_color': '#000',
        'lesson_number': 11.0, 'date': '2026-08-02', 'time': '16:00',
    }]


@pytest.mark.django_db
@override_settings(TELEGRAM_GENERAL_CHAT_ID=-100500)
def test_fill_digest_is_dm_only_and_has_footer(linked):
    with patch('apps.notifications.digests.fill_service.unfilled_lessons',
               return_value=_unfilled(linked.id)):
        digests.send_fill_digest(day=TODAY)

    rows = list(NotificationMessage.objects.all())
    assert len(rows) == 1
    assert rows[0].channel == CHANNEL_DM
    assert rows[0].kind == KIND_FILL_DIGEST
    assert 'Если уроков не было, сообщите менеджеру или администратору.' in rows[0].text


@pytest.mark.django_db
def test_fill_digest_is_idempotent_within_a_day(linked):
    with patch('apps.notifications.digests.fill_service.unfilled_lessons',
               return_value=_unfilled(linked.id)):
        digests.send_fill_digest(day=TODAY)
        digests.send_fill_digest(day=TODAY)
    assert NotificationMessage.objects.filter(kind=KIND_FILL_DIGEST).count() == 1


@pytest.mark.django_db
def test_fill_digest_repeats_next_day(linked):
    with patch('apps.notifications.digests.fill_service.unfilled_lessons',
               return_value=_unfilled(linked.id)):
        digests.send_fill_digest(day=TODAY)
        digests.send_fill_digest(day=TODAY + datetime.timedelta(days=1))
    assert NotificationMessage.objects.filter(kind=KIND_FILL_DIGEST).count() == 2
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest apps/notifications/tests/test_fill_digest.py -v`
Expected: FAIL — приписки нет / сообщений ноль (в зависимости от состояния Task 8).

- [ ] **Step 3: Создать Celery-задачи**

`apps/notifications/tasks.py`:

```python
"""
Celery-задачи уведомлений.

Логика — в dispatcher.py и digests.py (тестируются без Celery); задачи только
делегируют. Модуль подхватывается автодискавером Celery, когда воркер запущен.
"""
from __future__ import annotations

from celery import shared_task

from apps.notifications import dispatcher, digests


@shared_task(name='apps.notifications.tasks.dispatch_outbox')
def dispatch_outbox() -> int:
    """Разгрести очередь. Возвращает число отправленных сообщений."""
    return dispatcher.dispatch()


@shared_task(name='apps.notifications.tasks.send_morning_digest')
def send_morning_digest() -> int:
    """Утренний список занятий (8:00 МСК)."""
    return digests.send_morning_digest()


@shared_task(name='apps.notifications.tasks.send_fill_digest')
def send_fill_digest() -> int:
    """Вечерний список незаполненных отчётов (21:00 МСК)."""
    return digests.send_fill_digest()
```

- [ ] **Step 4: Добавить расписание**

В `config/settings/base.py` в `CELERY_BEAT_SCHEDULE` добавить (импорт `from celery.schedules import crontab` — в шапку файла, под try/except, поскольку локально пакет `celery` может отсутствовать; при отсутствии расписание просто не задаётся):

```python
    'notifications-dispatch-outbox': {
        'task': 'apps.notifications.tasks.dispatch_outbox',
        'schedule': 60.0,  # страховка: точечные уведомления уходят раньше, по on_commit
    },
    'notifications-morning-digest': {
        'task': 'apps.notifications.tasks.send_morning_digest',
        'schedule': crontab(hour=8, minute=0),   # CELERY_TIMEZONE='Europe/Moscow'
    },
    'notifications-fill-digest': {
        'task': 'apps.notifications.tasks.send_fill_digest',
        'schedule': crontab(hour=21, minute=0),
    },
```

- [ ] **Step 5: Запустить тесты**

Run: `pytest apps/notifications -v`
Expected: все passed.

- [ ] **Step 6: Commit**

```bash
git add apps/notifications config/settings/base.py
git commit -m "feat(notifications): вечерний дайджест и расписание Celery-beat"
```

---

## Task 10: Точечные уведомления из доп.уроков

**Files:**
- Modify: `apps/extra_lessons/services.py:58` (`create_assignment`), `:136` (`create_extra_assignment`), `:252` (`cancel_assignment`)
- Test: `apps/notifications/tests/test_extra_lesson_events.py`

- [ ] **Step 1: Написать падающий тест**

`apps/notifications/tests/test_extra_lesson_events.py`:

```python
"""Назначение и отмена доп.урока ставят сообщения в очередь."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.notifications.constants import KIND_MAKEUP_ASSIGNED, KIND_MAKEUP_CANCELLED


@pytest.mark.django_db
def test_assign_makeup_enqueues_notification(makeup_fixture):
    """makeup_fixture — фабрика из apps/extra_lessons/tests/conftest.py.

    Если фикстуры с таким именем нет, использовать ту, что уже применяется в
    apps/extra_lessons/tests для создания пропуска и резолюции.
    """
    from apps.extra_lessons import services as extra_services
    from apps.notifications.models import NotificationMessage

    with patch('apps.notifications.services._request_dispatch'):
        extra_services.create_assignment(makeup_fixture.assign_payload(), makeup_fixture.request)

    kinds = set(NotificationMessage.objects.values_list('kind', flat=True))
    assert KIND_MAKEUP_ASSIGNED in kinds


@pytest.mark.django_db
def test_cancel_makeup_enqueues_notification(makeup_fixture):
    from apps.extra_lessons import services as extra_services
    from apps.notifications.models import NotificationMessage

    resolution_id = makeup_fixture.assigned_resolution_id()
    with patch('apps.notifications.services._request_dispatch'):
        extra_services.cancel_assignment(resolution_id, makeup_fixture.request)

    kinds = set(NotificationMessage.objects.values_list('kind', flat=True))
    assert KIND_MAKEUP_CANCELLED in kinds
```

Перед написанием теста открыть `apps/extra_lessons/tests/conftest.py` и переиспользовать существующие фикстуры создания пропуска и назначения — не изобретать свои фабрики.

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest apps/notifications/tests/test_extra_lesson_events.py -v`
Expected: FAIL — очередь пуста.

- [ ] **Step 3: Добавить вызовы в сервис доп.уроков**

В `apps/extra_lessons/services.py` создать приватный помощник и вызывать его внутри уже существующих блоков `with transaction.atomic():` — рядом с записью `log_event`, **до** выхода из транзакции:

```python
def _notify_makeup(resolution_id: int, kind: str) -> None:
    """
    Поставить уведомление о доп.уроке. Вызывается ВНУТРИ транзакции операции:
    либо назначение и сообщение, либо ничего (transactional outbox).

    Импорт локальный: apps.extra_lessons не должен зависеть от notifications на
    уровне модуля — доменное приложение про Telegram не знает.
    """
    from apps.notifications import messages as notif_messages
    from apps.notifications import services as notif_services
    from apps.notifications.constants import (
        KIND_MAKEUP_ASSIGNED, KIND_MAKEUP_CANCELLED, KIND_MAKEUP_CHANGED,
    )

    row = repository.get_resolution_full(resolution_id)
    if row is None or row.get('assigned_teacher_id') is None:
        return
    if row.get('scheduled_date') is None or row.get('scheduled_time') is None:
        return

    builder = {
        KIND_MAKEUP_ASSIGNED: notif_messages.makeup_assigned,
        KIND_MAKEUP_CHANGED: notif_messages.makeup_changed,
        KIND_MAKEUP_CANCELLED: notif_messages.makeup_cancelled,
    }[kind]

    common = {
        'teacher_name': row['assigned_teacher_name'],
        'group': row['group_name'],
        'direction': row['direction_name'],
        'day': row['scheduled_date'],
        'time': row['scheduled_time'].strftime('%H:%M'),
        'student_name': row['student_name'],
    }
    if kind == KIND_MAKEUP_ASSIGNED:
        common['is_beyond_course'] = row['kind'] == 'extra'

    notif_services.notify_teacher(
        kind=kind,
        teacher_id=row['assigned_teacher_id'],
        text=builder(**common),
        # Дата в ключе: перенос доп.урока даёт новый ключ, значит новое сообщение,
        # а повторный вызов той же операции — нет.
        dedup_prefix=f'{kind}:{resolution_id}:{row["scheduled_date"].isoformat()}',
        source_kind='absence_resolution',
        source_id=resolution_id,
        also_to_group_chat=True,
    )
```

Затем добавить вызовы:
- в `create_assignment` и `_assign_makeup_for_lesson` — `_notify_makeup(resolution_id, KIND_MAKEUP_ASSIGNED)`;
- в `create_extra_assignment` / `_assign_extra_beyond_course` — то же;
- в `cancel_assignment` — `_notify_makeup(resolution_id, KIND_MAKEUP_CANCELLED)` **до** изменения статуса, пока данные ещё доступны;
- если в файле есть путь изменения даты/времени назначенного доп.урока — `KIND_MAKEUP_CHANGED`.

Если `repository.get_resolution_full` не возвращает `assigned_teacher_name`, `group_name`, `direction_name`, `student_name` — дополнить `_full_values` в `apps/extra_lessons/repository.py` этими полями через `F(...)`-алиасы.

- [ ] **Step 4: Запустить тесты**

Run: `pytest apps/notifications apps/extra_lessons -v`
Expected: все passed.

- [ ] **Step 5: Commit**

```bash
git add apps/extra_lessons apps/notifications
git commit -m "feat(notifications): уведомления о назначении и отмене доп.уроков"
```

---

## Task 11: Точечные уведомления из расписания

**Files:**
- Modify: `apps/scheduling/services.py:290` (`reschedule`), `:305` (`change_teacher`), `:368` (`cancel`)
- Test: `apps/notifications/tests/test_scheduling_events.py`

- [ ] **Step 1: Написать падающий тест**

`apps/notifications/tests/test_scheduling_events.py`:

```python
"""Перенос, отмена и замена ставят сообщения в очередь."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.notifications.constants import (
    KIND_LESSON_CANCELLED, KIND_LESSON_MOVED, KIND_SUBSTITUTE_ASSIGNED,
)
from apps.notifications.models import NotificationMessage


@pytest.mark.django_db
def test_reschedule_enqueues_moved_notification(scheduling_fixture):
    """scheduling_fixture — существующая фикстура из apps/scheduling/tests/conftest.py."""
    from apps.scheduling import services as sched_services

    with patch('apps.notifications.services._request_dispatch'):
        sched_services.reschedule(
            scheduling_fixture.group_id, scheduling_fixture.lesson_id,
            {'scheduled_date': '2026-08-12', 'scheduled_time': '12:00'},
            scheduling_fixture.request,
        )
    assert NotificationMessage.objects.filter(kind=KIND_LESSON_MOVED).exists()


@pytest.mark.django_db
def test_cancel_enqueues_cancelled_notification(scheduling_fixture):
    from apps.scheduling import services as sched_services

    with patch('apps.notifications.services._request_dispatch'):
        sched_services.cancel(
            scheduling_fixture.group_id, scheduling_fixture.lesson_id,
            scheduling_fixture.request,
        )
    assert NotificationMessage.objects.filter(kind=KIND_LESSON_CANCELLED).exists()


@pytest.mark.django_db
def test_substitute_notifies_both_teachers(scheduling_fixture):
    """И тот, кто выходит, и тот, кого сняли, должны узнать."""
    from apps.scheduling import services as sched_services

    with patch('apps.notifications.services._request_dispatch'):
        sched_services.change_teacher(
            scheduling_fixture.group_id, scheduling_fixture.lesson_id,
            {'teacher_id': scheduling_fixture.other_teacher_id},
            scheduling_fixture.request,
        )
    rows = NotificationMessage.objects.filter(kind=KIND_SUBSTITUTE_ASSIGNED)
    teacher_ids = {r.recipient_teacher_id for r in rows if r.recipient_teacher_id}
    assert len(teacher_ids) == 2
```

Перед написанием открыть `apps/scheduling/tests/conftest.py` и переиспользовать существующие фикстуры плана группы. Если фикстуры с нужной формой нет — добавить её туда, а не создавать дубль в notifications.

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest apps/notifications/tests/test_scheduling_events.py -v`
Expected: FAIL — очередь пуста.

- [ ] **Step 3: Добавить вызовы в сервис расписания**

В `apps/scheduling/services.py` добавить помощник и вызывать его внутри существующих транзакций операций:

```python
def _notify_planned(row: dict, kind: str, *, teacher_ids: list[int],
                    substitute_name: str = '', from_day=None) -> None:
    """
    Поставить уведомление об изменении расписания.

    row — словарь плановой строки (как его отдаёт repository._plan_row_dict).
    teacher_ids — кому сообщить: при замене их двое (кто выходит и кого сняли).
    Импорт локальный: scheduling про Telegram не знает.
    """
    from apps.notifications import messages as notif_messages
    from apps.notifications import services as notif_services
    from apps.notifications.constants import (
        KIND_LESSON_CANCELLED, KIND_LESSON_MOVED,
        KIND_SUBSTITUTE_ASSIGNED, KIND_SUBSTITUTE_REMOVED,
    )

    day = row['scheduled_date']
    time_str = row['scheduled_time'].strftime('%H:%M') if row['scheduled_time'] else '—'
    base = {'group': row['group_name'], 'direction': row['direction_name']}

    for index, teacher_id in enumerate(dict.fromkeys(tid for tid in teacher_ids if tid)):
        if kind == KIND_LESSON_MOVED:
            text = notif_messages.lesson_moved(
                **base, seq=row.get('seq'), from_day=from_day, to_day=day, time=time_str)
        elif kind == KIND_LESSON_CANCELLED:
            text = notif_messages.lesson_cancelled(
                **base, seq=row.get('seq'), day=day, time=time_str)
        elif kind == KIND_SUBSTITUTE_ASSIGNED:
            text = notif_messages.substitute_assigned(
                **base, day=day, time=time_str, substitute_name=substitute_name,
                for_substitute=(index == 0))
        else:
            text = notif_messages.substitute_removed(
                **base, day=day, time=time_str, for_substitute=(index == 0))

        notif_services.notify_teacher(
            kind=kind, teacher_id=teacher_id, text=text,
            dedup_prefix=f'{kind}:{row["id"]}:{day.isoformat()}:{teacher_id}',
            source_kind='planned_lesson', source_id=row['id'],
            also_to_group_chat=(index == 0),
        )
```

`also_to_group_chat=(index == 0)` — дубль в общий чат ставится один раз на событие, а не по разу на каждого адресата: иначе при замене чат получит два одинаковых сообщения.

Вызовы:
- `reschedule` — `_notify_planned(row, KIND_LESSON_MOVED, teacher_ids=[effective_teacher_id], from_day=<старая дата>)`; старую дату взять до мутации строки;
- `cancel` — `_notify_planned(row, KIND_LESSON_CANCELLED, teacher_ids=[effective_teacher_id])`;
- `change_teacher` — при назначении замены `KIND_SUBSTITUTE_ASSIGNED` с `teacher_ids=[новый, прежний]`, при снятии — `KIND_SUBSTITUTE_REMOVED`.

- [ ] **Step 4: Запустить тесты**

Run: `pytest apps/notifications apps/scheduling -v`
Expected: все passed.

- [ ] **Step 5: Commit**

```bash
git add apps/scheduling apps/notifications
git commit -m "feat(notifications): уведомления о переносах, отменах и заменах"
```

---

## Task 12: Служебный API для бота

**Files:**
- Create: `apps/notifications/authentication.py`, `apps/notifications/integration_views.py`, `apps/notifications/integration_urls.py`
- Test: `apps/notifications/tests/test_integration_api.py`
- Modify: `config/urls.py`, `config/settings/base.py` (throttle rates)

- [ ] **Step 1: Написать падающие тесты**

`apps/notifications/tests/test_integration_api.py`:

```python
"""Служебные эндпоинты бота: доступ только по общему секрету."""
from __future__ import annotations

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.notifications.models import TelegramRecipient, TelegramUser
from apps.teachers.models import Teacher

IDENTIFY = '/api/integrations/telegram/identify'
MY = '/api/integrations/telegram/my'


@pytest.mark.django_db
@override_settings(BOT_SERVICE_TOKEN='s3cret')
def test_identify_requires_token():
    response = APIClient().post(IDENTIFY, {'telegram_id': 1, 'full_name': 'Иван'},
                                format='json')
    assert response.status_code in (401, 403)


@pytest.mark.django_db
@override_settings(BOT_SERVICE_TOKEN='s3cret')
def test_identify_rejects_wrong_token():
    client = APIClient()
    response = client.post(IDENTIFY, {'telegram_id': 1, 'full_name': 'Иван'},
                           format='json', HTTP_X_BOT_TOKEN='wrong')
    assert response.status_code in (401, 403)


@pytest.mark.django_db
@override_settings(BOT_SERVICE_TOKEN='s3cret')
def test_identify_upserts_telegram_user():
    client = APIClient()
    payload = {'telegram_id': 777, 'username': 'anna', 'full_name': 'Анна Петрова'}
    first = client.post(IDENTIFY, payload, format='json', HTTP_X_BOT_TOKEN='s3cret')
    assert first.status_code == 204

    payload['username'] = 'anna_new'
    second = client.post(IDENTIFY, payload, format='json', HTTP_X_BOT_TOKEN='s3cret')
    assert second.status_code == 204

    assert TelegramUser.objects.filter(chat_id=777).count() == 1
    assert TelegramUser.objects.get(chat_id=777).username == 'anna_new'


@pytest.mark.django_db
@override_settings(BOT_SERVICE_TOKEN='s3cret')
def test_my_returns_404_for_unlinked_account():
    TelegramUser.objects.create(chat_id=888, username='bob', full_name='Боб')
    response = APIClient().get(f'{MY}?telegram_id=888', HTTP_X_BOT_TOKEN='s3cret')
    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(BOT_SERVICE_TOKEN='s3cret')
def test_my_returns_events_for_linked_teacher():
    teacher = Teacher.objects.create(name='Анна', created_at='2026-08-01T00:00:00Z')
    tg = TelegramUser.objects.create(chat_id=999, username='anna', full_name='Анна')
    TelegramRecipient.objects.create(teacher=teacher, telegram_user=tg)

    response = APIClient().get(f'{MY}?telegram_id=999', HTTP_X_BOT_TOKEN='s3cret')
    assert response.status_code == 200
    assert 'events' in response.data
    assert isinstance(response.data['events'], list)


@pytest.mark.django_db
@override_settings(BOT_SERVICE_TOKEN='')
def test_empty_configured_token_denies_everyone():
    """Пустой секрет в настройках не должен означать «пускать всех»."""
    response = APIClient().post(IDENTIFY, {'telegram_id': 1, 'full_name': 'И'},
                                format='json', HTTP_X_BOT_TOKEN='')
    assert response.status_code in (401, 403)
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest apps/notifications/tests/test_integration_api.py -v`
Expected: FAIL — 404 на все адреса.

- [ ] **Step 3: Реализовать аутентификацию**

`apps/notifications/authentication.py`:

```python
"""
Аутентификация служебных эндпоинтов бота.

Общий секрет в заголовке X-Bot-Token, сравнение за постоянное время. Это НЕ
пользовательская аутентификация: request.user остаётся анонимным, доступ решает
permission-класс.

Аутентификация не сессионная ⇒ CSRF к этим вьюхам не применяется; @csrf_exempt
не нужен и не ставится.
"""
from __future__ import annotations

from django.conf import settings
from django.utils.crypto import constant_time_compare
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission

HEADER = 'HTTP_X_BOT_TOKEN'


def _token_matches(request) -> bool:
    expected = getattr(settings, 'BOT_SERVICE_TOKEN', '')
    if not expected:
        # Пустой секрет в настройках не означает «пускать всех».
        return False
    provided = request.META.get(HEADER, '')
    return bool(provided) and constant_time_compare(provided, expected)


class BotServiceAuthentication(BaseAuthentication):
    """Ничего не аутентифицирует — нужна только чтобы DRF не вернул 403 из-за CSRF."""

    def authenticate(self, request):
        return None


class IsBotService(BasePermission):
    """Пускает только запросы с корректным X-Bot-Token."""
    message = 'Bot service token required.'

    def has_permission(self, request, view) -> bool:
        return _token_matches(request)
```

- [ ] **Step 4: Реализовать вьюхи**

`apps/notifications/integration_views.py`:

```python
"""
Служебные эндпоинты для Telegram-бота.

Закрыты общим секретом И правилом nginx (allow 127.0.0.1; deny all) — бот и
журнал на одной машине, наружу этому торчать незачем.
"""
from __future__ import annotations

import datetime

from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.utils.dates import msk_now
from apps.notifications.authentication import BotServiceAuthentication, IsBotService
from apps.notifications.models import TelegramRecipient, TelegramUser
from apps.scheduling import repository as scheduling_repo


class TelegramIdentifyView(APIView):
    """POST /api/integrations/telegram/identify — «этому chat_id соответствует такой ник»."""

    authentication_classes = [BotServiceAuthentication]
    permission_classes = [IsBotService]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'bot_service'

    def post(self, request: Request) -> Response:
        telegram_id = request.data.get('telegram_id')
        full_name = (request.data.get('full_name') or '').strip()
        if not telegram_id or not full_name:
            raise ValidationError('telegram_id и full_name обязательны.')

        username = (request.data.get('username') or '').lstrip('@') or None
        TelegramUser.objects.update_or_create(
            chat_id=int(telegram_id),
            defaults={'username': username, 'full_name': full_name},
        )
        return Response(status=204)


class TelegramMyView(APIView):
    """GET /api/integrations/telegram/my?telegram_id= — ближайшие события преподавателя."""

    authentication_classes = [BotServiceAuthentication]
    permission_classes = [IsBotService]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'bot_service'

    WINDOW_DAYS = 7

    def get(self, request: Request) -> Response:
        telegram_id = request.query_params.get('telegram_id')
        if not telegram_id:
            raise ValidationError('telegram_id обязателен.')

        recipient = (TelegramRecipient.objects
                     .filter(telegram_user__chat_id=int(telegram_id))
                     .select_related('teacher')
                     .first())
        if recipient is None:
            raise NotFound('Аккаунт не привязан к преподавателю.')

        today = msk_now().date()
        window_to = today + datetime.timedelta(days=self.WINDOW_DAYS)
        rows = scheduling_repo.planned_lessons_in_window(
            today, window_to, teacher_id=recipient.teacher_id)

        events = [{
            'date': row['scheduled_date'].isoformat(),
            'time': row['scheduled_time'].strftime('%H:%M') if row['scheduled_time'] else None,
            'group': row['group_name'],
            'direction': row['direction_name'],
            'seq': row['seq'],
            'is_substitute': row['substitute_teacher_id'] is not None,
        } for row in rows]
        events.sort(key=lambda e: (e['date'], e['time'] or ''))

        return Response({'teacher_name': recipient.teacher.name, 'events': events})
```

`apps/notifications/integration_urls.py`:

```python
"""Маршруты служебного API бота. Монтируются как /api/integrations/telegram."""
from django.urls import path

from apps.notifications.integration_views import TelegramIdentifyView, TelegramMyView

urlpatterns = [
    path('/identify', TelegramIdentifyView.as_view(), name='telegram-identify'),
    path('/my', TelegramMyView.as_view(), name='telegram-my'),
]
```

- [ ] **Step 5: Смонтировать роутер и настроить throttle**

В `config/urls.py` добавить перед строкой `path('api', include('apps.teacher_spa.urls')),`:

```python
    # Служебный API Telegram-бота (закрыт секретом + nginx allow 127.0.0.1)
    path('api/integrations/telegram', include('apps.notifications.integration_urls')),
```

В `config/settings/base.py` в `REST_FRAMEWORK` в секцию `DEFAULT_THROTTLE_RATES` (создать, если её нет) добавить:

```python
        'bot_service': '120/min',
```

и убедиться, что в `DEFAULT_THROTTLE_CLASSES` присутствует `'rest_framework.throttling.ScopedRateThrottle'` либо что он подключается точечно во вьюхах (как сделано выше через `throttle_classes`).

- [ ] **Step 6: Закрыть путь в nginx**

В `deploy/nginx/journal-kotokod.conf` добавить блок перед общим `location /api/`:

```nginx
    # Служебный API Telegram-бота: только с самой машины.
    location /api/integrations/ {
        allow 127.0.0.1;
        deny all;
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/proxy_params;
    }
```

Точные директивы `proxy_*` скопировать из соседнего блока `location /api/` в том же файле.

- [ ] **Step 7: Запустить тесты**

Run: `pytest apps/notifications/tests/test_integration_api.py -v`
Expected: 6 passed.

- [ ] **Step 8: Commit**

```bash
git add apps/notifications config/urls.py config/settings/base.py deploy/nginx
git commit -m "feat(notifications): служебный API для Telegram-бота"
```

---

## Task 13: API привязки Telegram в карточке преподавателя

**Files:**
- Modify: `apps/teachers/urls.py`, `apps/teachers/views.py`, `apps/teachers/serializers.py`
- Test: `apps/notifications/tests/test_binding_api.py`

- [ ] **Step 1: Написать падающие тесты**

`apps/notifications/tests/test_binding_api.py`:

```python
"""Привязка Telegram: менеджер видит, меняет только админ."""
from __future__ import annotations

import pytest

from apps.notifications.models import TelegramRecipient, TelegramUser
from apps.teachers.models import Teacher


@pytest.fixture
def teacher(db):
    return Teacher.objects.create(name='Анна Петрова', created_at='2026-08-01T00:00:00Z')


@pytest.fixture
def tg_user(db):
    return TelegramUser.objects.create(chat_id=777, username='anna', full_name='Анна')


@pytest.mark.django_db
def test_manager_can_list_known_telegram_accounts(manager_client, tg_user):
    response = manager_client.get('/api/admin/telegram-users')
    assert response.status_code == 200
    assert any(row['chat_id'] == 777 for row in response.data['rows'])


@pytest.mark.django_db
def test_manager_cannot_bind(manager_client, teacher, tg_user):
    response = manager_client.post(
        f'/api/admin/teachers/{teacher.id}/telegram',
        {'chat_id': 777}, format='json')
    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_binds_and_unbinds(admin_client, teacher, tg_user):
    bound = admin_client.post(
        f'/api/admin/teachers/{teacher.id}/telegram', {'chat_id': 777}, format='json')
    assert bound.status_code in (200, 201)
    assert TelegramRecipient.objects.filter(teacher=teacher, is_active=True).exists()

    unbound = admin_client.delete(f'/api/admin/teachers/{teacher.id}/telegram')
    assert unbound.status_code in (200, 204)
    assert not TelegramRecipient.objects.filter(teacher=teacher).exists()


@pytest.mark.django_db
def test_rebinding_reactivates_after_block(admin_client, teacher, tg_user):
    TelegramRecipient.objects.create(
        teacher=teacher, telegram_user=tg_user, is_active=False,
        blocked_reason='bot was blocked by the user')

    response = admin_client.post(
        f'/api/admin/teachers/{teacher.id}/telegram', {'chat_id': 777}, format='json')
    assert response.status_code in (200, 201)
    recipient = TelegramRecipient.objects.get(teacher=teacher)
    assert recipient.is_active is True
    assert recipient.blocked_reason is None


@pytest.mark.django_db
def test_anonymous_is_denied(anon_client, teacher):
    assert anon_client.get('/api/admin/telegram-users').status_code in (401, 403)
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest apps/notifications/tests/test_binding_api.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Реализовать вьюхи**

В `apps/notifications/views.py` добавить (файл создаётся здесь, дополняется в Task 14):

```python
"""Админские вьюхи: справочник аккаунтов, привязка, раздел «Уведомления»."""
from __future__ import annotations

from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin, ReadStaffWriteAdmin
from apps.notifications.models import TelegramRecipient, TelegramUser


class TelegramUsersView(APIView):
    """GET /api/admin/telegram-users — аккаунты, известные боту (для выбора при привязке)."""

    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        rows = list(
            TelegramUser.objects
            .order_by('full_name')
            .values('chat_id', 'username', 'full_name')
            .annotate()
        )
        bound = dict(
            TelegramRecipient.objects
            .values_list('telegram_user__chat_id', 'teacher__name')
        )
        for row in rows:
            row['bound_to'] = bound.get(row['chat_id'])
        return Response({'rows': rows, 'total': len(rows)})


class TeacherTelegramView(APIView):
    """POST/DELETE /api/admin/teachers/<id>/telegram — привязка и отвязка."""

    permission_classes = [ReadStaffWriteAdmin]

    def post(self, request: Request, teacher_id: int) -> Response:
        chat_id = request.data.get('chat_id')
        if not chat_id:
            raise ValidationError('chat_id обязателен.')
        try:
            tg_user = TelegramUser.objects.get(chat_id=int(chat_id))
        except TelegramUser.DoesNotExist:
            raise NotFound('Аккаунт неизвестен боту. Попросите написать боту /start.')

        recipient, _created = TelegramRecipient.objects.update_or_create(
            teacher_id=teacher_id,
            defaults={
                'telegram_user': tg_user,
                # Повторная привязка снимает пометку блокировки: человек мог
                # разблокировать бота, и признак должен обнулиться.
                'is_active': True,
                'blocked_reason': None,
            },
        )
        return Response({
            'chat_id': tg_user.chat_id,
            'username': tg_user.username,
            'full_name': tg_user.full_name,
            'is_active': recipient.is_active,
        })

    def delete(self, request: Request, teacher_id: int) -> Response:
        TelegramRecipient.objects.filter(teacher_id=teacher_id).delete()
        return Response(status=204)
```

- [ ] **Step 4: Смонтировать маршруты**

В `apps/teachers/urls.py` добавить маршрут привязки (внутри уже смонтированного префикса `/api/admin/teachers`):

```python
from apps.notifications.views import TeacherTelegramView

urlpatterns += [
    path('/<int:teacher_id>/telegram', TeacherTelegramView.as_view(),
         name='teacher-telegram'),
]
```

В `config/urls.py` добавить справочник аккаунтов:

```python
    path('api/admin/telegram-users', include('apps.notifications.urls')),
```

`apps/notifications/urls.py` (дополняется в Task 14):

```python
"""Маршруты справочника Telegram-аккаунтов."""
from django.urls import path

from apps.notifications.views import TelegramUsersView

urlpatterns = [
    path('', TelegramUsersView.as_view(), name='telegram-users'),
]
```

- [ ] **Step 5: Отдавать привязку в карточке преподавателя**

В сериализаторе преподавателя (`apps/teachers/serializers.py`) добавить read-only поле `telegram`:

```python
    telegram = serializers.SerializerMethodField()

    def get_telegram(self, obj):
        recipient = getattr(obj, 'telegram_recipient', None)
        if recipient is None:
            return None
        return {
            'chat_id': recipient.telegram_user.chat_id,
            'username': recipient.telegram_user.username,
            'full_name': recipient.telegram_user.full_name,
            'is_active': recipient.is_active,
            'blocked_reason': recipient.blocked_reason,
        }
```

В queryset списка и детали преподавателя добавить `.select_related('telegram_recipient__telegram_user')` — иначе N+1 на списке преподавателей.

- [ ] **Step 6: Запустить тесты**

Run: `pytest apps/notifications apps/teachers -v`
Expected: все passed.

- [ ] **Step 7: Commit**

```bash
git add apps/notifications apps/teachers config/urls.py
git commit -m "feat(notifications): API привязки Telegram к преподавателю"
```

---

## Task 14: API раздела «Уведомления»

**Files:**
- Create: `apps/notifications/serializers.py`, `apps/notifications/repository.py`
- Modify: `apps/notifications/views.py`, `apps/notifications/urls.py`, `config/urls.py`
- Test: `apps/notifications/tests/test_admin_api.py`

- [ ] **Step 1: Написать падающие тесты**

`apps/notifications/tests/test_admin_api.py`:

```python
"""Раздел «Уведомления»: доступ, фильтры, пагинация, вкладка «Расписание»."""
from __future__ import annotations

import pytest

from apps.notifications.constants import (
    CHANNEL_DM, CHANNEL_GROUP, KIND_FILL_DIGEST, KIND_MORNING_DIGEST,
    STATUS_QUEUED, STATUS_SENT,
)
from apps.notifications.models import NotificationMessage

LIST_URL = '/api/admin/notifications'
SCHEDULE_URL = '/api/admin/notifications/schedule'


@pytest.fixture
def messages_fixture(db):
    NotificationMessage.objects.create(
        kind=KIND_MORNING_DIGEST, channel=CHANNEL_DM, chat_id=1,
        text='утро', dedup_key='m1', status=STATUS_SENT)
    NotificationMessage.objects.create(
        kind=KIND_FILL_DIGEST, channel=CHANNEL_DM, chat_id=1,
        text='вечер', dedup_key='f1', status=STATUS_QUEUED)
    NotificationMessage.objects.create(
        kind=KIND_MORNING_DIGEST, channel=CHANNEL_GROUP, chat_id=-100,
        text='чат', dedup_key='g1', status=STATUS_SENT)


@pytest.mark.django_db
def test_manager_is_denied(manager_client, messages_fixture):
    """Раздел системный — как «Журнал изменений», для manager закрыт."""
    assert manager_client.get(LIST_URL).status_code == 403


@pytest.mark.django_db
def test_admin_sees_paginated_envelope(admin_client, messages_fixture):
    response = admin_client.get(LIST_URL)
    assert response.status_code == 200
    assert set(response.data.keys()) >= {'rows', 'total', 'page', 'page_size'}
    assert response.data['total'] == 3


@pytest.mark.django_db
def test_filter_by_kind(admin_client, messages_fixture):
    response = admin_client.get(f'{LIST_URL}?kind={KIND_FILL_DIGEST}')
    assert response.data['total'] == 1


@pytest.mark.django_db
def test_filter_by_channel_and_status(admin_client, messages_fixture):
    assert admin_client.get(f'{LIST_URL}?channel={CHANNEL_GROUP}').data['total'] == 1
    assert admin_client.get(f'{LIST_URL}?status={STATUS_QUEUED}').data['total'] == 1


@pytest.mark.django_db
def test_newest_first(admin_client, messages_fixture):
    rows = admin_client.get(LIST_URL).data['rows']
    dates = [r['created_at'] for r in rows]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.django_db
def test_schedule_tab_reports_jobs(admin_client, messages_fixture):
    response = admin_client.get(SCHEDULE_URL)
    assert response.status_code == 200
    jobs = {j['key'] for j in response.data['jobs']}
    assert {'morning_digest', 'fill_digest', 'dispatch'} <= jobs
    morning = next(j for j in response.data['jobs'] if j['key'] == 'morning_digest')
    assert morning['schedule'] == '08:00'
    assert 'last_run_at' in morning
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest apps/notifications/tests/test_admin_api.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Реализовать сериализатор и репозиторий**

`apps/notifications/serializers.py`:

```python
"""Сериализаторы раздела «Уведомления»."""
from __future__ import annotations

from rest_framework import serializers

from apps.notifications.models import NotificationMessage


class NotificationMessageSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source='recipient_teacher.name',
                                         read_only=True, default=None)

    class Meta:
        model = NotificationMessage
        fields = [
            'id', 'kind', 'channel', 'chat_id', 'teacher_name', 'text',
            'status', 'attempts', 'last_error', 'created_at', 'sent_at',
            'source_kind', 'source_id',
        ]
```

`apps/notifications/repository.py`:

```python
"""Запросы раздела «Уведомления»."""
from __future__ import annotations

from django.db.models import Max, QuerySet

from apps.notifications.constants import (
    CHANNEL_CHOICES, KIND_CHOICES, KIND_FILL_DIGEST, KIND_MORNING_DIGEST,
    STATUS_CHOICES,
)
from apps.notifications.models import NotificationMessage


def filtered(*, kind: str | None, channel: str | None, status: str | None) -> QuerySet:
    """Лента сообщений, новые сверху. Неизвестные значения фильтров игнорируются."""
    qs = (NotificationMessage.objects
          .select_related('recipient_teacher')
          .order_by('-created_at', '-id'))
    if kind in KIND_CHOICES:
        qs = qs.filter(kind=kind)
    if channel in CHANNEL_CHOICES:
        qs = qs.filter(channel=channel)
    if status in STATUS_CHOICES:
        qs = qs.filter(status=status)
    return qs


def last_runs() -> dict[str, str | None]:
    """
    Когда каждый дайджест отработал в последний раз.

    Считаем по данным очереди (max created_at по kind), а не опрашивая
    внутренности Celery-beat: это дёшево и не ломается при перезапуске beat.
    """
    rows = (NotificationMessage.objects
            .filter(kind__in=[KIND_MORNING_DIGEST, KIND_FILL_DIGEST])
            .values('kind')
            .annotate(last=Max('created_at')))
    by_kind = {row['kind']: row['last'] for row in rows}
    return {
        'morning_digest': by_kind.get(KIND_MORNING_DIGEST),
        'fill_digest': by_kind.get(KIND_FILL_DIGEST),
        'dispatch': NotificationMessage.objects.aggregate(last=Max('sent_at'))['last'],
    }


def counts_by_status() -> dict[str, int]:
    """Сколько сообщений в каждом статусе — для шапки вкладки «Расписание»."""
    return {
        status: NotificationMessage.objects.filter(status=status).count()
        for status in STATUS_CHOICES
    }
```

- [ ] **Step 4: Добавить вьюхи**

В `apps/notifications/views.py` дописать:

```python
from apps.core.pagination import StandardPagination
from apps.core.permissions import IsAdminOrSuperAdmin
from apps.notifications import repository
from apps.notifications.constants import KIND_FILL_DIGEST, KIND_MORNING_DIGEST
from apps.notifications.serializers import NotificationMessageSerializer


class NotificationListView(APIView):
    """GET /api/admin/notifications — журнал доставки."""

    permission_classes = [IsAdminOrSuperAdmin]

    def get(self, request: Request) -> Response:
        qs = repository.filtered(
            kind=request.query_params.get('kind'),
            channel=request.query_params.get('channel'),
            status=request.query_params.get('status'),
        )
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        data = NotificationMessageSerializer(page, many=True).data
        return paginator.get_paginated_response(data)


class NotificationScheduleView(APIView):
    """GET /api/admin/notifications/schedule — вкладка «Расписание»."""

    permission_classes = [IsAdminOrSuperAdmin]

    def get(self, request: Request) -> Response:
        last = repository.last_runs()
        return Response({
            'jobs': [
                {'key': 'morning_digest', 'title': 'Утренний дайджест расписания',
                 'schedule': '08:00', 'kind': KIND_MORNING_DIGEST,
                 'last_run_at': last['morning_digest']},
                {'key': 'fill_digest', 'title': 'Незаполненные отчёты',
                 'schedule': '21:00', 'kind': KIND_FILL_DIGEST,
                 'last_run_at': last['fill_digest']},
                {'key': 'dispatch', 'title': 'Отправка очереди',
                 'schedule': 'каждую минуту', 'kind': None,
                 'last_run_at': last['dispatch']},
            ],
            'counts': repository.counts_by_status(),
        })
```

- [ ] **Step 5: Смонтировать маршруты**

`apps/notifications/urls.py` целиком:

```python
"""Маршруты admin-API уведомлений."""
from django.urls import path

from apps.notifications.views import (
    NotificationListView, NotificationScheduleView, TelegramUsersView,
)

urlpatterns = [
    path('', NotificationListView.as_view(), name='notifications-list'),
    path('/schedule', NotificationScheduleView.as_view(), name='notifications-schedule'),
]

telegram_users_urlpatterns = [
    path('', TelegramUsersView.as_view(), name='telegram-users'),
]
```

В `config/urls.py` заменить строку из Task 13 на две:

```python
    path('api/admin/notifications', include('apps.notifications.urls')),
    path('api/admin/telegram-users',
         include(('apps.notifications.urls', 'telegram_users'),
                 namespace='telegram-users')),
```

Если такая форма `include` окажется неудобной, вынести `TelegramUsersView` в отдельный модуль `apps/notifications/telegram_users_urls.py` с единственным `urlpatterns` и подключить обычным `include('apps.notifications.telegram_users_urls')`. Второй вариант проще — при сомнениях выбирать его.

- [ ] **Step 6: Запустить тесты**

Run: `pytest apps/notifications -v`
Expected: все passed.

- [ ] **Step 7: Commit**

```bash
git add apps/notifications config/urls.py
git commit -m "feat(notifications): admin-API раздела «Уведомления»"
```

---

## Task 15: Раздел «Уведомления» в Admin SPA

**Files:**
- Create: `frontend/admin-src/src/hooks/useNotifications.ts`
- Create: `frontend/admin-src/src/pages/notifications/NotificationsPage.tsx`
- Create: `frontend/admin-src/src/pages/notifications/NotificationDetailModal.tsx`
- Create: `frontend/admin-src/src/pages/notifications/SchedulePanel.tsx`
- Modify: `frontend/admin-src/src/components/shell/Sidebar.tsx:212-222`
- Modify: `frontend/admin-src/src/lib/labels.ts`
- Modify: файл роутов Admin SPA

**Важно:** `npm run build` НЕ запускать — собранный `dist/` не коммитится и засоряет диф.

- [ ] **Step 1: Добавить подписи в labels.ts**

В `frontend/admin-src/src/lib/labels.ts` добавить три словаря рядом с существующими:

```ts
export const NOTIFICATION_KIND_LABELS: Record<string, string> = {
  morning_digest:      'Утренний дайджест',
  fill_digest:         'Не заполнены отчёты',
  makeup_assigned:     'Назначен доп.урок',
  makeup_changed:      'Изменён доп.урок',
  makeup_cancelled:    'Отменён доп.урок',
  lesson_moved:        'Перенос занятия',
  lesson_cancelled:    'Отмена занятия',
  substitute_assigned: 'Назначена замена',
  substitute_removed:  'Снята замена',
};

export const NOTIFICATION_CHANNEL_LABELS: Record<string, string> = {
  dm:         'Личка',
  group_chat: 'Общий чат',
};

export const NOTIFICATION_STATUS_LABELS: Record<string, string> = {
  queued: 'В очереди',
  sent:   'Отправлено',
  failed: 'Не доставлено',
};
```

Там же в существующий словарь `CHANGELOG_OPERATION_LABELS` добавить подписи для операций, чьи правила заведены в Task 2 (без них журнал изменений покажет машинные ключи):

```ts
  'teacher.telegram_link':   'Привязка Telegram',
  'teacher.telegram_unlink': 'Отвязка Telegram',
```

- [ ] **Step 2: Написать хуки**

`frontend/admin-src/src/hooks/useNotifications.ts`:

```ts
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';

export type NotificationRow = {
  id: number;
  kind: string;
  channel: string;
  chat_id: number;
  teacher_name: string | null;
  text: string;
  status: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
  source_kind: string | null;
  source_id: number | null;
};

type ListResponse = {
  rows: NotificationRow[];
  total: number;
  page: number;
  page_size: number;
};

export type ScheduleJob = {
  key: string;
  title: string;
  schedule: string;
  kind: string | null;
  last_run_at: string | null;
};

export function useNotifications(params: {
  page: number;
  kind: string;
  channel: string;
  status: string;
}) {
  const search = new URLSearchParams({ page: String(params.page) });
  if (params.kind) search.set('kind', params.kind);
  if (params.channel) search.set('channel', params.channel);
  if (params.status) search.set('status', params.status);

  return useQuery({
    queryKey: ['notifications', params],
    queryFn: () => api<ListResponse>(`/api/admin/notifications?${search}`),
    // Обязательно во всех server-paginated хуках: без этого таблица мигает
    // пустотой при каждой смене страницы или фильтра.
    placeholderData: keepPreviousData,
  });
}

export function useNotificationSchedule() {
  return useQuery({
    queryKey: ['notifications', 'schedule'],
    queryFn: () =>
      api<{ jobs: ScheduleJob[]; counts: Record<string, number> }>(
        '/api/admin/notifications/schedule',
      ),
  });
}
```

Перед написанием сверить сигнатуру `api<T>()` с `frontend/admin-src/src/lib/api.ts` и точный способ построения URL — использовать тот, что уже применяется в соседних хуках (например, в хуке журнала изменений).

- [ ] **Step 3: Написать страницу**

`frontend/admin-src/src/pages/notifications/NotificationsPage.tsx` — вкладки «Журнал» и «Расписание», `PageHeader`, `FilterBar` с тремя `SelectInput` (нативный `<select>` запрещён), таблица с колонками из спеки, клик по строке открывает `NotificationDetailModal`. Разметку, классы таблицы и пагинатор копировать со страницы журнала изменений (`pages/changelog/`) — это ближайший по смыслу раздел, и он уже соответствует дизайн-системе. Никаких hardcoded цветов и отступов: только токены из `styles/tokens.css`.

Пустое состояние: «Сообщений пока нет» — а не пустая таблица без объяснений.

- [ ] **Step 4: Написать модалку и панель расписания**

`NotificationDetailModal.tsx` — полный текст сообщения (в `<pre>` с переносами), адресат, канал, статус, число попыток, `last_error` (если есть), времена постановки и отправки. Компонент модалки взять существующий из `components/`, свой не писать.

`SchedulePanel.tsx` — список задач из `useNotificationSchedule()`: название, расписание, когда последний раз отрабатывала. Если `last_run_at` пуст или старше суток для дайджестов — подсветить, потому что это ровно тот случай, ради которого вкладка и делается: beat умер, а сообщений просто нет и никто этого не замечает.

- [ ] **Step 5: Добавить пункт меню и маршрут**

В `frontend/admin-src/src/components/shell/Sidebar.tsx` в группу «Система» (строка 213) добавить после `changelog`:

```ts
      { key: 'notifications', label: 'Уведомления', path: '/admin/notifications', can: canSeeChangelog },
```

`can: canSeeChangelog` — раздел системный, доступ такой же, как у журнала изменений (admin/superadmin). Если предикат называется иначе — использовать тот, что реально объявлен в этом файле выше.

Маршрут `/admin/notifications` добавить туда же, где объявлены маршруты остальных разделов, с ленивой загрузкой, как у соседей.

- [ ] **Step 6: Проверить в браузере**

Run: `npm run dev` из `frontend/admin-src/` (или открыть локальный nginx на `:8080`, как принято в проекте).
Проверить: раздел виден в меню под «Системой»; таблица грузится; фильтры работают; клик открывает модалку; вкладка «Расписание» показывает три задачи; при смене страницы таблица не мигает пустотой.

- [ ] **Step 7: Commit**

```bash
git add frontend/admin-src/src
git commit -m "feat(admin): раздел «Уведомления» в группе «Система»"
```

Перед коммитом выполнить `git status --short` и убедиться, что в индексе нет `frontend/admin-dist/` или другой собранной статики.

---

## Task 16: Поле Telegram в карточке преподавателя

**Files:**
- Modify: форма преподавателя в `frontend/admin-src/src/pages/teachers/`
- Modify: `frontend/admin-src/src/hooks/` (хук справочника аккаунтов)

- [ ] **Step 1: Добавить хук справочника**

В `frontend/admin-src/src/hooks/useNotifications.ts` дописать:

```ts
export type TelegramAccount = {
  chat_id: number;
  username: string | null;
  full_name: string;
  bound_to: string | null;
};

export function useTelegramAccounts() {
  return useQuery({
    queryKey: ['telegram-users'],
    queryFn: () => api<{ rows: TelegramAccount[]; total: number }>('/api/admin/telegram-users'),
  });
}
```

- [ ] **Step 2: Добавить поле в форму преподавателя**

В форме редактирования преподавателя добавить поле «Telegram»:

- компонент — `Combobox` из `components/form/` (нативный `<select>` и текстовый ввод ника запрещены: по нику писать в личку нельзя, нужен числовой `chat_id`, а ручной ввод даёт опечатки);
- опции — из `useTelegramAccounts()`, подпись `«Имя (@ник)»`, у занятых — пометка «уже привязан: <ФИО>»;
- под полем — статус: «не привязан» / «привязан, @nick» / «заблокировал бота: <причина>» (последнее — красным токеном ошибки);
- сохранение — `POST /api/admin/teachers/<id>/telegram` с `{chat_id}`; очистка — `DELETE` того же адреса;
- после мутации — инвалидация ключей `['teachers']` и `['telegram-users']`;
- поле доступно только админу: менеджеру показывать в режиме чтения (бэкенд всё равно вернёт 403, но кнопка, которая заведомо не работает, — плохой интерфейс).

- [ ] **Step 3: Проверить в браузере**

Открыть карточку преподавателя, привязать аккаунт, обновить страницу — привязка сохранилась, статус отображается. Зайти менеджером — поле только для чтения.

- [ ] **Step 4: Commit**

```bash
git add frontend/admin-src/src
git commit -m "feat(admin): привязка Telegram в карточке преподавателя"
```

---

## Task 17: Полный прогон и документация

**Files:**
- Modify: `CLAUDE.md`, `docs/security-guidelines.md`, `deploy/README.md`

- [ ] **Step 1: Полный прогон тестов**

Run: `pytest -q`
Expected: все тесты зелёные, включая ранее существовавшие.

Прогон **обязательно полный**, не по приложениям: часть приложений no-op'ит `django_db_setup` и работает на persistent `journal_test`, часть создаёт свежую `test_journal_test`. Прогон по частям после миграции с новыми таблицами даёт ложнозелёный результат.

- [ ] **Step 2: Проверить, что миграция применяется на чистой БД**

Run: `python manage.py migrate --plan | tail -20`
Expected: миграция `notifications.0001_initial` в плане, без конфликтов.

- [ ] **Step 3: Обновить документацию**

В `CLAUDE.md` в раздел конфигурации добавить новые переменные окружения:

```
TELEGRAM_BOT_TOKEN=            # токен того же бота, что в kotocode-bot
TELEGRAM_GENERAL_CHAT_ID=      # общий чат сотрудников (-100...)
BOT_SERVICE_TOKEN=             # общий секрет журнал ↔ бот
NOTIFICATIONS_HISTORY_LIMIT=200
```

Там же короткий абзац: «Уведомления — `apps/notifications/`, очередь в PostgreSQL, диспетчер на Celery-beat. Доменные приложения про Telegram не знают, вызывают `notifications.services.notify_teacher()` внутри своей транзакции».

В `docs/security-guidelines.md` добавить пункт про служебные эндпоинты бота: секрет в заголовке, `constant_time_compare`, ограничение на `127.0.0.1` в nginx.

В `deploy/README.md` — что нового появилось в `.env` и что beat теперь несёт три дополнительных расписания.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs deploy
git commit -m "docs: уведомления Telegram — конфигурация и эксплуатация"
```

---

## Порядок выкатки на прод

Выполняется после того, как весь план пройден и тесты зелёные. Это не задача для агента — шаги делает человек с доступом к серверу.

1. Заполнить новые переменные в `.env` журнала; перезапустить `journal-django`, `journal-celery-worker`, `journal-celery-beat`.
2. Попросить нескольких сотрудников написать боту любое сообщение — журнал наполнит справочник аккаунтов. (После выката плана бота это будет происходить само.)
3. Админ привязывает **только себя** и ждёт 8:00 и 21:00 — смотрит оба дайджеста живьём. Это и есть замена «безопасного режима»: сообщения физически не могут уйти никому, кроме привязанных.
4. Убедившись, что тексты и состав верны, админ привязывает остальных преподавателей.
5. Только после этого выкатывается план переработки бота и удаляется ручной ввод.

---

## Self-review плана

Проверка покрытия спеки:

| Требование спеки | Задача |
|---|---|
| §4.2 три модели | 1 |
| §4.2 pghistory + registry | 1, 2 |
| §4.3 ключ идемпотентности | 4 |
| §4.4 транзакция и on_commit | 4 |
| §4.5 диспетчер, ошибки, подрезка | 5, 6 |
| §4.6 утренний дайджест | 7, 8 |
| §4.7 вечерний дайджест | 7, 9 |
| §4.8 точечные уведомления | 10, 11 |
| §5 служебный API + nginx | 12 |
| §6 привязка в админке | 13, 16 |
| §7 раздел «Уведомления» | 14, 15 |
| §9 безопасность | 12, 13, 17 |
| §10 производительность | 7, 8, 13 (select_related) |
| §11 тестирование | все задачи + 17 |
| §12 порядок внедрения | раздел «Порядок выкатки» |

§8 (переработка бота) вынесена в отдельный план — другой репозиторий.
