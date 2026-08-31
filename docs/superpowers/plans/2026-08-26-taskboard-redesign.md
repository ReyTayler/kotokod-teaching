# Переработка раздела «Задачи» — план реализации

> **Для агентов-исполнителей:** реализовывать по одной задаче за раз через
> `superpowers:subagent-driven-development` или `superpowers:executing-plans`.
> Шаги помечены чекбоксами (`- [ ]`).

**Цель:** превратить раздел «Задачи» из формы с параметрами в рабочее пространство —
компактная шапка, живая карточка, панель-карточка вместо длинной формы, отмена действий,
и общая цветная шапка стадии для всех досок системы.

**Архитектура:** бэкенд правится точечно (поиск, фильтр срока, записи в ленту,
счётчик комментариев) без миграций. Фронтенд: новый общий компонент шапки колонки
на две доски, перестроенная верхняя панель `TasksPage`, переработанные `TaskCard` и
`TaskDrawer`, расширенный `Toast` с отменой.

**Стек:** Django 5 + DRF + PostgreSQL, pytest; React 19 + TanStack Query v5 +
React Router v7 + `@dnd-kit` + Radix UI, Vite.

**Спека:** [`docs/superpowers/specs/2026-08-26-taskboard-redesign-design.md`](../specs/2026-08-26-taskboard-redesign-design.md)

---

## Правила исполнения

**Коммитов в шагах нет намеренно.** По `CLAUDE.md` коммитить и пушить можно только по явной
просьбе заказчика, а рабочее дерево сейчас содержит чужой WIP — `git add` затянул бы лишнее.
Вместо коммита каждая задача заканчивается прогоном проверки. Коммит — отдельным решением
в конце, руками.

**Бэкенд-тесты гонять полным прогоном.** Часть приложений no-op'ит `django_db_setup`
(общая `journal_test`), часть пересоздаёт `test_journal_test`. Прогон по одному файлу годится
только внутри цикла TDD; перед сдачей задачи — `pytest -q` целиком из `journal_django/`.

**Фронтенд-тестов в проекте нет.** Проверка фронтовых задач — `npm run typecheck` из
`journal_django/frontend/admin-src` плюс глазами в браузере. `npm run build` **не запускать**:
он перезаписывает `../admin-dist`, и сборочный мусор попадёт в диф.

**Правила проекта, которые легко нарушить в этих задачах:**
- нативные `<input>/<select>` в admin SPA запрещены — только `components/form/*`;
- цвета, радиусы, отступы — только токены из `styles/tokens.css`; единственное исключение —
  цвет стадии, приходящий с бэка;
- подписи enum'ов — только из `lib/labels.ts`;
- каждая новая вьюха DRF обязана задать `permission_classes` (здесь новых вьюх нет).

---

## Карта файлов

**Бэкенд** (`journal_django/apps/taskboard/`)

| Файл | Что делает после правок |
|---|---|
| `repository.py` | + умный поиск `q`, + фильтр `due`, + `comments_count` подзапросом, + `_needs_distinct` |
| `serializers.py` | + поле `due` в `TaskFilterSerializer` |
| `services.py` | `update_task` пишет в ленту все правки, не только смену исполнителя |
| `tests/test_repository.py` | + тесты поиска, `due`, `comments_count` |
| `tests/test_services_update.py` | + тесты записей в ленту |

**Фронтенд** (`journal_django/frontend/admin-src/src/`)

| Файл | Что делает |
|---|---|
| `lib/stage-tone.ts` | **создать** — цвет заливки стадии и читаемый цвет текста на нём |
| `components/board/BoardColumnHead.tsx` | **создать** — общая цветная шапка колонки |
| `components/ui/Toast.tsx` | + действие в toast'е, + настраиваемое время жизни |
| `pages/tasks/TaskBoardTabs.tsx` | **создать** — табы воронок с переполнением в «Ещё» |
| `pages/tasks/TaskSegments.tsx` | **создать** — «Все / Мои / Сегодня / Просроченные» |
| `pages/tasks/TaskFiltersPopover.tsx` | **создать** — свёрнутые фильтры |
| `pages/tasks/TaskCreateModal.tsx` | **создать** — полная форма создания задачи |
| `pages/tasks/InlineEdit.tsx` | **создать** — значение текстом → контрол по клику |
| `pages/tasks/TasksPage.tsx` | перестроенная шапка из двух рядов |
| `pages/tasks/TaskCard.tsx` | плотная карточка, hover-действия, `compact` |
| `pages/tasks/TaskColumn.tsx` | общая шапка, быстрое добавление внизу |
| `pages/tasks/TaskBoard.tsx` | закрытие перетаскиванием + toast с отменой |
| `pages/tasks/TaskDrawer.tsx` | карточка просмотра: контекст / свойства / описание / комментарии / история |
| `pages/tasks/TaskWeekView.tsx` | плотнее, «Сегодня» всегда, мягкая подсветка дня |
| `pages/renewals/RenewalColumn.tsx` | переезд на общую шапку колонки |
| `styles/components.css` | + блок `.board-col-head*` |
| `styles/pages/tasks.css` | плотность, новые блоки, снятие `border-top` |
| `styles/pages/renewals.css` | снятие `border-top`, подгонка под плашку |
| `lib/tasks.ts` | + `comments_count`, + `due` в `TaskFilters` |

---

## Задача 1: умный поиск по задачам

**Файлы:**
- Изменить: `journal_django/apps/taskboard/repository.py`
- Тест: `journal_django/apps/taskboard/tests/test_repository.py`

- [ ] **Шаг 1: написать падающие тесты**

Добавить в конец `tests/test_repository.py`:

```python
@pytest.mark.django_db
def test_search_by_hash_id(board):
    """`#124` ищет по номеру задачи, а не по тексту заголовка."""
    b, _ = board
    target = services.create_task(board_id=b.id, title='Первая', author_id=None)
    services.create_task(board_id=b.id, title='Вторая', author_id=None)

    ids = [t['id'] for t in repository.list_tasks({'board_id': b.id, 'q': f'#{target.id}'})]
    assert ids == [target.id]


@pytest.mark.django_db
def test_search_by_bare_number(board):
    """Номер без решётки работает так же — люди её не набирают."""
    b, _ = board
    target = services.create_task(board_id=b.id, title='Первая', author_id=None)

    ids = [t['id'] for t in repository.list_tasks({'board_id': b.id, 'q': str(target.id)})]
    assert ids == [target.id]


@pytest.mark.django_db
def test_search_by_student_name(board):
    from apps.students.models import Student

    b, _ = board
    student = Student.objects.create(full_name='__tb_Абдульманов Амир__')
    try:
        target = services.create_task(
            board_id=b.id, title='Позвонить', author_id=None, student_id=student.id)
        services.create_task(board_id=b.id, title='Другая', author_id=None)

        ids = [t['id'] for t in repository.list_tasks({'board_id': b.id, 'q': 'Абдульманов'})]
        assert ids == [target.id]
    finally:
        Task.objects.filter(student=student).update(student=None)
        student.delete()


@pytest.mark.django_db
def test_search_by_assignee_name(board, admin_account_id):
    b, _ = board
    target = services.create_task(
        board_id=b.id, title='Позвонить', author_id=None, assignee_id=admin_account_id)
    services.create_task(board_id=b.id, title='Другая', author_id=None)

    ids = [t['id'] for t in repository.list_tasks({'board_id': b.id, 'q': 'Тестовый'})]
    assert ids == [target.id]


@pytest.mark.django_db
def test_search_by_tag_label_without_duplicates(board):
    """Две подходящие метки на одной задаче не должны раздвоить строку выдачи."""
    from apps.taskboard.models import TaskTag

    b, _ = board
    first = TaskTag.objects.create(label='__tb_Python-основы__')
    second = TaskTag.objects.create(label='__tb_Python-продвинутый__')
    try:
        target = services.create_task(
            board_id=b.id, title='Проверить', author_id=None,
            tag_ids=[first.id, second.id])

        ids = [t['id'] for t in repository.list_tasks({'board_id': b.id, 'q': '__tb_Python'})]
        assert ids == [target.id]
    finally:
        # Удаление метки уносит и строки связи task_tag_link — чистить их руками не нужно.
        first.delete()
        second.delete()


@pytest.mark.django_db
def test_column_counts_match_search_results(board):
    """Счётчик колонки не должен врать относительно списка под ней."""
    from apps.taskboard.models import TaskTag

    b, stages = board
    first = TaskTag.objects.create(label='__tb_счёт-один__')
    second = TaskTag.objects.create(label='__tb_счёт-два__')
    try:
        services.create_task(
            board_id=b.id, title='Считаемая', author_id=None,
            stage_id=stages['new'].id, tag_ids=[first.id, second.id])

        params = {'board_id': b.id, 'q': '__tb_счёт'}
        counts = {c['stage_id']: c['count'] for c in repository.column_counts(b.id, params)}
        listed = repository.list_tasks({**params, 'stage_id': stages['new'].id})
        assert counts[stages['new'].id] == len(listed) == 1
    finally:
        first.delete()
        second.delete()
```

В шапку файла добавить импорт модели:

```python
from apps.taskboard.models import Task
```

- [ ] **Шаг 2: убедиться, что тесты падают**

Запустить: `cd journal_django && pytest apps/taskboard/tests/test_repository.py -q -k "search or column_counts_match"`
Ожидаемо: FAIL — поиск по `#id` вернёт пустой список, поиск по тегу отдаст две одинаковые строки.

- [ ] **Шаг 3: реализовать**

В `repository.py` добавить импорт `re` в шапку и три функции перед `_filters_q`:

```python
# Номер задачи в строке поиска: «#124» и «124». До 18 цифр — длиннее числа не
# влезает в bigint, и Postgres ответил бы ошибкой вместо пустой выдачи.
_TASK_ID_RE = re.compile(r'^#?(\d{1,18})$')


def _search_q(term: str, *, prefix: str = '') -> Q:
    """
    Строка поиска. Похоже на номер — ищем по номеру: «#124» в разделе значит
    конкретную задачу, а не заголовки, где встретилось «124».

    Иначе — OR по заголовку, ученику, исполнителю и метке. Join по меткам
    размножает строки, поэтому вызывающий обязан спросить _needs_distinct().
    """
    match = _TASK_ID_RE.match(term.strip())
    if match:
        return Q(**{f'{prefix}id': int(match.group(1))})
    return (
        Q(**{f'{prefix}title__icontains': term})
        | Q(**{f'{prefix}student__full_name__icontains': term})
        | Q(**{f'{prefix}assignee__full_name__icontains': term})
        | Q(**{f'{prefix}tags__label__icontains': term})
    )


def _needs_distinct(params: dict) -> bool:
    """
    Нужен ли DISTINCT. Только текстовый поиск join'ит метки и может выдать одну
    задачу дважды; поиск по номеру и остальные фильтры — нет. Вешать DISTINCT
    всегда дорого: он ложится на каждый запрос доски.
    """
    term = (params.get('q') or '').strip()
    return bool(term) and not _TASK_ID_RE.match(term)
```

В `_filters_q` заменить блок поиска:

```python
    if params.get('q'):
        q &= _search_q(params['q'], prefix=prefix)
```

Заменить `_apply_filters`:

```python
def _apply_filters(qs, params: dict):
    qs = qs.filter(_filters_q(params))
    return qs.distinct() if _needs_distinct(params) else qs
```

В `column_counts` заменить аннотацию:

```python
              .annotate(task_count=Count(
                  'tasks',
                  filter=_filters_q(params or {}, prefix='tasks__'),
                  distinct=_needs_distinct(params or {}),
              ))
```

- [ ] **Шаг 4: убедиться, что тесты проходят**

Запустить: `cd journal_django && pytest apps/taskboard/tests/test_repository.py -q`
Ожидаемо: PASS, все тесты файла.

- [ ] **Шаг 5: полный прогон**

Запустить: `cd journal_django && pytest -q`
Ожидаемо: ни одного падения. Если падает что-то вне `taskboard` — разбираться, а не игнорировать.

---

## Задача 2: фильтр «Срок» (`due`)

**Файлы:**
- Изменить: `journal_django/apps/taskboard/repository.py`, `journal_django/apps/taskboard/serializers.py`
- Тест: `journal_django/apps/taskboard/tests/test_repository.py`

- [ ] **Шаг 1: написать падающие тесты**

Добавить в конец `tests/test_repository.py`:

```python
@pytest.mark.django_db
def test_due_today(board):
    b, _ = board
    today = datetime.date.today()
    target = services.create_task(
        board_id=b.id, title='Сегодня', author_id=None, due_date=today)
    services.create_task(
        board_id=b.id, title='Завтра', author_id=None,
        due_date=today + datetime.timedelta(days=1))

    ids = [t['id'] for t in repository.list_tasks({'board_id': b.id, 'due': 'today'})]
    assert ids == [target.id]


@pytest.mark.django_db
def test_due_week_covers_monday_to_sunday(board):
    b, _ = board
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    inside = services.create_task(
        board_id=b.id, title='В неделе', author_id=None, due_date=monday)
    outside = services.create_task(
        board_id=b.id, title='Следующая', author_id=None,
        due_date=monday + datetime.timedelta(days=7))

    ids = [t['id'] for t in repository.list_tasks({'board_id': b.id, 'due': 'week'})]
    assert inside.id in ids
    assert outside.id not in ids


@pytest.mark.django_db
def test_due_overdue_excludes_closed(board):
    b, stages = board
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    open_task = services.create_task(
        board_id=b.id, title='Висит', author_id=None, due_date=yesterday)
    closed = services.create_task(
        board_id=b.id, title='Закрыта', author_id=None, due_date=yesterday)
    services.move_task(closed, to_stage_id=stages['done'].id,
                       resolution='done', author_id=None)

    ids = [t['id'] for t in repository.list_tasks({'board_id': b.id, 'due': 'overdue'})]
    assert ids == [open_task.id]


@pytest.mark.django_db
def test_due_none_finds_tasks_without_date(board):
    b, _ = board
    without = services.create_task(board_id=b.id, title='Без срока', author_id=None)
    services.create_task(
        board_id=b.id, title='Со сроком', author_id=None,
        due_date=datetime.date.today())

    ids = [t['id'] for t in repository.list_tasks({'board_id': b.id, 'due': 'none'})]
    assert ids == [without.id]
```

- [ ] **Шаг 2: убедиться, что тесты падают**

Запустить: `cd journal_django && pytest apps/taskboard/tests/test_repository.py -q -k due`
Ожидаемо: FAIL — фильтр игнорируется, выдача содержит обе задачи.

- [ ] **Шаг 3: реализовать**

В `repository.py` в шапку добавить `from datetime import date, timedelta` (заменив
существующий `from datetime import date`), и функцию рядом с `_search_q`:

```python
def _due_q(value: str, *, prefix: str = '') -> Q:
    """
    Значения селектора «Срок». `overdue` повторяет отдельный булев фильтр
    `overdue` — тот остался ради существующих вызовов (блок задач ученика),
    здесь он нужен как одно из значений единого селектора.
    """
    today = date.fromisoformat(msk_today())
    if value == 'today':
        return Q(**{f'{prefix}due_date': today})
    if value == 'week':
        monday = today - timedelta(days=today.weekday())
        return Q(**{f'{prefix}due_date__gte': monday,
                    f'{prefix}due_date__lte': monday + timedelta(days=6)})
    if value == 'overdue':
        return Q(**{f'{prefix}closed_at__isnull': True,
                    f'{prefix}due_date__lt': today})
    if value == 'none':
        return Q(**{f'{prefix}due_date__isnull': True})
    return Q()
```

В `_filters_q` перед блоком `q` добавить:

```python
    if params.get('due'):
        q &= _due_q(params['due'], prefix=prefix)
```

В `serializers.py` в `TaskFilterSerializer` добавить поле:

```python
    due = serializers.ChoiceField(
        choices=['today', 'week', 'overdue', 'none'], required=False)
```

- [ ] **Шаг 4: убедиться, что тесты проходят**

Запустить: `cd journal_django && pytest apps/taskboard/tests/test_repository.py -q -k due`
Ожидаемо: PASS, 4 теста.

- [ ] **Шаг 5: полный прогон**

Запустить: `cd journal_django && pytest -q`
Ожидаемо: ни одного падения.

---

## Задача 3: правки полей попадают в ленту

**Файлы:**
- Изменить: `journal_django/apps/taskboard/services.py`
- Тест: `journal_django/apps/taskboard/tests/test_services_update.py`

- [ ] **Шаг 1: написать падающие тесты**

Добавить в конец `tests/test_services_update.py`:

```python
@pytest.mark.django_db
def test_due_date_change_is_logged(board):
    import datetime

    from apps.taskboard.models import TaskActivity

    b, _ = board
    task = services.create_task(board_id=b.id, title='Задача', author_id=None)
    services.update_task(
        task, author_id=None, fields={'due_date': datetime.date(2026, 8, 28)})

    entry = (TaskActivity.objects
             .filter(task=task, kind='system')
             .order_by('-id').first())
    assert entry.meta['field'] == 'due_date'
    assert entry.meta['from'] is None
    assert entry.meta['to'] == '2026-08-28'


@pytest.mark.django_db
def test_priority_change_is_logged(board):
    from apps.taskboard.models import TaskActivity

    b, _ = board
    task = services.create_task(board_id=b.id, title='Задача', author_id=None)
    services.update_task(task, author_id=None, fields={'priority': 'high'})

    entry = (TaskActivity.objects
             .filter(task=task, kind='system')
             .order_by('-id').first())
    assert entry.meta == {'field': 'priority', 'from': 'normal', 'to': 'high'}


@pytest.mark.django_db
def test_unchanged_field_writes_nothing(board):
    from apps.taskboard.models import TaskActivity

    b, _ = board
    task = services.create_task(board_id=b.id, title='Задача', author_id=None)
    before = TaskActivity.objects.filter(task=task).count()
    services.update_task(task, author_id=None, fields={'priority': 'normal'})

    assert TaskActivity.objects.filter(task=task).count() == before


@pytest.mark.django_db
def test_assignee_change_still_uses_assign_kind(board, admin_account_id):
    """Смена исполнителя остаётся записью kind='assign', а не системной."""
    from apps.taskboard.models import TaskActivity

    b, _ = board
    task = services.create_task(board_id=b.id, title='Задача', author_id=None)
    services.update_task(task, author_id=None, fields={'assignee_id': admin_account_id})

    kinds = list(TaskActivity.objects.filter(task=task)
                 .order_by('id').values_list('kind', flat=True))
    assert kinds == ['system', 'assign']  # 'system' — запись о создании
```

- [ ] **Шаг 2: убедиться, что тесты падают**

Запустить: `cd journal_django && pytest apps/taskboard/tests/test_services_update.py -q -k "logged or unchanged"`
Ожидаемо: FAIL — `entry.meta['field']` падает, потому что последняя системная запись
сейчас относится к созданию задачи и поля `field` в ней нет.

- [ ] **Шаг 3: реализовать**

В `services.py` в шапку добавить `from datetime import date`.

Добавить хелпер перед `update_task`:

```python
def _jsonable(value):
    """`meta` уезжает в jsonb — дата обязана стать строкой."""
    return value.isoformat() if isinstance(value, date) else value
```

