# Раздел «Задачи» — бэкенд (этапы 1–3). План реализации

> **Для исполнителя:** ОБЯЗАТЕЛЬНАЯ ПОД-СКИЛЛ: используй `superpowers:subagent-driven-development`
> (рекомендуется) или `superpowers:executing-plans` для выполнения задача-за-задачей.
> Шаги помечены чекбоксами (`- [ ]`).

**Цель:** приложение `apps/taskboard` с настраиваемыми воронками, стадиями и карточками задач —
работающий и покрытый тестами REST API, до написания интерфейса.

**Архитектура:** модели → сервисный слой (все мутации только через него) → репозиторий (чтение) →
DRF-вьюхи на `APIView`. Единственный источник истины о том, закрыта ли задача — категория её стадии.
Доска не читается одним запросом: колонки и счётчики отдельно, карточки колонки — пагинированно.

**Стек:** Django 5.2.15 (внимание: requirements.txt пинит 5.1.4 — расхождение окружения), DRF 3.15.2, PostgreSQL, django-pghistory 3.9.2, pytest + pytest-django.

**Спека:** `docs/superpowers/specs/2026-08-24-taskboard-design.md`

---

## Важные правила проекта (читать до начала)

1. **Коммиты — только по явной просьбе пользователя.** Шаги «Коммит» ниже содержат готовые команды,
   но выполнять их можно, только если пользователь разрешил коммитить. Иначе — оставить изменения
   в рабочем дереве и сказать об этом.
2. **Гонять полный `pytest -q` из `journal_django/`**, а не по приложениям. Часть приложений
   no-op'ит `django_db_setup` (общая `journal_test`), часть пересоздаёт `test_journal_test`.
   Прогон по частям даёт ложно-зелёный результат.
3. **DRF по умолчанию `AllowAny`.** Каждая вьюха обязана задать `permission_classes`.
   Забыл — эндпоинт открыт всем.
4. **`APPEND_SLASH=False`** — маршруты без завершающего слэша.
5. **Никаких «велосипедов»**: пагинация — встроенная DRF, аутентификация — существующая
   `CookieJWTAuthentication`, права — классы из `apps/core/permissions.py`.
6. **Django 5.1**: у `CheckConstraint` аргумент называется `condition`, не `check`.

## Структура файлов

| Файл | Ответственность |
|---|---|
| `apps/taskboard/__init__.py` | пустой |
| `apps/taskboard/apps.py` | `AppConfig` (label `taskboard`) |
| `apps/taskboard/models.py` | шесть моделей, ограничения БД, индексы |
| `apps/taskboard/services.py` | все мутации: создание, перенос, закрытие, комментарии, теги |
| `apps/taskboard/repository.py` | чтение: список с фильтрами, колонки, неделя, лента |
| `apps/taskboard/serializers.py` | валидация входа |
| `apps/taskboard/views.py` | DRF-вьюхи и права |
| `apps/taskboard/urls.py` | маршруты |
| `apps/taskboard/migrations/` | схема + сид воронки по умолчанию |
| `apps/taskboard/tests/` | pytest-тесты по слоям |

Разнесение по слоям повторяет `apps/renewals` — это установленный паттерн проекта.

---

## Задача 1: Скелет приложения

**Файлы:**
- Создать: `journal_django/apps/taskboard/__init__.py`
- Создать: `journal_django/apps/taskboard/apps.py`
- Создать: `journal_django/apps/taskboard/migrations/__init__.py`
- Создать: `journal_django/apps/taskboard/tests/__init__.py`
- Создать: `journal_django/apps/taskboard/tests/test_app.py`
- Изменить: `journal_django/config/settings/base.py` (список `INSTALLED_APPS`, после `'apps.knowledge',`)

- [ ] **Шаг 1: Написать падающий тест**

Создать `journal_django/apps/taskboard/tests/test_app.py`:

```python
"""Приложение зарегистрировано под ожидаемым label."""
from django.apps import apps


def test_taskboard_app_registered():
    config = apps.get_app_config('taskboard')
    assert config.name == 'apps.taskboard'
```

- [ ] **Шаг 2: Запустить тест — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_app.py -v
```

Ожидаемо: `LookupError: No installed app with label 'taskboard'`.

- [ ] **Шаг 3: Создать приложение**

`journal_django/apps/taskboard/__init__.py` — пустой файл.
`journal_django/apps/taskboard/migrations/__init__.py` — пустой файл.
`journal_django/apps/taskboard/tests/__init__.py` — пустой файл.

`journal_django/apps/taskboard/apps.py`:

```python
"""AppConfig раздела «Задачи»."""
from django.apps import AppConfig


class TaskboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.taskboard'
    label = 'taskboard'
```

В `journal_django/config/settings/base.py` добавить в `INSTALLED_APPS` строкой ниже
`'apps.knowledge',`:

```python
    'apps.taskboard',
```

- [ ] **Шаг 4: Запустить тест — убедиться, что проходит**

```
cd journal_django && pytest apps/taskboard/tests/test_app.py -v
```

Ожидаемо: `1 passed`.

- [ ] **Шаг 5: Коммит** (только если пользователь разрешил коммитить)

```bash
git add journal_django/apps/taskboard journal_django/config/settings/base.py
git commit -m "feat(tasks): каркас приложения taskboard"
```

---

## Задача 2: Модели воронки и стадии

**Файлы:**
- Создать: `journal_django/apps/taskboard/models.py`
- Создать: `journal_django/apps/taskboard/tests/test_models_board.py`
- Создать: `journal_django/apps/taskboard/migrations/0001_initial.py` (генерируется)

- [ ] **Шаг 1: Написать падающие тесты**

Создать `journal_django/apps/taskboard/tests/test_models_board.py`:

```python
"""Ограничения БД на воронке и стадии."""
import pytest
from django.db import IntegrityError, transaction

from apps.taskboard.models import TaskBoard, TaskStage


@pytest.fixture
def board(db):
    b = TaskBoard.objects.create(name='__tb_test_board__')
    yield b
    TaskStage.objects.filter(board=b).delete()
    b.delete()


@pytest.mark.django_db
def test_stage_label_unique_within_board(board):
    TaskStage.objects.create(board=board, label='Новая', sort_order=0, category='open')
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TaskStage.objects.create(board=board, label='Новая', sort_order=1, category='open')


@pytest.mark.django_db
def test_stage_rejects_unknown_category(board):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TaskStage.objects.create(board=board, label='Х', sort_order=0, category='wat')


@pytest.mark.django_db
def test_stage_rejects_malformed_color(board):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TaskStage.objects.create(
                board=board, label='Х', sort_order=0, category='open', color='красный')


@pytest.mark.django_db
def test_stage_accepts_null_color(board):
    stage = TaskStage.objects.create(board=board, label='Без цвета', sort_order=0, category='open')
    assert stage.color is None
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_models_board.py -v
```

Ожидаемо: `ModuleNotFoundError: No module named 'apps.taskboard.models'`.

- [ ] **Шаг 3: Написать модели**

Создать `journal_django/apps/taskboard/models.py`:

```python
"""
Модели раздела «Задачи» — управляемые Django (managed=True), новые таблицы.

task_board    — воронка (произвольное число, заводит суперадмин).
task_stage    — стадия воронки; category ∈ {open, closed} — ЕДИНСТВЕННЫЙ источник
                истины о том, закрыта ли задача. Название и порядок — кастомные.
task_type     — справочник типов («Звонок», «Встреча», «Дело»).
task_tag      — справочник тегов.
task          — карточка.
task_activity — лента карточки: смена стадии, смена исполнителя, комментарий, системное.

Признак «просрочена» НЕ хранится — выводится на чтении (due_date < сегодня AND
closed_at IS NULL).
"""
from __future__ import annotations

import pghistory
from django.db import models

from apps.core.db_fields import TolerantJSONField


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class TaskBoard(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.TextField()
    description = models.TextField(null=True, blank=True)
    sort_order = models.IntegerField(default=0)
    # Архивная воронка не предлагается при создании задач, но её задачи доступны.
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'task_board'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='task_board_name_uq'),
        ]
        indexes = [
            models.Index(fields=['sort_order'], name='task_board_order_idx'),
        ]


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class TaskStage(models.Model):
    class Category(models.TextChoices):
        OPEN = 'open', 'Открыта'
        CLOSED = 'closed', 'Закрыта'

    id = models.BigAutoField(primary_key=True)
    board = models.ForeignKey(
        TaskBoard, on_delete=models.CASCADE,
        db_column='board_id', related_name='stages',
    )
    label = models.TextField()
    color = models.TextField(null=True, blank=True)
    sort_order = models.IntegerField()
    # Стабильного машинного ключа (как RenewalStage.key) здесь НЕТ намеренно:
    # он в продлениях существует ради авто-правил движка, а движка у нас нет.
    category = models.CharField(max_length=6, choices=Category.choices)

    class Meta:
        managed = True
        db_table = 'task_stage'
        constraints = [
            models.UniqueConstraint(fields=['board', 'label'], name='task_stage_board_label_uq'),
            models.CheckConstraint(
                name='task_stage_category_check',
                condition=models.Q(category__in=['open', 'closed']),
            ),
            models.CheckConstraint(
                name='task_stage_color_check',
                condition=models.Q(color__isnull=True) | models.Q(color__regex=r'^#[0-9a-fA-F]{6}$'),
            ),
        ]
        indexes = [
            models.Index(fields=['board', 'sort_order'], name='task_stage_order_idx'),
        ]
```

- [ ] **Шаг 4: Сгенерировать и применить миграцию**

```
cd journal_django && python manage.py makemigrations taskboard
cd journal_django && python manage.py migrate taskboard
```

Ожидаемо: создан `apps/taskboard/migrations/0001_initial.py`, применён без ошибок.

- [ ] **Шаг 5: Запустить тесты — убедиться, что проходят**

```
cd journal_django && pytest apps/taskboard/tests/test_models_board.py -v
```

Ожидаемо: `4 passed`.

- [ ] **Шаг 6: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard
git commit -m "feat(tasks): модели воронки и стадии с ограничениями БД"
```

---

## Задача 3: Модели справочников, карточки и ленты

**Файлы:**
- Изменить: `journal_django/apps/taskboard/models.py` (дописать в конец)
- Создать: `journal_django/apps/taskboard/tests/test_models_task.py`
- Создать: `journal_django/apps/taskboard/migrations/0002_*.py` (генерируется)

- [ ] **Шаг 1: Написать падающие тесты**

Создать `journal_django/apps/taskboard/tests/test_models_task.py`:

```python
"""Ограничения БД на карточке задачи."""
import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.taskboard.models import Task, TaskBoard, TaskStage


@pytest.fixture
def board_with_stages(db):
    board = TaskBoard.objects.create(name='__tb_test_task_board__')
    open_stage = TaskStage.objects.create(
        board=board, label='В работе', sort_order=0, category='open')
    closed_stage = TaskStage.objects.create(
        board=board, label='Готово', sort_order=1, category='closed')
    yield board, open_stage, closed_stage
    Task.objects.filter(board=board).delete()
    TaskStage.objects.filter(board=board).delete()
    board.delete()


@pytest.mark.django_db
def test_open_task_has_no_resolution(board_with_stages):
    board, open_stage, _ = board_with_stages
    task = Task.objects.create(board=board, stage=open_stage, title='Позвонить')
    assert task.resolution is None
    assert task.closed_at is None


@pytest.mark.django_db
def test_closed_at_requires_resolution(board_with_stages):
    """closed_at и resolution заполняются только вместе — CHECK на уровне БД."""
    board, _, closed_stage = board_with_stages
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Task.objects.create(
                board=board, stage=closed_stage, title='Битая',
                closed_at=timezone.now(), resolution=None)


@pytest.mark.django_db
def test_resolution_requires_closed_at(board_with_stages):
    board, open_stage, _ = board_with_stages
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Task.objects.create(
                board=board, stage=open_stage, title='Битая',
                closed_at=None, resolution='done')


@pytest.mark.django_db
def test_rejects_unknown_priority(board_with_stages):
    board, open_stage, _ = board_with_stages
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Task.objects.create(
                board=board, stage=open_stage, title='Х', priority='urgent')


@pytest.mark.django_db
def test_stage_with_tasks_cannot_be_deleted(board_with_stages):
    """FK RESTRICT: стадию с задачами удалить нельзя."""
    from django.db.models import RestrictedError

    board, open_stage, _ = board_with_stages
    Task.objects.create(board=board, stage=open_stage, title='Держит стадию')
    with pytest.raises(RestrictedError):
        with transaction.atomic():
            open_stage.delete()
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_models_task.py -v
```

