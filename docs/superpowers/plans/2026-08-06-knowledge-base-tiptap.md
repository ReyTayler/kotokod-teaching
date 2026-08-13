# База знаний на TipTap — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Раздел «База знаний» в admin SPA — документы на TipTap с правами чтения по ролям, черновиками и оптимизированными картинками.

**Architecture:** Новое Django-приложение `apps/knowledge` со стандартной раскладкой проекта (`models` → `repository` → `services` → `views`). Контент документа — TipTap-JSON в `jsonb`, валидируется на входе по белому списку узлов; на чтении рендерится React-элементами через `@tiptap/static-renderer`, поэтому HTML из строки не собирается и санитайзер не нужен. Картинки лежат на диске под именем sha256, оптимизируются в Celery, отдаются через `X-Accel-Redirect` с проверкой прав по таблице использований.

**Tech Stack:** Django 5.1.4 + DRF, PostgreSQL (jsonb, `text[]` + GIN), Celery, Pillow 12.2.0 (уже в requirements), React 19 + TanStack Query v5 + TipTap 3.29.2.

**Спека:** `docs/superpowers/specs/2026-08-06-knowledge-base-tiptap-design.md`

---

## Как исполнять этот план

**Коммиты — только по явной просьбе пользователя.** Это правило проекта (`CLAUDE.md`), оно перекрывает дефолт навыка. Поэтому вместо шага «Commit» в конце каждой задачи стоит **контрольная точка**: показать `git status --short` и `git diff`, дождаться ревью, дальше не идти. Если пользователь заранее разрешил коммитить — коммить с сообщением, указанным в задаче.

**Прогон тестов.** Точечно во время задачи: `pytest apps/knowledge/tests/test_x.py -v` из каталога `journal_django/`. В самом конце (Task 21) — **полный** `pytest -q`, не по приложениям: часть приложений no-op'ит `django_db_setup`, и прогон по частям даёт ложнозелёный результат.

**Новых Python-зависимостей не нужно** — Pillow уже стоит ради QR-кодов 2FA.

---

## Структура файлов

**Бэкенд** — `journal_django/apps/knowledge/`

| файл | ответственность |
|---|---|
| `models.py` | четыре модели и их ограничения |
| `content.py` | чистые функции над TipTap-JSON: валидация, plain text, сбор id картинок. В БД не ходит |
| `permissions.py` | один permission-класс раздела |
| `repository.py` | весь доступ к данным, включая фильтр видимости по роли |
| `services.py` | оркестрация: сохранение документа + пересборка использований, публикация |
| `images.py` | работа с файловой системой: пути, потоковый sha256, приём файла, разбор картинки Pillow |
| `serializers.py` | валидация входа DRF |
| `views.py` | разделы и документы |
| `image_views.py` | загрузка и отдача картинок |
| `tasks.py` | Celery: оптимизация и уборка |
| `urls.py` | маршруты |
| `management/commands/knowledge_optimize_pending.py` | догнать зависшие в `pending` |
| `tests/` | `test_content.py`, `test_sections_api.py`, `test_documents_api.py`, `test_permissions_matrix.py`, `test_images.py` |

`images.py` отделён от `image_views.py` намеренно: обращения к диску тестируются без HTTP-слоя.

**Фронт** — `journal_django/frontend/admin-src/src/`

| файл | ответственность |
|---|---|
| `lib/knowledge.ts` | типы раздела |
| `hooks/useKnowledge.ts` | TanStack Query: запросы и мутации |
| `pages/knowledge/KnowledgeListPage.tsx` | разделы + список документов |
| `pages/knowledge/KnowledgeDocumentPage.tsx` | чтение документа |
| `pages/knowledge/KnowledgeEditPage.tsx` | обвязка редактора: заголовок, права, кнопки |
| `components/knowledge/DocumentView.tsx` | рендер JSON через static-renderer |
| `components/knowledge/DocumentEditor.tsx` | сам TipTap, грузится через `React.lazy` |
| `components/knowledge/EditorToolbar.tsx` | кнопки форматирования |
| `components/knowledge/KnowledgeImageExtension.ts` | узел `knowledgeImage` с атрибутом `imageId` |
| `components/knowledge/ReaderRolesField.tsx` | галочки ролей-читателей |
| `styles/knowledge.css` | типографика документа на токенах |

---

## Task 1: Приложение и модели

**Files:**
- Create: `journal_django/apps/knowledge/__init__.py`
- Create: `journal_django/apps/knowledge/apps.py`
- Create: `journal_django/apps/knowledge/models.py`
- Create: `journal_django/apps/knowledge/migrations/__init__.py`
- Create: `journal_django/apps/knowledge/tests/__init__.py`
- Modify: `journal_django/config/settings/base.py` (`INSTALLED_APPS`, настройки медиа)

- [ ] **Step 1: Создать каталоги и пустые файлы**

```powershell
New-Item -ItemType Directory -Force journal_django/apps/knowledge/migrations
New-Item -ItemType Directory -Force journal_django/apps/knowledge/tests
New-Item -ItemType File journal_django/apps/knowledge/__init__.py
New-Item -ItemType File journal_django/apps/knowledge/migrations/__init__.py
New-Item -ItemType File journal_django/apps/knowledge/tests/__init__.py
```

- [ ] **Step 2: `apps.py`**

```python
"""AppConfig раздела «База знаний»."""
from __future__ import annotations

from django.apps import AppConfig


class KnowledgeConfig(AppConfig):
    default_auto_field = 'django.db.models.AutoField'
    name = 'apps.knowledge'
    label = 'knowledge'
    verbose_name = 'База знаний'
```

- [ ] **Step 3: `models.py`**

```python
"""
Модели раздела «База знаний».

Четыре таблицы:
  knowledge_sections      — разделы (два уровня: раздел → документы)
  knowledge_documents     — документы, контент — TipTap-JSON в jsonb
  knowledge_images        — картинки, адресуемые содержимым (sha256)
  knowledge_image_usages  — где какая картинка используется (права + уборка)

pghistory здесь НЕ применяется — решение пользователя (спека 2026-08-06).
"""
from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.core.db_fields import TolerantJSONField

# Роли, которые можно выдать в reader_roles. Совпадает с Account.Role.
READER_ROLES = ['teacher', 'manager', 'admin', 'superadmin']

# Роли, видящие всё: и черновики, и документы с пустым reader_roles.
FULL_ACCESS_ROLES = ('admin', 'superadmin')


class KnowledgeSection(models.Model):
    """Раздел базы знаний («Методика», «Продажи»)."""

    id = models.AutoField(primary_key=True)
    title = models.TextField(unique=True)
    position = models.IntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = 'knowledge_sections'
        indexes = [
            models.Index(
                fields=['position'], name='knowledge_sect_pos_idx',
                condition=models.Q(active=True),
            ),
        ]

    def __str__(self):
        return self.title


class KnowledgeDocument(models.Model):
    """Документ базы знаний. Источник правды по содержимому — поле content."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Черновик'
        PUBLISHED = 'published', 'Опубликован'

    id = models.AutoField(primary_key=True)
    section = models.ForeignKey(
        'knowledge.KnowledgeSection',
        on_delete=models.PROTECT,
        related_name='documents',
    )
    title = models.TextField()

    # ВАЖНО: TolerantJSONField, а не JSONField. Проект глобально регистрирует
    # jsonb-typecaster psycopg2 (apps/core/apps.py), из-за чего штатный JSONField
    # на чтении падает с «the JSON object must be str ... not dict».
    content = TolerantJSONField(default=dict)

    # Плоский текст документа. Пишет сервер при каждом сохранении
    # (content.extract_plain_text), клиент это поле не присылает.
    plain_text = models.TextField(default='', blank=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT,
    )
    reader_roles = ArrayField(
        models.CharField(max_length=20), default=list, blank=True,
    )
    position = models.IntegerField(default=0)
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='knowledge_documents_created',
    )
    updated_by = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='knowledge_documents_updated',
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = 'knowledge_documents'
        indexes = [
            models.Index(
                fields=['section', 'position'], name='knowledge_doc_secpos_idx',
                condition=models.Q(active=True),
            ),
            GinIndex(fields=['reader_roles'], name='knowledge_doc_roles_gin'),
            models.Index(
                fields=['status'], name='knowledge_doc_pub_idx',
                condition=models.Q(status='published'),
            ),
        ]
        constraints = [
            models.CheckConstraint(
                name='knowledge_doc_status_check',
                condition=models.Q(status__in=['draft', 'published']),
            ),
            models.CheckConstraint(
                name='knowledge_doc_roles_check',
                condition=models.Q(reader_roles__contained_by=READER_ROLES),
            ),
        ]

    def __str__(self):
        return self.title


class KnowledgeImage(models.Model):
    """
    Картинка, адресуемая содержимым: имя файла на диске — её sha256.

    Дедупликация: повторная загрузка того же файла возвращает существующую
    запись, второй копии на диске не появляется.
    """

    class OptimizeState(models.TextChoices):
        PENDING = 'pending', 'В очереди'
        READY = 'ready', 'Готово'
        FAILED = 'failed', 'Ошибка'

    id = models.AutoField(primary_key=True)
    sha256 = models.CharField(max_length=64, unique=True)
    original_name = models.TextField()
    mime = models.CharField(max_length=50)
    byte_size = models.BigIntegerField()
    width = models.IntegerField()
    height = models.IntegerField()
    original_path = models.TextField()
    optimized_path = models.TextField(null=True, blank=True)
    thumb_path = models.TextField(null=True, blank=True)
    optimize_state = models.CharField(
        max_length=10, choices=OptimizeState.choices, default=OptimizeState.PENDING,
    )
    uploaded_by = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='knowledge_images',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'knowledge_images'
        indexes = [
            models.Index(
                fields=['optimize_state'], name='knowledge_img_state_idx',
                condition=models.Q(optimize_state='pending'),
            ),
        ]


class KnowledgeImageUsage(models.Model):
    """
    Где используется картинка. Пересобирается при каждом сохранении документа.

    Нужна для двух вещей: прав на отдачу файла (видишь документ — видишь
    картинку) и уборки осиротевших файлов.
    """

    id = models.AutoField(primary_key=True)
    image = models.ForeignKey(
        KnowledgeImage, on_delete=models.CASCADE, related_name='usages',
    )
    document = models.ForeignKey(
        KnowledgeDocument, on_delete=models.CASCADE, related_name='image_usages',
    )

    class Meta:
        managed = True
        db_table = 'knowledge_image_usages'
        constraints = [
            models.UniqueConstraint(
                fields=['image', 'document'], name='knowledge_img_usage_uq',
            ),
        ]
```

- [ ] **Step 4: Зарегистрировать приложение и настройки**