В `update_task` заменить цикл присваивания, добавив словарь прежних значений:

```python
    before: dict[str, object] = {}
    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            continue
        # Для assignee_id сверяемся с previous_assignee (истина из БД), а не с
        # переданным объектом: иначе устаревший снимок с уже совпадающим
        # значением молча гасит смену исполнителя вместе с записью в ленте.
        current = previous_assignee if key == 'assignee_id' else getattr(task, key)
        if current == value:
            continue
        before[key] = current
        setattr(task, key, value)
        changed.append(key)
```

И заменить хвост функции (всё после `task.save(...)`) на:

```python
    if 'assignee_id' in changed:
        TaskActivity.objects.create(
            task=task, kind=TaskActivity.Kind.ASSIGN, author_id=author_id,
            meta={'from_assignee_id': previous_assignee, 'to_assignee_id': task.assignee_id},
        )

    # Остальные правки — системными записями. В meta лежат сырые значения (id и
    # даты), а не готовый русский текст: собранный сейчас текст переврал бы
    # историю после переименования типа или ученика. Подписи рисует фронт.
    for key in changed:
        if key == 'assignee_id':
            continue
        TaskActivity.objects.create(
            task=task, kind=TaskActivity.Kind.SYSTEM, author_id=author_id,
            meta={'field': key,
                  'from': _jsonable(before[key]),
                  'to': _jsonable(getattr(task, key))},
        )
    return task
```

- [ ] **Шаг 4: убедиться, что тесты проходят**

Запустить: `cd journal_django && pytest apps/taskboard/tests/test_services_update.py -q`
Ожидаемо: PASS, весь файл.

- [ ] **Шаг 5: полный прогон**

Запустить: `cd journal_django && pytest -q`
Ожидаемо: ни одного падения. Особое внимание — `test_invariants.py` и `test_api_tasks.py`:
они считают записи ленты.

---

## Задача 4: счётчик комментариев в строке карточки

**Файлы:**
- Изменить: `journal_django/apps/taskboard/repository.py`
- Тест: `journal_django/apps/taskboard/tests/test_repository.py`

- [ ] **Шаг 1: написать падающие тесты**

Добавить в конец `tests/test_repository.py`:

```python
@pytest.mark.django_db
def test_comments_count_in_row(board):
    b, _ = board
    task = services.create_task(board_id=b.id, title='С комментариями', author_id=None)
    services.add_comment(task, body='Первый', author_id=None)
    services.add_comment(task, body='Второй', author_id=None)

    row = repository.get_task(task.id)
    assert row['comments_count'] == 2


@pytest.mark.django_db
def test_comments_count_ignores_system_entries(board):
    """Системные записи и смены стадии — не комментарии."""
    b, stages = board
    task = services.create_task(board_id=b.id, title='Без комментариев', author_id=None)
    services.move_task(task, to_stage_id=stages['work'].id,
                       resolution=None, author_id=None)

    row = repository.get_task(task.id)
    assert row['comments_count'] == 0


@pytest.mark.django_db
def test_comments_count_does_not_add_queries(board):
    """Счётчик не должен стоить запроса на карточку."""
    b, _ = board
    for i in range(2):
        t = services.create_task(board_id=b.id, title=f'Задача {i}', author_id=None)
        services.add_comment(t, body='Комментарий', author_id=None)
    with CaptureQueriesContext(connection) as few:
        repository.list_tasks({'board_id': b.id})

    for i in range(2, 10):
        t = services.create_task(board_id=b.id, title=f'Задача {i}', author_id=None)
        services.add_comment(t, body='Комментарий', author_id=None)
    with CaptureQueriesContext(connection) as many:
        repository.list_tasks({'board_id': b.id})

    assert len(many) == len(few)
```

- [ ] **Шаг 2: убедиться, что тесты падают**

Запустить: `cd journal_django && pytest apps/taskboard/tests/test_repository.py -q -k comments_count`
Ожидаемо: FAIL — `KeyError: 'comments_count'`.

- [ ] **Шаг 3: реализовать**

В `repository.py` в шапку добавить импорты:

```python
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
```

Добавить подзапрос и подключить его к базовому queryset:

```python
def _comments_count_subquery():
    """
    Счётчик комментариев ПОДЗАПРОСОМ, а не аннотацией с JOIN.

    JOIN потребовал бы GROUP BY по всем колонкам семи присоединённых таблиц из
    select_related — на VPS с двумя ядрами это заметно дороже подзапроса,
    который ложится на готовый индекс task_activity_task_idx.
    """
    return Subquery(
        TaskActivity.objects
        .filter(task_id=OuterRef('id'), kind=TaskActivity.Kind.COMMENT)
        .values('task_id')
        .annotate(n=Count('id'))
        .values('n'),
        output_field=IntegerField(),
    )


def _base_queryset():
    return (Task.objects
            .select_related(*_RELATED)
            .prefetch_related('tags')
            .annotate(comments_count=Coalesce(_comments_count_subquery(), 0)))
```

В `_row` добавить поле рядом с `tags`:

```python
        'comments_count': getattr(task, 'comments_count', 0) or 0,
```

- [ ] **Шаг 4: убедиться, что тесты проходят**

Запустить: `cd journal_django && pytest apps/taskboard/tests/test_repository.py -q`
Ожидаемо: PASS, весь файл, включая старый N+1-страж.

- [ ] **Шаг 5: полный прогон**

Запустить: `cd journal_django && pytest -q`
Ожидаемо: ни одного падения.

---

## Задача 5: цвет стадии и читаемый текст на нём

**Файлы:**
- Создать: `journal_django/frontend/admin-src/src/lib/stage-tone.ts`

- [ ] **Шаг 1: написать файл**

```ts
import { nameColor } from './direction-color';

/** Заливка шапки стадии и цвет подписи на ней. */
export interface StageTone {
  bg: string;
  ink: string;
}

const WHITE = '#ffffff';
const DARK = '#16161a';

// Пороги относительной яркости (WCAG). Ниже LIGHT_TEXT_MAX белый текст даёт
// контраст не хуже 4.5:1, выше DARK_TEXT_MIN — тёмный. Между ними не проходит
// ни один из двух, поэтому заливка притемняется.
const LIGHT_TEXT_MAX = 0.183;
const DARK_TEXT_MIN = 0.211;

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

function channels(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function relativeLuminance(hex: string): number {
  const [r, g, b] = channels(hex).map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function darken(hex: string, factor: number): string {
  const parts = channels(hex)
    .map((c) => Math.round(c * factor).toString(16).padStart(2, '0'));
  return `#${parts.join('')}`;
}

/**
 * Тон шапки стадии.
 *
 * Цвет стадии задаёт суперадмин и может выбрать светло-жёлтый — белая подпись
 * на нём нечитаема. Поэтому цвет текста выводится из яркости заливки, а в узкой
 * полосе, где не проходит ни белый, ни тёмный, заливка притемняется на 20%:
 * яркость падает примерно вдвое и белый текст снова держит 4.5:1.
 *
 * Стадия без своего цвета получает детерминированный тон из названия — тот же
 * приём, что у направлений и аватаров. Серая заглушка отвергнута сознательно:
 * доска из восьми одинаковых серых плашек хуже, чем разноцветная.
 */
export function stageTone(color: string | null | undefined, label: string): StageTone {
  if (!color || !HEX_RE.test(color)) {
    // nameColor отдаёт hsl со светлотой 42% — он всегда тёмный, белый текст подходит.
    return { bg: nameColor(label), ink: WHITE };
  }
  const luminance = relativeLuminance(color);
  if (luminance >= DARK_TEXT_MIN) return { bg: color, ink: DARK };
  if (luminance <= LIGHT_TEXT_MAX) return { bg: color, ink: WHITE };
  return { bg: darken(color, 0.8), ink: WHITE };
}
```

- [ ] **Шаг 2: проверить типы**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
Ожидаемо: без ошибок.

---

## Задача 6: общий компонент шапки колонки

**Файлы:**
- Создать: `journal_django/frontend/admin-src/src/components/board/BoardColumnHead.tsx`
- Изменить: `journal_django/frontend/admin-src/src/styles/components.css`

- [ ] **Шаг 1: написать компонент**

```tsx
import type { ReactNode } from 'react';
import { stageTone } from '../../lib/stage-tone';

interface Props {
  label: string;
  count: number;
  /** Цвет стадии из справочника. Пусто — тон выведется из названия. */
  color?: string | null;
  /** Служебная пометка рядом с названием (например «авто» в «Продлениях»). */
  badge?: ReactNode;
  /** Кнопки справа от счётчика: поиск, меню. */
  actions?: ReactNode;
}

/**
 * Шапка колонки доски — сплошная плашка цветом стадии.
 *
 * Общая для «Задач» и «Продлений» по прямому требованию заказчика: шапка стадии
 * должна выглядеть одинаково во всей системе. Специфика разделов сюда не
 * переезжает — она приходит слотами `badge` и `actions`.
 *
 * Цвет подписи считает stageTone(): цвет стадии выбирает человек, и на светлой
 * заливке белый текст нечитаем.
 */
export function BoardColumnHead({ label, count, color, badge, actions }: Props) {
  const tone = stageTone(color, label);
  return (
    <div
      className="board-col-head"
      style={{ background: tone.bg, color: tone.ink }}
    >
      <span className="board-col-head__label" title={label}>{label}</span>
      {badge}
      <span className="board-col-head__count">{count}</span>
      {actions && <span className="board-col-head__actions">{actions}</span>}
    </div>
  );
}
```

- [ ] **Шаг 2: добавить стили**

В конец `styles/components.css`:

```css
/* ===== Шапка колонки доски =====
   Общая для «Задач» и «Продлений» (components/board/BoardColumnHead.tsx).
   Живёт здесь, а не в pages/tasks.css: вторая копия в renewals.css неизбежно
   разъехалась бы с первой.

   Заливка и цвет текста приходят инлайном из stageTone() — цвет стадии задаёт
   суперадмин, токеном его не выразить. Это то же исключение из правила «только
   токены», что и цвет направления. */