Ожидаемо: `ImportError: cannot import name 'Task'`.

- [ ] **Шаг 3: Дописать модели**

Дописать в конец `journal_django/apps/taskboard/models.py`:

```python
@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class TaskType(models.Model):
    """Справочник типов задач: «Звонок», «Встреча», «Дело»."""
    id = models.BigAutoField(primary_key=True)
    label = models.TextField()
    sort_order = models.IntegerField(default=0)

    class Meta:
        managed = True
        db_table = 'task_type'
        constraints = [
            models.UniqueConstraint(fields=['label'], name='task_type_label_uq'),
        ]


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class TaskTag(models.Model):
    id = models.BigAutoField(primary_key=True)
    label = models.TextField()
    color = models.TextField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = 'task_tag'
        constraints = [
            models.UniqueConstraint(fields=['label'], name='task_tag_label_uq'),
            models.CheckConstraint(
                name='task_tag_color_check',
                condition=models.Q(color__isnull=True) | models.Q(color__regex=r'^#[0-9a-fA-F]{6}$'),
            ),
        ]


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Task(models.Model):
    """
    Карточка задачи. id служит человекочитаемым номером «#20» в интерфейсе —
    отдельного поля номера нет намеренно (сквозной нумерации внутри воронки,
    как PROJ-12 в Jira, не делаем).

    Закрыта задача ⇔ её стадия имеет category='closed'. Отдельного флага
    «выполнено» нет: единственный источник истины — стадия.
    """
    class Priority(models.TextChoices):
        LOW = 'low', 'Низкий'
        NORMAL = 'normal', 'Обычный'
        HIGH = 'high', 'Высокий'

    class Resolution(models.TextChoices):
        DONE = 'done', 'Выполнено'
        CANCELLED = 'cancelled', 'Отменено'
        IRRELEVANT = 'irrelevant', 'Неактуально'

    id = models.BigAutoField(primary_key=True)
    board = models.ForeignKey(
        TaskBoard, on_delete=models.RESTRICT,
        db_column='board_id', related_name='tasks',
    )
    stage = models.ForeignKey(
        TaskStage, on_delete=models.RESTRICT,
        db_column='stage_id', related_name='tasks',
    )
    title = models.TextField()
    description = models.TextField(null=True, blank=True)
    # SET NULL на людях: учётку могут удалить, задачу терять нельзя.
    assignee = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL,
        db_column='assignee_id', related_name='assigned_tasks',
        null=True, blank=True,
    )
    created_by = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL,
        db_column='created_by_id', related_name='created_tasks',
        null=True, blank=True,
    )
    # SET NULL, а не RESTRICT: иначе старая задача заблокирует удаление группы.
    student = models.ForeignKey(
        'students.Student', on_delete=models.SET_NULL,
        db_column='student_id', related_name='tasks',
        null=True, blank=True,
    )
    group = models.ForeignKey(
        'groups.Group', on_delete=models.SET_NULL,
        db_column='group_id', related_name='tasks',
        null=True, blank=True,
    )
    task_type = models.ForeignKey(
        TaskType, on_delete=models.SET_NULL,
        db_column='task_type_id', related_name='tasks',
        null=True, blank=True,
    )
    # Промежуточная таблица связи pghistory НЕ трекает (модель автогенерируемая),
    # поэтому смена тегов пишется записью kind='system' в TaskActivity.
    tags = models.ManyToManyField(
        TaskTag, db_table='task_tag_link', related_name='tasks', blank=True,
    )
    # Дата без времени: время тянет часовые пояса, а «позвонить в 15:00» — это
    # уже календарь, а не задачник.
    due_date = models.DateField(null=True, blank=True)
    priority = models.CharField(
        max_length=6, choices=Priority.choices, default=Priority.NORMAL)
    resolution = models.CharField(
        max_length=10, choices=Resolution.choices, null=True, blank=True)
    stage_entered_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = 'task'
        constraints = [
            models.CheckConstraint(
                name='task_priority_check',
                condition=models.Q(priority__in=['low', 'normal', 'high']),
            ),
            models.CheckConstraint(
                name='task_resolution_check',
                condition=models.Q(resolution__isnull=True)
                | models.Q(resolution__in=['done', 'cancelled', 'irrelevant']),
            ),
            # closed_at и resolution заполняются строго вместе. Защита от
            # «полузакрытой» карточки, которую иначе легко создать мимо сервиса.
            models.CheckConstraint(
                name='task_closed_resolution_check',
                condition=models.Q(closed_at__isnull=True, resolution__isnull=True)
                | models.Q(closed_at__isnull=False, resolution__isnull=False),
            ),
        ]
        indexes = [
            models.Index(fields=['board', 'stage'], name='task_board_stage_idx'),
            models.Index(
                fields=['assignee'], name='task_assignee_open_idx',
                condition=models.Q(closed_at__isnull=True),
            ),
            models.Index(
                fields=['student'], name='task_student_idx',
                condition=models.Q(student__isnull=False),
            ),
            models.Index(
                fields=['due_date'], name='task_due_open_idx',
                condition=models.Q(closed_at__isnull=True),
            ),
        ]


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class TaskActivity(models.Model):
    class Kind(models.TextChoices):
        STAGE_CHANGE = 'stage_change', 'Смена стадии'
        ASSIGN = 'assign', 'Смена исполнителя'
        COMMENT = 'comment', 'Комментарий'
        SYSTEM = 'system', 'Системная запись'

    id = models.BigAutoField(primary_key=True)
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE,
        db_column='task_id', related_name='activity',
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    author = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL,
        db_column='author_id', related_name='task_activity',
        null=True, blank=True,
    )
    text = models.TextField(null=True, blank=True)
    # TolerantJSONField, а не JSONField: apps.core.apps регистрирует
    # register_default_jsonb, и psycopg2 отдаёт уже готовый объект — обычное
    # поле падало бы на json.loads(dict).
    meta = TolerantJSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'task_activity'
        constraints = [
            models.CheckConstraint(
                name='task_activity_kind_check',
                condition=models.Q(kind__in=['stage_change', 'assign', 'comment', 'system']),
            ),
        ]
        indexes = [
            models.Index(fields=['task', 'created_at'], name='task_activity_task_idx'),
        ]
```

- [ ] **Шаг 4: Сгенерировать и применить миграцию**

```
cd journal_django && python manage.py makemigrations taskboard
cd journal_django && python manage.py migrate taskboard
```

- [ ] **Шаг 5: Запустить тесты**

```
cd journal_django && pytest apps/taskboard/tests/test_models_task.py -v
```

Ожидаемо: `5 passed`.

- [ ] **Шаг 6: Применить миграции к общей тестовой БД `journal_test`**

Часть приложений (`accounts`, `auth_app` и др.) no-op'ит `django_db_setup` и ходит
в общую персистентную `journal_test`. Новые FK `Task.assignee/created_by → Account`
заставляют каскад `SET_NULL` обращаться к таблице `task`; если её там нет —
посыплются чужие тесты. Поэтому:

```
cd journal_django && python manage.py migrate taskboard --settings=config.settings.test
```

Операция аддитивная (только `CREATE TABLE`/`CREATE TRIGGER`). **Никаких
`recreate_test_db`, `flush` и удаления баз** — база общая для нескольких рабочих копий.

- [ ] **Шаг 7: Полный прогон**

```
cd journal_django && pytest -q
```

Ожидаемо: **одно** падение — `apps/changelog/tests/test_registry.py::test_registry_covers_all_tracked_models`.
Это НЕ дефект: guard требует регистрации новых трекаемых моделей, а она делается
задачей 5. Всё остальное обязано быть зелёным. Полностью зелёным прогон станет
после задачи 5, которую поэтому выполняем СРАЗУ после этой (до задачи 4).

- [ ] **Шаг 7: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard
git commit -m "feat(tasks): модели карточки, справочников и ленты активности"
```

---

## Задача 4: Сид воронки по умолчанию

**Файлы:**
- Создать: `journal_django/apps/taskboard/migrations/0003_seed_default_board.py`
- Создать: `journal_django/apps/taskboard/tests/test_seed.py`

- [ ] **Шаг 1: Написать падающий тест**

Создать `journal_django/apps/taskboard/tests/test_seed.py`:

```python
"""Стартовая воронка «Общие задачи» создана миграцией."""
import pytest

from apps.taskboard.models import TaskBoard, TaskStage


@pytest.mark.django_db
def test_default_board_seeded():
    board = TaskBoard.objects.get(name='Общие задачи')
    labels = list(
        TaskStage.objects.filter(board=board).order_by('sort_order')
        .values_list('label', 'category'))
    assert labels == [('Новая', 'open'), ('В работе', 'open'), ('Готово', 'closed')]
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_seed.py -v
```

Ожидаемо: `TaskBoard.DoesNotExist`.

- [ ] **Шаг 3: Написать data-миграцию**

Создать `journal_django/apps/taskboard/migrations/0003_seed_default_board.py`
(в `dependencies` подставить реальное имя миграции из задачи 3):

```python
"""Сид стартовой воронки «Общие задачи».

Идемпотентная data-миграция (get_or_create) — безопасна к повторному прогону.
Обратима: unseed удаляет стадии и воронку, но только если в ней нет задач.
"""
from django.db import migrations

# (label, color, category)
STAGES = [
    ('Новая',    '#6366F1', 'open'),
    ('В работе', '#F59E0B', 'open'),
    ('Готово',   '#22C55E', 'closed'),
]

BOARD_NAME = 'Общие задачи'


def seed(apps, schema_editor):
    TaskBoard = apps.get_model('taskboard', 'TaskBoard')
    TaskStage = apps.get_model('taskboard', 'TaskStage')

    board, _ = TaskBoard.objects.get_or_create(
        name=BOARD_NAME,
        defaults={'description': 'Воронка по умолчанию', 'sort_order': 0},
    )
    for i, (label, color, category) in enumerate(STAGES):
        TaskStage.objects.get_or_create(
            board=board,
            label=label,
            defaults={'color': color, 'category': category, 'sort_order': i},
        )