В `config/settings/base.py` в `INSTALLED_APPS` добавить две строки — `django.contrib.postgres` (нужен для `ArrayField`-lookup'ов и `GinIndex`) и само приложение. Ставить в конец списка, после `'apps.notifications',`:

```python
    'apps.notifications',
    'django.contrib.postgres',
    'apps.knowledge',
]
```

Там же, рядом с блоком `NOTIFICATIONS_HISTORY_LIMIT` (примерно строка 282), добавить настройки раздела:

```python
# ---------------------------------------------------------------------------
# База знаний (apps.knowledge) — хранилище картинок
# ---------------------------------------------------------------------------
# Корень файлового хранилища. Локально — journal_django/media (в .gitignore),
# на проде — отдельный каталог вне репозитория.
KNOWLEDGE_MEDIA_ROOT: str = env('KNOWLEDGE_MEDIA_ROOT', default=str(BASE_DIR / 'media'))

# Префикс internal-локации nginx для X-Accel-Redirect. Пусто → Django отдаёт
# файл сам через FileResponse (локальная разработка на runserver без nginx).
KNOWLEDGE_X_ACCEL_PREFIX: str = env('KNOWLEDGE_X_ACCEL_PREFIX', default='')

# Потолок размера загружаемой картинки.
KNOWLEDGE_MAX_IMAGE_BYTES: int = 10 * 1024 * 1024

# Защита от декомпрессионных бомб: 2 МБ файла могут развернуться в гигабайты RAM.
KNOWLEDGE_MAX_IMAGE_PIXELS: int = 50_000_000
```

В `REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']` (примерно строка 317) добавить лимит загрузки:

```python
    'DEFAULT_THROTTLE_RATES': {
        'bot_service': '120/min',
        # Загрузка картинок базы знаний — чтобы не залить диск (apps/knowledge).
        'knowledge_upload': '60/min',
    },
```

- [ ] **Step 5: Добавить каталог медиа в .gitignore**

В корневой `.gitignore` дописать:

```
journal_django/media/
```

- [ ] **Step 6: Сгенерировать миграцию**

```powershell
cd journal_django; python manage.py makemigrations knowledge
```
Ожидается: `Migrations for 'knowledge': apps/knowledge/migrations/0001_initial.py` с созданием четырёх моделей.

- [ ] **Step 7: Применить миграцию на тестовой БД и убедиться, что схема сходится**

```powershell
cd journal_django; python manage.py makemigrations --check --dry-run
```
Ожидается: `No changes detected` — значит модели и миграция согласованы.

- [ ] **Step 8: Контрольная точка**

Показать `git status --short`, дождаться ревью. Сообщение коммита, если разрешён: `feat(knowledge): модели раздела «База знаний»`

---

## Task 2: Валидация контента и plain text

Чистый модуль без БД — самая тестируемая часть раздела и единственный барьер между клиентом и колонкой `jsonb`.

**Files:**
- Create: `journal_django/apps/knowledge/content.py`
- Test: `journal_django/apps/knowledge/tests/test_content.py`

- [ ] **Step 1: Написать падающий тест**

`journal_django/apps/knowledge/tests/test_content.py`:

```python
"""
Тесты чистого модуля content.py — валидация TipTap-JSON и извлечение текста.

БД не нужна: модуль не ходит в базу, множество допустимых id картинок ему
передаётся аргументом.
"""
from __future__ import annotations

import pytest

from apps.knowledge import content


def _doc(*nodes) -> dict:
    return {'type': 'doc', 'content': list(nodes)}


def _para(text: str) -> dict:
    return {'type': 'paragraph', 'content': [{'type': 'text', 'text': text}]}


# ---------------------------------------------------------------------------
# validate_content
# ---------------------------------------------------------------------------

def test_valid_document_passes():
    content.validate_content(_doc(_para('Привет')))


def test_root_must_be_doc():
    with pytest.raises(content.ContentError, match='root'):
        content.validate_content({'type': 'paragraph'})


def test_unknown_node_type_rejected():
    with pytest.raises(content.ContentError, match='script'):
        content.validate_content(_doc({'type': 'script', 'content': []}))


def test_unknown_mark_rejected():
    node = {'type': 'text', 'text': 'x', 'marks': [{'type': 'evil'}]}
    with pytest.raises(content.ContentError, match='evil'):
        content.validate_content(_doc({'type': 'paragraph', 'content': [node]}))


def test_allowed_marks_pass():
    node = {'type': 'text', 'text': 'x', 'marks': [{'type': 'bold'}, {'type': 'italic'}]}
    content.validate_content(_doc({'type': 'paragraph', 'content': [node]}))


def test_link_href_must_be_http_or_relative():
    def linked(href):
        return _doc({'type': 'paragraph', 'content': [
            {'type': 'text', 'text': 'x',
             'marks': [{'type': 'link', 'attrs': {'href': href}}]},
        ]})

    content.validate_content(linked('https://example.com'))
    content.validate_content(linked('/admin/students'))
    with pytest.raises(content.ContentError, match='href'):
        content.validate_content(linked('javascript:alert(1)'))


def test_too_deep_rejected():
    node = {'type': 'paragraph', 'content': []}
    deep = node
    for _ in range(content.MAX_DEPTH + 2):
        deep = {'type': 'blockquote', 'content': [deep]}
    with pytest.raises(content.ContentError, match='глубин'):
        content.validate_content(_doc(deep))


def test_too_large_rejected():
    big = _doc(_para('я' * (content.MAX_CONTENT_BYTES)))
    with pytest.raises(content.ContentError, match='размер'):
        content.validate_content(big)


def test_image_must_reference_known_id():
    doc = _doc({'type': 'knowledgeImage', 'attrs': {'imageId': 7}})
    with pytest.raises(content.ContentError, match='7'):
        content.validate_content(doc, allowed_image_ids={1, 2})
    content.validate_content(doc, allowed_image_ids={7})


def test_image_without_id_rejected():
    doc = _doc({'type': 'knowledgeImage', 'attrs': {}})
    with pytest.raises(content.ContentError, match='imageId'):
        content.validate_content(doc, allowed_image_ids={1})


# ---------------------------------------------------------------------------
# collect_image_ids
# ---------------------------------------------------------------------------

def test_collect_image_ids_finds_nested():
    doc = _doc(
        {'type': 'knowledgeImage', 'attrs': {'imageId': 3}},
        {'type': 'blockquote', 'content': [
            {'type': 'knowledgeImage', 'attrs': {'imageId': 5}},
        ]},
    )
    assert content.collect_image_ids(doc) == {3, 5}


def test_collect_image_ids_empty():
    assert content.collect_image_ids(_doc(_para('нет картинок'))) == set()


# ---------------------------------------------------------------------------
# extract_plain_text
# ---------------------------------------------------------------------------

def test_extract_plain_text_joins_blocks():
    doc = _doc(
        {'type': 'heading', 'attrs': {'level': 2},
         'content': [{'type': 'text', 'text': 'Заголовок'}]},
        _para('Первый абзац'),
        _para('Второй абзац'),
    )
    assert content.extract_plain_text(doc) == 'Заголовок\nПервый абзац\nВторой абзац'


def test_extract_plain_text_handles_empty_doc():
    assert content.extract_plain_text({'type': 'doc', 'content': []}) == ''


def test_extract_plain_text_keeps_inline_text_together():
    doc = _doc({'type': 'paragraph', 'content': [
        {'type': 'text', 'text': 'жирный '},
        {'type': 'text', 'text': 'и обычный'},
    ]})
    assert content.extract_plain_text(doc) == 'жирный и обычный'
```

- [ ] **Step 2: Убедиться, что тест падает**

```powershell
cd journal_django; pytest apps/knowledge/tests/test_content.py -v
```
Ожидается: `ModuleNotFoundError: No module named 'apps.knowledge.content'` (собирается 0 тестов, ошибка на импорте).

- [ ] **Step 3: Написать `content.py`**

```python
"""
Чистые функции над TipTap-JSON. В БД не ходят, HTTP не знают.

Это единственный барьер между клиентом и колонкой content: всё, что не прошло
validate_content, в базу не попадает. Безопасность рендера обеспечивается здесь,
на входе, а не санитайзером на выходе — читатель получает JSON, из которого
фронт строит React-элементы, а не HTML-строку.
"""
from __future__ import annotations

import json

# Типы узлов, которые умеет показать DocumentView. Расширять этот список можно
# только вместе с рендерером — иначе документ сохранится, но не отобразится.
ALLOWED_NODES = frozenset({
    'doc', 'paragraph', 'text', 'heading',
    'bulletList', 'orderedList', 'listItem',
    'blockquote', 'codeBlock', 'horizontalRule', 'hardBreak',
    'table', 'tableRow', 'tableHeader', 'tableCell',
    'knowledgeImage',
})

ALLOWED_MARKS = frozenset({'bold', 'italic', 'strike', 'code', 'link'})

# Схемы ссылок, разрешённые в mark link. javascript: и data: отсекаются.
ALLOWED_LINK_PREFIXES = ('https://', 'http://', 'mailto:', '/')

MAX_CONTENT_BYTES = 512 * 1024
MAX_DEPTH = 20


class ContentError(ValueError):
    """Контент не прошёл проверку. Вьюха превращает это в 400 invalid_content."""


def validate_content(value, *, allowed_image_ids=frozenset()) -> None:
    """
    Проверить документ. Бросает ContentError с человекочитаемым текстом.

    allowed_image_ids — множество id существующих картинок; передаётся сервисом,
    сам модуль в БД не ходит.
    """
    if not isinstance(value, dict) or value.get('type') != 'doc':
        raise ContentError('Корневой узел (root) документа должен быть doc.')

    size = len(json.dumps(value, ensure_ascii=False).encode('utf-8'))
    if size > MAX_CONTENT_BYTES:
        raise ContentError(
            f'Превышен размер документа: {size} байт при лимите {MAX_CONTENT_BYTES}.'
        )

    _walk(value, depth=0, allowed_image_ids=set(allowed_image_ids))


def _walk(node, *, depth: int, allowed_image_ids: set) -> None:
    if depth > MAX_DEPTH:
        raise ContentError(f'Превышена глубина вложенности: максимум {MAX_DEPTH}.')
    if not isinstance(node, dict):
        raise ContentError('Узел документа должен быть объектом.')

    node_type = node.get('type')
    if node_type not in ALLOWED_NODES:
        raise ContentError(f'Неподдерживаемый тип узла: {node_type!r}.')

    for mark in node.get('marks') or []:
        _check_mark(mark)

    if node_type == 'knowledgeImage':
        _check_image(node, allowed_image_ids)

    for child in node.get('content') or []:
        _walk(child, depth=depth + 1, allowed_image_ids=allowed_image_ids)


def _check_mark(mark) -> None:
    if not isinstance(mark, dict):
        raise ContentError('Марка должна быть объектом.')
    mark_type = mark.get('type')
    if mark_type not in ALLOWED_MARKS:
        raise ContentError(f'Неподдерживаемая марка: {mark_type!r}.')
    if mark_type == 'link':
        href = (mark.get('attrs') or {}).get('href') or ''
        if not str(href).startswith(ALLOWED_LINK_PREFIXES):
            raise ContentError(f'Недопустимый href в ссылке: {href!r}.')


def _check_image(node, allowed_image_ids: set) -> None:
    image_id = (node.get('attrs') or {}).get('imageId')
    if not isinstance(image_id, int):
        raise ContentError('У картинки отсутствует числовой imageId.')
    if image_id not in allowed_image_ids:
        raise ContentError(f'Картинка {image_id} не найдена.')


def collect_image_ids(value) -> set[int]:
    """Собрать id всех картинок документа — для пересборки таблицы использований."""
    found: set[int] = set()
    _collect(value, found)
    return found


def _collect(node, found: set[int]) -> None:
    if not isinstance(node, dict):
        return
    if node.get('type') == 'knowledgeImage':
        image_id = (node.get('attrs') or {}).get('imageId')
        if isinstance(image_id, int):
            found.add(image_id)
    for child in node.get('content') or []:
        _collect(child, found)


def extract_plain_text(value) -> str:
    """
    Плоский текст документа: блочные узлы разделяются переводом строки,
    инлайновые куски внутри блока склеиваются.

    Используется для превью в списке; заодно это готовый источник для поиска,
    если он понадобится позже.
    """
    lines: list[str] = []
    _lines(value, lines)
    return '\n'.join(line for line in lines if line)


# Узлы, после которых текст переносится на новую строку.
_BLOCK_NODES = frozenset({
    'paragraph', 'heading', 'blockquote', 'codeBlock', 'listItem',
    'tableCell', 'tableHeader',
})


def _lines(node, lines: list[str]) -> None:
    if not isinstance(node, dict):
        return
    if node.get('type') in _BLOCK_NODES:
        text = _inline_text(node)
        if text:
            lines.append(text)
        # Внутри блока могут быть вложенные блоки (список в списке, цитата
        # в цитате) — их надо обойти отдельно, иначе текст потеряется.
        for child in node.get('content') or []:
            if isinstance(child, dict) and child.get('type') in _BLOCK_NODES:
                _lines(child, lines)
        return
    for child in node.get('content') or []:
        _lines(child, lines)


def _inline_text(node) -> str:
    parts: list[str] = []
    for child in node.get('content') or []:
        if not isinstance(child, dict):
            continue
        if child.get('type') == 'text':
            parts.append(child.get('text') or '')
        elif child.get('type') == 'hardBreak':
            parts.append(' ')
    return ''.join(parts).strip()
```

- [ ] **Step 4: Прогнать тесты**

```powershell
cd journal_django; pytest apps/knowledge/tests/test_content.py -v
```
Ожидается: все тесты PASS.

- [ ] **Step 5: Контрольная точка**

Сообщение коммита, если разрешён: `feat(knowledge): валидация TipTap-JSON и извлечение текста`

---

## Task 3: Права доступа и слой данных

**Files:**
- Create: `journal_django/apps/knowledge/permissions.py`
- Create: `journal_django/apps/knowledge/repository.py`

- [ ] **Step 1: `permissions.py`**

```python
"""
Права раздела «База знаний».

Класс отвечает только на вопрос «пускать ли в эндпоинт». Вопрос «какие строки
показать» решает repository.visible_documents_qs — иначе фильтрация расползётся
по вьюхам и рано или поздно где-то забудется.
"""
from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

# Читать раздел может любая аутентифицированная роль. teacher включён заранее:
# читалка в teacher SPA — следующий этап, и бэкенд к нему уже готов.
READ_ROLES = ('teacher', 'manager', 'admin', 'superadmin')
WRITE_ROLES = ('admin', 'superadmin')


class KnowledgeReadStaffWriteAdmin(BasePermission):
    """SAFE-методы — любая аутентифицированная роль; мутации — admin/superadmin."""

    message = 'Read for authenticated staff; write for admin or superadmin.'

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        # UNAUTHENTICATED_USER=None → без токена request.user is None.
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return user.role in READ_ROLES
        return user.role in WRITE_ROLES
```

- [ ] **Step 2: `repository.py`**

```python
"""
Единственное место доступа к данным раздела «База знаний».

Ключевая функция — visible_documents_qs: фильтр видимости по роли. Условие
уходит в SQL и попадает в GIN-индекс по reader_roles, никаких Python-циклов
по выборке.
"""
from __future__ import annotations

from typing import Optional

from django.db.models import Count, QuerySet

from apps.knowledge.models import (
    FULL_ACCESS_ROLES,
    KnowledgeDocument,
    KnowledgeImage,
    KnowledgeImageUsage,
    KnowledgeSection,
)


# ---------------------------------------------------------------------------
# Разделы
# ---------------------------------------------------------------------------

def list_sections(include_inactive: bool = False) -> list[dict]:
    qs = KnowledgeSection.objects.all()
    if not include_inactive:
        qs = qs.filter(active=True)
    return list(qs.order_by('position', 'title').values(
        'id', 'title', 'position', 'active',
    ))


def get_section(section_id: int) -> Optional[dict]:
    return KnowledgeSection.objects.filter(id=section_id).values(
        'id', 'title', 'position', 'active',
    ).first()


def create_section(title: str) -> dict:
    last = KnowledgeSection.objects.order_by('-position').values_list(
        'position', flat=True,
    ).first()
    obj = KnowledgeSection.objects.create(
        title=title, position=(last or 0) + 1,
    )
    return get_section(obj.id)


def update_section(section_id: int, data: dict) -> Optional[dict]:
    obj = KnowledgeSection.objects.filter(id=section_id).first()
    if obj is None:
        return None
    if 'title' in data:
        obj.title = data['title']
    if 'active' in data:
        obj.active = data['active']
    obj.save()
    return get_section(section_id)


def count_active_documents(section_id: int) -> int:
    """Активные документы раздела — проверка перед удалением (409)."""
    return KnowledgeDocument.objects.filter(
        section_id=section_id, active=True,
    ).count()


def soft_delete_section(section_id: int) -> bool:
    return KnowledgeSection.objects.filter(id=section_id).update(active=False) > 0


def reorder_sections(order: list[int]) -> None:
    for position, section_id in enumerate(order, start=1):
        KnowledgeSection.objects.filter(id=section_id).update(position=position)


# ---------------------------------------------------------------------------
# Документы
# ---------------------------------------------------------------------------

def visible_documents_qs(role: str) -> QuerySet:
    """
    Документы, доступные роли.

    admin/superadmin видят всё, включая черновики и документы с пустым
    reader_roles: иначе документ теряется, стоит снять все галочки.
    Остальные — только опубликованное, где их роль явно указана.
    """
    qs = KnowledgeDocument.objects.filter(active=True)
    if role in FULL_ACCESS_ROLES:
        return qs
    return qs.filter(
        status=KnowledgeDocument.Status.PUBLISHED,
        reader_roles__contains=[role],
    )


# Поля списка: content намеренно не выбирается — незачем тянуть мегабайты jsonb.
_LIST_FIELDS = (
    'id', 'section_id', 'title', 'status', 'reader_roles',
    'position', 'published_at', 'updated_at',
)


def list_documents(role: str, section_id: Optional[int] = None) -> QuerySet:
    qs = visible_documents_qs(role)
    if section_id is not None:
        qs = qs.filter(section_id=section_id)
    return qs.order_by('section_id', 'position', 'id').values(*_LIST_FIELDS)


def get_document(role: str, document_id: int) -> Optional[dict]:
    """Документ с контентом или None, если роли он не виден (вьюха отдаст 404)."""
    return visible_documents_qs(role).filter(id=document_id).values(
        *_LIST_FIELDS, 'content', 'plain_text', 'created_at',
    ).first()


def create_document(*, section_id: int, title: str, account_id: int) -> KnowledgeDocument:
    last = KnowledgeDocument.objects.filter(section_id=section_id).order_by(
        '-position',
    ).values_list('position', flat=True).first()
    return KnowledgeDocument.objects.create(
        section_id=section_id,
        title=title,
        content={'type': 'doc', 'content': []},
        plain_text='',
        status=KnowledgeDocument.Status.DRAFT,
        reader_roles=[],
        position=(last or 0) + 1,
        created_by_id=account_id,
        updated_by_id=account_id,
    )


def get_document_for_write(document_id: int) -> Optional[KnowledgeDocument]:
    """Модель документа для мутаций. Доступ уже проверен permission-классом."""
    return KnowledgeDocument.objects.filter(id=document_id, active=True).first()


def soft_delete_document(document_id: int) -> bool:
    return KnowledgeDocument.objects.filter(id=document_id).update(active=False) > 0


def reorder_documents(section_id: int, order: list[int]) -> None:
    for position, document_id in enumerate(order, start=1):
        KnowledgeDocument.objects.filter(
            id=document_id, section_id=section_id,
        ).update(position=position)


# ---------------------------------------------------------------------------
# Картинки и использования
# ---------------------------------------------------------------------------

def get_image_by_sha256(sha256: str) -> Optional[KnowledgeImage]:
    return KnowledgeImage.objects.filter(sha256=sha256).first()


def get_image(image_id: int) -> Optional[KnowledgeImage]:
    return KnowledgeImage.objects.filter(id=image_id).first()


def existing_image_ids(image_ids) -> set[int]:
    if not image_ids:
        return set()
    return set(KnowledgeImage.objects.filter(
        id__in=list(image_ids),
    ).values_list('id', flat=True))


def sync_image_usages(document_id: int, image_ids: set[int]) -> None:
    """Привести набор использований документа к переданному."""
    KnowledgeImageUsage.objects.filter(document_id=document_id).exclude(
        image_id__in=list(image_ids) or [0],
    ).delete()
    existing = set(KnowledgeImageUsage.objects.filter(
        document_id=document_id,
    ).values_list('image_id', flat=True))
    KnowledgeImageUsage.objects.bulk_create(
        [
            KnowledgeImageUsage(document_id=document_id, image_id=image_id)
            for image_id in image_ids - existing
        ],
        ignore_conflicts=True,
    )


def image_visible_to(role: str, image_id: int) -> bool:
    """
    Картинка видна, если хотя бы один документ, где она используется, доступен
    этой роли. Без этой проверки прямая ссылка на файл обходит ролевую модель.
    """
    return visible_documents_qs(role).filter(
        image_usages__image_id=image_id,
    ).exists()


def orphan_image_ids(older_than) -> list[int]:
    """Картинки без единого использования старше указанного момента."""
    return list(
        KnowledgeImage.objects
        .annotate(usage_count=Count('usages'))
        .filter(usage_count=0, created_at__lt=older_than)
        .values_list('id', flat=True)
    )


def pending_image_ids(limit: int = 100) -> list[int]:
    return list(
        KnowledgeImage.objects
        .filter(optimize_state=KnowledgeImage.OptimizeState.PENDING)
        .order_by('id')
        .values_list('id', flat=True)[:limit]
    )
```

- [ ] **Step 3: Проверить, что модуль импортируется и запросы собираются**

```powershell
cd journal_django; python -c "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.development'); django.setup(); from apps.knowledge import repository; print(repository.visible_documents_qs('manager').query)"
```
Ожидается: SQL-запрос, содержащий `\"reader_roles\" @>` и `status = published`.

- [ ] **Step 4: Контрольная точка**

Сообщение коммита, если разрешён: `feat(knowledge): права и слой доступа к данным`

---

## Task 4: API разделов

**Files:**
- Create: `journal_django/apps/knowledge/serializers.py`
- Create: `journal_django/apps/knowledge/views.py`
- Create: `journal_django/apps/knowledge/urls.py`
- Modify: `journal_django/config/urls.py`
- Test: `journal_django/apps/knowledge/tests/test_sections_api.py`

- [ ] **Step 1: Написать падающий тест**

`journal_django/apps/knowledge/tests/test_sections_api.py`:

```python
"""E2E-тесты /api/admin/knowledge/sections."""
from __future__ import annotations

import pytest
from django.db import connection

BASE_URL = '/api/admin/knowledge/sections'


def _cleanup(title_prefix: str = '__test_kb_') -> None:
    with connection.cursor() as cur:
        # Документы удаляются первыми: FK на раздел объявлен DEFERRABLE INITIALLY
        # DEFERRED, поэтому осиротевшая строка всплывает не здесь, а в
        # check_constraints() при закрытии тестовой транзакции.
        cur.execute(
            'DELETE FROM knowledge_documents WHERE title LIKE %s',
            [f'{title_prefix}%'],
        )
        cur.execute(
            'DELETE FROM knowledge_sections WHERE title LIKE %s',
            [f'{title_prefix}%'],
        )


@pytest.fixture(autouse=True)
def _clean():
    _cleanup()
    yield
    _cleanup()


# --- доступ ---------------------------------------------------------------

@pytest.mark.django_db
def test_anonymous_gets_401(anon_client):
    assert anon_client.get(BASE_URL).status_code == 401


@pytest.mark.django_db
def test_teacher_can_read(teacher_client):
    assert teacher_client.get(BASE_URL).status_code == 200


@pytest.mark.django_db
def test_manager_cannot_create(manager_client):
    resp = manager_client.post(BASE_URL, {'title': '__test_kb_x'}, format='json')
    assert resp.status_code == 403


@pytest.mark.django_db
def test_admin_can_create(admin_client):
    resp = admin_client.post(BASE_URL, {'title': '__test_kb_методика'}, format='json')
    assert resp.status_code == 201
    body = resp.json()
    assert body['title'] == '__test_kb_методика'
    assert body['active'] is True


# --- CRUD ------------------------------------------------------------------

@pytest.mark.django_db
def test_duplicate_title_returns_409(admin_client):
    admin_client.post(BASE_URL, {'title': '__test_kb_dup'}, format='json')
    resp = admin_client.post(BASE_URL, {'title': '__test_kb_dup'}, format='json')
    assert resp.status_code == 409


@pytest.mark.django_db
def test_patch_renames(admin_client):
    created = admin_client.post(BASE_URL, {'title': '__test_kb_a'}, format='json').json()
    resp = admin_client.patch(
        f"{BASE_URL}/{created['id']}", {'title': '__test_kb_b'}, format='json',
    )
    assert resp.status_code == 200
    assert resp.json()['title'] == '__test_kb_b'


@pytest.mark.django_db
def test_delete_empty_section_succeeds(admin_client):
    created = admin_client.post(BASE_URL, {'title': '__test_kb_del'}, format='json').json()
    assert admin_client.delete(f"{BASE_URL}/{created['id']}").status_code == 204


@pytest.mark.django_db
def test_delete_section_with_documents_returns_409(admin_client):
    section = admin_client.post(BASE_URL, {'title': '__test_kb_busy'}, format='json').json()
    admin_client.post(
        '/api/admin/knowledge/documents',
        {'section_id': section['id'], 'title': '__test_kb_doc'},
        format='json',
    )
    resp = admin_client.delete(f"{BASE_URL}/{section['id']}")
    assert resp.status_code == 409
    assert resp.json()['error'] == 'has_documents'


@pytest.mark.django_db
def test_reorder_sets_positions(admin_client):
    first = admin_client.post(BASE_URL, {'title': '__test_kb_1'}, format='json').json()
    second = admin_client.post(BASE_URL, {'title': '__test_kb_2'}, format='json').json()
    resp = admin_client.post(
        f'{BASE_URL}/reorder', {'order': [second['id'], first['id']]}, format='json',
    )
    assert resp.status_code == 200
    titles = [s['title'] for s in admin_client.get(BASE_URL).json()
              if s['title'].startswith('__test_kb_')]
    assert titles == ['__test_kb_2', '__test_kb_1']
```

- [ ] **Step 2: Убедиться, что тест падает**

```powershell
cd journal_django; pytest apps/knowledge/tests/test_sections_api.py -v
```
Ожидается: все тесты FAIL с 404 — маршрутов ещё нет.

- [ ] **Step 3: `serializers.py`**

```python
"""
Валидация входа раздела «База знаний».

Содержимое документа (content) здесь НЕ валидируется — этим занимается
content.validate_content, которому нужен список существующих картинок из БД.
Сериализатор проверяет только, что это объект.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.knowledge.models import READER_ROLES, KnowledgeDocument


class SectionWriteSerializer(serializers.Serializer):
    title = serializers.CharField(min_length=1, max_length=200)

    def validate_title(self, value: str) -> str:
        return value.strip()


class SectionUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(min_length=1, max_length=200, required=False)
    active = serializers.BooleanField(required=False)

    def validate_title(self, value: str) -> str:
        return value.strip()


class ReorderSerializer(serializers.Serializer):
    order = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class DocumentCreateSerializer(serializers.Serializer):
    section_id = serializers.IntegerField()
    title = serializers.CharField(min_length=1, max_length=300)

    def validate_title(self, value: str) -> str:
        return value.strip()


class DocumentUpdateSerializer(serializers.Serializer):
    """
    PATCH документа. Все поля необязательны — форма шлёт то, что изменилось.

    plain_text и published_at клиент не присылает: их пишет сервер.
    """

    title = serializers.CharField(min_length=1, max_length=300, required=False)
    section_id = serializers.IntegerField(required=False)
    content = serializers.JSONField(required=False)
    reader_roles = serializers.ListField(
        child=serializers.ChoiceField(choices=READER_ROLES),
        required=False, allow_empty=True,
    )

    def validate_title(self, value: str) -> str:
        return value.strip()

    def validate_content(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('content должен быть объектом.')
        return value

    def validate_reader_roles(self, value):
        # Дубли безвредны для @>, но в БД им делать нечего.
        return sorted(set(value))


class DocumentReadSerializer(serializers.Serializer):
    """Форма ответа detail-эндпоинта. Используется для документирования формы."""

    id = serializers.IntegerField()
    section_id = serializers.IntegerField()
    title = serializers.CharField()
    content = serializers.JSONField()
    status = serializers.ChoiceField(choices=KnowledgeDocument.Status.choices)
    reader_roles = serializers.ListField(child=serializers.CharField())
    position = serializers.IntegerField()
    published_at = serializers.DateTimeField(allow_null=True)
    updated_at = serializers.DateTimeField()
```

- [ ] **Step 4: `views.py` — часть про разделы**

```python
"""
Вьюхи раздела «База знаний»: разделы и документы.

Права — KnowledgeReadStaffWriteAdmin на каждой вьюхе. DRF по умолчанию AllowAny,
поэтому пропуск permission_classes открыл бы эндпоинт всем.

Недоступный документ отдаётся как 404, а не 403: 403 сообщил бы о его
существовании.
"""
from __future__ import annotations

from django.db import IntegrityError
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.knowledge import repository, services
from apps.knowledge.content import ContentError
from apps.knowledge.permissions import KnowledgeReadStaffWriteAdmin
from apps.knowledge.serializers import (
    DocumentCreateSerializer,
    DocumentUpdateSerializer,
    ReorderSerializer,
    SectionUpdateSerializer,
    SectionWriteSerializer,
)


def _is_unique_violation(exc: Exception) -> bool:
    # Проверка по SQLSTATE (23505), а не по тексту сообщения: сообщение
    # локализовано (PostgreSQL на русской локали), 'unique' в нём не встретится.
    pgcode = getattr(exc, 'pgcode', None)
    if pgcode == '23505':
        return True
    cause = getattr(exc, '__cause__', None)
    if cause and getattr(cause, 'pgcode', None) == '23505':
        return True
    return False


class SectionListCreateView(APIView):
    """GET — список разделов, POST — создать раздел."""

    permission_classes = [KnowledgeReadStaffWriteAdmin]

    def get(self, request: Request) -> Response:
        include_inactive = request.query_params.get('include_inactive') == '1'
        return Response(repository.list_sections(include_inactive=include_inactive))

    def post(self, request: Request) -> Response:
        serializer = SectionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            section = repository.create_section(serializer.validated_data['title'])
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                return Response({'error': 'Already exists'}, status=status.HTTP_409_CONFLICT)
            raise
        return Response(section, status=status.HTTP_201_CREATED)


class SectionDetailView(APIView):
    """GET/PATCH/DELETE одного раздела."""

    permission_classes = [KnowledgeReadStaffWriteAdmin]

    def get(self, request: Request, pk: int) -> Response:
        section = repository.get_section(pk)
        if section is None:
            raise NotFound()
        return Response(section)

    def patch(self, request: Request, pk: int) -> Response:
        serializer = SectionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            section = repository.update_section(pk, serializer.validated_data)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                return Response({'error': 'Already exists'}, status=status.HTTP_409_CONFLICT)
            raise
        if section is None:
            raise NotFound()
        return Response(section)

    def delete(self, request: Request, pk: int) -> Response:
        if repository.count_active_documents(pk) > 0:
            return Response(
                {'error': 'has_documents',
                 'message': 'В разделе есть документы — сначала перенесите или удалите их.'},
                status=status.HTTP_409_CONFLICT,
            )
        if not repository.soft_delete_section(pk):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SectionReorderView(APIView):
    """POST — задать порядок разделов списком id."""

    permission_classes = [KnowledgeReadStaffWriteAdmin]

    def post(self, request: Request) -> Response:
        serializer = ReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repository.reorder_sections(serializer.validated_data['order'])
        return Response({'ok': True})
```

Вызовы `repository.create_section` и `repository.update_section` обязаны стоять внутри `with transaction.atomic():` (импорт `from django.db import transaction`). Пойманный `IntegrityError` без savepoint отравляет окружающую транзакцию, и следующий запрос падает с «current transaction is aborted» — в тестах это ломает даже teardown-фикстуру.

- [ ] **Step 5: `urls.py` (пока только разделы)**

```python
"""
Маршруты раздела «База знаний».

Монтируются в config/urls.py как:
  path('api/admin/knowledge', include('apps.knowledge.urls'))
"""
from django.urls import path

from apps.knowledge.views import (
    SectionDetailView,
    SectionListCreateView,
    SectionReorderView,
)

urlpatterns = [
    path('/sections', SectionListCreateView.as_view(), name='knowledge-sections'),
    path('/sections/reorder', SectionReorderView.as_view(), name='knowledge-sections-reorder'),
    path('/sections/<int:pk>', SectionDetailView.as_view(), name='knowledge-section-detail'),
]
```

Порядок важен: `/sections/reorder` объявлен до `/sections/<int:pk>`, иначе `reorder` не совпадёт с `int` и даст 404 по другой причине — лучше не полагаться на это и держать явный порядок.

- [ ] **Step 6: Смонтировать в `config/urls.py`**

Добавить после строки с `path('api/admin/reports', include('apps.reports.urls')),`:

```python
    # База знаний — документация компании (спека 2026-08-06).
    # Чтение — любая аутентифицированная роль, запись — admin/superadmin.
    path('api/admin/knowledge', include('apps.knowledge.urls')),
```

- [ ] **Step 7: Прогнать тесты разделов**

```powershell
cd journal_django; pytest apps/knowledge/tests/test_sections_api.py -v
```
Ожидается: все PASS, кроме `test_delete_section_with_documents_returns_409` — он падает, потому что эндпоинта документов ещё нет. Это ожидаемо, он зазеленеет в Task 5.

- [ ] **Step 8: Контрольная точка**

Сообщение коммита, если разрешён: `feat(knowledge): API разделов базы знаний`

---

## Task 5: API документов

**Files:**
- Create: `journal_django/apps/knowledge/services.py`
- Modify: `journal_django/apps/knowledge/views.py` (дописать вьюхи документов)
- Modify: `journal_django/apps/knowledge/urls.py`
- Test: `journal_django/apps/knowledge/tests/test_documents_api.py`

- [ ] **Step 1: Написать падающий тест**

`journal_django/apps/knowledge/tests/test_documents_api.py`:

```python
"""E2E-тесты /api/admin/knowledge/documents."""
from __future__ import annotations

import pytest
from django.db import connection

DOCS = '/api/admin/knowledge/documents'
SECTIONS = '/api/admin/knowledge/sections'


def _cleanup() -> None:
    with connection.cursor() as cur:
        cur.execute("DELETE FROM knowledge_documents WHERE title LIKE '__test_kb_%'")
        cur.execute("DELETE FROM knowledge_sections WHERE title LIKE '__test_kb_%'")


@pytest.fixture(autouse=True)
def _clean():
    _cleanup()
    yield
    _cleanup()


@pytest.fixture
def section(admin_client):
    return admin_client.post(
        SECTIONS, {'title': '__test_kb_раздел'}, format='json',
    ).json()


def _doc_content(text: str) -> dict:
    return {'type': 'doc', 'content': [
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': text}]},
    ]}


# --- создание и правка -----------------------------------------------------

@pytest.mark.django_db
def test_create_returns_draft(admin_client, section):
    resp = admin_client.post(
        DOCS, {'section_id': section['id'], 'title': '__test_kb_регламент'},
        format='json',
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body['status'] == 'draft'
    assert body['reader_roles'] == []


@pytest.mark.django_db
def test_manager_cannot_create(manager_client, section):
    resp = manager_client.post(
        DOCS, {'section_id': section['id'], 'title': '__test_kb_x'}, format='json',
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_patch_saves_content_and_plain_text(admin_client, section):
    doc = admin_client.post(
        DOCS, {'section_id': section['id'], 'title': '__test_kb_d'}, format='json',
    ).json()
    resp = admin_client.patch(
        f"{DOCS}/{doc['id']}", {'content': _doc_content('Текст документа')},
        format='json',
    )
    assert resp.status_code == 200
    assert resp.json()['content']['type'] == 'doc'

    with connection.cursor() as cur:
        cur.execute('SELECT plain_text FROM knowledge_documents WHERE id = %s', [doc['id']])
        assert cur.fetchone()[0] == 'Текст документа'


@pytest.mark.django_db
def test_patch_rejects_unknown_node(admin_client, section):
    doc = admin_client.post(
        DOCS, {'section_id': section['id'], 'title': '__test_kb_d'}, format='json',
    ).json()
    bad = {'type': 'doc', 'content': [{'type': 'script', 'content': []}]}
    resp = admin_client.patch(f"{DOCS}/{doc['id']}", {'content': bad}, format='json')
    assert resp.status_code == 400
    assert resp.json()['code'] == 'invalid_content'


@pytest.mark.django_db
def test_patch_sets_reader_roles(admin_client, section):
    doc = admin_client.post(
        DOCS, {'section_id': section['id'], 'title': '__test_kb_d'}, format='json',
    ).json()
    resp = admin_client.patch(
        f"{DOCS}/{doc['id']}", {'reader_roles': ['manager', 'teacher']}, format='json',
    )
    assert resp.status_code == 200
    assert resp.json()['reader_roles'] == ['manager', 'teacher']


# --- публикация ------------------------------------------------------------

@pytest.mark.django_db
def test_publish_sets_status_and_timestamp(admin_client, section):
    doc = admin_client.post(
        DOCS, {'section_id': section['id'], 'title': '__test_kb_d'}, format='json',
    ).json()
    resp = admin_client.post(f"{DOCS}/{doc['id']}/publish", {}, format='json')
    assert resp.status_code == 200
    body = resp.json()
    assert body['status'] == 'published'
    assert body['published_at'] is not None


@pytest.mark.django_db
def test_unpublish_returns_to_draft(admin_client, section):
    doc = admin_client.post(
        DOCS, {'section_id': section['id'], 'title': '__test_kb_d'}, format='json',
    ).json()
    admin_client.post(f"{DOCS}/{doc['id']}/publish", {}, format='json')
    resp = admin_client.post(f"{DOCS}/{doc['id']}/unpublish", {}, format='json')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'draft'


# --- удаление и список -----------------------------------------------------

@pytest.mark.django_db
def test_delete_is_soft(admin_client, section):
    doc = admin_client.post(
        DOCS, {'section_id': section['id'], 'title': '__test_kb_d'}, format='json',
    ).json()
    assert admin_client.delete(f"{DOCS}/{doc['id']}").status_code == 204
    assert admin_client.get(f"{DOCS}/{doc['id']}").status_code == 404
    with connection.cursor() as cur:
        cur.execute('SELECT active FROM knowledge_documents WHERE id = %s', [doc['id']])
        assert cur.fetchone()[0] is False


@pytest.mark.django_db
def test_list_is_paginated_and_without_content(admin_client, section):
    admin_client.post(
        DOCS, {'section_id': section['id'], 'title': '__test_kb_d'}, format='json',
    )
    body = admin_client.get(f"{DOCS}?section_id={section['id']}").json()
    assert set(body) >= {'rows', 'total', 'page', 'page_size'}
    assert 'content' not in body['rows'][0]
```

- [ ] **Step 2: Убедиться, что тесты падают**

```powershell
cd journal_django; pytest apps/knowledge/tests/test_documents_api.py -v
```
Ожидается: FAIL с 404 на всех — вьюх документов нет.

- [ ] **Step 3: `services.py`**

```python
"""
Оркестрация раздела «База знаний».

Сохранение документа — единственное место, где сходятся три вещи: валидация
контента, запись документа и пересборка использований картинок. Всё в одной
транзакции: либо документ и его картинки согласованы, либо не меняется ничего.
"""
from __future__ import annotations

from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.knowledge import content as content_module
from apps.knowledge import repository
from apps.knowledge.models import KnowledgeDocument


class DocumentNotFound(Exception):
    """Документ не найден или недоступен — вьюха отдаёт 404."""


@transaction.atomic
def update_document(document_id: int, data: dict, *, account_id: int) -> dict:
    """
    Обновить документ. Бросает DocumentNotFound или content.ContentError.

    Порядок важен: сначала проверяем контент (в том числе что все картинки
    существуют), только потом пишем. Иначе в БД попал бы документ со ссылкой на
    несуществующую картинку.
    """
    document = repository.get_document_for_write(document_id)
    if document is None:
        raise DocumentNotFound()

    new_content = data.get('content')
    if new_content is not None:
        image_ids = content_module.collect_image_ids(new_content)
        allowed = repository.existing_image_ids(image_ids)
        content_module.validate_content(new_content, allowed_image_ids=allowed)
        document.content = new_content
        document.plain_text = content_module.extract_plain_text(new_content)

    if 'title' in data:
        document.title = data['title']
    if 'section_id' in data:
        document.section_id = data['section_id']
    if 'reader_roles' in data:
        document.reader_roles = data['reader_roles']

    document.updated_by_id = account_id
    document.save()

    if new_content is not None:
        repository.sync_image_usages(
            document.id, content_module.collect_image_ids(new_content),
        )

    return _serialize(document)


@transaction.atomic
def set_published(document_id: int, published: bool, *, account_id: int) -> dict:
    document = repository.get_document_for_write(document_id)
    if document is None:
        raise DocumentNotFound()
    if published:
        document.status = KnowledgeDocument.Status.PUBLISHED
        document.published_at = timezone.now()
    else:
        document.status = KnowledgeDocument.Status.DRAFT
        document.published_at = None
    document.updated_by_id = account_id
    document.save()
    return _serialize(document)


def create_document(*, section_id: int, title: str, account_id: int) -> dict:
    document = repository.create_document(
        section_id=section_id, title=title, account_id=account_id,
    )
    return _serialize(document)


def get_document(role: str, document_id: int) -> Optional[dict]:
    return repository.get_document(role, document_id)


def _serialize(document: KnowledgeDocument) -> dict:
    return {
        'id': document.id,
        'section_id': document.section_id,
        'title': document.title,
        'content': document.content,
        'status': document.status,
        'reader_roles': document.reader_roles,
        'position': document.position,
        'published_at': document.published_at,
        'updated_at': document.updated_at,
    }
```

- [ ] **Step 4: Дописать вьюхи документов в `views.py`**

Добавить в конец файла:

В шапку `views.py` добавить импорт пагинатора:

```python
from apps.core.pagination import StandardPagination
```

Дальше сами вьюхи:

```python
class DocumentListCreateView(APIView):
    """GET — список документов (без content), POST — создать черновик."""

    permission_classes = [KnowledgeReadStaffWriteAdmin]
    pagination_class = StandardPagination

    def get(self, request: Request) -> Response:
        section_id = request.query_params.get('section_id')
        rows = repository.list_documents(
            request.user.role,
            section_id=int(section_id) if section_id else None,
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(list(page))

    def post(self, request: Request) -> Response:
        serializer = DocumentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if repository.get_section(serializer.validated_data['section_id']) is None:
            raise NotFound('Раздел не найден.')
        document = services.create_document(
            section_id=serializer.validated_data['section_id'],
            title=serializer.validated_data['title'],
            account_id=request.user.id,
        )
        return Response(document, status=status.HTTP_201_CREATED)


class DocumentDetailView(APIView):
    """GET/PATCH/DELETE одного документа."""

    permission_classes = [KnowledgeReadStaffWriteAdmin]

    def get(self, request: Request, pk: int) -> Response:
        document = services.get_document(request.user.role, pk)
        if document is None:
            # Именно 404: 403 сообщил бы, что документ с таким id существует.
            raise NotFound()
        return Response(document)

    def patch(self, request: Request, pk: int) -> Response:
        serializer = DocumentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            document = services.update_document(
                pk, serializer.validated_data, account_id=request.user.id,
            )
        except services.DocumentNotFound:
            raise NotFound()
        except ContentError as exc:
            return Response(
                {'error': str(exc), 'code': 'invalid_content'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(document)

    def delete(self, request: Request, pk: int) -> Response:
        if not repository.soft_delete_document(pk):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DocumentPublishView(APIView):
    """POST — опубликовать документ."""

    permission_classes = [KnowledgeReadStaffWriteAdmin]
    published = True

    def post(self, request: Request, pk: int) -> Response:
        try:
            document = services.set_published(
                pk, self.published, account_id=request.user.id,
            )
        except services.DocumentNotFound:
            raise NotFound()
        return Response(document)


class DocumentUnpublishView(DocumentPublishView):
    """POST — снять документ с публикации."""

    published = False


class DocumentReorderView(APIView):
    """POST — задать порядок документов внутри раздела."""

    permission_classes = [KnowledgeReadStaffWriteAdmin]

    def post(self, request: Request) -> Response:
        serializer = ReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        section_id = request.data.get('section_id')
        if section_id is None:
            return Response(
                {'error': 'section_id обязателен.'}, status=status.HTTP_400_BAD_REQUEST,
            )
        repository.reorder_documents(int(section_id), serializer.validated_data['order'])
        return Response({'ok': True})
```

- [ ] **Step 5: Дописать маршруты в `urls.py`**

```python
from apps.knowledge.views import (
    DocumentDetailView,
    DocumentListCreateView,
    DocumentPublishView,
    DocumentReorderView,
    DocumentUnpublishView,
    SectionDetailView,
    SectionListCreateView,
    SectionReorderView,
)

urlpatterns = [
    path('/sections', SectionListCreateView.as_view(), name='knowledge-sections'),
    path('/sections/reorder', SectionReorderView.as_view(), name='knowledge-sections-reorder'),
    path('/sections/<int:pk>', SectionDetailView.as_view(), name='knowledge-section-detail'),
    path('/documents', DocumentListCreateView.as_view(), name='knowledge-documents'),
    path('/documents/reorder', DocumentReorderView.as_view(), name='knowledge-documents-reorder'),
    path('/documents/<int:pk>', DocumentDetailView.as_view(), name='knowledge-document-detail'),
    path('/documents/<int:pk>/publish', DocumentPublishView.as_view(), name='knowledge-document-publish'),
    path('/documents/<int:pk>/unpublish', DocumentUnpublishView.as_view(), name='knowledge-document-unpublish'),
]
```

- [ ] **Step 6: Прогнать тесты документов и разделов**

```powershell
cd journal_django; pytest apps/knowledge/tests/test_documents_api.py apps/knowledge/tests/test_sections_api.py -v
```
Ожидается: все PASS, включая `test_delete_section_with_documents_returns_409` из Task 4.

- [ ] **Step 7: Контрольная точка**

Сообщение коммита, если разрешён: `feat(knowledge): API документов, публикация, мягкое удаление`

---

## Task 6: Матрица прав доступа

Отдельная задача, потому что это ядро требования 3 и самая вероятная точка регресса.

**Files:**
- Test: `journal_django/apps/knowledge/tests/test_permissions_matrix.py`

- [ ] **Step 1: Написать тест**

```python
"""
Матрица видимости документов: роль × статус × reader_roles.

Читается так: admin и superadmin видят всё; manager и teacher — только
опубликованное, где их роль явно указана. Недоступный документ отдаётся как
404, а не 403.
"""
from __future__ import annotations

import pytest
from django.db import connection

DOCS = '/api/admin/knowledge/documents'
SECTIONS = '/api/admin/knowledge/sections'


def _cleanup() -> None:
    with connection.cursor() as cur:
        cur.execute("DELETE FROM knowledge_documents WHERE title LIKE '__test_kb_%'")
        cur.execute("DELETE FROM knowledge_sections WHERE title LIKE '__test_kb_%'")


@pytest.fixture(autouse=True)
def _clean():
    _cleanup()
    yield
    _cleanup()


@pytest.fixture
def section(admin_client):
    return admin_client.post(
        SECTIONS, {'title': '__test_kb_раздел'}, format='json',
    ).json()


def _make_document(admin_client, section, *, title, roles, published):
    doc = admin_client.post(
        DOCS, {'section_id': section['id'], 'title': title}, format='json',
    ).json()
    admin_client.patch(f"{DOCS}/{doc['id']}", {'reader_roles': roles}, format='json')
    if published:
        admin_client.post(f"{DOCS}/{doc['id']}/publish", {}, format='json')
    return doc


# --- detail ----------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize(
    'roles,published,manager_expects,teacher_expects',
    [
        (['manager'], True, 200, 404),          # опубликован, только менеджерам
        (['teacher'], True, 404, 200),          # опубликован, только преподавателям
        (['manager', 'teacher'], True, 200, 200),
        (['manager'], False, 404, 404),         # черновик не виден никому, кроме админов
        ([], True, 404, 404),                   # опубликован, но роли не выданы
    ],
)
def test_visibility_matrix(
    admin_client, manager_client, teacher_client, section,
    roles, published, manager_expects, teacher_expects,
):
    doc = _make_document(
        admin_client, section, title='__test_kb_матрица', roles=roles, published=published,
    )
    url = f"{DOCS}/{doc['id']}"
    assert manager_client.get(url).status_code == manager_expects
    assert teacher_client.get(url).status_code == teacher_expects
    # admin и superadmin видят документ при любых настройках
    assert admin_client.get(url).status_code == 200


@pytest.mark.django_db
def test_superadmin_sees_draft(superadmin_client, admin_client, section):
    doc = _make_document(
        admin_client, section, title='__test_kb_черновик', roles=[], published=False,
    )
    assert superadmin_client.get(f"{DOCS}/{doc['id']}").status_code == 200


# --- list ------------------------------------------------------------------

@pytest.mark.django_db
def test_list_hides_invisible_documents(admin_client, manager_client, section):
    _make_document(
        admin_client, section, title='__test_kb_видимый',
        roles=['manager'], published=True,
    )
    _make_document(
        admin_client, section, title='__test_kb_скрытый',
        roles=['teacher'], published=True,
    )
    rows = manager_client.get(f"{DOCS}?section_id={section['id']}").json()['rows']
    titles = [r['title'] for r in rows]
    assert titles == ['__test_kb_видимый']


@pytest.mark.django_db
def test_admin_list_includes_drafts(admin_client, section):
    _make_document(
        admin_client, section, title='__test_kb_черновик', roles=[], published=False,
    )
    rows = admin_client.get(f"{DOCS}?section_id={section['id']}").json()['rows']
    assert [r['title'] for r in rows] == ['__test_kb_черновик']


# --- запись ----------------------------------------------------------------

@pytest.mark.django_db
def test_teacher_cannot_write(teacher_client, admin_client, section):
    doc = _make_document(
        admin_client, section, title='__test_kb_д', roles=['teacher'], published=True,
    )
    assert teacher_client.patch(
        f"{DOCS}/{doc['id']}", {'title': 'взлом'}, format='json',
    ).status_code == 403
    assert teacher_client.delete(f"{DOCS}/{doc['id']}").status_code == 403
    assert teacher_client.post(
        f"{DOCS}/{doc['id']}/publish", {}, format='json',
    ).status_code == 403


@pytest.mark.django_db
def test_anonymous_gets_401(anon_client, admin_client, section):
    doc = _make_document(
        admin_client, section, title='__test_kb_д', roles=['teacher'], published=True,
    )
    assert anon_client.get(f"{DOCS}/{doc['id']}").status_code == 401
```

- [ ] **Step 2: Прогнать**

```powershell
cd journal_django; pytest apps/knowledge/tests/test_permissions_matrix.py -v
```
Ожидается: все PASS. Если какой-то падает — чинить `repository.visible_documents_qs`, а не тест.

- [ ] **Step 3: Контрольная точка**

Сообщение коммита, если разрешён: `test(knowledge): матрица прав доступа к документам`

---

## Task 7: Файловый слой картинок

**Files:**
- Create: `journal_django/apps/knowledge/images.py`
- Test: `journal_django/apps/knowledge/tests/test_images.py` (первая половина)

- [ ] **Step 1: Написать падающий тест**

```python
"""Тесты файлового слоя картинок: пути, хеш, приём файла, оптимизация."""
from __future__ import annotations

import io

import pytest
from django.test import override_settings
from PIL import Image

from apps.knowledge import images


def _png_bytes(width: int = 20, height: int = 10, color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', (width, height), color).save(buf, format='PNG')
    return buf.getvalue()


# --- пути ------------------------------------------------------------------

def test_relative_path_shards_by_first_hex_pairs():
    path = images.relative_path('abcdef' + '0' * 58, 'png')
    assert path == 'knowledge/ab/cd/' + 'abcdef' + '0' * 58 + '.png'


def test_variant_path_appends_suffix():
    sha = 'ab' + '0' * 62
    assert images.variant_path(sha, 'w400') == f'knowledge/ab/00/{sha}.w400.webp'


# --- приём файла -----------------------------------------------------------

def test_store_upload_writes_file_and_returns_metadata(tmp_path):
    payload = _png_bytes(30, 15)
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        meta = images.store_upload(io.BytesIO(payload), 'скрин.png')

    assert meta.mime == 'image/png'
    assert meta.width == 30 and meta.height == 15
    assert meta.byte_size == len(payload)
    assert len(meta.sha256) == 64
    assert (tmp_path / meta.relative_path).exists()


def test_store_upload_is_deterministic_by_content(tmp_path):
    payload = _png_bytes()
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        first = images.store_upload(io.BytesIO(payload), 'a.png')
        second = images.store_upload(io.BytesIO(payload), 'b.png')
    assert first.sha256 == second.sha256


def test_store_upload_rejects_non_image(tmp_path):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        with pytest.raises(images.ImageRejected, match='формат'):
            images.store_upload(io.BytesIO(b'not an image at all'), 'x.png')


def test_store_upload_rejects_svg(tmp_path):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        with pytest.raises(images.ImageRejected, match='формат'):
            images.store_upload(io.BytesIO(svg), 'x.svg')


def test_store_upload_rejects_oversized(tmp_path):
    payload = _png_bytes()
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path), KNOWLEDGE_MAX_IMAGE_BYTES=10):
        with pytest.raises(images.ImageTooLarge):
            images.store_upload(io.BytesIO(payload), 'x.png')


# --- оптимизация -----------------------------------------------------------

def test_build_variants_creates_webp_files(tmp_path):
    payload = _png_bytes(2000, 1000)
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        meta = images.store_upload(io.BytesIO(payload), 'big.png')
        result = images.build_variants(meta.sha256, meta.relative_path)

    optimized = tmp_path / result.optimized_path
    thumb = tmp_path / result.thumb_path
    assert optimized.exists() and thumb.exists()
    with Image.open(optimized) as im:
        assert im.width == 1600          # ужато по длинной стороне
        assert im.format == 'WEBP'
    with Image.open(thumb) as im:
        assert im.width == 400


def test_build_variants_strips_exif(tmp_path):
    buf = io.BytesIO()
    im = Image.new('RGB', (100, 50), (0, 128, 0))
    exif = im.getexif()
    exif[271] = 'TestCamera'             # Make
    im.save(buf, format='JPEG', exif=exif)

    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        meta = images.store_upload(io.BytesIO(buf.getvalue()), 'photo.jpg')
        result = images.build_variants(meta.sha256, meta.relative_path)

    with Image.open(tmp_path / result.optimized_path) as out:
        assert dict(out.getexif()) == {}
```

- [ ] **Step 2: Убедиться, что падает**

```powershell
cd journal_django; pytest apps/knowledge/tests/test_images.py -v
```
Ожидается: `ModuleNotFoundError: No module named 'apps.knowledge.images'`.

- [ ] **Step 3: Написать `images.py`**

```python
"""
Файловый слой картинок базы знаний.

Хранилище адресуется содержимым: имя файла — sha256 загруженных байтов, каталог
шардируется по первым двум парам hex-символов. Из этого следуют два полезных
свойства: одинаковые картинки не дублируются, а содержимое по конкретному пути
никогда не меняется — поэтому ETag можно ставить неизменяемый.

Приём файла (store_upload) намеренно дёшев: запись на диск и один проход
Pillow ради размеров. Перекодирование живёт в build_variants и вызывается из
Celery — воркеру gunicorn нечего делать с 2-мегабайтным PNG.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps

# Форматы Pillow → mime. SVG отсутствует намеренно: это XML со встраиваемым
# скриптом, отдача с нашего origin обошла бы CSP.
ALLOWED_FORMATS = {
    'PNG': ('image/png', 'png'),
    'JPEG': ('image/jpeg', 'jpg'),
    'WEBP': ('image/webp', 'webp'),
}

OPTIMIZED_WIDTH = 1600
THUMB_WIDTH = 400
WEBP_QUALITY = 82

_CHUNK = 64 * 1024


class ImageRejected(ValueError):
    """Файл не является поддерживаемой картинкой — вьюха отдаёт 415."""


class ImageTooLarge(ValueError):
    """Файл больше лимита — вьюха отдаёт 413."""


@dataclass(frozen=True)
class StoredImage:
    sha256: str
    relative_path: str
    mime: str
    byte_size: int
    width: int
    height: int


@dataclass(frozen=True)
class Variants:
    optimized_path: str
    thumb_path: str


def media_root() -> Path:
    return Path(settings.KNOWLEDGE_MEDIA_ROOT)


def relative_path(sha256: str, ext: str) -> str:
    """knowledge/ab/cd/<sha256>.<ext> — два уровня шардирования по hex."""
    return f'knowledge/{sha256[0:2]}/{sha256[2:4]}/{sha256}.{ext}'


def variant_path(sha256: str, suffix: str) -> str:
    return f'knowledge/{sha256[0:2]}/{sha256[2:4]}/{sha256}.{suffix}.webp'


def absolute_path(rel_path: str) -> Path:
    return media_root() / rel_path


def store_upload(stream, original_name: str) -> StoredImage:
    """
    Принять файл: записать во временный, посчитать sha256 потоково, проверить
    формат Pillow, переложить на постоянное место.

    Бросает ImageRejected / ImageTooLarge.
    """
    max_bytes = settings.KNOWLEDGE_MAX_IMAGE_BYTES
    digest = hashlib.sha256()
    size = 0

    tmp_fd, tmp_name = tempfile.mkstemp(prefix='kb-upload-')
    try:
        with os.fdopen(tmp_fd, 'wb') as tmp:
            while True:
                chunk = stream.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ImageTooLarge(
                        f'Файл больше {max_bytes // (1024 * 1024)} МБ.'
                    )
                digest.update(chunk)
                tmp.write(chunk)

        mime, ext, width, height = _probe(tmp_name)
        sha256 = digest.hexdigest()
        rel = relative_path(sha256, ext)
        target = absolute_path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Файл с таким содержимым мог быть загружен раньше — перезапись
        # безопасна, содержимое то же самое по построению.
        shutil.move(tmp_name, target)
        tmp_name = None
        return StoredImage(
            sha256=sha256, relative_path=rel, mime=mime,
            byte_size=size, width=width, height=height,
        )
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _probe(path: str) -> tuple[str, str, int, int]:
    """Определить формат и размеры. Расширению файла не верим — только Pillow."""
    try:
        with Image.open(path) as im:
            fmt = im.format
            width, height = im.size
    except Exception as exc:                       # noqa: BLE001 — любой сбой = отказ
        raise ImageRejected('Не удалось распознать формат изображения.') from exc

    if fmt not in ALLOWED_FORMATS:
        raise ImageRejected(
            f'Неподдерживаемый формат {fmt!r}: поддерживаются PNG, JPEG, WebP.'
        )
    if width * height > settings.KNOWLEDGE_MAX_IMAGE_PIXELS:
        raise ImageTooLarge('Слишком большое изображение по числу пикселей.')

    mime, ext = ALLOWED_FORMATS[fmt]
    return mime, ext, width, height


def build_variants(sha256: str, source_rel_path: str) -> Variants:
    """
    Сделать WebP-варианты. Вызывается из Celery, в запросе не используется.

    EXIF срезается: в нём геотеги и модель устройства. Ориентация при этом
    применяется до сброса — иначе фото с телефона осталось бы лежать боком.
    """
    source = absolute_path(source_rel_path)
    optimized_rel = variant_path(sha256, f'w{OPTIMIZED_WIDTH}')
    thumb_rel = variant_path(sha256, f'w{THUMB_WIDTH}')

    with Image.open(source) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert('RGB')
        _save_resized(im, absolute_path(optimized_rel), OPTIMIZED_WIDTH)
        _save_resized(im, absolute_path(thumb_rel), THUMB_WIDTH)

    return Variants(optimized_path=optimized_rel, thumb_path=thumb_rel)


def _save_resized(im: Image.Image, target: Path, max_width: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if im.width > max_width:
        height = round(im.height * max_width / im.width)
        resized = im.resize((max_width, height), Image.LANCZOS)
    else:
        resized = im.copy()
    # exif не передаём — метаданные не попадают в результат.
    resized.save(target, format='WEBP', quality=WEBP_QUALITY, method=4)
```

- [ ] **Step 4: Прогнать тесты**

```powershell
cd journal_django; pytest apps/knowledge/tests/test_images.py -v
```
Ожидается: все PASS.

- [ ] **Step 5: Контрольная точка**

Сообщение коммита, если разрешён: `feat(knowledge): файловый слой картинок с дедупликацией по sha256`

---

## Task 8: Загрузка и отдача картинок

**Files:**
- Create: `journal_django/apps/knowledge/image_views.py`
- Create: `journal_django/apps/knowledge/tasks.py`
- Modify: `journal_django/apps/knowledge/urls.py`
- Test: `journal_django/apps/knowledge/tests/test_images.py` (дописать API-часть)

- [ ] **Step 1: Дописать тесты в `test_images.py`**

Добавить в конец файла:

```python
# ---------------------------------------------------------------------------
# API загрузки и отдачи
# ---------------------------------------------------------------------------

import pytest as _pytest                                        # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile    # noqa: E402
from django.db import connection                                 # noqa: E402

IMAGES = '/api/admin/knowledge/images'
DOCS = '/api/admin/knowledge/documents'
SECTIONS = '/api/admin/knowledge/sections'


def _cleanup_kb() -> None:
    with connection.cursor() as cur:
        # Использования удаляются первыми. on_delete=CASCADE Django эмулирует в
        # ORM, а не в БД, поэтому raw-SQL DELETE оставляет осиротевшие строки —
        # и они всплывают в check_constraints() при закрытии тестовой транзакции.
        cur.execute(
            'DELETE FROM knowledge_image_usages WHERE document_id IN'
            " (SELECT id FROM knowledge_documents WHERE title LIKE '__test_kb_%')"
            ' OR image_id IN'
            " (SELECT id FROM knowledge_images WHERE original_name LIKE '__test_kb_%')"
        )
        cur.execute("DELETE FROM knowledge_documents WHERE title LIKE '__test_kb_%'")
        cur.execute("DELETE FROM knowledge_sections WHERE title LIKE '__test_kb_%'")
        cur.execute("DELETE FROM knowledge_images WHERE original_name LIKE '__test_kb_%'")


@_pytest.fixture
def kb_clean():
    _cleanup_kb()
    yield
    _cleanup_kb()


def _upload(client, tmp_path, name='__test_kb_a.png', payload=None):
    file = SimpleUploadedFile(name, payload or _png_bytes(), content_type='image/png')
    return client.post(IMAGES, {'file': file}, format='multipart')


@_pytest.mark.django_db
def test_upload_returns_pending_image(admin_client, tmp_path, kb_clean):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        resp = _upload(admin_client, tmp_path)
    assert resp.status_code == 201
    body = resp.json()
    assert body['optimize_state'] in ('pending', 'ready')
    assert body['width'] == 20 and body['height'] == 10


@_pytest.mark.django_db
def test_upload_deduplicates_by_content(admin_client, tmp_path, kb_clean):
    payload = _png_bytes(33, 22)
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        first = _upload(admin_client, tmp_path, '__test_kb_1.png', payload).json()
        second = _upload(admin_client, tmp_path, '__test_kb_2.png', payload).json()
    assert first['id'] == second['id']


@_pytest.mark.django_db
def test_manager_cannot_upload(manager_client, tmp_path, kb_clean):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        assert _upload(manager_client, tmp_path).status_code == 403


@_pytest.mark.django_db
def test_upload_rejects_svg(admin_client, tmp_path, kb_clean):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    file = SimpleUploadedFile('__test_kb_x.svg', svg, content_type='image/svg+xml')
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        resp = admin_client.post(IMAGES, {'file': file}, format='multipart')
    assert resp.status_code == 415


@_pytest.mark.django_db
def test_upload_rejects_oversized(admin_client, tmp_path, kb_clean):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path), KNOWLEDGE_MAX_IMAGE_BYTES=10):
        resp = _upload(admin_client, tmp_path)
    assert resp.status_code == 413


@_pytest.mark.django_db
def test_serve_uses_x_accel_redirect(admin_client, tmp_path, kb_clean):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        image = _upload(admin_client, tmp_path).json()
        section = admin_client.post(
            SECTIONS, {'title': '__test_kb_раздел'}, format='json',
        ).json()
        doc = admin_client.post(
            DOCS, {'section_id': section['id'], 'title': '__test_kb_док'}, format='json',
        ).json()
        admin_client.patch(
            f"{DOCS}/{doc['id']}",
            {'content': {'type': 'doc', 'content': [
                {'type': 'knowledgeImage', 'attrs': {'imageId': image['id']}},
            ]}},
            format='json',
        )
        with override_settings(KNOWLEDGE_X_ACCEL_PREFIX='/internal-media'):
            resp = admin_client.get(f"{IMAGES}/{image['id']}")

    assert resp.status_code == 200
    assert resp['X-Accel-Redirect'].startswith('/internal-media/knowledge/')
    assert resp.content == b''          # байты отдаёт nginx, не Python


@_pytest.mark.django_db
def test_serve_denied_when_no_visible_document(
    admin_client, teacher_client, tmp_path, kb_clean,
):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        image = _upload(admin_client, tmp_path).json()
        section = admin_client.post(
            SECTIONS, {'title': '__test_kb_раздел'}, format='json',
        ).json()
        doc = admin_client.post(
            DOCS, {'section_id': section['id'], 'title': '__test_kb_док'}, format='json',
        ).json()
        admin_client.patch(
            f"{DOCS}/{doc['id']}",
            {'content': {'type': 'doc', 'content': [
                {'type': 'knowledgeImage', 'attrs': {'imageId': image['id']}},
            ]}},
            format='json',
        )
        # Документ остался черновиком без ролей → преподавателю картинка не видна.
        resp = teacher_client.get(f"{IMAGES}/{image['id']}")

    assert resp.status_code == 404


@_pytest.mark.django_db
def test_serve_falls_back_to_original_when_not_optimized(
    admin_client, tmp_path, kb_clean,
):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        image = _upload(admin_client, tmp_path).json()
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE knowledge_images SET optimize_state='pending',"
                ' optimized_path=NULL WHERE id = %s', [image['id']],
            )
        section = admin_client.post(
            SECTIONS, {'title': '__test_kb_раздел'}, format='json',
        ).json()
        doc = admin_client.post(
            DOCS, {'section_id': section['id'], 'title': '__test_kb_док'}, format='json',
        ).json()
        admin_client.patch(
            f"{DOCS}/{doc['id']}",
            {'content': {'type': 'doc', 'content': [
                {'type': 'knowledgeImage', 'attrs': {'imageId': image['id']}},
            ]}},
            format='json',
        )
        with override_settings(KNOWLEDGE_X_ACCEL_PREFIX='/internal-media'):
            resp = admin_client.get(f"{IMAGES}/{image['id']}?variant=optimized")

    assert resp.status_code == 200
    # Отдан оригинал: путь заканчивается на .png, а не на .webp
    assert resp['X-Accel-Redirect'].endswith('.png')


@_pytest.mark.django_db
def test_serve_rejects_unknown_variant(admin_client, tmp_path, kb_clean):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        image = _upload(admin_client, tmp_path).json()
        resp = admin_client.get(f"{IMAGES}/{image['id']}?variant=huge")
    assert resp.status_code == 400
```

- [ ] **Step 2: Убедиться, что падают**

```powershell
cd journal_django; pytest apps/knowledge/tests/test_images.py -v -k "upload or serve"
```
Ожидается: FAIL с 404 — маршрутов картинок нет.

- [ ] **Step 3: `tasks.py`**

```python
"""
Celery-задачи раздела «База знаний».

optimize_image — перекодирование в WebP. Живёт вне запроса намеренно: на VPS с
двумя ядрами перекодирование в воркере gunicorn отняло бы CPU у всех остальных
запросов.

Модуль импортируется автодискавером Celery только когда запущен воркер или beat.
Логика — в images.build_variants, она тестируется без Celery.
"""
from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.knowledge import images, repository
from apps.knowledge.models import KnowledgeImage

# Отсрочка удаления осиротевших картинок: картинка появляется при загрузке, а в
# документ попадает при сохранении. Немедленная уборка ломала бы черновики.
ORPHAN_GRACE_DAYS = 7


@shared_task(name='apps.knowledge.tasks.optimize_image')
def optimize_image(image_id: int) -> str:
    """Сделать WebP-варианты картинки. Возвращает итоговое состояние."""
    image = repository.get_image(image_id)
    if image is None:
        return 'missing'
    try:
        variants = images.build_variants(image.sha256, image.original_path)
    except Exception:                                  # noqa: BLE001
        KnowledgeImage.objects.filter(id=image_id).update(
            optimize_state=KnowledgeImage.OptimizeState.FAILED,
        )
        raise
    KnowledgeImage.objects.filter(id=image_id).update(
        optimized_path=variants.optimized_path,
        thumb_path=variants.thumb_path,
        optimize_state=KnowledgeImage.OptimizeState.READY,
    )
    return 'ready'


@shared_task(name='apps.knowledge.tasks.cleanup_orphan_images')
def cleanup_orphan_images() -> int:
    """Удалить картинки без единого использования старше ORPHAN_GRACE_DAYS."""
    cutoff = timezone.now() - timedelta(days=ORPHAN_GRACE_DAYS)
    removed = 0
    for image_id in repository.orphan_image_ids(cutoff):
        image = repository.get_image(image_id)
        if image is None:
            continue
        for rel in (image.original_path, image.optimized_path, image.thumb_path):
            if not rel:
                continue
            path = images.absolute_path(rel)
            if path.exists():
                path.unlink()
        image.delete()
        removed += 1
    return removed
```

- [ ] **Step 4: `image_views.py`**

```python
"""
Загрузка и отдача картинок базы знаний.

Отдача идёт через X-Accel-Redirect: Django проверяет права и отвечает пустым
телом с заголовком, дальше файл отдаёт nginx через sendfile. Воркер
освобождается сразу, а не держится на всё время передачи.

Если KNOWLEDGE_X_ACCEL_PREFIX пуст (локальный runserver без nginx), файл
отдаётся через FileResponse. Права проверяются одинаково в обоих режимах.
"""
from __future__ import annotations

from django.conf import settings
from django.http import FileResponse, HttpResponse
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.knowledge import images, repository
from apps.knowledge.models import KnowledgeImage
from apps.knowledge.permissions import KnowledgeReadStaffWriteAdmin

VARIANTS = ('optimized', 'thumb', 'original')


def _serialize(image: KnowledgeImage) -> dict:
    return {
        'id': image.id,
        'mime': image.mime,
        'byte_size': image.byte_size,
        'width': image.width,
        'height': image.height,
        'optimize_state': image.optimize_state,
    }


class ImageUploadView(APIView):
    """POST — загрузить картинку. Только admin/superadmin (мутация)."""

    permission_classes = [KnowledgeReadStaffWriteAdmin]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'knowledge_upload'

    def post(self, request: Request) -> Response:
        upload = request.FILES.get('file')
        if upload is None:
            return Response(
                {'error': 'Файл не передан (поле file).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            stored = images.store_upload(upload, upload.name)
        except images.ImageTooLarge as exc:
            return Response(
                {'error': str(exc)},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        except images.ImageRejected as exc:
            return Response(
                {'error': str(exc)},
                status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        existing = repository.get_image_by_sha256(stored.sha256)
        if existing is not None:
            # Тот же файл уже загружен — второй записи и второй копии не будет.
            return Response(_serialize(existing), status=status.HTTP_201_CREATED)

        image = KnowledgeImage.objects.create(
            sha256=stored.sha256,
            original_name=upload.name[:255],
            mime=stored.mime,
            byte_size=stored.byte_size,
            width=stored.width,
            height=stored.height,
            original_path=stored.relative_path,
            uploaded_by_id=request.user.id,
        )
        _enqueue_optimize(image.id)
        image.refresh_from_db()
        return Response(_serialize(image), status=status.HTTP_201_CREATED)


def _enqueue_optimize(image_id: int) -> None:
    """
    Поставить задачу оптимизации. Недоступность Celery/Redis не должна ронять
    загрузку: картинка останется в pending и будет отдаваться в оригинале, пока
    её не догонит knowledge_optimize_pending.
    """
    try:
        from apps.knowledge.tasks import optimize_image
        optimize_image.delay(image_id)
    except Exception:                                  # noqa: BLE001
        pass


class ImageServeView(APIView):
    """GET — отдать файл картинки с проверкой прав."""

    permission_classes = [KnowledgeReadStaffWriteAdmin]

    def get(self, request: Request, pk: int):
        variant = request.query_params.get('variant', 'optimized')
        if variant not in VARIANTS:
            return Response(
                {'error': f'Неизвестный variant: {variant!r}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        image = repository.get_image(pk)
        if image is None:
            raise NotFound()
        if not repository.image_visible_to(request.user.role, pk):
            # 404, а не 403 — существование файла тоже не разглашаем.
            raise NotFound()

        rel_path, mime = _resolve_variant(image, variant)
        return _file_response(rel_path, mime, image.sha256)


def _resolve_variant(image: KnowledgeImage, variant: str) -> tuple[str, str]:
    """Путь и mime запрошенного варианта; фолбэк на оригинал, если не готов."""
    if variant == 'optimized' and image.optimized_path:
        return image.optimized_path, 'image/webp'
    if variant == 'thumb' and image.thumb_path:
        return image.thumb_path, 'image/webp'
    return image.original_path, image.mime


def _file_response(rel_path: str, mime: str, sha256: str):
    prefix = settings.KNOWLEDGE_X_ACCEL_PREFIX
    if prefix:
        response = HttpResponse(content_type=mime)
        response['X-Accel-Redirect'] = f'{prefix.rstrip("/")}/{rel_path}'
        # Content-Length ставит nginx; пустое тело здесь — это норма.
        del response['Content-Length']
    else:
        path = images.absolute_path(rel_path)
        if not path.exists():
            raise NotFound()
        response = FileResponse(path.open('rb'), content_type=mime)

    # Содержимое по конкретному пути неизменно (имя файла = хеш содержимого),
    # поэтому кэш безопасен. private, а не public: файл не должен осесть в общем
    # прокси в обход проверки прав.
    response['ETag'] = f'"{sha256}"'
    response['Cache-Control'] = 'private, max-age=86400'
    return response
```

- [ ] **Step 5: Дописать маршруты в `urls.py`**

Добавить импорт и два маршрута:

```python
from apps.knowledge.image_views import ImageServeView, ImageUploadView
```

```python
    path('/images', ImageUploadView.as_view(), name='knowledge-images'),
    path('/images/<int:pk>', ImageServeView.as_view(), name='knowledge-image-serve'),
```

- [ ] **Step 6: Прогнать тесты картинок**

```powershell
cd journal_django; pytest apps/knowledge/tests/test_images.py -v
```
Ожидается: все PASS.

- [ ] **Step 7: Контрольная точка**

Сообщение коммита, если разрешён: `feat(knowledge): загрузка и отдача картинок через X-Accel-Redirect`

---

## Task 9: Уборка, догон pending и nginx

**Files:**
- Create: `journal_django/apps/knowledge/management/__init__.py`
- Create: `journal_django/apps/knowledge/management/commands/__init__.py`
- Create: `journal_django/apps/knowledge/management/commands/knowledge_optimize_pending.py`
- Modify: `journal_django/config/settings/base.py` (`CELERY_BEAT_SCHEDULE`)
- Modify: `deploy/nginx/journal-kotokod.conf`
- Modify: `deploy/nginx/local/nginx.conf`

- [ ] **Step 1: Management-команда**

```powershell
New-Item -ItemType Directory -Force journal_django/apps/knowledge/management/commands
New-Item -ItemType File journal_django/apps/knowledge/management/__init__.py
New-Item -ItemType File journal_django/apps/knowledge/management/commands/__init__.py
```

`journal_django/apps/knowledge/management/commands/knowledge_optimize_pending.py`:

```python
"""
Догнать картинки, застрявшие в состоянии pending.

Нужна в двух случаях: Celery не работал в момент загрузки (локальная разработка
без Redis) и задача упала. Запускается вручную или из cron.

    python manage.py knowledge_optimize_pending
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.knowledge import repository
from apps.knowledge.tasks import optimize_image


class Command(BaseCommand):
    help = 'Построить WebP-варианты для картинок в состоянии pending.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        image_ids = repository.pending_image_ids(limit=options['limit'])
        if not image_ids:
            self.stdout.write('Нечего обрабатывать.')
            return
        for image_id in image_ids:
            # Синхронный вызов задачи: команда для того и нужна, чтобы обойтись
            # без брокера.
            result = optimize_image(image_id)
            self.stdout.write(f'{image_id}: {result}')
        self.stdout.write(self.style.SUCCESS(f'Обработано: {len(image_ids)}'))
```

- [ ] **Step 2: Добавить уборку в расписание Celery**

В `config/settings/base.py` в `CELERY_BEAT_SCHEDULE` добавить запись рядом с существующими:

```python
    'knowledge-cleanup-orphan-images': {
        'task': 'apps.knowledge.tasks.cleanup_orphan_images',
        'schedule': crontab(hour=4, minute=30),   # CELERY_TIMEZONE='Europe/Moscow'
    },
```

Запись должна попасть в тот же блок, что и другие `crontab`-задачи, — то есть внутрь `if crontab is not None:`-ветки, где живут дайджесты уведомлений. Если запись положить в верхний словарь, при отсутствующем `celery` (`crontab is None`) настройки упадут на импорте.

- [ ] **Step 3: nginx — боевой конфиг**

В `deploy/nginx/journal-kotokod.conf` добавить internal-локацию рядом с остальными `location`, и поднять лимит тела запроса на загрузке:

```nginx
    # Медиа базы знаний. internal — снаружи недоступно; сюда попадают только
    # ответы Django с заголовком X-Accel-Redirect, то есть после проверки прав.
    location /internal-media/ {
        internal;
        alias /var/www/journal-media/;
        # Заголовки кэширования ставит Django (ETag + Cache-Control).
    }

    # Загрузка картинок базы знаний — единственный эндпоинт с большим телом.
    location = /api/admin/knowledge/images {
        client_max_body_size 12m;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
```

Значение `alias` должно совпадать с `KNOWLEDGE_MEDIA_ROOT` в `.env` на проде. В `.env` прописать:

```
KNOWLEDGE_MEDIA_ROOT=/var/www/journal-media
KNOWLEDGE_X_ACCEL_PREFIX=/internal-media
```

Проверить, что заголовки `proxy_set_header` совпадают с теми, что уже стоят в основной `location /api`-секции этого файла: если там задан другой набор (например, добавлен `proxy_read_timeout`), продублировать его — иначе загрузка пойдёт с другими условиями, чем остальной API.

- [ ] **Step 4: nginx — локальный конфиг**

То же самое в `deploy/nginx/local/nginx.conf`, с локальными путями:

```nginx
        location /internal-media/ {
            internal;
            alias C:/Users/ilyap/TestKOTOKOD/journal_django/media/;
        }
```

Локально можно и не включать `KNOWLEDGE_X_ACCEL_PREFIX` — тогда Django отдаст файлы сам через `FileResponse`. Это штатный режим разработки на runserver без nginx.

- [ ] **Step 5: Проверить команду вручную**

```powershell
cd journal_django; python manage.py knowledge_optimize_pending
```
Ожидается: `Нечего обрабатывать.` на пустой базе.

- [ ] **Step 6: Контрольная точка**

Сообщение коммита, если разрешён: `feat(knowledge): уборка осиротевших картинок и раздача через nginx`

---

## Task 10: Фронт — зависимости, типы, загрузка файлов

**Files:**
- Modify: `journal_django/frontend/admin-src/package.json`
- Modify: `journal_django/frontend/admin-src/src/lib/api.ts`
- Create: `journal_django/frontend/admin-src/src/lib/knowledge.ts`

- [ ] **Step 1: Поставить TipTap**

```powershell
cd journal_django/frontend/admin-src; npm install @tiptap/react@^3.29.2 @tiptap/starter-kit@^3.29.2 @tiptap/extension-table@^3.29.2 @tiptap/static-renderer@^3.29.2 @tiptap/core@^3.29.2
```
Ожидается: пакеты появились в `dependencies`, `npm ls @tiptap/react` без ошибок.

- [ ] **Step 2: Добавить `apiUpload` в `lib/api.ts`**

Существующий `api()` всегда ставит `Content-Type: application/json` и сериализует тело — для multipart он не подходит. Добавить рядом отдельную функцию (после `export async function api<T>`):

```typescript
/**
 * Загрузка файла multipart-ом. Отдельно от api(): там тело всегда JSON, а для
 * FormData Content-Type обязан выставить сам браузер — иначе теряется boundary.
 *
 * CSRF и обновление access-токена работают так же, как в api().
 */
export async function apiUpload<T>(path: string, file: File): Promise<T> {
  const send = async (): Promise<Response> => {
    const form = new FormData();
    form.append('file', file);
    const headers: Record<string, string> = {};
    const token = await ensureCsrfToken();
    if (token) headers['X-CSRFToken'] = token;
    return fetch(path, {
      method: 'POST',
      credentials: 'include',
      headers,
      body: form,
    });
  };

  let res = await send();
  if (res.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) res = await send();
  }

  const text = await res.text();
  const json = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new ApiError(res.status, json?.error || res.statusText, json?.details, json?.code);
  }
  return json as T;
}
```

Таймаут здесь намеренно не ставится: загрузка большого файла на медленном канале легально идёт дольше 25 секунд, и обрывать её по общему потолку `api()` неправильно.

- [ ] **Step 3: `lib/knowledge.ts`**

```typescript
/** Типы раздела «База знаний». Форма ответов — из apps/knowledge/views.py. */

export type KnowledgeRole = 'teacher' | 'manager' | 'admin' | 'superadmin';

export type DocumentStatus = 'draft' | 'published';

export interface KnowledgeSection {
  id: number;
  title: string;
  position: number;
  active: boolean;
}

/** Строка списка документов — без content. */
export interface KnowledgeDocumentRow {
  id: number;
  section_id: number;
  title: string;
  status: DocumentStatus;
  reader_roles: KnowledgeRole[];
  position: number;
  published_at: string | null;
  updated_at: string;
}

/** Документ целиком, с содержимым. */
export interface KnowledgeDocument extends KnowledgeDocumentRow {
  content: TipTapDoc;
  plain_text?: string;
}

/** Корень TipTap-документа. Структура узлов проверяется на сервере. */
export interface TipTapDoc {
  type: 'doc';
  content?: TipTapNode[];
}

export interface TipTapNode {
  type: string;
  attrs?: Record<string, unknown>;
  content?: TipTapNode[];
  marks?: { type: string; attrs?: Record<string, unknown> }[];
  text?: string;
}

export interface KnowledgeImage {
  id: number;
  mime: string;
  byte_size: number;
  width: number;
  height: number;
  optimize_state: 'pending' | 'ready' | 'failed';
}

export const EMPTY_DOC: TipTapDoc = { type: 'doc', content: [] };


/** URL картинки для рендера. Собирается из id — в JSON хранится только он. */
export function imageUrl(imageId: number, variant: 'optimized' | 'thumb' = 'optimized'): string {
  return `/api/admin/knowledge/images/${imageId}?variant=${variant}`;
}
```

- [ ] **Step 4: Проверить типы**

```powershell
cd journal_django/frontend/admin-src; npm run typecheck
```
Ожидается: без ошибок.

- [ ] **Step 5: Контрольная точка**

Сообщение коммита, если разрешён: `feat(admin): зависимости TipTap и типы базы знаний`

Важно: `npm run build` на этом шаге **не запускать** — собранный бандл коммитится отдельно в самом конце (Task 15), иначе `admin-dist/` замусорит каждый промежуточный коммит.

---

## Task 11: Фронт — хуки данных

**Files:**
- Create: `journal_django/frontend/admin-src/src/hooks/useKnowledge.ts`

- [ ] **Step 1: Написать хуки**

```typescript
import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api, apiUpload } from '../lib/api';
import type {
  KnowledgeDocument,
  KnowledgeDocumentRow,
  KnowledgeImage,
  KnowledgeRole,
  KnowledgeSection,
  TipTapDoc,
} from '../lib/knowledge';
import type { Paginated } from '../lib/types';

const BASE = '/api/admin/knowledge';

export const knowledgeKeys = {
  sections: ['knowledge', 'sections'] as const,
  documents: (sectionId: number | null) => ['knowledge', 'documents', sectionId] as const,
  document: (id: number) => ['knowledge', 'document', id] as const,
};

export function useKnowledgeSections() {
  return useQuery({
    queryKey: knowledgeKeys.sections,
    queryFn: () => api<KnowledgeSection[]>('GET', `${BASE}/sections`),
  });
}

export function useKnowledgeDocuments(sectionId: number | null) {
  return useQuery({
    queryKey: knowledgeKeys.documents(sectionId),
    queryFn: () =>
      api<Paginated<KnowledgeDocumentRow>>(
        'GET',
        sectionId === null
          ? `${BASE}/documents`
          : `${BASE}/documents?section_id=${sectionId}`,
      ),
    // Обязательно во всех server-paginated хуках проекта: без этого при смене
    // раздела список схлопывается в пустой и страница «прыгает».
    placeholderData: keepPreviousData,
  });
}

export function useKnowledgeDocument(id: number | undefined) {
  return useQuery({
    queryKey: knowledgeKeys.document(id ?? 0),
    queryFn: () => api<KnowledgeDocument>('GET', `${BASE}/documents/${id}`),
    enabled: id !== undefined,
  });
}

export function useCreateSection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (title: string) =>
      api<KnowledgeSection>('POST', `${BASE}/sections`, { title }),
    onSuccess: () => qc.invalidateQueries({ queryKey: knowledgeKeys.sections }),
  });
}

export function useRenameSection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) =>
      api<KnowledgeSection>('PATCH', `${BASE}/sections/${id}`, { title }),
    onSuccess: () => qc.invalidateQueries({ queryKey: knowledgeKeys.sections }),
  });
}

export function useDeleteSection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>('DELETE', `${BASE}/sections/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: knowledgeKeys.sections }),
  });
}