.board-col-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 34px;
  padding: 0 var(--space-3);
  border-radius: var(--r) var(--r) 0 0;
}

.board-col-head__label {
  flex: 1;
  min-width: 0;
  font-size: var(--fs-sm);
  font-weight: 600;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.board-col-head__count {
  font-size: var(--fs-sm);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  opacity: 0.85;
}

/* Кнопки наследуют цвет подписи: на цветной заливке иконка токеном --text
   местами исчезает. */
.board-col-head__actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  color: inherit;
}

.board-col-head__actions .ui-iconbtn {
  color: inherit;
}
```

- [ ] **Шаг 3: проверить типы**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
Ожидаемо: без ошибок. Компонент пока никем не используется — это нормально.

---

## Задача 7: перевести обе доски на общую шапку

**Файлы:**
- Изменить: `journal_django/frontend/admin-src/src/pages/tasks/TaskColumn.tsx`
- Изменить: `journal_django/frontend/admin-src/src/pages/renewals/RenewalColumn.tsx`
- Изменить: `journal_django/frontend/admin-src/src/styles/pages/tasks.css`
- Изменить: `journal_django/frontend/admin-src/src/styles/pages/renewals.css`

- [ ] **Шаг 1: подключить в задачах**

В `TaskColumn.tsx` добавить импорт `import { BoardColumnHead } from '../../components/board/BoardColumnHead';`,
снять инлайновый `borderTopColor` с корневого `<div>` и заменить блок `.task-col__head` на:

```tsx
      <BoardColumnHead label={col.label} count={col.count} color={col.color} />
```

- [ ] **Шаг 2: подключить в продлениях**

В `RenewalColumn.tsx` добавить тот же импорт, снять инлайновый `borderTopColor`, и заменить
ветку `else` внутри `.renewal-col__head` (название + счётчик + лупа) на:

```tsx
      {searchOpen ? (
        <div className="renewal-col__search">
          {/* поле поиска и кнопка закрытия — без изменений */}
        </div>
      ) : (
        <BoardColumnHead
          label={col.label}
          count={count}
          color={col.color}
          badge={isAutoOnly && (
            <span
              className="renewal-col__auto-badge"
              title="Двигает только система по событиям — вручную перенести сделку сюда нельзя"
            >
              авто
            </span>
          )}
          actions={(
            <IconButton
              ref={searchToggleRef}
              size="sm"
              label={`Поиск в стадии «${col.label}»`}
              active={searching}
              onClick={() => setSearchOpen(true)}
              icon={<SearchGlyph />}
            />
          )}
        />
      )}
```

Обёртку `<div className="renewal-col__head">` при этом убрать — плашка сама себе шапка,
а развёрнутый поиск остаётся отдельной строкой под ней.

- [ ] **Шаг 3: поправить стили колонок**

В `styles/pages/tasks.css` в правиле `.task-col`:
- убрать строку `border-top: 3px solid var(--border-strong);` вместе с комментарием про
  исключение из токенов (комментарий переехал в `components.css`);
- заменить `padding: var(--space-3);` на `padding: 0;`;
- добавить `overflow: hidden;` — иначе скругление плашки срежется прямым углом колонки;
- удалить правила `.task-col__head`, `.task-col__label`, `.task-col__stats` целиком.

Добавить внутренние отступы телу колонки — в правило `.task-col__body`:

```css
  padding: var(--space-3);
```

В `styles/pages/renewals.css` симметрично: убрать `border-top` у `.renewal-col`, обнулить
padding колонки, добавить `overflow: hidden`, удалить `.renewal-col__head`,
`.renewal-col__label`, `.renewal-col__stats`, дать `padding: var(--space-3)` телу
`.renewal-col__body` и строке `.renewal-col__search`. Правило `.renewal-col__auto-badge`
оставить, но заменить `color: var(--text3);` на `color: inherit; opacity: 0.75;` — на цветной
заливке серый токен пропадает.

- [ ] **Шаг 4: проверить типы**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
Ожидаемо: без ошибок.

- [ ] **Шаг 5: проверить глазами**

Открыть `/admin/tasks` и `/admin/renewals`. Убедиться: плашки цветные, подписи читаются на
всех стадиях, скругление сверху не срезано, счётчик на месте, лупа в «Продлениях» работает и
видна, бейдж «авто» читается.

---

## Задача 8: toast с действием и отменой

**Файлы:**
- Изменить: `journal_django/frontend/admin-src/src/components/ui/Toast.tsx`
- Изменить: `journal_django/frontend/admin-src/src/styles/components.css`

- [ ] **Шаг 1: расширить провайдер**

Заменить содержимое `Toast.tsx` на:

```tsx
import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

type ToastKind = 'ok' | 'error' | 'info';

/** Действие в toast'е — обычно «Отменить» у обратимой операции. */
export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  kind?: ToastKind;
  /** Сколько висит, мс. Toast с действием должен жить дольше — его надо успеть нажать. */
  duration?: number;
  actions?: ToastAction[];
}

interface ToastItem extends ToastOptions { id: number; message: string; }

const DEFAULT_DURATION = 3000;
const ACTION_DURATION = 8000;