def unseed(apps, schema_editor):
    TaskBoard = apps.get_model('taskboard', 'TaskBoard')
    TaskStage = apps.get_model('taskboard', 'TaskStage')
    Task = apps.get_model('taskboard', 'Task')

    board = TaskBoard.objects.filter(name=BOARD_NAME).first()
    if board is None:
        return
    # В воронке появились задачи — откат сида молча оставляем, иначе FK RESTRICT
    # уронит миграцию посреди отката.
    if Task.objects.filter(board=board).exists():
        return
    TaskStage.objects.filter(board=board).delete()
    board.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('taskboard', '0002_task_tasktag_tasktype_taskactivity'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
```

- [ ] **Шаг 4: Применить и проверить**

```
cd journal_django && python manage.py migrate taskboard
cd journal_django && pytest apps/taskboard/tests/test_seed.py -v
```

Ожидаемо: `1 passed`.

- [ ] **Шаг 5: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard
git commit -m "feat(tasks): стартовая воронка «Общие задачи»"
```

---

## Задача 5: Регистрация в журнале изменений

**Файлы:**
- Изменить: `journal_django/apps/changelog/registry.py` (словарь `TRACKED`)
- Изменить: `journal_django/apps/changelog/labels.py` (список `RULES`)
- Создать: `journal_django/apps/taskboard/tests/test_changelog_registry.py`

- [ ] **Шаг 1: Написать падающий тест**

Создать `journal_django/apps/taskboard/tests/test_changelog_registry.py`:

```python
"""Модели taskboard зарегистрированы в журнале изменений."""
from apps.changelog.registry import TRACKED


def test_taskboard_models_registered():
    expected = {
        'taskboard.TaskBoard': ('task_board', True),
        'taskboard.TaskType': ('task_type', True),
        'taskboard.TaskTag': ('task_tag', True),
        'taskboard.TaskStage': ('task_stage', True),
        'taskboard.Task': ('task', True),
        'taskboard.TaskActivity': ('task_activity', False),
    }
    for key, (entity, revertable) in expected.items():
        assert key in TRACKED, f'{key} не зарегистрирована'
        assert TRACKED[key].entity == entity
        assert TRACKED[key].revertable is revertable


def test_task_label_rules_present():
    from apps.changelog.labels import RULES

    ops = {op for _, _, op in RULES}
    assert 'task.create' in ops
    assert 'task.move' in ops
    assert 'task.complete' in ops
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_changelog_registry.py -v
```

Ожидаемо: `AssertionError: taskboard.TaskBoard не зарегистрирована`.

- [ ] **Шаг 3: Дописать реестр**

В `journal_django/apps/changelog/registry.py`, в словарь `TRACKED`, добавить
(topo: справочники раньше стадий, стадии раньше задач, лента последней):

```python
    # Раздел «Задачи» (спека 2026-08-24). Лента активности неоткатываема —
    # это лог, восстанавливать в нём нечего.
    'taskboard.TaskBoard':    TrackedModel('task_board', True, 10),
    'taskboard.TaskType':     TrackedModel('task_type', True, 10),
    'taskboard.TaskTag':      TrackedModel('task_tag', True, 10),
    'taskboard.TaskStage':    TrackedModel('task_stage', True, 20),
    'taskboard.Task':         TrackedModel('task', True, 30),
    'taskboard.TaskActivity': TrackedModel('task_activity', False, 40),
```

- [ ] **Шаг 4: Дописать правила меток**

В `journal_django/apps/changelog/labels.py`, в список `RULES`, добавить
**до** generic-правил (порядок важен — специфичное выше):

```python
    # Задачи (спека 2026-08-24). Специфичные пути — до /<pk>-правил.
    ('POST', re.compile(r'^/api/admin/tasks/\d+/move$'), 'task.move'),
    ('POST', re.compile(r'^/api/admin/tasks/\d+/complete$'), 'task.complete'),
    ('POST', re.compile(r'^/api/admin/tasks/\d+/comment$'), 'task.comment'),
    ('POST', re.compile(r'^/api/admin/tasks/boards$'), 'task_board.create'),
    ('PATCH', re.compile(r'^/api/admin/tasks/boards/\d+$'), 'task_board.update'),
    ('DELETE', re.compile(r'^/api/admin/tasks/boards/\d+$'), 'task_board.delete'),
    ('POST', re.compile(r'^/api/admin/tasks/boards/\d+/stages$'), 'task_stage.create'),
    ('POST', re.compile(r'^/api/admin/tasks/stages/reorder$'), 'task_stage.reorder'),
    ('PATCH', re.compile(r'^/api/admin/tasks/stages/\d+$'), 'task_stage.update'),
    ('DELETE', re.compile(r'^/api/admin/tasks/stages/\d+$'), 'task_stage.delete'),
    ('POST', re.compile(r'^/api/admin/tasks$'), 'task.create'),
    ('PATCH', re.compile(r'^/api/admin/tasks/\d+$'), 'task.update'),
    ('DELETE', re.compile(r'^/api/admin/tasks/\d+$'), 'task.delete'),
```

- [ ] **Шаг 5: Запустить тесты**

```
cd journal_django && pytest apps/taskboard/tests/test_changelog_registry.py apps/changelog -v
```

Ожидаемо: все зелёные, включая `test_registry_covers_all_tracked_models`.

- [ ] **Шаг 6: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/changelog journal_django/apps/taskboard
git commit -m "feat(tasks): регистрация моделей задач в журнале изменений"
```

---

## Задача 6: Сервис создания задачи

**Файлы:**
- Создать: `journal_django/apps/taskboard/services.py`
- Создать: `journal_django/apps/taskboard/tests/conftest.py`
- Создать: `journal_django/apps/taskboard/tests/test_services_create.py`

- [ ] **Шаг 1: Написать фикстуры**

Создать `journal_django/apps/taskboard/tests/conftest.py`:

```python
"""Фикстуры taskboard: реальная воронка со стадиями, убираем в teardown."""
from __future__ import annotations

import pytest

from apps.taskboard.models import Task, TaskActivity, TaskBoard, TaskStage


@pytest.fixture
def board(db):
    """Воронка с тремя стадиями: две открытых, одна закрытая."""
    b = TaskBoard.objects.create(name='__tb_fixture_board__')
    stages = {
        'new': TaskStage.objects.create(board=b, label='Новая', sort_order=0, category='open'),
        'work': TaskStage.objects.create(board=b, label='В работе', sort_order=1, category='open'),
        'done': TaskStage.objects.create(board=b, label='Готово', sort_order=2, category='closed'),
    }
    yield b, stages
    TaskActivity.objects.filter(task__board=b).delete()
    Task.objects.filter(board=b).delete()
    TaskStage.objects.filter(board=b).delete()
    b.delete()
```

- [ ] **Шаг 2: Написать падающий тест**

Создать `journal_django/apps/taskboard/tests/test_services_create.py`:

```python
"""Создание задачи через сервисный слой."""
import pytest

from apps.taskboard import services
from apps.taskboard.models import TaskActivity


@pytest.mark.django_db
def test_create_puts_task_into_first_open_stage(board):
    b, stages = board
    task = services.create_task(board_id=b.id, title='Позвонить Ивановым', author_id=None)
    assert task.stage_id == stages['new'].id
    assert task.closed_at is None
    assert task.resolution is None


@pytest.mark.django_db
def test_create_writes_system_activity(board):
    b, _ = board
    task = services.create_task(board_id=b.id, title='Позвонить', author_id=None)
    entry = TaskActivity.objects.get(task=task)
    assert entry.kind == 'system'


@pytest.mark.django_db
def test_create_accepts_explicit_stage(board):
    b, stages = board
    task = services.create_task(
        board_id=b.id, title='Уже в работе', author_id=None, stage_id=stages['work'].id)
    assert task.stage_id == stages['work'].id


@pytest.mark.django_db
def test_create_rejects_stage_from_another_board(board):
    from apps.taskboard.models import TaskBoard, TaskStage
    from rest_framework.serializers import ValidationError

    b, _ = board
    other = TaskBoard.objects.create(name='__tb_other_board__')
    alien = TaskStage.objects.create(board=other, label='Чужая', sort_order=0, category='open')
    try:
        with pytest.raises(ValidationError):
            services.create_task(
                board_id=b.id, title='Х', author_id=None, stage_id=alien.id)
    finally:
        alien.delete()
        other.delete()


@pytest.mark.django_db
def test_create_rejects_board_without_open_stage(db):
    from apps.taskboard.models import TaskBoard, TaskStage
    from rest_framework.serializers import ValidationError

    empty = TaskBoard.objects.create(name='__tb_empty_board__')
    TaskStage.objects.create(board=empty, label='Готово', sort_order=0, category='closed')
    try:
        with pytest.raises(ValidationError):
            services.create_task(board_id=empty.id, title='Х', author_id=None)
    finally:
        TaskStage.objects.filter(board=empty).delete()
        empty.delete()
```

- [ ] **Шаг 3: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_services_create.py -v
```

Ожидаемо: `ModuleNotFoundError: No module named 'apps.taskboard.services'`.

- [ ] **Шаг 4: Написать сервис**

Создать `journal_django/apps/taskboard/services.py`:

```python
"""
Мутации раздела «Задачи». ВСЕ изменения проходят через этот модуль — вьюхи
не трогают модели напрямую.

Это же точка расширения под будущую автогенерацию задач по событиям: правило
вызовет create_task(), и переписывать создание не придётся.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.serializers import ValidationError

from apps.taskboard.models import Task, TaskActivity, TaskStage


def _first_stage(board_id: int, *, category: str) -> TaskStage | None:
    # Уникальности sort_order в пределах воронки нет — нужен вторичный ключ,
    # иначе «Выполнено» выбирает стадию недетерминированно.
    return (TaskStage.objects
            .filter(board_id=board_id, category=category)
            .order_by('sort_order', 'id')
            .first())


@transaction.atomic
def create_task(
    *,
    board_id: int,
    title: str,
    author_id: int | None,
    stage_id: int | None = None,
    description: str | None = None,
    assignee_id: int | None = None,
    student_id: int | None = None,
    group_id: int | None = None,
    task_type_id: int | None = None,
    due_date=None,
    priority: str = Task.Priority.NORMAL,
    tag_ids: list[int] | None = None,
) -> Task:
    """Создать задачу. Без явной стадии кладём в первую открытую стадию воронки."""
    if stage_id is None:
        stage = _first_stage(board_id, category=TaskStage.Category.OPEN)
        if stage is None:
            raise ValidationError({'board_id': 'В воронке нет ни одной открытой стадии'})
    else:
        stage = TaskStage.objects.filter(id=stage_id, board_id=board_id).first()
        if stage is None:
            raise ValidationError({'stage_id': 'Стадия не принадлежит этой воронке'})

    task = Task.objects.create(
        board_id=board_id,
        stage=stage,
        title=title,
        description=description,
        assignee_id=assignee_id,
        created_by_id=author_id,
        student_id=student_id,
        group_id=group_id,
        task_type_id=task_type_id,
        due_date=due_date,
        priority=priority,
    )
    if tag_ids:
        task.tags.set(tag_ids)

    TaskActivity.objects.create(
        task=task, kind=TaskActivity.Kind.SYSTEM, author_id=author_id,
        text='Задача создана', meta={'stage_id': stage.id},
    )
    return task
```

- [ ] **Шаг 5: Запустить тесты**

```
cd journal_django && pytest apps/taskboard/tests/test_services_create.py -v
```

Ожидаемо: `5 passed`.

- [ ] **Шаг 6: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard
git commit -m "feat(tasks): сервис создания задачи"
```

---

## Задача 7: Правила переноса и закрытия

**Файлы:**
- Изменить: `journal_django/apps/taskboard/services.py` (дописать)
- Создать: `journal_django/apps/taskboard/tests/test_services_move.py`

- [ ] **Шаг 1: Написать падающие тесты**

Создать `journal_django/apps/taskboard/tests/test_services_move.py`:

```python
"""Перенос между стадиями и правила закрытия."""
import pytest
from rest_framework.serializers import ValidationError

from apps.taskboard import services
from apps.taskboard.models import TaskActivity


@pytest.mark.django_db
def test_move_between_open_stages_keeps_task_open(board):
    b, stages = board
    task = services.create_task(board_id=b.id, title='Х', author_id=None)
    moved = services.move_task(task, to_stage_id=stages['work'].id,
                               resolution=None, author_id=None)
    assert moved.stage_id == stages['work'].id
    assert moved.closed_at is None
    assert moved.resolution is None


@pytest.mark.django_db
def test_move_to_closed_stage_requires_resolution(board):
    b, stages = board
    task = services.create_task(board_id=b.id, title='Х', author_id=None)
    with pytest.raises(ValidationError):
        services.move_task(task, to_stage_id=stages['done'].id,
                           resolution=None, author_id=None)


@pytest.mark.django_db
def test_move_to_closed_stage_sets_closed_at(board):
    b, stages = board
    task = services.create_task(board_id=b.id, title='Х', author_id=None)
    closed = services.move_task(task, to_stage_id=stages['done'].id,
                                resolution='done', author_id=None)
    assert closed.closed_at is not None
    assert closed.resolution == 'done'


@pytest.mark.django_db
def test_reopening_clears_resolution(board):
    b, stages = board
    task = services.create_task(board_id=b.id, title='Х', author_id=None)
    services.move_task(task, to_stage_id=stages['done'].id, resolution='done', author_id=None)
    reopened = services.move_task(task, to_stage_id=stages['work'].id,
                                  resolution=None, author_id=None)
    assert reopened.closed_at is None
    assert reopened.resolution is None


@pytest.mark.django_db
def test_move_rejects_stage_from_another_board(board):
    from apps.taskboard.models import TaskBoard, TaskStage

    b, _ = board
    task = services.create_task(board_id=b.id, title='Х', author_id=None)
    other = TaskBoard.objects.create(name='__tb_move_other__')
    alien = TaskStage.objects.create(board=other, label='Чужая', sort_order=0, category='open')
    try:
        with pytest.raises(ValidationError):
            services.move_task(task, to_stage_id=alien.id, resolution=None, author_id=None)
    finally:
        alien.delete()
        other.delete()


@pytest.mark.django_db
def test_complete_moves_to_first_closed_stage(board):
    b, stages = board
    task = services.create_task(board_id=b.id, title='Х', author_id=None)
    done = services.complete_task(task, resolution='done', author_id=None)
    assert done.stage_id == stages['done'].id
    assert done.resolution == 'done'


@pytest.mark.django_db
def test_move_writes_stage_change_activity(board):
    b, stages = board
    task = services.create_task(board_id=b.id, title='Х', author_id=None)
    services.move_task(task, to_stage_id=stages['work'].id, resolution=None, author_id=None)
    kinds = list(TaskActivity.objects.filter(task=task).values_list('kind', flat=True))
    assert 'stage_change' in kinds
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_services_move.py -v
```

Ожидаемо: `AttributeError: module 'apps.taskboard.services' has no attribute 'move_task'`.

- [ ] **Шаг 3: Дописать сервис**

Дописать в конец `journal_django/apps/taskboard/services.py`:

```python
@transaction.atomic
def move_task(
    task: Task, *, to_stage_id: int, resolution: str | None, author_id: int | None,
) -> Task:
    """
    Перенести задачу в стадию той же воронки.

    Задача закрыта ⇔ стадия имеет category='closed'. Переход в закрытую стадию
    ТРЕБУЕТ результата; возврат в открытую результат и дату закрытия обнуляет.

    Работаем не с переданным объектом, а с перечитанной под блокировкой строкой:
    на канбан-доске двое штатно тянут одну карточку, и у второго объект в памяти
    устаревший — иначе `closed_at or now` затрёт исходную дату закрытия.
    """
    locked = Task.objects.select_for_update().filter(id=task.id).first()
    if locked is None:
        raise ValidationError({'task': 'Задача не найдена'})

    target = TaskStage.objects.filter(id=to_stage_id, board_id=locked.board_id).first()
    if target is None:
        raise ValidationError({'to_stage_id': 'Стадия не принадлежит воронке задачи'})

    from_stage_id = locked.stage_id
    now = timezone.now()

    if target.category == TaskStage.Category.CLOSED:
        if not resolution:
            raise ValidationError({'resolution': 'Укажите результат при закрытии задачи'})
        # Сервис — точка входа и для будущей автогенерации задач, мимо сериализатора.
        # Без этой проверки произвольная строка доезжает до CHECK в БД и даёт 500.
        if resolution not in Task.Resolution.values:
            raise ValidationError({'resolution': 'Неизвестный результат'})
        locked.resolution = resolution
        locked.closed_at = locked.closed_at or now
    else:
        locked.resolution = None
        locked.closed_at = None

    fields = ['resolution', 'closed_at', 'updated_at']
    if target.id != from_stage_id:
        # Промах мышью на ту же колонку не сбрасывает «сколько висит в стадии».
        # Смена результата внутри той же закрытой стадии при этом разрешена.
        locked.stage = target
        locked.stage_entered_at = now
        fields += ['stage', 'stage_entered_at']
    locked.save(update_fields=fields)

    TaskActivity.objects.create(
        task=locked, kind=TaskActivity.Kind.STAGE_CHANGE, author_id=author_id,
        meta={'from_stage_id': from_stage_id, 'to_stage_id': target.id,
              'resolution': locked.resolution},
    )
    return locked


@transaction.atomic
def complete_task(task: Task, *, resolution: str, author_id: int | None) -> Task:
    """
    Кнопка «Выполнено» — не флаг, а ДЕЙСТВИЕ: перенос в первую закрытую стадию
    воронки. Для пользователя один клик из любой колонки; в данных остаётся
    единственный источник истины — стадия.
    """
    target = _first_stage(task.board_id, category=TaskStage.Category.CLOSED)
    if target is None:
        raise ValidationError({'board_id': 'В воронке нет ни одной закрытой стадии'})
    return move_task(task, to_stage_id=target.id, resolution=resolution, author_id=author_id)
```

- [ ] **Шаг 4: Запустить тесты**

```
cd journal_django && pytest apps/taskboard/tests/test_services_move.py -v
```

Ожидаемо: `7 passed`.

- [ ] **Шаг 5: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard
git commit -m "feat(tasks): правила переноса, закрытия и кнопки «Выполнено»"
```

---

## Задача 8: Правки карточки, комментарии и теги

**Файлы:**
- Изменить: `journal_django/apps/taskboard/services.py` (дописать)
- Создать: `journal_django/apps/taskboard/tests/test_services_update.py`

- [ ] **Шаг 1: Написать падающие тесты**

Создать `journal_django/apps/taskboard/tests/test_services_update.py`:

```python
"""Правка полей, смена исполнителя, комментарии, теги."""
import pytest

from apps.taskboard import services
from apps.taskboard.models import TaskActivity, TaskTag


@pytest.mark.django_db
def test_update_changes_title_and_due_date(board):
    import datetime

    b, _ = board
    task = services.create_task(board_id=b.id, title='Старое', author_id=None)
    updated = services.update_task(
        task, author_id=None,
        fields={'title': 'Новое', 'due_date': datetime.date(2026, 9, 1)})
    assert updated.title == 'Новое'
    assert updated.due_date == datetime.date(2026, 9, 1)


@pytest.mark.django_db
def test_update_ignores_unknown_fields(board):
    b, _ = board
    task = services.create_task(board_id=b.id, title='Х', author_id=None)
    updated = services.update_task(task, author_id=None, fields={'closed_at': 'нельзя'})
    assert updated.closed_at is None


@pytest.mark.django_db
def test_assignee_change_writes_assign_activity(board, admin_account_id):
    b, _ = board
    task = services.create_task(board_id=b.id, title='Х', author_id=None)
    services.update_task(task, author_id=None, fields={'assignee_id': admin_account_id})
    kinds = list(TaskActivity.objects.filter(task=task).values_list('kind', flat=True))
    assert 'assign' in kinds


@pytest.mark.django_db
def test_add_comment_creates_entry(board):
    b, _ = board
    task = services.create_task(board_id=b.id, title='Х', author_id=None)
    entry = services.add_comment(task, body='Позвонил, не берёт', author_id=None)
    assert entry.kind == 'comment'
    assert entry.text == 'Позвонил, не берёт'


@pytest.mark.django_db
def test_set_tags_writes_system_activity(board):
    b, _ = board
    tag = TaskTag.objects.create(label='__tb_tag__')
    task = services.create_task(board_id=b.id, title='Х', author_id=None)
    try:
        services.set_tags(task, tag_ids=[tag.id], author_id=None)
        assert list(task.tags.values_list('id', flat=True)) == [tag.id]
        texts = list(
            TaskActivity.objects.filter(task=task, kind='system')
            .values_list('text', flat=True))
        assert any('Теги' in t for t in texts)
    finally:
        task.tags.clear()
        tag.delete()
```

Тесту нужна фикстура `admin_account_id`. Дописать в
`journal_django/apps/taskboard/tests/conftest.py`:

```python
@pytest.fixture
def admin_account_id(db):
    """Реальная учётка admin — для проверок смены исполнителя."""
    from django.contrib.auth.hashers import make_password

    from apps.accounts.models import Account

    account = Account.objects.create(
        username='__tb_admin__', email='__tb_admin__@example.com',
        password=make_password('testpass_sentinel'), role='admin', name='Тестовый админ',
    )
    yield account.id
    account.delete()
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_services_update.py -v
```

Ожидаемо: `AttributeError: module 'apps.taskboard.services' has no attribute 'update_task'`.

- [ ] **Шаг 3: Дописать сервис**

Дописать в конец `journal_django/apps/taskboard/services.py`:

```python
# Поля, которые можно менять через update_task. Стадия, результат и дата
# закрытия сюда НЕ входят намеренно — они меняются только move_task/complete_task,
# иначе появится «полузакрытая» карточка мимо правил.
EDITABLE_FIELDS = frozenset({
    'title', 'description', 'assignee_id', 'student_id', 'group_id',
    'task_type_id', 'due_date', 'priority',
})


@transaction.atomic
def update_task(task: Task, *, author_id: int | None, fields: dict) -> Task:
    """Изменить разрешённые поля карточки. Незнакомые ключи молча игнорируются."""
    changed: list[str] = []
    previous_assignee = task.assignee_id

    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            continue
        if getattr(task, key) == value:
            continue
        setattr(task, key, value)
        changed.append(key)

    if not changed:
        return task

    task.save(update_fields=[*changed, 'updated_at'])

    if 'assignee_id' in changed:
        TaskActivity.objects.create(
            task=task, kind=TaskActivity.Kind.ASSIGN, author_id=author_id,
            meta={'from_assignee_id': previous_assignee, 'to_assignee_id': task.assignee_id},
        )
    return task


@transaction.atomic
def add_comment(task: Task, *, body: str, author_id: int | None) -> TaskActivity:
    return TaskActivity.objects.create(
        task=task, kind=TaskActivity.Kind.COMMENT, author_id=author_id, text=body)


@transaction.atomic
def set_tags(task: Task, *, tag_ids: list[int], author_id: int | None) -> Task:
    """
    Заменить набор тегов. Промежуточную таблицу связи pghistory не трекает
    (модель автогенерируемая), поэтому изменение фиксируем в ленте вручную.
    """
    task.tags.set(tag_ids)
    labels = list(task.tags.order_by('label').values_list('label', flat=True))
    TaskActivity.objects.create(
        task=task, kind=TaskActivity.Kind.SYSTEM, author_id=author_id,
        text=f'Теги: {", ".join(labels) if labels else "нет"}',
        meta={'tag_ids': tag_ids},
    )
    return task
```

- [ ] **Шаг 4: Запустить тесты**

```
cd journal_django && pytest apps/taskboard/tests/test_services_update.py -v
```

Ожидаемо: `5 passed`.

- [ ] **Шаг 5: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard
git commit -m "feat(tasks): правка карточки, комментарии и теги"
```

---

## Задача 9: Репозиторий чтения

**Файлы:**
- Создать: `journal_django/apps/taskboard/repository.py`
- Создать: `journal_django/apps/taskboard/tests/test_repository.py`

- [ ] **Шаг 1: Написать падающие тесты**

Создать `journal_django/apps/taskboard/tests/test_repository.py`:

```python
"""Чтение: фильтры, просрочка, отсутствие N+1."""
import datetime

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.taskboard import repository, services


@pytest.mark.django_db
def test_filter_only_open_excludes_closed(board):
    b, stages = board
    open_task = services.create_task(board_id=b.id, title='Открытая', author_id=None)
    closed = services.create_task(board_id=b.id, title='Закрытая', author_id=None)
    services.move_task(closed, to_stage_id=stages['done'].id,
                       resolution='done', author_id=None)

    ids = [t['id'] for t in repository.list_tasks({'board_id': b.id, 'only_open': True})]
    assert open_task.id in ids
    assert closed.id not in ids


@pytest.mark.django_db
def test_overdue_flag_is_derived(board):
    b, _ = board
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    task = services.create_task(
        board_id=b.id, title='Просроченная', author_id=None, due_date=yesterday)
    row = next(t for t in repository.list_tasks({'board_id': b.id}) if t['id'] == task.id)
    assert row['is_overdue'] is True


@pytest.mark.django_db
def test_closed_task_is_never_overdue(board):
    b, stages = board
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    task = services.create_task(
        board_id=b.id, title='Закрытая просрочка', author_id=None, due_date=yesterday)
    services.move_task(task, to_stage_id=stages['done'].id,
                       resolution='done', author_id=None)
    row = next(t for t in repository.list_tasks({'board_id': b.id}) if t['id'] == task.id)
    assert row['is_overdue'] is False


@pytest.mark.django_db
def test_list_does_not_grow_queries_with_rows(board):
    """N+1-страж: 10 задач стоят столько же запросов, сколько 2."""
    b, _ = board
    for i in range(2):
        services.create_task(board_id=b.id, title=f'Задача {i}', author_id=None)
    with CaptureQueriesContext(connection) as few:
        repository.list_tasks({'board_id': b.id})

    for i in range(2, 10):
        services.create_task(board_id=b.id, title=f'Задача {i}', author_id=None)
    with CaptureQueriesContext(connection) as many:
        repository.list_tasks({'board_id': b.id})

    assert len(many) == len(few)


@pytest.mark.django_db
def test_week_returns_only_dated_tasks_in_range(board):
    b, _ = board
    today = datetime.date.today()
    dated = services.create_task(
        board_id=b.id, title='С датой', author_id=None, due_date=today)
    undated = services.create_task(board_id=b.id, title='Без даты', author_id=None)

    ids = [t['id'] for t in repository.list_week(date_from=today, date_to=today)]
    assert dated.id in ids
    assert undated.id not in ids
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_repository.py -v
```

Ожидаемо: `ModuleNotFoundError: No module named 'apps.taskboard.repository'`.

- [ ] **Шаг 3: Написать репозиторий**

Создать `journal_django/apps/taskboard/repository.py`:

```python
"""
Чтение раздела «Задачи». Возвращает списки dict — сериализаторы на чтении не
используются (паттерн apps/renewals).

Признак просрочки выводится здесь, а не хранится: due_date < сегодня и задача
не закрыта.
"""
from __future__ import annotations

from datetime import date

from apps.core.utils.dates import msk_today
from apps.taskboard.models import Task, TaskActivity

# Связи, без которых каждая карточка давала бы лишние запросы.
_RELATED = ('board', 'stage', 'assignee', 'created_by', 'student', 'group', 'task_type')


def _base_queryset():
    return (Task.objects
            .select_related(*_RELATED)
            .prefetch_related('tags'))


def _row(task: Task, *, today: date) -> dict:
    return {
        'id': task.id,
        'board_id': task.board_id,
        'stage_id': task.stage_id,
        'stage_label': task.stage.label,
        'stage_category': task.stage.category,
        'stage_color': task.stage.color,
        'title': task.title,
        'description': task.description,
        'assignee_id': task.assignee_id,
        'assignee_name': task.assignee.full_name if task.assignee else None,
        'created_by_id': task.created_by_id,
        'student_id': task.student_id,
        'student_name': task.student.full_name if task.student else None,
        'group_id': task.group_id,
        'group_name': task.group.name if task.group else None,
        'task_type_id': task.task_type_id,
        'task_type_label': task.task_type.label if task.task_type else None,
        'tags': [{'id': t.id, 'label': t.label, 'color': t.color} for t in task.tags.all()],
        'due_date': task.due_date.isoformat() if task.due_date else None,
        'priority': task.priority,
        'resolution': task.resolution,
        'is_closed': task.closed_at is not None,
        'is_overdue': (
            task.closed_at is None
            and task.due_date is not None
            and task.due_date < today
        ),
        'closed_at': task.closed_at.isoformat() if task.closed_at else None,
        'created_at': task.created_at.isoformat(),
    }


def _apply_filters(qs, params: dict):
    if params.get('board_id'):
        qs = qs.filter(board_id=params['board_id'])
    if params.get('stage_id'):
        qs = qs.filter(stage_id=params['stage_id'])
    if params.get('assignee_id'):
        qs = qs.filter(assignee_id=params['assignee_id'])
    if params.get('student_id'):
        qs = qs.filter(student_id=params['student_id'])
    if params.get('group_id'):
        qs = qs.filter(group_id=params['group_id'])
    if params.get('priority'):
        qs = qs.filter(priority=params['priority'])
    if params.get('task_type_id'):
        qs = qs.filter(task_type_id=params['task_type_id'])
    if params.get('tag_id'):
        qs = qs.filter(tags__id=params['tag_id'])
    if params.get('only_open'):
        qs = qs.filter(closed_at__isnull=True)
    if params.get('overdue'):
        qs = qs.filter(closed_at__isnull=True, due_date__lt=date.fromisoformat(msk_today()))
    if params.get('q'):
        qs = qs.filter(title__icontains=params['q'])
    return qs


def tasks_queryset(params: dict):
    """
    Отфильтрованный и отсортированный queryset — для СЕРВЕРНОЙ пагинации.

    Вьюха накладывает на него LIMIT/OFFSET и превращает в строки только
    страницу: иначе воронка с тысячей задач читалась бы целиком ради 20 карточек.
    """
    return _apply_filters(_base_queryset(), params).order_by('due_date', '-created_at')


def rows(tasks, *, today: date | None = None) -> list[dict]:
    """Превратить набор задач (обычно одну страницу) в строки выдачи."""
    today = today or date.fromisoformat(msk_today())
    return [_row(t, today=today) for t in tasks]


def list_tasks(params: dict) -> list[dict]:
    """
    Полный список без пагинации — для мест, где выборка заведомо мала
    (блок задач на странице ученика, колонка доски). Для списков произвольного
    размера вьюха обязана идти через tasks_queryset + rows.
    """
    return rows(tasks_queryset(params))


def get_task(task_id: int) -> dict | None:
    """Одна карточка тем же форматом, что и строка списка."""
    today = date.fromisoformat(msk_today())
    task = _base_queryset().filter(id=task_id).first()
    return _row(task, today=today) if task else None


def list_column(stage_id: int) -> list[dict]:
    """Карточки одной колонки доски."""
    return list_tasks({'stage_id': stage_id})


def list_week(*, date_from: date, date_to: date) -> list[dict]:
    """Задачи со сроком в диапазоне (границы включительно). Без срока — не попадают."""
    today = date.fromisoformat(msk_today())
    qs = (_base_queryset()
          .filter(due_date__gte=date_from, due_date__lte=date_to)
          .order_by('due_date', '-created_at'))
    return [_row(t, today=today) for t in qs]


def list_activity(task_id: int) -> list[dict]:
    """Лента карточки, старые записи сверху."""
    entries = (TaskActivity.objects
               .select_related('author')
               .filter(task_id=task_id)
               .order_by('created_at', 'id'))
    return [{
        'id': e.id,
        'kind': e.kind,
        'author_id': e.author_id,
        'author_name': e.author.full_name if e.author else None,
        'text': e.text,
        'meta': e.meta,
        'created_at': e.created_at.isoformat(),
    } for e in entries]
```

- [ ] **Шаг 4: Запустить тесты**

```
cd journal_django && pytest apps/taskboard/tests/test_repository.py -v
```

Ожидаемо: `5 passed`.

- [ ] **Шаг 5: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard
git commit -m "feat(tasks): репозиторий чтения с фильтрами и стражем N+1"
```

---

## Задача 10: Сериализаторы входа

**Файлы:**
- Создать: `journal_django/apps/taskboard/serializers.py`
- Создать: `journal_django/apps/taskboard/tests/test_serializers.py`

- [ ] **Шаг 1: Написать падающие тесты**

Создать `journal_django/apps/taskboard/tests/test_serializers.py`:

```python
"""Валидация входных данных."""
from apps.taskboard.serializers import (
    MoveSerializer, TaskCreateSerializer, TaskPatchSerializer,
)


def test_create_requires_board_and_title():
    s = TaskCreateSerializer(data={})
    assert not s.is_valid()
    assert 'board_id' in s.errors
    assert 'title' in s.errors


def test_create_accepts_minimal_payload():
    s = TaskCreateSerializer(data={'board_id': 1, 'title': 'Позвонить'})
    assert s.is_valid(), s.errors
    assert s.validated_data['priority'] == 'normal'


def test_create_rejects_unknown_priority():
    s = TaskCreateSerializer(data={'board_id': 1, 'title': 'Х', 'priority': 'urgent'})
    assert not s.is_valid()
    assert 'priority' in s.errors


def test_move_requires_stage():
    s = MoveSerializer(data={})
    assert not s.is_valid()
    assert 'to_stage_id' in s.errors


def test_move_rejects_unknown_resolution():
    s = MoveSerializer(data={'to_stage_id': 1, 'resolution': 'почти'})
    assert not s.is_valid()
    assert 'resolution' in s.errors


def test_patch_allows_partial_payload():
    s = TaskPatchSerializer(data={'title': 'Новое'})
    assert s.is_valid(), s.errors
    assert s.validated_data == {'title': 'Новое'}
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_serializers.py -v
```

Ожидаемо: `ModuleNotFoundError: No module named 'apps.taskboard.serializers'`.

- [ ] **Шаг 3: Написать сериализаторы**

Создать `journal_django/apps/taskboard/serializers.py`:

```python
"""Сериализаторы taskboard: только валидация ВХОДА. Чтение — dict из repository."""
from __future__ import annotations

from rest_framework import serializers

PRIORITIES = ['low', 'normal', 'high']
RESOLUTIONS = ['done', 'cancelled', 'irrelevant']


class TaskCreateSerializer(serializers.Serializer):
    board_id = serializers.IntegerField()
    title = serializers.CharField(max_length=500)
    # Без явной стадии сервис кладёт задачу в первую открытую стадию воронки.
    stage_id = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    assignee_id = serializers.IntegerField(required=False, allow_null=True)
    student_id = serializers.IntegerField(required=False, allow_null=True)
    group_id = serializers.IntegerField(required=False, allow_null=True)
    task_type_id = serializers.IntegerField(required=False, allow_null=True)
    due_date = serializers.DateField(required=False, allow_null=True)
    priority = serializers.ChoiceField(choices=PRIORITIES, required=False, default='normal')
    tag_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class TaskPatchSerializer(serializers.Serializer):
    """Частичная правка. Стадии, результата и даты закрытия здесь нет намеренно —
    они меняются только через /move и /complete."""
    title = serializers.CharField(max_length=500, required=False)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    assignee_id = serializers.IntegerField(required=False, allow_null=True)
    student_id = serializers.IntegerField(required=False, allow_null=True)
    group_id = serializers.IntegerField(required=False, allow_null=True)
    task_type_id = serializers.IntegerField(required=False, allow_null=True)
    due_date = serializers.DateField(required=False, allow_null=True)
    priority = serializers.ChoiceField(choices=PRIORITIES, required=False)
    tag_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class MoveSerializer(serializers.Serializer):
    to_stage_id = serializers.IntegerField()
    # Обязателен при переходе в закрытую стадию — проверяет сервис, потому что
    # категория целевой стадии известна только там.
    resolution = serializers.ChoiceField(
        choices=RESOLUTIONS, required=False, allow_null=True)


class CompleteSerializer(serializers.Serializer):
    resolution = serializers.ChoiceField(choices=RESOLUTIONS, required=False, default='done')


class CommentSerializer(serializers.Serializer):
    body = serializers.CharField()


class BoardWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    is_archived = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(required=False)


class StageWriteSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=200)
    color = serializers.RegexField(r'^#[0-9a-fA-F]{6}$', required=False, allow_null=True)
    category = serializers.ChoiceField(choices=['open', 'closed'])


class StageReorderSerializer(serializers.Serializer):
    order = serializers.ListField(child=serializers.IntegerField())  # stage_id в новом порядке


class WeekQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()

    def validate(self, data: dict) -> dict:
        if data['date_from'] > data['date_to']:
            raise serializers.ValidationError({'date_to': 'Конец диапазона раньше начала'})
        return data
```

- [ ] **Шаг 4: Запустить тесты**

```
cd journal_django && pytest apps/taskboard/tests/test_serializers.py -v
```

Ожидаемо: `6 passed`.

- [ ] **Шаг 5: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard
git commit -m "feat(tasks): сериализаторы входных данных"
```

---

## Задача 11: API карточек — коллекция и деталь

**Файлы:**
- Создать: `journal_django/apps/taskboard/views.py`
- Создать: `journal_django/apps/taskboard/urls.py`
- Изменить: `journal_django/config/urls.py` (добавить маршрут)
- Создать: `journal_django/apps/taskboard/tests/test_api_tasks.py`

- [ ] **Шаг 1: Написать падающие тесты**

Создать `journal_django/apps/taskboard/tests/test_api_tasks.py`:

```python
"""API карточек: доступ по ролям, создание, правка, удаление."""
import pytest

BASE = '/api/admin/tasks'


@pytest.mark.django_db
def test_teacher_is_denied(teacher_client, board):
    b, _ = board
    assert teacher_client.get(f'{BASE}?board_id={b.id}').status_code == 403


@pytest.mark.django_db
def test_anonymous_is_denied(anon_client, board):
    b, _ = board
    assert anon_client.get(f'{BASE}?board_id={b.id}').status_code == 401


@pytest.mark.django_db
def test_manager_creates_and_reads(manager_client, board):
    b, _ = board
    created = manager_client.post(
        BASE, {'board_id': b.id, 'title': 'Позвонить Ивановым'}, format='json')
    assert created.status_code == 201
    task_id = created.json()['id']

    listing = manager_client.get(f'{BASE}?board_id={b.id}')
    assert listing.status_code == 200
    assert task_id in [t['id'] for t in listing.json()['results']]


@pytest.mark.django_db
def test_manager_patches_title(manager_client, board):
    b, _ = board
    task_id = manager_client.post(
        BASE, {'board_id': b.id, 'title': 'Старое'}, format='json').json()['id']
    resp = manager_client.patch(f'{BASE}/{task_id}', {'title': 'Новое'}, format='json')
    assert resp.status_code == 200
    assert resp.json()['title'] == 'Новое'


@pytest.mark.django_db
def test_manager_cannot_delete(manager_client, board):
    b, _ = board
    task_id = manager_client.post(
        BASE, {'board_id': b.id, 'title': 'Х'}, format='json').json()['id']
    assert manager_client.delete(f'{BASE}/{task_id}').status_code == 403


@pytest.mark.django_db
def test_admin_deletes(admin_client, board):
    b, _ = board
    task_id = admin_client.post(
        BASE, {'board_id': b.id, 'title': 'Х'}, format='json').json()['id']
    assert admin_client.delete(f'{BASE}/{task_id}').status_code == 204
    assert admin_client.get(f'{BASE}/{task_id}').status_code == 404
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_api_tasks.py -v
```

Ожидаемо: все падают с 404 (маршрут не смонтирован).

- [ ] **Шаг 3: Написать вьюхи**

Создать `journal_django/apps/taskboard/views.py`:

```python
"""
Вьюхи раздела «Задачи».

DRF по умолчанию AllowAny — permission_classes задан ЯВНО в каждом классе.
Карточки: manager/admin. Структура (воронки, стадии, справочники): только
superadmin на запись. Физическое удаление задачи: admin/superadmin.
"""
from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdminOrSuperAdmin, IsManagerOrAdmin
from apps.taskboard import repository, services
from apps.taskboard.models import Task
from apps.taskboard.serializers import TaskCreateSerializer, TaskPatchSerializer


class TaskPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


def _paginated(request: Request, queryset) -> Response:
    """Режем в БД: LIMIT/OFFSET на queryset, в словари превращаем только страницу."""
    paginator = TaskPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(repository.rows(page))


def _filters_from(request: Request) -> dict:
    q = request.query_params
    return {
        'board_id': q.get('board_id'),
        'stage_id': q.get('stage_id'),
        'assignee_id': q.get('assignee_id'),
        'student_id': q.get('student_id'),
        'group_id': q.get('group_id'),
        'priority': q.get('priority'),
        'task_type_id': q.get('task_type_id'),
        'tag_id': q.get('tag_id'),
        'only_open': q.get('only_open') == 'true',
        'overdue': q.get('overdue') == 'true',
        'q': q.get('q'),
    }


class TaskCollectionView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        return _paginated(request, repository.tasks_queryset(_filters_from(request)))

    def post(self, request: Request) -> Response:
        serializer = TaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        tag_ids = data.pop('tag_ids', None)
        task = services.create_task(author_id=request.user.id, tag_ids=tag_ids, **data)
        return Response(repository.get_task(task.id), status=201)


class TaskDetailView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get_permissions(self):
        # Штатный способ убрать задачу — закрыть с результатом «неактуально».
        # Физическое удаление — только для явного мусора, роль admin/superadmin.
        if self.request.method == 'DELETE':
            return [IsAdminOrSuperAdmin()]
        return [IsManagerOrAdmin()]

    def get(self, request: Request, pk: int) -> Response:
        get_object_or_404(Task, pk=pk)
        return Response(repository.get_task(pk))

    def patch(self, request: Request, pk: int) -> Response:
        task = get_object_or_404(Task, pk=pk)
        serializer = TaskPatchSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        tag_ids = fields.pop('tag_ids', None)
        # Правка полей и смена тегов — ОДНА транзакция. Иначе при падении тегов
        # на валидации клиент получит 400, а изменённый заголовок уже сохранится.
        with transaction.atomic():
            services.update_task(task, author_id=request.user.id, fields=fields)
            if tag_ids is not None:
                services.set_tags(task, tag_ids=tag_ids, author_id=request.user.id)
        return Response(repository.get_task(pk))

    def delete(self, request: Request, pk: int) -> Response:
        # Лента уходит каскадом (TaskActivity.task = CASCADE), связи с тегами
        # Django чистит сам — ручная зачистка была бы лишними запросами.
        get_object_or_404(Task, pk=pk).delete()
        return Response(status=204)
```

Создать `journal_django/apps/taskboard/urls.py`:

```python
"""Маршруты taskboard. APPEND_SLASH=False — без trailing slash."""
from django.urls import path

from apps.taskboard.views import TaskCollectionView, TaskDetailView

urlpatterns = [
    path('', TaskCollectionView.as_view(), name='tasks-collection'),
    # Литеральные пути добавятся в задачах 12–15 и ОБЯЗАНЫ стоять выше /<int:pk>.
    path('/<int:pk>', TaskDetailView.as_view(), name='tasks-detail'),
]
```

В `journal_django/config/urls.py` добавить рядом с маршрутом продлений:

```python
    # Задачи — воронки/стадии/карточки (спека 2026-08-24, role=manager/admin)
    path('api/admin/tasks', include('apps.taskboard.urls')),
```

- [ ] **Шаг 4: Запустить тесты**

```
cd journal_django && pytest apps/taskboard/tests/test_api_tasks.py -v
```

Ожидаемо: `6 passed`.

- [ ] **Шаг 5: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard journal_django/config/urls.py
git commit -m "feat(tasks): API коллекции и детали карточки"
```

---

## Задача 12: API переноса, закрытия, комментариев и ленты

**Файлы:**
- Изменить: `journal_django/apps/taskboard/views.py` (дописать)
- Изменить: `journal_django/apps/taskboard/urls.py`
- Создать: `journal_django/apps/taskboard/tests/test_api_move.py`

- [ ] **Шаг 1: Написать падающие тесты**

Создать `journal_django/apps/taskboard/tests/test_api_move.py`:

```python
"""API переноса, закрытия, комментариев."""
import pytest

BASE = '/api/admin/tasks'


@pytest.mark.django_db
def test_move_to_closed_without_resolution_is_400(manager_client, board):
    b, stages = board
    task_id = manager_client.post(
        BASE, {'board_id': b.id, 'title': 'Х'}, format='json').json()['id']
    resp = manager_client.post(
        f'{BASE}/{task_id}/move', {'to_stage_id': stages['done'].id}, format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_move_to_closed_with_resolution_succeeds(manager_client, board):
    b, stages = board
    task_id = manager_client.post(
        BASE, {'board_id': b.id, 'title': 'Х'}, format='json').json()['id']
    resp = manager_client.post(
        f'{BASE}/{task_id}/move',
        {'to_stage_id': stages['done'].id, 'resolution': 'done'}, format='json')
    assert resp.status_code == 200
    assert resp.json()['is_closed'] is True


@pytest.mark.django_db
def test_complete_closes_task(manager_client, board):
    b, stages = board
    task_id = manager_client.post(
        BASE, {'board_id': b.id, 'title': 'Х'}, format='json').json()['id']
    resp = manager_client.post(f'{BASE}/{task_id}/complete', {}, format='json')
    assert resp.status_code == 200
    body = resp.json()
    assert body['is_closed'] is True
    assert body['stage_id'] == stages['done'].id
    assert body['resolution'] == 'done'


@pytest.mark.django_db
def test_comment_appears_in_activity(manager_client, board):
    b, _ = board
    task_id = manager_client.post(
        BASE, {'board_id': b.id, 'title': 'Х'}, format='json').json()['id']
    assert manager_client.post(
        f'{BASE}/{task_id}/comment', {'body': 'Не берёт трубку'},
        format='json').status_code == 201

    activity = manager_client.get(f'{BASE}/{task_id}/activity').json()
    comments = [a for a in activity if a['kind'] == 'comment']
    assert len(comments) == 1
    assert comments[0]['text'] == 'Не берёт трубку'


@pytest.mark.django_db
def test_teacher_cannot_move(teacher_client, board):
    b, stages = board
    resp = teacher_client.post(
        f'{BASE}/1/move', {'to_stage_id': stages['work'].id}, format='json')
    assert resp.status_code == 403
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_api_move.py -v
```

Ожидаемо: 404 на всех маршрутах `/move`, `/complete`, `/comment`, `/activity`.

- [ ] **Шаг 3: Дописать вьюхи**

Дописать в конец `journal_django/apps/taskboard/views.py`:

```python
class TaskMoveView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        from apps.taskboard.serializers import MoveSerializer

        task = get_object_or_404(Task, pk=pk)
        serializer = MoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.move_task(
            task,
            to_stage_id=serializer.validated_data['to_stage_id'],
            resolution=serializer.validated_data.get('resolution'),
            author_id=request.user.id,
        )
        return Response(repository.get_task(pk))


class TaskCompleteView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        from apps.taskboard.serializers import CompleteSerializer

        task = get_object_or_404(Task, pk=pk)
        serializer = CompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.complete_task(
            task,
            resolution=serializer.validated_data['resolution'],
            author_id=request.user.id,
        )
        return Response(repository.get_task(pk))


class TaskCommentView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request: Request, pk: int) -> Response:
        from apps.taskboard.serializers import CommentSerializer

        task = get_object_or_404(Task, pk=pk)
        serializer = CommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_comment(
            task, body=serializer.validated_data['body'], author_id=request.user.id)
        return Response({'ok': True}, status=201)


class TaskActivityView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, pk: int) -> Response:
        get_object_or_404(Task, pk=pk)
        return Response(repository.list_activity(pk))
```

В `journal_django/apps/taskboard/urls.py` добавить импорты и маршруты
**после** `/<int:pk>`:

```python
    path('/<int:pk>/move', TaskMoveView.as_view(), name='tasks-move'),
    path('/<int:pk>/complete', TaskCompleteView.as_view(), name='tasks-complete'),
    path('/<int:pk>/comment', TaskCommentView.as_view(), name='tasks-comment'),
    path('/<int:pk>/activity', TaskActivityView.as_view(), name='tasks-activity'),
```

- [ ] **Шаг 4: Запустить тесты**

```
cd journal_django && pytest apps/taskboard/tests/test_api_move.py -v
```

Ожидаемо: `5 passed`.

- [ ] **Шаг 5: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard
git commit -m "feat(tasks): API переноса, закрытия, комментариев и ленты"
```

---

## Задача 13: API колонок и недельного вида

**Файлы:**
- Изменить: `journal_django/apps/taskboard/views.py` (дописать)
- Изменить: `journal_django/apps/taskboard/urls.py`
- Изменить: `journal_django/apps/taskboard/repository.py` (дописать `column_counts`)
- Создать: `journal_django/apps/taskboard/tests/test_api_views.py`

- [ ] **Шаг 1: Написать падающие тесты**

Создать `journal_django/apps/taskboard/tests/test_api_views.py`:

```python
"""API доски (колонки со счётчиками) и недельного вида."""
import datetime

import pytest

BASE = '/api/admin/tasks'


@pytest.mark.django_db
def test_column_counts_by_stage(manager_client, board):
    b, stages = board
    for i in range(3):
        manager_client.post(BASE, {'board_id': b.id, 'title': f'Т{i}'}, format='json')

    resp = manager_client.get(f'{BASE}/boards/{b.id}/columns')
    assert resp.status_code == 200
    counts = {c['stage_id']: c['count'] for c in resp.json()}
    assert counts[stages['new'].id] == 3
    assert counts[stages['work'].id] == 0


@pytest.mark.django_db
def test_column_cards_are_paginated(manager_client, board):
    b, stages = board
    manager_client.post(BASE, {'board_id': b.id, 'title': 'Одна'}, format='json')
    resp = manager_client.get(f'{BASE}/columns/{stages["new"].id}')
    assert resp.status_code == 200
    assert 'results' in resp.json()
    assert resp.json()['count'] == 1


@pytest.mark.django_db
def test_week_requires_valid_range(manager_client):
    resp = manager_client.get(f'{BASE}/week?date_from=2026-09-10&date_to=2026-09-01')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_week_returns_dated_tasks(manager_client, board):
    b, _ = board
    today = datetime.date.today().isoformat()
    manager_client.post(
        BASE, {'board_id': b.id, 'title': 'Сегодня', 'due_date': today}, format='json')
    manager_client.post(BASE, {'board_id': b.id, 'title': 'Без даты'}, format='json')

    resp = manager_client.get(f'{BASE}/week?date_from={today}&date_to={today}')
    assert resp.status_code == 200
    titles = [t['title'] for t in resp.json()]
    assert 'Сегодня' in titles
    assert 'Без даты' not in titles
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_api_views.py -v
```

Ожидаемо: 404 на `/boards/<id>/columns`, `/columns/<id>`, `/week`.

- [ ] **Шаг 3: Дописать репозиторий**

Дописать в конец `journal_django/apps/taskboard/repository.py`:

```python
def column_counts(board_id: int) -> list[dict]:
    """
    Колонки доски со счётчиками — ОДИН лёгкий агрегат.

    Карточки колонок сюда НЕ входят: доска не грузится одним запросом, иначе
    воронка с тысячей закрытых задач кладёт страницу.
    """
    from django.db.models import Count

    from apps.taskboard.models import TaskStage

    stages = (TaskStage.objects
              .filter(board_id=board_id)
              .annotate(task_count=Count('tasks'))
              .order_by('sort_order'))
    return [{
        'stage_id': s.id,
        'label': s.label,
        'color': s.color,
        'category': s.category,
        'sort_order': s.sort_order,
        'count': s.task_count,
    } for s in stages]
```

- [ ] **Шаг 4: Дописать вьюхи**

Дописать в конец `journal_django/apps/taskboard/views.py`:

```python
class BoardColumnsView(APIView):
    """Колонки доски со счётчиками — без карточек."""
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, board_id: int) -> Response:
        return Response(repository.column_counts(board_id))