export function useCreateDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sectionId, title }: { sectionId: number; title: string }) =>
      api<KnowledgeDocument>('POST', `${BASE}/documents`, {
        section_id: sectionId,
        title,
      }),
    onSuccess: (doc) =>
      qc.invalidateQueries({ queryKey: knowledgeKeys.documents(doc.section_id) }),
  });
}

export interface DocumentPatch {
  title?: string;
  section_id?: number;
  content?: TipTapDoc;
  reader_roles?: KnowledgeRole[];
}

export function useUpdateDocument(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: DocumentPatch) =>
      api<KnowledgeDocument>('PATCH', `${BASE}/documents/${id}`, patch),
    onSuccess: (doc) => {
      qc.setQueryData(knowledgeKeys.document(id), doc);
      qc.invalidateQueries({ queryKey: knowledgeKeys.documents(doc.section_id) });
    },
  });
}

export function useSetPublished(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (published: boolean) =>
      api<KnowledgeDocument>(
        'POST',
        `${BASE}/documents/${id}/${published ? 'publish' : 'unpublish'}`,
        {},
      ),
    onSuccess: (doc) => {
      qc.setQueryData(knowledgeKeys.document(id), doc);
      qc.invalidateQueries({ queryKey: knowledgeKeys.documents(doc.section_id) });
    },
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>('DELETE', `${BASE}/documents/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['knowledge', 'documents'] }),
  });
}

export function useUploadImage() {
  return useMutation({
    mutationFn: (file: File) => apiUpload<KnowledgeImage>(`${BASE}/images`, file),
  });
}
```

- [ ] **Step 2: Сверить тип `Paginated`**

Открыть `src/lib/types.ts` и убедиться, что `Paginated<T>` описан как `{ rows: T[]; total: number; page: number; page_size: number }`. Если имя другое — использовать существующее, новый тип не заводить.

- [ ] **Step 3: Проверить типы**

```powershell
cd journal_django/frontend/admin-src; npm run typecheck
```
Ожидается: без ошибок.

- [ ] **Step 4: Контрольная точка**

Сообщение коммита, если разрешён: `feat(admin): хуки данных базы знаний`

---

## Task 12: Фронт — рендер документа и стили

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/knowledge/DocumentView.tsx`
- Create: `journal_django/frontend/admin-src/src/styles/knowledge.css`
- Modify: `journal_django/frontend/admin-src/src/styles/` (подключение импорта — см. шаг 3)

⚠️ **Главная ловушка задачи.** Импортировать в `DocumentView` расширения TipTap
(`StarterKit`, `@tiptap/extension-table`) нельзя: они тянут ядро ProseMirror, а
`DocumentView` подключён статически — ProseMirror уедет в основной бандл и его
будут грузить все страницы админки (замер: +471 КБ, +46 %).

Мало того, импорт из корня `@tiptap/static-renderer` тоже не годится: этот модуль
сам делает `import { mergeAttributes } from '@tiptap/core'` на верхнем уровне.
Нужен **сабпуть** `@tiptap/static-renderer/json/react` — самостоятельный модуль,
зависящий только от `react`, и явная таблица соответствий узлов/марок
(`documentRenderMap.tsx`) вместо расширений.

Контроль: после сборки `grep -c prosemirror` по `admin-dist/assets/index-*.js`
обязан дать **0**, а чанк `DocumentEditor-*.js` — существовать отдельным файлом.

- [ ] **Step 1: `DocumentView.tsx`**

```tsx
import { renderToReactElement } from '@tiptap/static-renderer';
import StarterKit from '@tiptap/starter-kit';
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table';
import { KnowledgeImageExtension } from './KnowledgeImageExtension';
import type { TipTapDoc } from '../../lib/knowledge';

/**
 * Рендер документа для чтения.
 *
 * Ключевой момент: JSON превращается в React-элементы, а не в HTML-строку.
 * Поэтому здесь нет dangerouslySetInnerHTML и не нужен санитайзер — вставить
 * исполняемую разметку через контент документа физически нечем.
 *
 * Расширения передаются те же, что и в редакторе: рендерер должен понимать
 * ровно те узлы, которые редактор умеет создавать, а бэкенд — пропускать.
 */
// underline: false — StarterKit 3 включает подчёркивание, а его нет в белом
// списке apps/knowledge/content.py: Ctrl+U создавал бы контент, который сервер
// откажется сохранить.
// renderWrapper: true — даёт обёртку .tableWrapper, на которую вешается
// overflow-x, чтобы широкая таблица не растягивала страницу.
const EXTENSIONS = [
  StarterKit.configure({ underline: false }),
  Table.configure({ renderWrapper: true }),
  TableRow,
  TableHeader,
  TableCell,
  KnowledgeImageExtension,
];

export function DocumentView({ content }: { content: TipTapDoc }) {
  return (
    <article className="kb-doc">
      {renderToReactElement({ content, extensions: EXTENSIONS })}
    </article>
  );
}
```

- [ ] **Step 2: `styles/knowledge.css`**

```css
/*
 * Типографика документа базы знаний.
 *
 * Все значения — из tokens.css. Ни одного захардкоженного цвета, радиуса или
 * отступа: tokens.css — единственный источник (docs/design-system.md).
 */

.kb-doc {
  max-width: 76ch;
  color: var(--color-text);
  font-size: var(--font-size-md);
  line-height: var(--line-height-relaxed);
}

.kb-doc > * + * {
  margin-top: var(--space-4);
}

.kb-doc h1,
.kb-doc h2,
.kb-doc h3 {
  color: var(--color-text-strong);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-tight);
}

.kb-doc h1 { font-size: var(--font-size-2xl); }
.kb-doc h2 { font-size: var(--font-size-xl); }
.kb-doc h3 { font-size: var(--font-size-lg); }

.kb-doc h2,
.kb-doc h3 {
  margin-top: var(--space-8);
}

.kb-doc ul,
.kb-doc ol {
  padding-left: var(--space-6);
}

.kb-doc li + li {
  margin-top: var(--space-2);
}

.kb-doc a {
  color: var(--color-primary);
  text-decoration: underline;
}

.kb-doc blockquote {
  padding-left: var(--space-4);
  border-left: 3px solid var(--color-border);
  color: var(--color-text-muted);
}

.kb-doc code {
  padding: 0 var(--space-1);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
}

.kb-doc pre {
  overflow-x: auto;
  padding: var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.kb-doc pre code {
  padding: 0;
  background: none;
}

/* Таблица шире колонки текста — прокручиваем её саму, а не страницу. */
.kb-doc .kb-doc__table-wrap {
  overflow-x: auto;
}

.kb-doc table {
  width: 100%;
  border-collapse: collapse;
}

.kb-doc th,
.kb-doc td {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  text-align: left;
}

.kb-doc th {
  background: var(--color-surface-muted);
  font-weight: var(--font-weight-semibold);
}

.kb-doc img {
  max-width: 100%;
  height: auto;
  border-radius: var(--radius-md);
}

/* Полотно редактора наследует ту же типографику — что видишь, то и сохранится. */
.kb-editor .ProseMirror {
  min-height: 40vh;
  outline: none;
}

.kb-editor .ProseMirror p.is-editor-empty:first-child::before {
  content: attr(data-placeholder);
  color: var(--color-text-muted);
  float: left;
  height: 0;
  pointer-events: none;
}
```

Перед написанием файла открыть `src/styles/tokens.css` и сверить имена переменных: если в проекте, например, `--text-muted` вместо `--color-text-muted`, использовать существующие имена. Переменной, которой нет в `tokens.css`, быть не должно — `var()` схлопнется молча, и цвет просто пропадёт.

- [ ] **Step 3: Подключить стиль**

Найти файл, где импортируются остальные стили (`grep -rn "styles/" src/main.tsx src/styles/index.css`), и добавить импорт `knowledge.css` в том же месте и в том же виде, что у соседних файлов. Порядок импорта важен: плоский `@import` работает по правилу «кто последний, тот и прав», поэтому `knowledge.css` должен идти после `tokens.css`.

- [ ] **Step 4: Проверить типы**

```powershell
cd journal_django/frontend/admin-src; npm run typecheck
```
Ожидается: ошибка про отсутствующий `./KnowledgeImageExtension` — он появится в Task 13. Остальных ошибок быть не должно.

- [ ] **Step 5: Контрольная точка**

Сообщение коммита, если разрешён: `feat(admin): рендер документа базы знаний и типографика`

---

## Task 13: Фронт — редактор

**Files:**
- Create: `journal_django/frontend/admin-src/src/components/knowledge/KnowledgeImageExtension.ts`
- Create: `journal_django/frontend/admin-src/src/components/knowledge/EditorToolbar.tsx`
- Create: `journal_django/frontend/admin-src/src/components/knowledge/DocumentEditor.tsx`
- Create: `journal_django/frontend/admin-src/src/components/knowledge/ReaderRolesField.tsx`

- [ ] **Step 1: `KnowledgeImageExtension.ts`**

```typescript
import { Node, mergeAttributes } from '@tiptap/core';
import { imageUrl } from '../../lib/knowledge';

/**
 * Узел картинки базы знаний.
 *
 * В документе хранится только imageId — не URL. Благодаря этому смена схемы
 * раздачи файлов не потребует переписывать содержимое документов: src
 * собирается при рендере.
 */
export const KnowledgeImageExtension = Node.create({
  name: 'knowledgeImage',
  group: 'block',
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      imageId: {
        default: null,
        parseHTML: (element) => {
          const raw = element.getAttribute('data-image-id');
          return raw ? Number(raw) : null;
        },
        renderHTML: (attributes) => ({ 'data-image-id': attributes.imageId }),
      },
      alt: { default: '' },
    };
  },

  parseHTML() {
    return [{ tag: 'img[data-image-id]' }];
  },

  renderHTML({ HTMLAttributes, node }) {
    const id = node.attrs.imageId as number | null;
    return [
      'img',
      mergeAttributes(HTMLAttributes, {
        src: id ? imageUrl(id) : '',
        loading: 'lazy',
      }),
    ];
  },
});
```

- [ ] **Step 2: `EditorToolbar.tsx`**

```tsx
import type { Editor } from '@tiptap/react';
import { Button } from '../ui/Button';