const ToastContext = createContext<{
  toast: (msg: string, kindOrOptions?: ToastKind | ToastOptions) => void;
}>(null!);

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Второй аргумент остался совместимым со старым `toast(msg, 'ok')` — вызовов
  // по всему admin SPA несколько десятков, переписывать их незачем.
  const toast = useCallback((
    message: string,
    kindOrOptions: ToastKind | ToastOptions = 'info',
  ) => {
    const options: ToastOptions = typeof kindOrOptions === 'string'
      ? { kind: kindOrOptions }
      : kindOrOptions;
    const id = nextId++;
    const hasActions = !!options.actions?.length;
    const duration = options.duration
      ?? (hasActions ? ACTION_DURATION : DEFAULT_DURATION);
    setItems((prev) => [...prev, { ...options, id, message, kind: options.kind ?? 'info' }]);
    setTimeout(() => dismiss(id), duration);
  }, [dismiss]);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="toast-container">
        {items.map((t) => (
          <div key={t.id} className={`toast toast--${t.kind}`}>
            <span className="toast__text">{t.message}</span>
            {t.actions?.map((action) => (
              <button
                key={action.label}
                type="button"
                className="toast__action"
                onClick={() => { dismiss(t.id); action.onClick(); }}
              >
                {action.label}
              </button>
            ))}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() { return useContext(ToastContext); }

export function showApiError(
  err: unknown,
  toast: (m: string, k?: ToastKind | ToastOptions) => void,
) {
  if (typeof err === 'object' && err && 'message' in err) {
    toast(String((err as { message: unknown }).message), 'error');
  } else {
    toast('Ошибка', 'error');
  }
}
```

- [ ] **Шаг 2: стили действия**

В `styles/components.css` рядом с существующим блоком `.toast`:

```css
.toast__text { flex: 1; }

/* Действие в toast'е («Отменить»). Подчёркнутая кнопка, не вторая заливка:
   toast и так висит поверх интерфейса, второй акцент в нём — шум. */
.toast__action {
  flex: none;
  border: 0;
  background: none;
  padding: 0;
  font: inherit;
  font-weight: 600;
  color: inherit;
  text-decoration: underline;
  cursor: pointer;
}
```

В существующее правило `.toast` добавить `display: flex; align-items: center; gap: var(--space-3);`

- [ ] **Шаг 3: проверить типы**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
Ожидаемо: без ошибок — старые вызовы `toast('Готово', 'ok')` обязаны продолжать
компилироваться. Если где-то тип поехал — чинить, а не менять сигнатуру обратно.

- [ ] **Шаг 4: проверить глазами**

Открыть любую страницу, где уже показывается toast (например, сохранение оплаты) —
убедиться, что вид не изменился.

---

## Задача 9: типы фронта под новые поля бэкенда

**Файлы:**
- Изменить: `journal_django/frontend/admin-src/src/lib/tasks.ts`

- [ ] **Шаг 1: дописать типы**

В `TaskRow` добавить рядом с `tags`:

```ts
  comments_count: number;
```

В `TaskFilters` добавить:

```ts
  /** Значения селектора «Срок». `overdue` дублирует булев фильтр выше — так на бэке. */
  due?: 'today' | 'week' | 'overdue' | 'none';
```

- [ ] **Шаг 2: проверить типы**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
Ожидаемо: без ошибок.

---

## Задача 10: карточка задачи

**Файлы:**
- Изменить: `journal_django/frontend/admin-src/src/pages/tasks/TaskCard.tsx`
- Изменить: `journal_django/frontend/admin-src/src/styles/pages/tasks.css`

- [ ] **Шаг 1: переписать содержимое карточки**

Заменить `TaskCardContent` на:

```tsx
interface ContentProps {
  task: TaskRow;
  /** Недельный вид: срок уже написан на колонке, в карточке он лишний. */
  compact?: boolean;
}

export function TaskCardContent({ task, compact }: ContentProps) {
  const chips = [
    task.priority !== 'normal' && (
      <span key="priority" className={`task-card__chip is-${task.priority}`}>
        {TASK_PRIORITY_LABELS[task.priority]}
      </span>
    ),
    task.task_type_label && (
      <span key="type" className="task-card__chip">{task.task_type_label}</span>
    ),
    ...task.tags.map((tag) => (
      <span key={`tag-${tag.id}`} className="task-card__chip">{tag.label}</span>
    )),
  ].filter(Boolean);

  return (
    <>
      <div className="task-card__top">
        <span className="task-card__id">#{task.id}</span>
        {task.student_name && (
          <span className="task-card__student" title={task.student_name}>
            {task.student_name}
          </span>
        )}
      </div>

      {/* Закрытая задача — зачёркнутый заголовок с галочкой, а не отдельный
          статус-бейдж: «закрыто» видно с первого взгляда. */}
      <div className={`task-card__title${task.is_closed ? ' is-closed' : ''}`}>
        {task.is_closed && <CheckGlyph />}
        <span>{task.title}</span>
      </div>

      {/* Показываем только заполненное: пустые свойства ряд не занимают. */}
      {chips.length > 0 && <div className="task-card__chips">{chips}</div>}

      <div className="task-card__meta">
        <span title={task.assignee_name || 'Не назначен'}>
          <Avatar name={task.assignee_name || '—'} size={18} />
        </span>
        <span className="task-card__assignee">{task.assignee_name || 'Не назначен'}</span>
        {task.comments_count > 0 && (
          <span className="task-card__comments" title="Комментарии">
            <CommentGlyph />{task.comments_count}
          </span>
        )}
        {!compact && task.due_date && (
          <span className={`task-card__due${task.is_overdue ? ' is-overdue' : ''}`}>
            {task.is_overdue && <span className="task-card__overdue-dot" aria-hidden="true" />}
            {task.is_overdue ? overdueLabel(task.due_date) : fmtDate(task.due_date)}
          </span>
        )}
      </div>
    </>
  );
}
```

- [ ] **Шаг 2: добавить подпись просрочки**

В тот же файл, рядом с глифами:

Импорт: `import { isoDate, parseIsoDate, todayMsk } from '../../shared/calendar/lib';`

```tsx
/**
 * «просрочено 2 дн.» вместо голой даты: сама дата ничего не говорит, пока не
 * посчитаешь разницу в уме. Считаем от MSK-сегодня — тем же хелпером, что и
 * календарь, иначе поздним вечером цифра разойдётся с бэкендом.
 */
function overdueLabel(due: string): string {
  const today = parseIsoDate(isoDate(todayMsk()));
  const days = Math.max(1, Math.round(
    (today.getTime() - parseIsoDate(due).getTime()) / 86_400_000,
  ));
  return `просрочено ${days} ${plural(days, 'день', 'дня', 'дней')}`;
}

/** Склонение существительного при числе. Общего хелпера в проекте нет. */
function plural(n: number, one: string, few: string, many: string): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return many;
  const mod10 = n % 10;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}
```

- [ ] **Шаг 3: добавить глиф комментариев и hover-действия**

Глиф:

```tsx
function CommentGlyph() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}
```

В `TaskCard` (обёртке с drag) добавить проп `actions?: ReactNode` и отрисовать его
поверх карточки:

```tsx
      {actions && (
        <div
          className="task-card__actions"
          // Клик по действию не должен открывать панель и стартовать drag.
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
        >
          {actions}
        </div>
      )}
```

Также добавить проп `compact?: boolean` и пробросить его в `TaskCardContent`.

- [ ] **Шаг 4: стили**

В `styles/pages/tasks.css` в блоке карточки:
- сократить вертикальные отступы примерно на 20% (`padding` карточки и `gap` между её
  строками — на одну ступень токенов вниз);
- добавить правила `.task-card__chips`, `.task-card__chip`, `.task-card__student`,
  `.task-card__comments`, `.task-card__overdue-dot`, `.task-card__actions`;
- `.task-card` получает `position: relative`, `.task-card__actions` —
  `position: absolute; top: var(--space-1); right: var(--space-1); opacity: 0;`
  и `opacity: 1` на `.task-card:hover .task-card__actions`,
  `.task-card:focus-within .task-card__actions`;
- удалить осиротевшее правило `.task-card__priority` — приоритет теперь чип.

Цвет точки просрочки — токеном `--danger` (или тем, что в `tokens.css` отвечает за
негативный статус; проверить перед использованием, hardcode запрещён).

- [ ] **Шаг 5: проверить типы**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
Ожидаемо: без ошибок.

- [ ] **Шаг 6: проверить глазами**

Открыть `/admin/tasks`: карточка без типа/тегов/комментариев не показывает пустых строк;
просроченная показывает точку и «просрочено N дн.»; на hover появляется зона действий.

---

## Задача 11: быстрое добавление задачи внизу колонки

**Файлы:**
- Изменить: `journal_django/frontend/admin-src/src/pages/tasks/TaskColumn.tsx`
- Изменить: `journal_django/frontend/admin-src/src/styles/pages/tasks.css`

- [ ] **Шаг 1: заменить всегда видимое поле на разворачивающееся**

В `TaskColumn.tsx` добавить состояние `const [adding, setAdding] = useState(false);`,
убрать `<TextInput className="task-col__quick-add" …>` из шапки колонки и добавить в самый
низ колонки (после кнопки «Показать ещё»):

```tsx
      {/* Задача не может родиться закрытой — бэкенд отклонит создание в стадии
          category='closed', поэтому в такой колонке добавлять нечего. */}
      {col.category !== 'closed' && (
        adding ? (
          <TextInput
            className="task-col__quick-add"
            value={quickTitle}
            autoFocus
            onChange={(e) => setQuickTitle(e.target.value)}
            onKeyDown={handleQuickAddKey}
            onBlur={() => { if (!quickTitle.trim()) setAdding(false); }}
            placeholder="Название задачи…"
            disabled={create.isPending}
            aria-label={`Добавить задачу в стадию «${col.label}»`}
          />
        ) : (
          <button
            type="button"
            className="task-col__add"
            onClick={() => setAdding(true)}
          >
            + Добавить задачу
          </button>
        )
      )}
```

- [ ] **Шаг 2: обработать Esc и очистку**

Заменить `handleQuickAddKey`:

```tsx
  const handleQuickAddKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      setQuickTitle('');
      setAdding(false);
      return;
    }
    if (e.key !== 'Enter') return;
    const title = quickTitle.trim();
    if (!title) return;
    create.mutate(
      { board_id: boardId, title, stage_id: col.stage_id },
      {
        // Поле остаётся открытым: задачи заводят пачками, и повторный клик по
        // ссылке после каждой был бы лишним шагом.
        onSuccess: () => setQuickTitle(''),
        onError: (err) => showError(err, 'Не удалось создать задачу'),
      },
    );
  };
```

- [ ] **Шаг 3: стили**

В `styles/pages/tasks.css` добавить `.task-col__add` — ссылкообразная кнопка во всю ширину:
прозрачный фон, `color: var(--text3)`, при hover — `color: var(--text)` и подложка
`var(--bg2)`, скругление `var(--r-sm)`, отступ `var(--space-2)`.

- [ ] **Шаг 4: проверить типы и глазами**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
Открыть доску: ссылка внизу колонки, клик разворачивает поле, Enter создаёт задачу в этой
стадии, Esc сворачивает, в закрытой колонке ссылки нет.

---

## Задача 12: закрытие перетаскиванием и отмена

**Файлы:**
- Изменить: `journal_django/frontend/admin-src/src/pages/tasks/TaskBoard.tsx`

- [ ] **Шаг 1: убрать диалог из пути перетаскивания**

В `handleDragEnd` удалить ветку с `setCompleteTarget` и заменить вызов `move` на общий
обработчик:

```tsx
  const handleDragEnd = (event: DragEndEvent) => {
    setActiveTask(null);
    const { active, over } = event;
    if (!over) return;

    const taskId = Number(active.id);
    const toStageId = Number(over.id);
    const fromStageId = dragFromStage(event);
    if (fromStageId == null || fromStageId === toStageId) return;

    const targetStage = (stages || []).find((s) => s.id === toStageId);
    if (!targetStage) return;

    // Перенос в закрытую стадию закрывает задачу сразу с результатом «Выполнено»:
    // сценарий доски — «перетащил, и всё». Результат правится из toast'а, а
    // диалог остаётся на кнопке «Выполнено» в панели задачи.
    moveWithUndo({
      taskId,
      fromStageId,
      toStageId,
      resolution: targetStage.category === 'closed' ? 'done' : undefined,
      stageLabel: targetStage.label,
    });
  };
```

- [ ] **Шаг 2: написать перенос с отменой**

Добавить в `TaskBoard`:

```tsx
  const { toast } = useToast();

  interface MoveRequest {
    taskId: number;
    fromStageId: number;
    toStageId: number;
    resolution?: TaskResolution;
    stageLabel: string;
  }

  const moveWithUndo = (req: MoveRequest) => {
    move.mutate(
      { id: req.taskId, to_stage_id: req.toStageId, resolution: req.resolution },
      {
        onSuccess: () => {
          const actions = [{
            label: 'Отменить',
            // Возврат в открытую стадию бэкенд отработает сам: move_task
            // обнуляет resolution и closed_at, отдельного «переоткрыть» не нужно.
            onClick: () => move.mutate(
              { id: req.taskId, to_stage_id: req.fromStageId },
              { onError: (err) => showError(conflictError(err), 'Не удалось отменить перенос') },
            ),
          }];
          if (req.resolution) {
            actions.push({
              label: 'Изменить результат',
              onClick: () => setCompleteTarget({ taskId: req.taskId, toStageId: req.toStageId }),
            });
          }
          toast(`Задача перемещена в «${req.stageLabel}»`, { kind: 'ok', actions });
        },
        onError: (err) => showError(conflictError(err), 'Не удалось перенести задачу'),
      },
    );
  };