class ColumnCardsView(APIView):
    """Карточки одной колонки, пагинированно."""
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request, stage_id: int) -> Response:
        return _paginated(request, repository.tasks_queryset({'stage_id': stage_id}))


class WeekView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        from apps.taskboard.serializers import WeekQuerySerializer

        serializer = WeekQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return Response(repository.list_week(
            date_from=serializer.validated_data['date_from'],
            date_to=serializer.validated_data['date_to'],
        ))
```

В `journal_django/apps/taskboard/urls.py` добавить маршруты **выше** `/<int:pk>`:

```python
    path('/week', WeekView.as_view(), name='tasks-week'),
    path('/columns/<int:stage_id>', ColumnCardsView.as_view(), name='tasks-column-cards'),
    path('/boards/<int:board_id>/columns', BoardColumnsView.as_view(), name='tasks-board-columns'),
```

- [ ] **Шаг 5: Запустить тесты**

```
cd journal_django && pytest apps/taskboard/tests/test_api_views.py -v
```

Ожидаемо: `4 passed`.

- [ ] **Шаг 6: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard
git commit -m "feat(tasks): API колонок доски и недельного вида"
```

---

## Задача 14: API воронок

> **Грабля, найденная при реализации.** Перехват `IntegrityError` вокруг
> `Model.objects.create(...)` / `instance.save()` ОБЯЗАН быть обёрнут в
> `with transaction.atomic():` внутри `try`. Иначе необработанное нарушение
> ограничения ломает текущую транзакцию целиком, и следующий же запрос падает
> с `TransactionManagementError: You can't execute queries until the end of the
> 'atomic' block`. В тестах это проявляется падением teardown фикстур, в бою —
> развалом обработчика после первой же попытки завести дубль. Приём уже принят
> в проекте: см. `apps/groups/repository.py`. Касается всех шести мест ниже,
> где ловится `IntegrityError`.