/**
 * Панель форматирования. Native form-элементы в админке запрещены, поэтому
 * кнопки — существующий Button проекта, а не <button> напрямую.
 */
export function EditorToolbar({
  editor,
  onPickImage,
  uploading,
}: {
  editor: Editor;
  onPickImage: () => void;
  uploading: boolean;
}) {
  const chain = () => editor.chain().focus();

  return (
    <div className="kb-editor__toolbar">
      <Button
        variant={editor.isActive('heading', { level: 2 }) ? 'primary' : 'ghost'}
        onClick={() => chain().toggleHeading({ level: 2 }).run()}
      >
        Заголовок
      </Button>
      <Button
        variant={editor.isActive('heading', { level: 3 }) ? 'primary' : 'ghost'}
        onClick={() => chain().toggleHeading({ level: 3 }).run()}
      >
        Подзаголовок
      </Button>
      <Button
        variant={editor.isActive('bold') ? 'primary' : 'ghost'}
        onClick={() => chain().toggleBold().run()}
      >
        Жирный
      </Button>
      <Button
        variant={editor.isActive('italic') ? 'primary' : 'ghost'}
        onClick={() => chain().toggleItalic().run()}
      >
        Курсив
      </Button>
      <Button
        variant={editor.isActive('bulletList') ? 'primary' : 'ghost'}
        onClick={() => chain().toggleBulletList().run()}
      >
        Список
      </Button>
      <Button
        variant={editor.isActive('orderedList') ? 'primary' : 'ghost'}
        onClick={() => chain().toggleOrderedList().run()}
      >
        Нумерация
      </Button>
      <Button
        variant={editor.isActive('blockquote') ? 'primary' : 'ghost'}
        onClick={() => chain().toggleBlockquote().run()}
      >
        Цитата
      </Button>
      <Button
        variant={editor.isActive('codeBlock') ? 'primary' : 'ghost'}
        onClick={() => chain().toggleCodeBlock().run()}
      >
        Код
      </Button>
      <Button
        variant="ghost"
        onClick={() =>
          chain().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
        }
      >
        Таблица
      </Button>
      <Button variant="ghost" onClick={onPickImage} disabled={uploading}>
        {uploading ? 'Загрузка…' : 'Картинка'}
      </Button>
    </div>
  );
}
```

Сверить имена пропсов `Button` с реальным компонентом (`src/components/ui/Button.tsx`): если у него не `variant`, а, скажем, `kind`, — использовать существующий API, новый вариант не добавлять.

- [ ] **Step 3: `DocumentEditor.tsx`**

```tsx
import { useCallback, useEffect, useRef } from 'react';
import { EditorContent, useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table';
import { KnowledgeImageExtension } from './KnowledgeImageExtension';
import { EditorToolbar } from './EditorToolbar';
import { useUploadImage } from '../../hooks/useKnowledge';
import { useApiError } from '../../hooks/useApiError';
import type { TipTapDoc } from '../../lib/knowledge';

/**
 * Редактор документа. Грузится через React.lazy — читателям этот чанк не нужен.
 *
 * Набор расширений обязан совпадать с DocumentView и с белым списком в
 * apps/knowledge/content.py: узел, который здесь можно создать, но нельзя
 * сохранить, — это потерянная работа пользователя.
 */
export default function DocumentEditor({
  content,
  onChange,
}: {
  content: TipTapDoc;
  onChange: (doc: TipTapDoc) => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const upload = useUploadImage();
  const showError = useApiError();

  const editor = useEditor({
    // Набор обязан совпадать с DocumentView — включая .configure().
    extensions: [
      StarterKit.configure({ underline: false }),
      Table.configure({ renderWrapper: true }),
      TableRow, TableHeader, TableCell, KnowledgeImageExtension,
    ],
    content,
    onUpdate: ({ editor: e }) => onChange(e.getJSON() as TipTapDoc),
  });

  const insertImage = useCallback(
    async (file: File) => {
      try {
        const image = await upload.mutateAsync(file);
        editor?.chain().focus().insertContent({
          type: 'knowledgeImage',
          attrs: { imageId: image.id, alt: file.name },
        }).run();
      } catch (err) {
        showError(err);
      }
    },
    [editor, upload, showError],
  );

  // Вставка картинки из буфера и перетаскиванием — самый частый способ
  // добавить скриншот, кнопкой пользуются реже.
  useEffect(() => {
    if (!editor) return;
    const dom = editor.view.dom;

    const onPaste = (event: ClipboardEvent) => {
      const file = Array.from(event.clipboardData?.files ?? [])[0];
      if (file && file.type.startsWith('image/')) {
        event.preventDefault();
        void insertImage(file);
      }
    };
    const onDrop = (event: DragEvent) => {
      const file = Array.from(event.dataTransfer?.files ?? [])[0];
      if (file && file.type.startsWith('image/')) {
        event.preventDefault();
        void insertImage(file);
      }
    };

    dom.addEventListener('paste', onPaste);
    dom.addEventListener('drop', onDrop);
    return () => {
      dom.removeEventListener('paste', onPaste);
      dom.removeEventListener('drop', onDrop);
    };
  }, [editor, insertImage]);

  if (!editor) return null;

  return (
    <div className="kb-editor">
      <EditorToolbar
        editor={editor}
        uploading={upload.isPending}
        onPickImage={() => fileInput.current?.click()}
      />
      <input
        ref={fileInput}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void insertImage(file);
          e.target.value = '';
        }}
      />
      <EditorContent editor={editor} className="kb-doc" />
    </div>
  );
}
```

Скрытый `<input type="file">` — единственное исключение из правила «никаких native form-элементов»: диалог выбора файла в браузере иначе не открыть, и визуально этот элемент не существует. Проверить фактическое имя и сигнатуру `useApiError` (`grep -rn "useApiError" src/hooks/`) — если хук называется иначе или возвращает объект, поправить вызов под существующий API.

- [ ] **Step 4: `ReaderRolesField.tsx`**

```tsx
import { Checkbox } from '../form/Checkbox';
import { ROLE_LABELS } from '../../lib/labels';
import type { KnowledgeRole } from '../../lib/knowledge';