```

Импорты: `import { useToast } from '../../components/ui/Toast';`

- [ ] **Шаг 3: оставить диалог для правки результата**

`TaskCompleteDialog` и `completeTarget` остаются — теперь они открываются только из toast'а
(«Изменить результат») и из панели задачи. `handleCompleteConfirm` не меняется.

- [ ] **Шаг 4: проверить типы и глазами**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
На доске: перетащить карточку между открытыми колонками → toast с «Отменить», нажать —
карточка вернулась. Перетащить в «Готово» → задача закрыта без диалога, в toast'е две кнопки,
«Изменить результат» открывает диалог.

---

## Задача 13: полная форма создания задачи

**Файлы:**
- Создать: `journal_django/frontend/admin-src/src/pages/tasks/TaskCreateModal.tsx`

- [ ] **Шаг 1: написать модалку**

Компонент на `components/ui/Dialog` (Radix, уже используется во всех модалках проекта).
Пропсы: `{ open, onOpenChange, boardId, onCreated }`.

Поля — только из `components/form/`: `TextInput` (заголовок), `Combobox` (исполнитель,
ученик, группа), `DateInput` (срок), `SelectInput` (приоритет, тип), `Checkbox` на каждый
тег, `Textarea` (описание). Обязателен только заголовок — кнопка «Создать» заблокирована,
пока он пуст.

Справочники брать теми же хуками, что и `TaskDrawer`: `useTaskAssignees`, `useTaskTypes`,
`useTaskTags`, `useStudentsAll`, `useGroupsAll`. Подпись исполнителя — `full_name`, а если
пуст, роль из `ROLE_LABELS` (как в `TaskDrawer.assigneeLabel`).

Отправка — `useTaskMutations().create` с телом:

```tsx
    create.mutate({
      board_id: boardId,
      title: title.trim(),
      description: description.trim() || null,
      assignee_id: assigneeId ? Number(assigneeId) : null,
      student_id: studentId ? Number(studentId) : null,
      group_id: groupId ? Number(groupId) : null,
      task_type_id: typeId ? Number(typeId) : null,
      due_date: dueDate || null,
      priority,
      tag_ids: tagIds,
    }, {
      onSuccess: (row) => {
        toast('Задача создана', 'ok');
        onOpenChange(false);
        onCreated(row.id);
      },
      onError: (err) => showError(err, 'Не удалось создать задачу'),
    });
```

Стадию не передаём — сервис положит задачу в первую открытую стадию воронки.

`onCreated(id)` вызывающий использует, чтобы сразу открыть панель новой задачи.

- [ ] **Шаг 2: проверить типы**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
Ожидаемо: без ошибок.

---

## Задача 14: табы воронок

**Файлы:**
- Создать: `journal_django/frontend/admin-src/src/pages/tasks/TaskBoardTabs.tsx`
- Изменить: `journal_django/frontend/admin-src/src/styles/pages/tasks.css`

- [ ] **Шаг 1: написать компонент**

```tsx
import { ActionMenu } from '../../components/ui/ActionMenu';
import type { TaskBoard } from '../../lib/tasks';

// Больше шести воронок в ряд не влезает без переноса — остальные уходят в «Ещё».
const MAX_VISIBLE = 6;

interface Props {
  boards: TaskBoard[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

/**
 * Выбор воронки табами рядом с заголовком. Был отдельным полем в своём ряду —
 * ряд целиком уходил под один селектор, а рабочая область начиналась ниже.
 */
export function TaskBoardTabs({ boards, selectedId, onSelect }: Props) {
  const selectedIndex = boards.findIndex((b) => b.id === selectedId);
  // Выбранная воронка обязана быть видимой, даже если она седьмая по счёту —
  // иначе непонятно, что вообще открыто.
  const visible = selectedIndex >= MAX_VISIBLE
    ? [...boards.slice(0, MAX_VISIBLE - 1), boards[selectedIndex]]
    : boards.slice(0, MAX_VISIBLE);
  const hidden = boards.filter((b) => !visible.includes(b));

  return (
    <div className="board-tabs" role="tablist" aria-label="Воронки задач">
      {visible.map((b) => (
        <button
          key={b.id}
          type="button"
          role="tab"
          aria-selected={b.id === selectedId}
          className={`board-tabs__tab${b.id === selectedId ? ' is-active' : ''}`}
          onClick={() => onSelect(b.id)}
        >
          {b.name}
        </button>
      ))}
      {hidden.length > 0 && (
        <ActionMenu
          label="Другие воронки"
          items={hidden.map((b) => ({ label: b.name, onSelect: () => onSelect(b.id) }))}
        />
      )}
    </div>
  );
}
```

- [ ] **Шаг 2: стили**

В `styles/pages/tasks.css` добавить `.board-tabs` (флекс, `gap: var(--space-1)`) и
`.board-tabs__tab`: прозрачный фон, `color: var(--text2)`, скругление `var(--r-sm)`,
padding `var(--space-1) var(--space-2)`; активный — фон `var(--bg2)`, `color: var(--text)`,
`font-weight: 600`.

- [ ] **Шаг 3: проверить типы**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`

---

## Задача 15: сегменты «Все / Мои / Сегодня / Просроченные»

**Файлы:**
- Создать: `journal_django/frontend/admin-src/src/pages/tasks/TaskSegments.tsx`
- Изменить: `journal_django/frontend/admin-src/src/styles/pages/tasks.css`

- [ ] **Шаг 1: написать компонент**

```tsx
import { useAuth } from '../../hooks/useAuth';

/** Ключи фильтра, которыми управляют сегменты. */
const SEGMENT_KEYS = ['assignee_id', 'due', 'overdue'] as const;

interface Props {
  /** Текущие значения из URL: ключ → строка. */
  values: Record<string, string>;
  /** Записать набор ключей разом; пустая строка удаляет ключ. */
  onApply: (patch: Record<string, string>) => void;
}

/**
 * Быстрые представления. Своего состояния НЕ заводят: сегмент — это ярлык,
 * который пишет обычные ключи фильтра, а подсветка выводится из них обратно.
 * Отдельный ключ вида ?seg= был бы вторым источником истины и разъехался бы с
 * popover'ом «Фильтры».
 */
export function TaskSegments({ values, onApply }: Props) {
  const { me } = useAuth();
  const myId = me?.account_id != null ? String(me.account_id) : '';

  const clear: Record<string, string> = Object.fromEntries(
    SEGMENT_KEYS.map((k) => [k, '']),
  );

  const segments = [
    { key: 'all', label: 'Все', patch: clear,
      active: SEGMENT_KEYS.every((k) => !values[k]) },
    { key: 'mine', label: 'Мои', patch: { ...clear, assignee_id: myId },
      active: !!myId && values.assignee_id === myId },
    { key: 'today', label: 'Сегодня', patch: { ...clear, due: 'today' },
      active: values.due === 'today' },
    { key: 'overdue', label: 'Просроченные', patch: { ...clear, overdue: 'true' },
      active: values.overdue === 'true' },
  ];

  return (
    <div className="task-segments" role="group" aria-label="Быстрые представления">
      {segments.map((s) => (
        <button
          key={s.key}
          type="button"
          className={`task-segments__btn${s.active ? ' is-active' : ''}`}
          aria-pressed={s.active}
          onClick={() => onApply(s.patch)}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Шаг 2: стили**

Переиспользовать вид существующего `.segmented` (переключатель «Доска/Неделя»): добавить в
`tasks.css` `.task-segments` и `.task-segments__btn` по образцу `.segmented`/`.segmented__btn`
из `styles/components.css`, но плотнее — `--fs-sm`, `padding: var(--space-1) var(--space-2)`.

- [ ] **Шаг 3: проверить типы**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`

---

## Задача 16: popover «Фильтры»

**Файлы:**
- Создать: `journal_django/frontend/admin-src/src/pages/tasks/TaskFiltersPopover.tsx`
- Изменить: `journal_django/frontend/admin-src/package.json` (новая зависимость)
- Изменить: `journal_django/frontend/admin-src/src/styles/pages/tasks.css`

- [ ] **Шаг 1: поставить Radix Popover**

Запустить: `cd journal_django/frontend/admin-src && npm install @radix-ui/react-popover`

Почему не своими руками: в проекте уже шесть пакетов Radix (dialog, dropdown-menu, select,
tabs, toast, tooltip), и popover из той же семьи даёт ловушку фокуса, Escape, клик вне и
подбор позиции у края экрана. `DropdownMenu` для формы не годится — он забирает стрелки и
Enter на пункты меню, и селекты внутри него работают криво.

- [ ] **Шаг 2: написать компонент**

Триггер — кнопка «Фильтры» со счётчиком активных полей. Внутри — четыре поля через
`Field` + `SelectInput`:

- **Стадия** — опции из `useTaskStages(boardId)`, значение `stage_id`;
- **Срок** — `today | week | overdue | none`, значение `due`;
- **Приоритет** — `TASK_PRIORITY_LABELS`, значение `priority`;
- **Тип** — `useTaskTypes()`, значение `task_type_id`;
- **Checkbox** «Только открытые» — значение `only_open`.

Плюс кнопка «Сбросить», очищающая эти ключи.

Скелет:

```tsx
import * as Popover from '@radix-ui/react-popover';

interface Props {
  boardId: number;
  values: Record<string, string>;
  onSet: (key: string, value: string) => void;
  onReset: () => void;
}

const KEYS = ['stage_id', 'due', 'priority', 'task_type_id', 'only_open'];

export function TaskFiltersPopover({ boardId, values, onSet, onReset }: Props) {
  const activeCount = KEYS.filter((k) => values[k]).length;
  return (
    <Popover.Root>
      <Popover.Trigger className={`task-filters__trigger${activeCount ? ' is-active' : ''}`}>
        Фильтры{activeCount > 0 && <span className="task-filters__badge">{activeCount}</span>}
      </Popover.Trigger>
      <Popover.Portal>
        {/* data-floating-popover — метка для Dialog.onInteractOutside: клик по
            всплывашке не должен закрывать модалку, если popover открыт внутри неё. */}
        <Popover.Content className="task-filters__panel" data-floating-popover align="end" sideOffset={6}>
          {/* поля */}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
```

- [ ] **Шаг 3: стили**

В `tasks.css` добавить `.task-filters__trigger` (вид как у `.btn-reset-filters`, но с
рамкой), `.task-filters__badge` (кружок с числом на акцентном фоне) и `.task-filters__panel`
(карточка: `background: var(--bg)`, `border: 1px solid var(--border)`,
`border-radius: var(--r)`, `box-shadow` из токенов, `padding: var(--space-3)`,
`width: 260px`, поля в столбик через `gap: var(--space-3)`).

- [ ] **Шаг 4: проверить типы**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`

---

## Задача 17: собрать новую шапку страницы

**Файлы:**
- Изменить: `journal_django/frontend/admin-src/src/pages/tasks/TasksPage.tsx`
- Изменить: `journal_django/frontend/admin-src/src/styles/pages/tasks.css`

- [ ] **Шаг 1: перестроить шапку**

`PageHeader` получает `dense`, табы воронок в `sub` и кнопки справа:

```tsx
      <PageHeader
        title="Задачи"
        dense
        sub={(
          <TaskBoardTabs boards={boards} selectedId={selectedBoardId} onSelect={(id) => setBoard(String(id))} />
        )}
        actions={(
          <>
            <Button variant="primary" onClick={() => setCreateOpen(true)}>
              + Новая задача
            </Button>
            {canWriteTaskStages(me?.role as Role) && (
              <Link
                to="/admin/tasks/stages"
                className="ui-iconbtn ui-iconbtn--md"
                aria-label="Настроить воронки"
                title="Настроить воронки"
              >
                <GearGlyph />
              </Link>
            )}
          </>
        )}
      />
```

- [ ] **Шаг 2: заменить два ряда управления на один**

Удалить блок `.tasks-page__toolbar` целиком (поле «Воронка» переехало в табы) и заменить
`.tasks-filterbar` на один ряд:

```tsx
          <div className="tasks-filterbar">
            <TaskSegments values={filterValues} onApply={applyFilters} />
            <SelectInput
              className="tasks-filterbar__select"
              value={sp.get('priority') ?? ''}
              onChange={(e) => setFilter('priority', e.target.value)}
              options={priorityOptions}
            />
            <SelectInput
              className="tasks-filterbar__select"
              value={sp.get('tag_id') ?? ''}
              onChange={(e) => setFilter('tag_id', e.target.value)}
              options={tagOptions}
            />
            {selectedBoardId != null && (
              <TaskFiltersPopover
                boardId={selectedBoardId}
                values={filterValues}
                onSet={setFilter}
                onReset={resetAdvancedFilters}
              />
            )}
            <SearchInput
              value={sp.get('q') ?? ''}
              onChange={(v) => setFilter('q', v)}
              placeholder="Поиск задач: название, #124, ученик…"
              width={280}
            />
            <div className="tasks-filterbar__spacer" />
            <div className="segmented" role="group" aria-label="Вид раздела">
              {/* кнопки «Доска» / «Неделя» — без изменений */}
            </div>
          </div>
```

- [ ] **Шаг 3: добавить недостающие обработчики**

```tsx
  // Плоский снимок фильтров из URL — сегменты и popover читают его, чтобы
  // подсветить активное состояние, и не заводят своего состояния.
  const filterValues = useMemo(() => Object.fromEntries(
    FILTER_KEYS.map((k) => [k, sp.get(k) ?? '']),
  ), [spKey]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Записать несколько ключей разом: сегменту нужно снять чужие и поставить свой. */
  const applyFilters = (patch: Record<string, string>) => {
    const next = new URLSearchParams(sp);
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value); else next.delete(key);
    }
    setSp(next, { replace: true });
  };