**Файлы:**
- Изменить: `journal_django/apps/taskboard/views.py`, `urls.py`
- Создать: `journal_django/apps/taskboard/tests/test_api_boards.py`

- [ ] **Шаг 1: Написать падающие тесты**

Создать `journal_django/apps/taskboard/tests/test_api_boards.py`:

```python
"""API воронок: чтение — staff, запись — только superadmin."""
import pytest

BASE = '/api/admin/tasks/boards'


@pytest.mark.django_db
def test_manager_reads_boards(manager_client):
    assert manager_client.get(BASE).status_code == 200


@pytest.mark.django_db
def test_manager_cannot_create_board(manager_client):
    assert manager_client.post(BASE, {'name': 'Своя'}, format='json').status_code == 403


@pytest.mark.django_db
def test_superadmin_creates_renames_and_deletes(superadmin_client):
    created = superadmin_client.post(
        BASE, {'name': '__tb_api_board__', 'description': 'Проверка'}, format='json')
    assert created.status_code == 201
    board_id = created.json()['id']

    renamed = superadmin_client.patch(
        f'{BASE}/{board_id}', {'name': '__tb_api_board_2__'}, format='json')
    assert renamed.status_code == 200
    assert renamed.json()['name'] == '__tb_api_board_2__'

    assert superadmin_client.delete(f'{BASE}/{board_id}').status_code == 204


@pytest.mark.django_db
def test_board_with_tasks_cannot_be_deleted(superadmin_client, board):
    """Воронку с задачами удалить нельзя → 409, не 500."""
    b, _ = board
    superadmin_client.post(
        '/api/admin/tasks', {'board_id': b.id, 'title': 'Держит воронку'}, format='json')
    resp = superadmin_client.delete(f'{BASE}/{b.id}')
    assert resp.status_code == 409
    assert resp.json()['error'] == 'has_tasks'


@pytest.mark.django_db
def test_duplicate_board_name_is_409(superadmin_client, board):
    b, _ = board
    resp = superadmin_client.post(BASE, {'name': b.name}, format='json')
    assert resp.status_code == 409
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_api_boards.py -v
```