// admin и superadmin видят всё всегда — выдавать им доступ галочкой нечего.
const SELECTABLE: KnowledgeRole[] = ['teacher', 'manager'];

/**
 * Кто читает документ. Галочки — Checkbox проекта, подписи — из lib/labels.ts
 * (enum-подписи только оттуда, правило дизайн-системы).
 */
export function ReaderRolesField({
  value,
  onChange,
  disabled,
}: {
  value: KnowledgeRole[];
  onChange: (roles: KnowledgeRole[]) => void;
  disabled?: boolean;
}) {
  const toggle = (role: KnowledgeRole, checked: boolean) => {
    const next = checked ? [...value, role] : value.filter((r) => r !== role);
    onChange([...new Set(next)].sort());
  };

  return (
    <fieldset className="kb-roles">
      <legend className="kb-roles__legend">Кто может читать</legend>
      {SELECTABLE.map((role) => (
        <Checkbox
          key={role}
          checked={value.includes(role)}
          onCheckedChange={(checked) => toggle(role, checked)}
          disabled={disabled}
          label={ROLE_LABELS[role] ?? role}
        />
      ))}
      <p className="kb-roles__hint">
        Администраторы видят документ всегда, включая черновики.
      </p>
    </fieldset>
  );
}
```

Сверить с реальным `components/form/Checkbox.tsx`: имена пропсов (`onCheckedChange` против `onChange`, `label` против детей) взять из существующего компонента. Проверить, есть ли в `lib/labels.ts` словарь подписей ролей; если он называется иначе — использовать существующий, если его нет — добавить туда (не заводить подписи локально в компоненте).

- [ ] **Step 5: Дописать стили тулбара и полей в `knowledge.css`**

```css
.kb-editor__toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  margin-bottom: var(--space-4);
}