  const resetAdvancedFilters = () => {
    applyFilters({ stage_id: '', due: '', priority: '', task_type_id: '', only_open: '' });
  };
```

Константу `FILTER_KEYS` расширить: `['assignee_id', 'priority', 'tag_id', 'only_open',
'overdue', 'q', 'due', 'stage_id', 'task_type_id']`.

Объект `filters` дополнить новыми ключами:

```tsx
    due: (sp.get('due') as TaskFilters['due']) || undefined,
    stage_id: sp.get('stage_id') ? Number(sp.get('stage_id')) : undefined,
    task_type_id: sp.get('task_type_id') ? Number(sp.get('task_type_id')) : undefined,
```

**Осторожно:** `stage_id` в `filters` уезжает и в `useTaskColumnCards`, который сам задаёт
стадию колонки. Проверить `TaskColumn`: если `filters.stage_id` перекроет стадию колонки,
колонки покажут одно и то же. Если перекрывает — вырезать `stage_id` из объекта, который
`TaskBoard` передаёт колонкам, и оставить его только для недельного вида и счётчиков.

- [ ] **Шаг 4: подключить модалку создания**

```tsx
  const [createOpen, setCreateOpen] = useState(false);
  …
      {selectedBoardId != null && (
        <TaskCreateModal
          open={createOpen}
          onOpenChange={setCreateOpen}
          boardId={selectedBoardId}
          onCreated={openTask}
        />
      )}
```

- [ ] **Шаг 5: стили одного ряда**

В `tasks.css` переписать `.tasks-filterbar`: один флекс-ряд с `flex-wrap: wrap`,
`gap: var(--space-2)`, `align-items: center`; `.tasks-filterbar__spacer { flex: 1 }`
отжимает переключатель вида вправо. Удалить `.tasks-filterbar__row`,
`.tasks-filterbar__reset-row`, `.tasks-page__toolbar` и `.tasks-filterbar__assignee`,
если они больше не используются.

- [ ] **Шаг 6: проверить типы и глазами**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
Открыть `/admin/tasks`: два ряда вместо трёх, «+ Новая задача» справа в шапке, сегменты
переключаются и подсвечиваются, «Фильтры» показывает счётчик, поиск по `#124` открывает
нужную задачу в выдаче, переключатель вида прижат вправо.

---

## Задача 18: inline-редактирование значения

**Файлы:**
- Создать: `journal_django/frontend/admin-src/src/pages/tasks/InlineEdit.tsx`
- Изменить: `journal_django/frontend/admin-src/src/styles/pages/tasks.css`

- [ ] **Шаг 1: написать компонент**

```tsx
import { useState, type ReactNode } from 'react';

interface Props {
  /** Подпись поля: «Срок», «Приоритет». */
  label: string;
  /** Что видно, пока не редактируют. Пустое значение — прочерк. */
  display: ReactNode;
  /** Контрол правки. Получает функцию закрытия — вызвать её после сохранения. */
  children: (done: () => void) => ReactNode;
}

/**
 * Значение текстом, редактор — по клику.
 *
 * Панель задачи была длинной формой: каждое свойство выглядело как поле ввода,
 * хотя чаще всего карточку просто читают. Здесь по умолчанию виден результат,
 * а контрол появляется только когда его позвали.
 */
export function InlineEdit({ label, display, children }: Props) {
  const [editing, setEditing] = useState(false);
  const done = () => setEditing(false);

  return (
    <div className="inline-edit">
      <div className="inline-edit__label">{label}</div>
      {editing ? (
        <div className="inline-edit__control">{children(done)}</div>
      ) : (
        <button
          type="button"
          className="inline-edit__value"
          onClick={() => setEditing(true)}
        >
          <span>{display}</span>
          <PencilGlyph />
        </button>
      )}
    </div>
  );
}

function PencilGlyph() {
  return (
    <svg className="inline-edit__pencil" width="13" height="13" viewBox="0 0 24 24"
         fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
    </svg>
  );
}
```

- [ ] **Шаг 2: стили**

В `tasks.css`:
- `.inline-edit` — строка с подписью сверху (`--fs-2xs`, `text-transform: uppercase`,
  `letter-spacing: .06em`, `color: var(--text3)`) и значением под ней;
- `.inline-edit__value` — кнопка без рамки и фона, во всю ширину, выравнивание по левому
  краю, `color: var(--text)`; на hover — подложка `var(--bg2)` и скругление `var(--r-sm)`;
- `.inline-edit__pencil` — `opacity: 0`, на `.inline-edit__value:hover` и `:focus-visible` →
  `opacity: .6`.

- [ ] **Шаг 3: проверить типы**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`

---

## Задача 19: переработать панель задачи

**Файлы:**
- Изменить: `journal_django/frontend/admin-src/src/pages/tasks/TaskDrawer.tsx`
- Изменить: `journal_django/frontend/admin-src/src/styles/pages/tasks.css`

- [ ] **Шаг 1: шапка и статус**

Заголовок перестаёт быть постоянным `<input>`: показывается текстом, по клику превращается
в `TextInput` (тем же приёмом, что `InlineEdit`, но во всю ширину и без подписи). Рядом —
`ActionMenu` с пунктами:

```tsx
              <ActionMenu
                label="Действия с задачей"
                items={[
                  { label: 'Дублировать', onSelect: handleDuplicate },
                  { label: 'Удалить', onSelect: handleDelete, danger: true,
                    disabled: !canDeleteTask(me?.role as Role),
                    hint: 'Удалять задачи может только администратор' },
                ]}
              />
```

Пункты «Изменить» и «Перенести» из ТЗ не заводим: правка теперь inline прямо в панели,
а перенос делается перетаскиванием и сменой стадии — отдельные пункты меню дублировали бы
уже существующие пути. Дублирование — `create` с полями текущей задачи и заголовком
`«<title> (копия)»`. Удаление — `remove` с подтверждением через `ConfirmModal`.

Проверить в `lib/permissions.ts`, есть ли готовый предикат для роли admin/superadmin
(бэкенд на DELETE требует `IsAdminOrSuperAdmin`). Если нет — добавить рядом с
`canWriteTaskStages`, по тому же образцу.

Под шапкой — строка статуса: точка цветом стадии (`stageTone(task.stage_color,
task.stage_label).bg`) и подпись стадии. Кнопка «Выполнено» остаётся справа от неё.

- [ ] **Шаг 2: блоки КОНТЕКСТ и СВОЙСТВА**

Заменить сплошной `.task-drawer__fields` на два блока с заголовками. Каждое поле — через
`InlineEdit`. Пример для срока:

```tsx
              <InlineEdit
                label="Срок"
                display={task.due_date ? fmtDate(task.due_date) : '—'}
              >
                {(done) => (
                  <DateInput
                    value={task.due_date ?? ''}
                    autoFocus
                    onChange={(e) => { save({ due_date: e.target.value || null }); done(); }}
                    onBlur={done}
                  />
                )}
              </InlineEdit>
```

КОНТЕКСТ: исполнитель, ученик, группа (у ученика и группы под значением остаётся ссылка
`EntityLink` «Открыть карточку →»).
СВОЙСТВА: срок, приоритет, тип, теги (у тегов `display` — список меток или «—», редактор —
существующий набор `Checkbox`).

Локальный буфер `tagIds` и его ре-синхронизация по `task?.id` сохраняются: два быстрых
клика по разным тегам до ответа сервера иначе роняют первую правку.

- [ ] **Шаг 3: описание**

```tsx
              <div className="task-drawer__section">
                <div className="task-drawer__section-title">Описание</div>
                {descriptionOpen || task.description ? (
                  <Textarea
                    className="task-drawer__description-input"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    onBlur={handleDescriptionBlur}
                    rows={4}
                    placeholder="Описание задачи…"
                  />
                ) : (
                  <button
                    type="button"
                    className="task-drawer__add-description"
                    onClick={() => setDescriptionOpen(true)}
                  >
                    Добавить описание…
                  </button>
                )}
              </div>
```

- [ ] **Шаг 4: разделить комментарии и историю**

```tsx
  const comments = (activity || []).filter((a) => a.kind === 'comment');
  const history = (activity || []).filter((a) => a.kind !== 'comment');
```

Блок КОММЕНТАРИИ: список (автор, дата, текст) или «Пока нет комментариев», ниже — поле
ввода и кнопка «Добавить» (существующая логика `handleAddComment` не меняется).

Блок ИСТОРИЯ: `history` в обратном порядке (новые сверху) в виде timeline —
`<ol className="task-timeline">`, каждый пункт с точкой, датой, автором и описанием.

- [ ] **Шаг 5: научить ленту читать новые системные записи**

В `ActivityLine` ветка `default` сейчас показывает голый `item.text`. Новые записи правок
приходят без текста, с `meta = {field, from, to}`. Добавить перед `default`:

```tsx
    case 'system': {
      // Записи о создании задачи и о смене тегов приходят с готовым text и без
      // meta.field — их показываем как есть. Правки полей приходят наоборот.
      const field = meta.field ? String(meta.field) : null;
      if (!field) { body = <>{item.text}</>; break; }
      body = (
        <>
          {TASK_FIELD_LABELS[field] || field}: {formatFieldValue(field, meta.from, refs)}
          {' → '}
          {formatFieldValue(field, meta.to, refs)}
        </>
      );
      break;
    }
```

`refs` — новый проп `ActivityLine`, справочники для расшифровки id:

```tsx
interface ActivityRefs {
  types: TaskType[] | undefined;
  students: { id: number; full_name: string }[] | undefined;
  groups: { id: number; name: string }[] | undefined;
}
```

`TaskDrawer` собирает его один раз из уже загруженных `useTaskTypes()`, `useStudentsAll()`,
`useGroupsAll()` и передаёт в каждый `<ActivityLine>` — новых запросов не появляется.

`TASK_FIELD_LABELS` добавить в `lib/labels.ts` (подписи enum'ов и полей живут только там):

```ts
export const TASK_FIELD_LABELS: Record<string, string> = {
  title: 'Заголовок',
  description: 'Описание',
  due_date: 'Срок',
  priority: 'Приоритет',
  task_type_id: 'Тип',
  student_id: 'Ученик',
  group_id: 'Группа',
};
```

`formatFieldValue` — локальная функция в `TaskDrawer.tsx`: `null` → «—», `due_date` →
`fmtDate`, `priority` → `TASK_PRIORITY_LABELS`, `task_type_id` → название из `useTaskTypes`,
`student_id` → имя из `useStudentsAll`, `group_id` → название из `useGroupsAll`, остальное →
строка как есть. Именно ради этого бэкенд кладёт в `meta` сырые id, а не готовый текст.

- [ ] **Шаг 6: проверить типы и глазами**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
Открыть задачу: панель читается как карточка, не как форма; клик по сроку открывает
календарь и сразу сохраняет; пустое описание — строка-приглашение; комментарии отдельно от
истории; в истории видно смену срока и приоритета человеческими словами.

---

## Задача 20: недельный вид

**Файлы:**
- Изменить: `journal_django/frontend/admin-src/src/pages/tasks/TaskWeekView.tsx`
- Изменить: `journal_django/frontend/admin-src/src/styles/pages/tasks.css`

- [ ] **Шаг 1: карточки без дублирующей даты**

В отрисовке карточек добавить `compact`:

```tsx
                    <TaskCard key={task.id} task={task} stageId={task.stage_id}
                              onOpen={onOpen} compact />
```

- [ ] **Шаг 2: «Сегодня» видна всегда**

Заменить условный рендер кнопки на постоянный, с блокировкой на текущей неделе:

```tsx
        <button
          type="button"
          className="task-week__today-btn"
          disabled={isCurrentWeek}
          onClick={() => goWeek(currentMonday)}
        >
          Сегодня
        </button>
```

- [ ] **Шаг 3: мягкая подсветка текущего дня**

В `tasks.css` в правиле `.task-week__col.is-today` заменить рамку на фон и акцентную дату:

```css
.task-week__col.is-today {
  background: color-mix(in oklab, var(--accent) 6%, var(--bg3));
  border-color: color-mix(in oklab, var(--accent) 25%, var(--border));
}

.task-week__col.is-today .task-week__col-date {
  color: var(--accent);
  font-weight: 600;
}
```

Проверить имя акцентного токена в `styles/tokens.css` перед использованием — если акцент
называется иначе, взять фактическое имя. Hardcode цвета запрещён.

- [ ] **Шаг 4: плотность**

Сократить `gap` и `padding` в `.task-week__grid`, `.task-week__col`, `.task-week__col-head`
на одну ступень токенов — недельный вид должен дышать так же, как доска.

- [ ] **Шаг 5: проверить типы и глазами**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
Открыть вид «Неделя»: в карточках нет даты, «Сегодня» на месте и заблокирована на текущей
неделе, текущий день видно, но он не похож на поле в фокусе.

---

## Задача 21: финальная проверка

**Файлы:** без изменений кода, если ничего не всплывёт.

- [ ] **Шаг 1: полный прогон бэкенда**

Запустить: `cd journal_django && pytest -q`
Ожидаемо: ни одного падения.

- [ ] **Шаг 2: типы фронта**

Запустить: `cd journal_django/frontend/admin-src && npm run typecheck`
Ожидаемо: без ошибок.

- [ ] **Шаг 3: пройти сценарии ТЗ руками**

1. Создать задачу: «+ Новая задача» → название → «Создать».
2. Создать задачу в колонке: «+ Добавить задачу» → название → Enter.
3. Сменить статус перетаскиванием; отменить из toast'а.
4. Закрыть перетаскиванием в «Готово»; изменить результат из toast'а.
5. Сменить срок из панели в два клика.
6. «Мои задачи» → «Сегодня» → «Просроченные» → «Все».
7. Найти задачу по `#<номер>`, по фамилии ученика, по имени исполнителя, по метке.
8. Проверить «Продления» — доска не сломалась общей шапкой колонки.
9. Проверить блок задач на странице ученика — он ходит в тот же список.

- [ ] **Шаг 4: отчитаться заказчику**

Показать, что сделано, что осталось за рамками (вид «Список», P2), и спросить про коммит —
сам не коммитить.

---

## Самопроверка плана

**Покрытие спеки:**

| Раздел спеки | Задача |
|---|---|
| 3.1 умный поиск | 1 |
| 3.2 фильтр `due` | 2 |
| 3.3 история правок | 3 (бэк) + 19 шаг 5 (рендер) |
| 3.4 `comments_count` | 4 (бэк) + 9 (тип) + 10 (карточка) |
| 4 общая шапка стадии | 5, 6, 7 |
| 5.1 табы воронок | 14, 17 |
| 5.2 CTA «+ Новая задача» | 13, 17 |
| 5.3 сегменты | 15, 17 |
| 5.4 popover «Фильтры» | 16, 17 |
| 6 карточка | 10 |
| 7 панель задачи | 18, 19 |
| 8 toast и отмена | 8, 12 |
| 9 недельный вид | 20 |
| 10 быстрое добавление | 11 |
| 12 проверка | 21 |

**Известная развилка, требующая решения при исполнении:** `stage_id` в общем объекте
`filters` (задача 17, шаг 3) может перекрыть стадию колонки на доске. Проверить и, если
перекрывает, не передавать `stage_id` в `TaskColumn`.