Ожидаемо: 404 на `/boards`.

- [ ] **Шаг 3: Дописать вьюхи**

Сначала дополнить блок импортов **вверху** `journal_django/apps/taskboard/views.py`:

```python
from django.db import IntegrityError

from apps.core.permissions import IsAdminOrSuperAdmin, IsManagerOrAdmin, ReadStaffWriteSuperAdmin
from apps.taskboard.models import Task, TaskBoard, TaskStage, TaskTag, TaskType
```

Затем дописать в конец файла:

```python
def _board_row(b: TaskBoard) -> dict:
    return {
        'id': b.id,
        'name': b.name,
        'description': b.description,
        'sort_order': b.sort_order,
        'is_archived': b.is_archived,
    }


class BoardCollectionView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def get(self, request: Request) -> Response:
        boards = TaskBoard.objects.order_by('sort_order', 'id')
        return Response([_board_row(b) for b in boards])

    def post(self, request: Request) -> Response:
        from apps.taskboard.serializers import BoardWriteSerializer

        serializer = BoardWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            board = TaskBoard.objects.create(**serializer.validated_data)
        except IntegrityError:
            return Response({'error': 'duplicate_name'}, status=409)
        return Response(_board_row(board), status=201)


class BoardDetailView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def patch(self, request: Request, pk: int) -> Response:
        from apps.taskboard.serializers import BoardWriteSerializer

        board = get_object_or_404(TaskBoard, pk=pk)
        serializer = BoardWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for key, value in serializer.validated_data.items():
            setattr(board, key, value)
        try:
            board.save()
        except IntegrityError:
            return Response({'error': 'duplicate_name'}, status=409)
        return Response(_board_row(board))

    def delete(self, request: Request, pk: int) -> Response:
        board = get_object_or_404(TaskBoard, pk=pk)
        # Стадии удалились бы каскадом, но задачи держат стадию через RESTRICT —
        # на уровне БД это упало бы ошибкой FK. Проверяем заранее и отдаём 409.
        if Task.objects.filter(board=board).exists():
            return Response({'error': 'has_tasks'}, status=409)
        board.stages.all().delete()
        board.delete()
        return Response(status=204)
```