.kb-roles {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: 0;
  border: none;
}

.kb-roles__legend {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
}

.kb-roles__hint {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
```

- [ ] **Step 6: Проверить типы**

```powershell
cd journal_django/frontend/admin-src; npm run typecheck
```
Ожидается: без ошибок.

- [ ] **Step 7: Контрольная точка**

Сообщение коммита, если разрешён: `feat(admin): редактор документов базы знаний`

---

## Task 14: Фронт — страницы и навигация

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/knowledge/KnowledgeListPage.tsx`
- Create: `journal_django/frontend/admin-src/src/pages/knowledge/KnowledgeDocumentPage.tsx`
- Create: `journal_django/frontend/admin-src/src/pages/knowledge/KnowledgeEditPage.tsx`
- Modify: `journal_django/frontend/admin-src/src/App.tsx`
- Modify: `journal_django/frontend/admin-src/src/components/shell/Sidebar.tsx`

- [ ] **Step 1: `KnowledgeListPage.tsx`**

```tsx
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader } from '../../components/shell/PageHeader';
import { Button } from '../../components/ui/Button';
import { useAuth } from '../../hooks/useAuth';
import {
  useCreateDocument,
  useCreateSection,
  useKnowledgeDocuments,
  useKnowledgeSections,
} from '../../hooks/useKnowledge';

const WRITE_ROLES = ['admin', 'superadmin'];

export default function KnowledgeListPage() {
  const { me } = useAuth();
  const canWrite = !!me && WRITE_ROLES.includes(me.role);

  const sections = useKnowledgeSections();
  const [activeSection, setActiveSection] = useState<number | null>(null);
  const documents = useKnowledgeDocuments(activeSection);

  const createSection = useCreateSection();
  const createDocument = useCreateDocument();

  const current = activeSection ?? sections.data?.[0]?.id ?? null;

  return (
    <div className="page">
      <PageHeader
        title="База знаний"
        actions={
          canWrite ? (
            <>
              <Button
                variant="ghost"
                onClick={() => {
                  const title = window.prompt('Название раздела');
                  if (title) createSection.mutate(title);
                }}
              >
                Новый раздел
              </Button>
              <Button
                disabled={current === null}
                onClick={() => {
                  const title = window.prompt('Название документа');
                  if (title && current !== null) {
                    createDocument.mutate({ sectionId: current, title });
                  }
                }}
              >
                Новый документ
              </Button>
            </>
          ) : null
        }
      />

      <div className="kb-layout">
        <nav className="kb-sections">
          {sections.data?.map((section) => (
            <button
              key={section.id}
              type="button"
              className={
                section.id === current ? 'kb-sections__item is-active' : 'kb-sections__item'
              }
              onClick={() => setActiveSection(section.id)}
            >
              {section.title}
            </button>
          ))}
        </nav>

        <ul className="kb-documents">
          {documents.data?.rows.map((doc) => (
            <li key={doc.id} className="kb-documents__item">
              <Link to={`/admin/knowledge/${doc.id}`}>{doc.title}</Link>
              {doc.status === 'draft' && <span className="kb-badge">Черновик</span>}
            </li>
          ))}
          {documents.data?.rows.length === 0 && (
            <li className="kb-documents__empty">В этом разделе пока нет документов.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
```

`window.prompt` здесь — временное решение уровня «работает»; если в проекте уже есть модалка ввода имени (посмотреть `components/ui/`), использовать её вместо prompt.

- [ ] **Step 2: `KnowledgeDocumentPage.tsx`**

```tsx
import { Link, useParams } from 'react-router-dom';
import { PageHeader } from '../../components/shell/PageHeader';
import { Button } from '../../components/ui/Button';
import { DocumentView } from '../../components/knowledge/DocumentView';
import { useAuth } from '../../hooks/useAuth';
import { useKnowledgeDocument } from '../../hooks/useKnowledge';

const WRITE_ROLES = ['admin', 'superadmin'];

export default function KnowledgeDocumentPage() {
  const { id } = useParams();
  const documentId = id ? Number(id) : undefined;
  const { data, isLoading, isError } = useKnowledgeDocument(documentId);
  const { me } = useAuth();
  const canWrite = !!me && WRITE_ROLES.includes(me.role);

  if (isLoading) return <div className="page">Загрузка…</div>;
  if (isError || !data) {
    return (
      <div className="page">
        <PageHeader title="Документ не найден" />
        <p>Документ удалён или у вас нет к нему доступа.</p>
        <Link to="/admin/knowledge">Вернуться к списку</Link>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader
        title={data.title}
        actions={
          canWrite ? (
            <Link to={`/admin/knowledge/${data.id}/edit`}>
              <Button>Редактировать</Button>
            </Link>
          ) : null
        }
      />
      {data.status === 'draft' && (
        <p className="kb-badge">Черновик — читателям он пока не виден.</p>
      )}
      <DocumentView content={data.content} />
    </div>
  );
}
```

- [ ] **Step 3: `KnowledgeEditPage.tsx`**

```tsx
import { Suspense, lazy, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { PageHeader } from '../../components/shell/PageHeader';
import { PageLoading } from '../../components/ui/Skeleton';
import { Button } from '../../components/ui/Button';
import { ReaderRolesField } from '../../components/knowledge/ReaderRolesField';
import { useApiError } from '../../hooks/useApiError';
import {
  useKnowledgeDocument,
  useSetPublished,
  useUpdateDocument,
} from '../../hooks/useKnowledge';
import { EMPTY_DOC } from '../../lib/knowledge';
import type { KnowledgeRole, TipTapDoc } from '../../lib/knowledge';

// TipTap — тяжёлая зависимость, держим её вне основного бандла: читателям
// документов редактор не нужен.
const DocumentEditor = lazy(() => import('../../components/knowledge/DocumentEditor'));

export default function KnowledgeEditPage() {
  const { id } = useParams();
  const documentId = Number(id);
  const navigate = useNavigate();
  const showError = useApiError();

  const { data, isLoading } = useKnowledgeDocument(documentId);
  const update = useUpdateDocument(documentId);
  const setPublished = useSetPublished(documentId);

  const [content, setContent] = useState<TipTapDoc>(EMPTY_DOC);
  const [roles, setRoles] = useState<KnowledgeRole[]>([]);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (data) {
      setContent(data.content ?? EMPTY_DOC);
      setRoles(data.reader_roles);
      setDirty(false);
    }
  }, [data]);

  // Автосохранения нет, поэтому уход со страницы с несохранёнными правками
  // надо перехватывать — иначе закрытая вкладка означает потерянную статью.
  // ⚠️ НЕ useBlocker: он требует data router (createBrowserRouter), а App.tsx
  // собран на плоском <BrowserRouter> — invariant бросает ошибку при первом
  // рендере. Свой хук с тремя перехватчиками: beforeunload (закрытие вкладки),
  // клик по <a> в capture-фазе (внутренние переходы), popstate со страховочной
  // записью в истории (кнопка «Назад»).
  useUnsavedChangesGuard(dirty);

  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  if (isLoading || !data) return <PageLoading />;

  const save = async () => {
    try {
      await update.mutateAsync({ content, reader_roles: roles });
      setDirty(false);
    } catch (err) {
      showError(err);
    }
  };

  return (
    <div className="page">
      <PageHeader
        title={data.title}
        actions={
          <>
            <Button variant="ghost" onClick={() => navigate(`/admin/knowledge/${documentId}`)}>
              Закрыть
            </Button>
            <Button
              variant="ghost"
              onClick={() => setPublished.mutate(data.status === 'draft')}
              disabled={setPublished.isPending}
            >
              {data.status === 'draft' ? 'Опубликовать' : 'Снять с публикации'}
            </Button>
            <Button onClick={save} disabled={!dirty || update.isPending}>
              {update.isPending ? 'Сохранение…' : 'Сохранить'}
            </Button>
          </>
        }
      />

      <ReaderRolesField
        value={roles}
        onChange={(next) => {
          setRoles(next);
          setDirty(true);
        }}
      />

      <Suspense fallback={<PageLoading />}>
        <DocumentEditor
          content={content}
          onChange={(doc) => {
            setContent(doc);
            setDirty(true);
          }}
        />
      </Suspense>
    </div>
  );
}
```

Проверить сигнатуру `PageHeader` (`src/components/shell/PageHeader.tsx`) — если проп называется не `actions`, использовать существующий.

- [ ] **Step 4: Маршруты в `App.tsx`**

Добавить импорты рядом с остальными страницами:

```tsx
import KnowledgeListPage from './pages/knowledge/KnowledgeListPage';
import KnowledgeDocumentPage from './pages/knowledge/KnowledgeDocumentPage';
import KnowledgeEditPage from './pages/knowledge/KnowledgeEditPage';
```

И три маршрута внутри `<Route element={<AppShell />}>`, после блока `/admin/reports`:

```tsx
            <Route path="/admin/knowledge" element={<KnowledgeListPage />} />
            <Route path="/admin/knowledge/:id" element={<KnowledgeDocumentPage />} />
            <Route path="/admin/knowledge/:id/edit" element={<RequireRole roles={['admin','superadmin']}><KnowledgeEditPage /></RequireRole>} />
```

Порядок маршрутов важен: `/admin/knowledge/:id/edit` должен идти после `/admin/knowledge/:id`, иначе React Router 7 разрешит его корректно, но читать список станет труднее — держим тот же стиль, что у остальных разделов.

- [ ] **Step 5: Пункт в сайдбаре**

В `src/components/shell/Sidebar.tsx` добавить пункт в ту же группу, где `reports` (строка ~215):

```tsx
      { key: 'knowledge', label: 'База знаний', path: '/admin/knowledge' },
```

Пункт без `can` — раздел виден всем ролям админки; бэкенд сам покажет каждому только доступное. Если в файле есть словарь `NAV_ICONS` (используется на строке ~321), добавить туда иконку для ключа `knowledge` — взять подходящую из `lucide-react` (например, `BookOpen`), по образцу соседних записей.

- [ ] **Step 6: Дописать стили списка в `knowledge.css`**

```css
.kb-layout {
  display: grid;
  grid-template-columns: minmax(180px, 240px) 1fr;
  gap: var(--space-6);
  align-items: start;
}

.kb-sections {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.kb-sections__item {
  padding: var(--space-2) var(--space-3);
  border: none;
  border-radius: var(--radius-md);
  background: none;
  color: var(--color-text);
  text-align: left;
  cursor: pointer;
}

.kb-sections__item.is-active {
  background: var(--color-surface-muted);
  font-weight: var(--font-weight-semibold);
}

.kb-documents {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  list-style: none;
  padding: 0;
}

.kb-documents__item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.kb-documents__empty {
  color: var(--color-text-muted);
}

.kb-badge {
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

@media (max-width: 720px) {
  .kb-layout {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 7: Проверить типы и поднять dev-сервер**

```powershell
cd journal_django/frontend/admin-src; npm run typecheck
```
Ожидается: без ошибок.

- [ ] **Step 8: Контрольная точка**

Сообщение коммита, если разрешён: `feat(admin): страницы базы знаний и пункт навигации`

---

## Task 15: Полная проверка и сборка

**Files:**
- Modify: `journal_django/frontend/admin-dist/**` (результат сборки)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Полный прогон pytest**

```powershell
cd journal_django; pytest -q
```
Ожидается: все тесты PASS, число тестов выросло примерно на 60 относительно базы.

Гнать нужно именно полностью, а не `pytest apps/knowledge`: часть приложений no-op'ит `django_db_setup` (общая `journal_test`), часть пересоздаёт `test_journal_test`. Прогон по частям даёт ложнозелёный результат — особенно после миграции с новыми NOT NULL-полями.

- [ ] **Step 2: Проверить, что миграции не разъехались**

```powershell
cd journal_django; python manage.py makemigrations --check --dry-run
```
Ожидается: `No changes detected`.

- [ ] **Step 3: Браузерный прогон**

Поднять бэкенд и фронт:

```powershell
cd journal_django; python manage.py runserver
```
```powershell
cd journal_django/frontend/admin-src; npm run dev
```

Пройти вручную и отметить каждый пункт:

- [ ] под `superadmin`: создать раздел, создать документ, набрать текст с заголовком, списком и таблицей, сохранить, открыть на чтение — вёрстка совпадает с редактором;
- [ ] вставить скриншот из буфера — картинка появляется, после сохранения и перезагрузки страницы остаётся на месте;
- [ ] выдать документу роль «менеджер», опубликовать; зайти под менеджером — документ виден, кнопки «Редактировать» нет;
- [ ] снять с публикации — у менеджера документ пропал из списка, прямая ссылка даёт «Документ не найден»;
- [ ] открыть в новой вкладке прямую ссылку на картинку под менеджером, пока документ в черновике, — 404;
- [ ] начать правку и попробовать уйти со страницы — появляется предупреждение о несохранённых изменениях;
- [ ] попытаться загрузить SVG — тост «Поддерживаются PNG, JPEG, WebP»;
- [ ] проверить вкладку Network: чанк редактора не грузится на странице чтения.

- [ ] **Step 4: Проверить оптимизацию картинок**

```powershell
cd journal_django; python manage.py knowledge_optimize_pending
```
Ожидается: строки вида `12: ready`. Затем в браузере перезагрузить документ и убедиться в Network, что картинка отдаётся как `image/webp` и весит заметно меньше исходного файла.

- [ ] **Step 5: Собрать бандл**

```powershell
cd journal_django/frontend/admin-src; npm run build
```
Ожидается: сборка успешна, в `admin-dist/assets/` появились новые файлы, включая **отдельный чанк редактора** (имя содержит `DocumentEditor`). Если чанка нет — `React.lazy` не сработал, редактор попал в основной бандл; проверить импорт в `KnowledgeEditPage.tsx`.

- [ ] **Step 6: Проверить, что в сборку не попало лишнее**

```powershell
git status --short journal_django/frontend/admin-dist
```
Ожидается: только удалённые старые ассеты и добавленные новые, плюс изменённый `index.html`.

- [ ] **Step 7: Дописать раздел в `CLAUDE.md`**

В блок «Критичные соглашения» добавить абзац:

```markdown
**База знаний** — `apps/knowledge/`. Контент документов — TipTap-JSON в `jsonb`, валидируется белым списком узлов в `content.py`; расширять список можно только вместе с `DocumentView.tsx`, иначе документ сохранится, но не отрендерится. Права на чтение — `reader_roles text[]` на документе; `admin`/`superadmin` видят всё всегда, недоступный документ отдаётся как 404, а не 403. Картинки лежат на диске под именем sha256, оптимизируются в Celery и раздаются через `X-Accel-Redirect` — Python байты не перекачивает. pghistory на моделях раздела намеренно нет. Спека: `docs/superpowers/specs/2026-08-06-knowledge-base-tiptap-design.md`.
```

- [ ] **Step 8: Финальная контрольная точка**

Показать `git status --short` и `git diff --stat`. Сообщение коммита, если разрешён: `feat(knowledge): раздел «База знаний» на TipTap`

Бандл коммитить отдельным коммитом: `build(admin): пересборка бандла` — так принято в проекте.

---

## Самопроверка плана

**Покрытие спеки:**

| требование спеки | задача |
|---|---|
| приложение `apps/knowledge`, четыре таблицы | Task 1 |
| `TolerantJSONField`, инвариант «админ видит всё» | Task 1, Task 3 |
| белый список узлов, лимиты, `plain_text` | Task 2 |
| permission-класс, фильтр видимости, 404 вместо 403 | Task 3, Task 5, Task 6 |
| API разделов, 409 на непустом разделе | Task 4 |
| API документов, публикация, мягкое удаление | Task 5 |
| матрица прав роль × статус × роли | Task 6 |
| sha256, дедупликация, шардирование, EXIF, WebP | Task 7 |
| загрузка, `X-Accel-Redirect`, фолбэк на оригинал, ETag | Task 8 |
| уборка сирот, догон pending, nginx, CSP без изменений | Task 9 |
| TipTap-зависимости, `apiUpload`, типы | Task 10 |
| хуки с `keepPreviousData` | Task 11 |
| `static-renderer`, типографика на токенах | Task 12 |
| редактор в отдельном чанке, узел `knowledgeImage`, галочки ролей | Task 13 |
| маршруты, `RequireRole`, сайдбар, защита от потери правок | Task 14 |
| полный `pytest`, браузерный прогон, сборка | Task 15 |

**Согласованность имён между задачами:** `KnowledgeDocument.Status` (Task 1) используется в `repository.visible_documents_qs` и `services.set_published`; `content.collect_image_ids` (Task 2) вызывается в `services.update_document` (Task 5); `images.StoredImage.relative_path` (Task 7) читается в `image_views.ImageUploadView` (Task 8); `imageUrl` из `lib/knowledge.ts` (Task 10) используется в `KnowledgeImageExtension` (Task 13); узел `knowledgeImage` объявлен одинаково в `content.ALLOWED_NODES` (Task 2), расширении (Task 13) и `DocumentView` (Task 12).

**Известные места, требующие сверки с кодом при исполнении** (отмечены прямо в шагах): имена CSS-переменных в `tokens.css`, пропсы `Button`, `Checkbox`, `PageHeader`, наличие `ROLE_LABELS` в `lib/labels.ts`, сигнатура `useApiError`, имя типа `Paginated`. Это не пробелы плана, а точки, где нужно использовать то, что уже есть в проекте, вместо заведения дублей.