В `journal_django/apps/taskboard/urls.py` добавить **выше** `/<int:pk>`:

```python
    path('/boards', BoardCollectionView.as_view(), name='tasks-boards'),
    path('/boards/<int:pk>', BoardDetailView.as_view(), name='tasks-board-detail'),
```

Маршрут `/boards/<int:board_id>/columns` из задачи 13 должен стоять
**выше** `/boards/<int:pk>` — иначе `columns` не разберётся.

- [ ] **Шаг 4: Запустить тесты**

```
cd journal_django && pytest apps/taskboard/tests/test_api_boards.py -v
```

Ожидаемо: `5 passed`.

- [ ] **Шаг 5: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard
git commit -m "feat(tasks): API воронок"
```

---

## Задача 15: API стадий и справочников

**Файлы:**
- Изменить: `journal_django/apps/taskboard/views.py`, `urls.py`
- Изменить: `journal_django/apps/taskboard/services.py` (валидация удаления стадии)
- Создать: `journal_django/apps/taskboard/tests/test_api_stages.py`

- [ ] **Шаг 1: Написать падающие тесты**

Создать `journal_django/apps/taskboard/tests/test_api_stages.py`:

```python
"""API стадий: порядок, категории, защита от удаления последней стадии категории."""
import pytest

BASE = '/api/admin/tasks'


@pytest.mark.django_db
def test_manager_reads_stages(manager_client, board):
    b, _ = board
    assert manager_client.get(f'{BASE}/boards/{b.id}/stages').status_code == 200


@pytest.mark.django_db
def test_manager_cannot_create_stage(manager_client, board):
    b, _ = board
    resp = manager_client.post(
        f'{BASE}/boards/{b.id}/stages',
        {'label': 'Своя', 'category': 'open'}, format='json')
    assert resp.status_code == 403


@pytest.mark.django_db
def test_superadmin_creates_stage(superadmin_client, board):
    b, _ = board
    resp = superadmin_client.post(
        f'{BASE}/boards/{b.id}/stages',
        {'label': 'Ждём ответа', 'category': 'open', 'color': '#AABBCC'}, format='json')
    assert resp.status_code == 201
    assert resp.json()['label'] == 'Ждём ответа'


@pytest.mark.django_db
def test_duplicate_stage_label_is_409(superadmin_client, board):
    b, _ = board
    resp = superadmin_client.post(
        f'{BASE}/boards/{b.id}/stages',
        {'label': 'Новая', 'category': 'open'}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_cannot_delete_last_closed_stage(superadmin_client, board):
    """В воронке обязана остаться минимум одна стадия каждой категории."""
    b, stages = board
    resp = superadmin_client.delete(f'{BASE}/stages/{stages["done"].id}')
    assert resp.status_code == 409
    assert resp.json()['error'] == 'last_stage_of_category'


@pytest.mark.django_db
def test_cannot_delete_stage_with_tasks(superadmin_client, board):
    b, stages = board
    superadmin_client.post(
        BASE, {'board_id': b.id, 'title': 'Держит стадию'}, format='json')
    resp = superadmin_client.delete(f'{BASE}/stages/{stages["new"].id}')
    assert resp.status_code == 409
    assert resp.json()['error'] == 'has_tasks'


@pytest.mark.django_db
def test_reorder_changes_sort_order(superadmin_client, board):
    b, stages = board
    order = [stages['work'].id, stages['new'].id, stages['done'].id]
    resp = superadmin_client.post(f'{BASE}/stages/reorder', {'order': order}, format='json')
    assert resp.status_code == 200
    assert [s['id'] for s in resp.json()] == order
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

```
cd journal_django && pytest apps/taskboard/tests/test_api_stages.py -v
```

Ожидаемо: 404 на маршрутах стадий.

- [ ] **Шаг 3: Дописать сервис валидации**

Дописать в конец `journal_django/apps/taskboard/services.py`:

```python
def stage_delete_blocker(stage: TaskStage) -> str | None:
    """
    Почему стадию нельзя удалить, или None если можно.

    'has_tasks'               — на стадии висят задачи (FK RESTRICT);
    'last_stage_of_category'  — это последняя открытая или последняя закрытая
                                стадия воронки, без неё воронка сломается.
    """
    if Task.objects.filter(stage=stage).exists():
        return 'has_tasks'
    siblings = (TaskStage.objects
                .filter(board_id=stage.board_id, category=stage.category)
                .exclude(id=stage.id)
                .count())
    if siblings == 0:
        return 'last_stage_of_category'
    return None
```

- [ ] **Шаг 4: Дописать вьюхи**

Дописать в конец `journal_django/apps/taskboard/views.py`
(импорты `TaskStage`, `TaskTag`, `TaskType` добавлены в задаче 14):

```python
def _stage_row(s) -> dict:
    return {
        'id': s.id, 'board_id': s.board_id, 'label': s.label,
        'color': s.color, 'category': s.category, 'sort_order': s.sort_order,
    }


class StageCollectionView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def get(self, request: Request, board_id: int) -> Response:
        stages = TaskStage.objects.filter(board_id=board_id).order_by('sort_order')
        return Response([_stage_row(s) for s in stages])

    def post(self, request: Request, board_id: int) -> Response:
        from apps.taskboard.serializers import StageWriteSerializer

        get_object_or_404(TaskBoard, pk=board_id)
        serializer = StageWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        last = (TaskStage.objects.filter(board_id=board_id)
                .order_by('-sort_order').values_list('sort_order', flat=True).first())
        try:
            stage = TaskStage.objects.create(
                board_id=board_id, sort_order=(last or 0) + 1, **serializer.validated_data)
        except IntegrityError:
            return Response({'error': 'duplicate_label'}, status=409)
        return Response(_stage_row(stage), status=201)


class StageDetailView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def patch(self, request: Request, pk: int) -> Response:
        from apps.taskboard.serializers import StageWriteSerializer

        stage = get_object_or_404(TaskStage, pk=pk)
        serializer = StageWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for key, value in serializer.validated_data.items():
            setattr(stage, key, value)
        try:
            stage.save()
        except IntegrityError:
            return Response({'error': 'duplicate_label'}, status=409)
        return Response(_stage_row(stage))

    def delete(self, request: Request, pk: int) -> Response:
        stage = get_object_or_404(TaskStage, pk=pk)
        blocker = services.stage_delete_blocker(stage)
        if blocker:
            return Response({'error': blocker}, status=409)
        stage.delete()
        return Response(status=204)


class StageReorderView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def post(self, request: Request) -> Response:
        from apps.taskboard.serializers import StageReorderSerializer

        serializer = StageReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.validated_data['order']
        stages = {s.id: s for s in TaskStage.objects.filter(id__in=order)}
        if len(stages) != len(order):
            return Response({'error': 'unknown_stage'}, status=400)
        for position, stage_id in enumerate(order):
            stage = stages[stage_id]
            stage.sort_order = position
            stage.save(update_fields=['sort_order'])
        refreshed = TaskStage.objects.filter(id__in=order).order_by('sort_order')
        return Response([_stage_row(s) for s in refreshed])


class TagListView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def get(self, request: Request) -> Response:
        tags = TaskTag.objects.order_by('label')
        return Response([{'id': t.id, 'label': t.label, 'color': t.color} for t in tags])

    def post(self, request: Request) -> Response:
        label = (request.data.get('label') or '').strip()
        if not label:
            return Response({'label': 'Укажите название тега'}, status=400)
        try:
            tag = TaskTag.objects.create(label=label, color=request.data.get('color'))
        except IntegrityError:
            return Response({'error': 'duplicate_label'}, status=409)
        return Response({'id': tag.id, 'label': tag.label, 'color': tag.color}, status=201)


class TypeListView(APIView):
    permission_classes = [ReadStaffWriteSuperAdmin]

    def get(self, request: Request) -> Response:
        types = TaskType.objects.order_by('sort_order', 'label')
        return Response([{'id': t.id, 'label': t.label} for t in types])

    def post(self, request: Request) -> Response:
        label = (request.data.get('label') or '').strip()
        if not label:
            return Response({'label': 'Укажите название типа'}, status=400)
        try:
            task_type = TaskType.objects.create(label=label)
        except IntegrityError:
            return Response({'error': 'duplicate_label'}, status=409)
        return Response({'id': task_type.id, 'label': task_type.label}, status=201)
```

В `journal_django/apps/taskboard/urls.py` добавить **выше** `/<int:pk>`:

```python
    path('/tags', TagListView.as_view(), name='tasks-tags'),
    path('/types', TypeListView.as_view(), name='tasks-types'),
    path('/stages/reorder', StageReorderView.as_view(), name='tasks-stages-reorder'),
    path('/stages/<int:pk>', StageDetailView.as_view(), name='tasks-stage-detail'),
    path('/boards/<int:board_id>/stages', StageCollectionView.as_view(), name='tasks-stages'),
```

`/stages/reorder` обязан стоять выше `/stages/<int:pk>` — иначе `reorder`
попытается разобраться как число.

- [ ] **Шаг 5: Запустить тесты**

```
cd journal_django && pytest apps/taskboard/tests/test_api_stages.py -v
```

Ожидаемо: `7 passed`.

- [ ] **Шаг 6: Коммит** (только если пользователь разрешил)

```bash
git add journal_django/apps/taskboard
git commit -m "feat(tasks): API стадий, тегов и типов"
```

---

## Задача 16: Финальная проверка бэкенда

**Файлы:** изменений кода не предполагается — только проверки и, при находках, точечные правки.

- [ ] **Шаг 1: Полный прогон тестов**

```
cd journal_django && pytest -q
```

Ожидаемо: все тесты проекта зелёные. **Прогон по приложениям не годится** —
часть приложений no-op'ит `django_db_setup`, часть пересоздаёт `test_journal_test`.

- [ ] **Шаг 2: Проверить, что миграции не разъехались**

```
cd journal_django && python manage.py makemigrations --check --dry-run
```

Ожидаемо: `No changes detected`.

- [ ] **Шаг 3: Проверить, что ни одна вьюха не осталась без прав**

```
cd journal_django && grep -c "permission_classes" apps/taskboard/views.py
cd journal_django && grep -c "^class .*View(APIView)" apps/taskboard/views.py
```

Ожидаемо: **оба числа совпадают**. Если вьюх больше — какая-то осталась
открытой всем, это блокер.

- [ ] **Шаг 4: Проверить порядок маршрутов**

```
cd journal_django && python manage.py shell -c "from django.urls import resolve; print(resolve('/api/admin/tasks/stages/reorder').url_name); print(resolve('/api/admin/tasks/week').url_name); print(resolve('/api/admin/tasks/boards/1/columns').url_name)"
```

Ожидаемо: `tasks-stages-reorder`, `tasks-week`, `tasks-board-columns`.
Если что-то разобралось как `tasks-detail` — литеральный путь стоит ниже
`/<int:pk>` и его надо поднять.

- [ ] **Шаг 5: Проверить журнал изменений вживую**

```
cd journal_django && pytest apps/changelog -v
```

Ожидаемо: зелено, включая `test_registry_covers_all_tracked_models`.

- [ ] **Шаг 6: Коммит** (только если пользователь разрешил)

```bash
git add journal_django
git commit -m "test(tasks): финальная проверка бэкенда раздела задач"
```

---

## Что дальше

После зелёного полного прогона бэкенд готов и проверяем через API без интерфейса.
План этапов 4–5 (фронтенд: доска, панель справа, настройки воронок, вид «Неделя»,
блок на странице ученика) пишется отдельно — против уже существующих ручек,
а не против воображаемых.
