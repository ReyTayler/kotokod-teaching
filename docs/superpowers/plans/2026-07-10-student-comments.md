# Комментарии к ученику — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an append-only comment log to the Student entity — manager/admin can write timestamped, authored notes about a student; admin can delete; visible in a new "Комментарии" tab on the student detail page.

**Architecture:** New `StudentComment` model in the existing `apps/students` Django app (mirrors `apps/renewals.RenewalActivity`'s comment pattern but simpler — no `kind`, no stage/payment links). Thin `APIView`/`ListAPIView` classes reuse existing permission classes (`IsManagerOrAdmin`, `ReadStaffWriteAdmin`) and the project's `StandardPagination`. Deliberately **not** tracked by pghistory/changelog (decision recorded in the design spec). Frontend adds a third tab to `StudentDetailPage.tsx` with a new `StudentCommentsBlock` component, following the `RenewalDrawer.tsx` comment-section pattern.

**Tech Stack:** Django 5 + DRF (backend), React 19 + TanStack Query v5 (frontend), pytest + pytest-django (backend tests), PostgreSQL (`journal` dev / `journal_test` test DB).

**Spec:** `docs/superpowers/specs/2026-07-10-student-comments-design.md` (approved)

---

## Context for the implementer

- Backend app root: `journal_django/`. Run all backend commands from there.
- Python: `.venv/Scripts/python.exe` (Windows venv already set up).
- Tests: `.venv/Scripts/python.exe -m pytest <path> -v` — settings come from `pytest.ini` (`DJANGO_SETTINGS_MODULE=config.settings.test`, DB `journal_test`). **Never** override this to point at the dev DB (`journal`) — see the fail-fast guard in `config/settings/test.py`.
- Migrations must be applied to **both** databases separately:
  - Dev DB (`journal`, default settings): `.venv/Scripts/python.exe manage.py migrate students`
  - Test DB (`journal_test`): `DJANGO_SETTINGS_MODULE=config.settings.test .venv/Scripts/python.exe manage.py migrate students`
- Frontend root: `journal_django/frontend/admin-src/`. Build: `npm run build`. Typecheck: `npx tsc --noEmit`.
- Existing pattern this plan mirrors throughout: `apps/renewals/models.py::RenewalActivity` (model), `apps/renewals/views.py::RenewalCommentView`/`RenewalActivityView` (views), `apps/teacher_spa/views.py::MyLessonsView` (ListAPIView + StandardPagination), `frontend/admin-src/src/pages/renewals/RenewalDrawer.tsx` (comment UI).
- Root pytest fixtures (`journal_django/conftest.py`): `anon_client`, `teacher_client`, `manager_client`, `admin_client`, `superadmin_client` — real JWT-authenticated `APIClient` instances backed by real accounts in `journal_test`, torn down after each test. `make_auth_client(account)` is importable via `from conftest import make_auth_client` (already used this way elsewhere in the codebase).

---

### Task 1: Model — `StudentComment`

**Files:**
- Modify: `journal_django/apps/students/models.py`
- Create: `journal_django/apps/students/tests/test_comment_model.py`
- Create (generated): `journal_django/apps/students/migrations/0008_studentcomment.py`

- [ ] **Step 1: Write the failing test**

```python
"""Тесты модели StudentComment (без БД — только объявление/метаданные)."""
from __future__ import annotations

from django.db import models

from apps.students.models import StudentComment


def test_table_name():
    assert StudentComment._meta.db_table == 'student_comment'


def test_fields():
    field_names = {f.name for f in StudentComment._meta.get_fields()}
    assert {'id', 'student', 'body', 'author', 'created_at'} <= field_names


def test_author_on_delete_set_null():
    field = StudentComment._meta.get_field('author')
    assert field.remote_field.on_delete is models.SET_NULL


def test_student_on_delete_cascade():
    field = StudentComment._meta.get_field('student')
    assert field.remote_field.on_delete is models.CASCADE


def test_not_pghistory_tracked():
    """
    Осознанное исключение из общего правила CLAUDE.md («каждая новая модель →
    pghistory + registry») — см. docs/superpowers/specs/2026-07-10-student-comments-design.md.
    Комментарий уже self-audit (author+created_at видны в UI), отдельный
    changelog-след избыточен.
    """
    from apps.changelog.registry import TRACKED
    assert 'students.StudentComment' not in TRACKED
```

Create `journal_django/apps/students/tests/test_comment_model.py` with the content above.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_comment_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'StudentComment' from 'apps.students.models'`

- [ ] **Step 3: Add the model**

Append to `journal_django/apps/students/models.py` (after the existing `Student` class, keep the existing `import pghistory` / `from django.db import models` at top unchanged):

```python
class StudentComment(models.Model):
    """
    Комментарий менеджера/админа к ученику. Append-only: без UpdateEvent, без
    API редактирования. Не трекается pghistory — сам факт (author+created_at)
    уже виден в UI, отдельный changelog-след избыточен (осознанное отступление
    от общего правила CLAUDE.md, см. docs/superpowers/specs/2026-07-10-student-comments-design.md).
    """

    id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE,
        db_column='student_id', related_name='comments',
    )
    body = models.TextField()
    author = models.ForeignKey(
        'accounts.Account', on_delete=models.SET_NULL, null=True, blank=True,
        db_column='author_id', related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'student_comment'
        indexes = [
            models.Index(fields=['student', '-created_at'], name='student_comment_student_idx'),
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_comment_model.py -v`
Expected: 5 passed

- [ ] **Step 5: Generate and apply the migration**

Run: `cd journal_django && .venv/Scripts/python.exe manage.py makemigrations students`
Expected: `Migrations for 'students': apps/students/migrations/0008_studentcomment.py - Create model StudentComment`

Run: `cd journal_django && .venv/Scripts/python.exe manage.py migrate students`
Expected: `Applying students.0008_studentcomment... OK` (applies to dev DB `journal`)

Run: `cd journal_django && DJANGO_SETTINGS_MODULE=config.settings.test .venv/Scripts/python.exe manage.py migrate students`
Expected: `Applying students.0008_studentcomment... OK` (applies to test DB `journal_test`)

- [ ] **Step 6: Commit**

```bash
git add journal_django/apps/students/models.py journal_django/apps/students/tests/test_comment_model.py journal_django/apps/students/migrations/0008_studentcomment.py
git commit -m "feat(students): add StudentComment model (append-only, not changelog-tracked)"
```

---

### Task 2: Repository + services functions

**Files:**
- Modify: `journal_django/apps/students/repository.py`
- Modify: `journal_django/apps/students/services.py`
- Create: `journal_django/apps/students/tests/test_comment_repository.py`

- [ ] **Step 1: Write the failing test**

Create `journal_django/apps/students/tests/test_comment_repository.py`:

```python
"""Тесты StudentsRepository — функции комментариев."""
from __future__ import annotations

import pytest
from django.db import connection

from apps.students import repository


def _create_student() -> int:
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status, created_at) "
            "VALUES ('__test_repo_comment_student__', 'enrolled', NOW()) RETURNING id"
        )
        return cur.fetchone()[0]


def _cleanup(student_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM student_comment WHERE student_id = %s', [student_id])
        cur.execute('DELETE FROM students WHERE id = %s', [student_id])


@pytest.mark.django_db
def test_add_comment_creates_row():
    student_id = _create_student()
    try:
        comment = repository.add_comment(student_id, 'Текст', author_id=None)
        assert comment.id is not None
        assert comment.student_id == student_id
        assert comment.body == 'Текст'
        assert comment.author_id is None
    finally:
        _cleanup(student_id)


@pytest.mark.django_db
def test_delete_comment_removes_row_and_reports_missing():
    student_id = _create_student()
    try:
        comment = repository.add_comment(student_id, 'Текст', author_id=None)
        assert repository.delete_comment(student_id, comment.id) is True
        assert repository.delete_comment(student_id, comment.id) is False
    finally:
        _cleanup(student_id)


@pytest.mark.django_db
def test_delete_comment_scoped_to_student():
    """Комментарий другого ученика delete_comment не трогает (student_id обязателен в WHERE)."""
    student_a = _create_student()
    student_b = _create_student()
    try:
        comment = repository.add_comment(student_a, 'Текст', author_id=None)
        assert repository.delete_comment(student_b, comment.id) is False
    finally:
        _cleanup(student_a)
        _cleanup(student_b)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_comment_repository.py -v`
Expected: FAIL — `AttributeError: module 'apps.students.repository' has no attribute 'add_comment'`

- [ ] **Step 3: Implement repository functions**

In `journal_django/apps/students/repository.py`, change the import line:

```python
from .models import Student
```

to:

```python
from .models import Student, StudentComment
```

Then append at the end of the file:

```python
# ---------------------------------------------------------------------------
# Repository functions — student comments (ORM)
# ---------------------------------------------------------------------------

def add_comment(student_id: int, body: str, author_id: Optional[int]) -> StudentComment:
    """Создаёт комментарий (INSERT). Существование student_id проверяет вызывающий (view)."""
    return StudentComment.objects.create(student_id=student_id, body=body, author_id=author_id)


def delete_comment(student_id: int, comment_id: int) -> bool:
    """Удаляет комментарий. False если не найден (или принадлежит другому ученику)."""
    deleted, _ = StudentComment.objects.filter(id=comment_id, student_id=student_id).delete()
    return deleted > 0
```

In `journal_django/apps/students/services.py`, append at the end of the file:

```python
def add_comment(student_id: int, body: str, author_id: Optional[int]):
    """Создаёт комментарий к ученику."""
    return repository.add_comment(student_id, body, author_id)


def delete_comment(student_id: int, comment_id: int) -> bool:
    """Удаляет комментарий. False если не найден."""
    return repository.delete_comment(student_id, comment_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_comment_repository.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/students/repository.py journal_django/apps/students/services.py journal_django/apps/students/tests/test_comment_repository.py
git commit -m "feat(students): add repository/service functions for student comments"
```

---

### Task 3: Serializers

**Files:**
- Modify: `journal_django/apps/students/serializers.py`
- Create: `journal_django/apps/students/tests/test_comment_serializers.py`

- [ ] **Step 1: Write the failing test**

Create `journal_django/apps/students/tests/test_comment_serializers.py`:

```python
"""Тесты сериализаторов комментариев (без БД)."""
from __future__ import annotations

from apps.students.serializers import StudentCommentWriteSerializer


def test_rejects_blank_body():
    ser = StudentCommentWriteSerializer(data={'body': '   '})
    assert not ser.is_valid()
    assert 'body' in ser.errors


def test_strips_body():
    ser = StudentCommentWriteSerializer(data={'body': '  Привет  '})
    assert ser.is_valid(), ser.errors
    assert ser.validated_data['body'] == 'Привет'


def test_rejects_too_long_body():
    ser = StudentCommentWriteSerializer(data={'body': 'x' * 5001})
    assert not ser.is_valid()
    assert 'body' in ser.errors


def test_accepts_max_length_body():
    ser = StudentCommentWriteSerializer(data={'body': 'x' * 5000})
    assert ser.is_valid(), ser.errors
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_comment_serializers.py -v`
Expected: FAIL — `ImportError: cannot import name 'StudentCommentWriteSerializer' from 'apps.students.serializers'`

- [ ] **Step 3: Implement serializers**

Append to `journal_django/apps/students/serializers.py`:

```python
class StudentCommentSerializer(serializers.Serializer):
    """Read-only элемент списка комментариев (GET .../comments)."""

    id = serializers.IntegerField()
    body = serializers.CharField()
    created_at = serializers.DateTimeField()
    author_id = serializers.IntegerField(allow_null=True)
    author_name = serializers.SerializerMethodField()

    def get_author_name(self, obj) -> str | None:
        return obj.author.full_name if obj.author_id and obj.author else None


class StudentCommentWriteSerializer(serializers.Serializer):
    """Ввод для POST .../comments."""

    body = serializers.CharField(max_length=5000, allow_blank=False)

    def validate_body(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError('body must not be blank')
        return stripped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_comment_serializers.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add journal_django/apps/students/serializers.py journal_django/apps/students/tests/test_comment_serializers.py
git commit -m "feat(students): add comment serializers"
```

---

### Task 4: Views + URLs + API tests

**Files:**
- Modify: `journal_django/apps/students/views.py`
- Modify: `journal_django/apps/students/urls.py`
- Create: `journal_django/apps/students/tests/test_comment_api.py`

- [ ] **Step 1: Write the failing test**

Create `journal_django/apps/students/tests/test_comment_api.py`:

```python
"""API-тесты для /api/admin/students/:id/comments."""
from __future__ import annotations

import pytest
from django.contrib.auth.hashers import make_password
from django.db import connection

from conftest import make_auth_client

BASE_URL = '/api/admin/students'


def _create_student() -> int:
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO students (full_name, enrollment_status, created_at) "
            "VALUES ('__test_api_comment_student__', 'enrolled', NOW()) RETURNING id"
        )
        return cur.fetchone()[0]


def _cleanup_student(student_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM student_comment WHERE student_id = %s', [student_id])
        cur.execute('DELETE FROM students WHERE id = %s', [student_id])


def _create_named_admin_client(full_name: str):
    from apps.accounts.models import Account
    pw = make_password('testpass_sentinel')
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO accounts "
            "(email, password, role, is_active, is_staff, is_superuser, "
            "first_name, last_name, full_name, token_version, date_joined) "
            "VALUES (%s, %s, 'admin', true, false, false, '', '', %s, 0, NOW()) RETURNING id",
            ['__test_named_admin__@test.local', pw, full_name],
        )
        acc_id = cur.fetchone()[0]
    account = Account.objects.get(pk=acc_id)
    return make_auth_client(account), acc_id


def _cleanup_account(acc_id: int) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM accounts WHERE id = %s', [acc_id])


@pytest.mark.django_db
def test_no_cookie_returns_401(anon_client):
    student_id = _create_student()
    try:
        resp = anon_client.get(f'{BASE_URL}/{student_id}/comments')
        assert resp.status_code == 401
    finally:
        _cleanup_student(student_id)


@pytest.mark.django_db
def test_teacher_cannot_list(teacher_client):
    student_id = _create_student()
    try:
        resp = teacher_client.get(f'{BASE_URL}/{student_id}/comments')
        assert resp.status_code == 403
    finally:
        _cleanup_student(student_id)


@pytest.mark.django_db
def test_unknown_student_returns_404(admin_client):
    resp = admin_client.get(f'{BASE_URL}/999999999/comments')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_manager_can_create_and_list(manager_client):
    student_id = _create_student()
    try:
        resp = manager_client.post(
            f'{BASE_URL}/{student_id}/comments',
            {'body': 'Родители просили перенести занятия'},
            format='json',
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body['body'] == 'Родители просили перенести занятия'
        assert 'author_name' in body

        resp = manager_client.get(f'{BASE_URL}/{student_id}/comments')
        assert resp.status_code == 200
        data = resp.json()
        assert data['total'] == 1
        assert data['rows'][0]['body'] == 'Родители просили перенести занятия'
    finally:
        _cleanup_student(student_id)


@pytest.mark.django_db
def test_create_blank_body_returns_400(admin_client):
    student_id = _create_student()
    try:
        resp = admin_client.post(f'{BASE_URL}/{student_id}/comments', {'body': '  '}, format='json')
        assert resp.status_code == 400
    finally:
        _cleanup_student(student_id)


@pytest.mark.django_db
def test_author_name_reflects_creator():
    """author_name в ответе — реальное имя автора (join на accounts)."""
    student_id = _create_student()
    client, acc_id = _create_named_admin_client('Иван Иванов')
    try:
        resp = client.post(f'{BASE_URL}/{student_id}/comments', {'body': 'Комментарий'}, format='json')
        assert resp.status_code == 201
        resp = client.get(f'{BASE_URL}/{student_id}/comments')
        row = resp.json()['rows'][0]
        assert row['author_name'] == 'Иван Иванов'
    finally:
        _cleanup_student(student_id)
        _cleanup_account(acc_id)


@pytest.mark.django_db
def test_manager_cannot_delete(manager_client):
    student_id = _create_student()
    try:
        resp = manager_client.post(f'{BASE_URL}/{student_id}/comments', {'body': 'x'}, format='json')
        comment_id = resp.json()['id']
        resp = manager_client.delete(f'{BASE_URL}/{student_id}/comments/{comment_id}')
        assert resp.status_code == 403
    finally:
        _cleanup_student(student_id)


@pytest.mark.django_db
def test_admin_can_delete(admin_client):
    student_id = _create_student()
    try:
        resp = admin_client.post(f'{BASE_URL}/{student_id}/comments', {'body': 'x'}, format='json')
        comment_id = resp.json()['id']
        resp = admin_client.delete(f'{BASE_URL}/{student_id}/comments/{comment_id}')
        assert resp.status_code == 204
        resp = admin_client.delete(f'{BASE_URL}/{student_id}/comments/{comment_id}')
        assert resp.status_code == 404
    finally:
        _cleanup_student(student_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_comment_api.py -v`
Expected: FAIL — 404s across the board (no route registered for `/comments`)

- [ ] **Step 3: Implement views**

In `journal_django/apps/students/views.py`, update imports at the top:

```python
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import StandardPagination
from apps.core.permissions import IsManagerOrAdmin, ReadStaffWriteAdmin
from apps.students import services
from apps.students.models import StudentComment
from apps.students.serializers import (
    StudentCommentSerializer,
    StudentCommentWriteSerializer,
    StudentUpdateSerializer,
    StudentWriteSerializer,
)
```

(This adds `generics`, `ReadStaffWriteAdmin`, `StudentComment`, and the two new serializers to the existing import block — keep everything else in the file unchanged.)

Append at the end of `journal_django/apps/students/views.py`:

```python
class StudentCommentListView(generics.ListAPIView):
    """
    GET  /api/admin/students/:id/comments — список комментариев, пагинация
    POST /api/admin/students/:id/comments — добавить комментарий → 201

    404 если ученик не найден (единообразно с StudentStatsView).
    """

    permission_classes = [IsManagerOrAdmin]
    pagination_class = StandardPagination
    serializer_class = StudentCommentSerializer

    def get_queryset(self):
        return (
            StudentComment.objects
            .filter(student_id=self.kwargs['pk'])
            .select_related('author')
            .order_by('-created_at')
        )

    def get(self, request: Request, pk: int) -> Response:
        if services.get_student(pk) is None:
            raise NotFound({'error': 'Not found'})
        return super().get(request, pk)

    def post(self, request: Request, pk: int) -> Response:
        if services.get_student(pk) is None:
            raise NotFound({'error': 'Not found'})
        ser = StudentCommentWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        comment = services.add_comment(pk, ser.validated_data['body'], getattr(request.user, 'id', None))
        return Response(StudentCommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class StudentCommentDetailView(APIView):
    """DELETE /api/admin/students/:id/comments/:comment_id — только admin/superadmin."""

    permission_classes = [ReadStaffWriteAdmin]

    def delete(self, request: Request, pk: int, comment_id: int) -> Response:
        ok = services.delete_comment(pk, comment_id)
        if not ok:
            raise NotFound({'error': 'Not found'})
        return Response(status=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Wire URLs**

Replace `journal_django/apps/students/urls.py` in full:

```python
"""
URL маршруты для раздела students.

Монтируются в config/urls.py как:
  path('api/admin/students', include('apps.students.urls'))

APPEND_SLASH=False — пути без trailing slash (зеркало Express/Nest).
"""
from django.urls import path

from apps.students.views import (
    StudentBalanceView,
    StudentCommentDetailView,
    StudentCommentListView,
    StudentDetailView,
    StudentListCreateView,
    StudentStatsView,
)

urlpatterns = [
    path('', StudentListCreateView.as_view(), name='students-list-create'),
    path('/<int:pk>', StudentDetailView.as_view(), name='students-detail'),
    path('/<int:pk>/stats', StudentStatsView.as_view(), name='students-stats'),
    path('/<int:pk>/balance', StudentBalanceView.as_view(), name='students-balance'),
    path('/<int:pk>/comments', StudentCommentListView.as_view(), name='students-comments'),
    path(
        '/<int:pk>/comments/<int:comment_id>',
        StudentCommentDetailView.as_view(),
        name='students-comment-detail',
    ),
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students/tests/test_comment_api.py -v`
Expected: 8 passed

- [ ] **Step 6: Run the full students test suite (regression check)**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest apps/students -v`
Expected: all tests pass (no regressions in existing `test_students_api.py`/`test_students_repository.py`)

- [ ] **Step 7: Commit**

```bash
git add journal_django/apps/students/views.py journal_django/apps/students/urls.py journal_django/apps/students/tests/test_comment_api.py
git commit -m "feat(students): add comments API (list/create/delete)"
```

---

### Task 5: Frontend — permissions helper, types, hooks

**Files:**
- Modify: `journal_django/frontend/admin-src/src/lib/permissions.ts`
- Create: `journal_django/frontend/admin-src/src/lib/student-comments.ts`
- Create: `journal_django/frontend/admin-src/src/hooks/useStudentComments.ts`

- [ ] **Step 1: Add permission helper**

In `journal_django/frontend/admin-src/src/lib/permissions.ts`, append:

```typescript
export const canDeleteStudentComments = isAdminUp; // удаление комментария к ученику
```

- [ ] **Step 2: Add the comment type**

Create `journal_django/frontend/admin-src/src/lib/student-comments.ts`:

```typescript
// Тип для комментариев к ученику. Бэкенд: /api/admin/students/:id/comments
// (Django+DRF, см. docs/superpowers/plans/2026-07-10-student-comments.md).

export interface StudentComment {
  id: number;
  body: string;
  created_at: string;
  author_id: number | null;
  author_name: string | null;
}
```

- [ ] **Step 3: Add query/mutation hooks**

Create `journal_django/frontend/admin-src/src/hooks/useStudentComments.ts`:

```typescript
import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Paginated } from '../lib/types';
import type { StudentComment } from '../lib/student-comments';

const KEY = ['students', 'comments'] as const;

export function useStudentComments(studentId: number | null, page: number, pageSize: number) {
  return useQuery({
    queryKey: [...KEY, studentId, page, pageSize],
    queryFn: () => api<Paginated<StudentComment>>(
      'GET',
      `/api/admin/students/${studentId}/comments?page=${page}&page_size=${pageSize}`,
    ),
    enabled: !!studentId,
    placeholderData: keepPreviousData,
  });
}

export function useStudentCommentMutations(studentId: number | null) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: [...KEY, studentId] });
  return {
    add: useMutation({
      mutationFn: (body: string) =>
        api<StudentComment>('POST', `/api/admin/students/${studentId}/comments`, { body }),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (commentId: number) =>
        api('DELETE', `/api/admin/students/${studentId}/comments/${commentId}`),
      onSuccess: invalidate,
    }),
  };
}
```

- [ ] **Step 4: Typecheck**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add journal_django/frontend/admin-src/src/lib/permissions.ts journal_django/frontend/admin-src/src/lib/student-comments.ts journal_django/frontend/admin-src/src/hooks/useStudentComments.ts
git commit -m "feat(admin-spa): add types/hooks for student comments"
```

---

### Task 6: Frontend — `StudentCommentsBlock` component + styles

**Files:**
- Create: `journal_django/frontend/admin-src/src/pages/students/StudentCommentsBlock.tsx`
- Modify: `journal_django/frontend/admin-src/src/styles/pages/detail.css`

- [ ] **Step 1: Create the component**

Create `journal_django/frontend/admin-src/src/pages/students/StudentCommentsBlock.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { Textarea } from '../../components/form/Textarea';
import { fmtDateTime } from '../../lib/format';
import { canDeleteStudentComments, type Role } from '../../lib/permissions';
import { useStudentComments, useStudentCommentMutations } from '../../hooks/useStudentComments';
import type { StudentComment } from '../../lib/student-comments';

const PAGE_SIZE = 20;

interface Props {
  studentId: number;
}

export default function StudentCommentsBlock({ studentId }: Props) {
  const { me } = useAuth();
  const canDelete = canDeleteStudentComments(me?.role as Role);

  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<StudentComment[]>([]);
  const [text, setText] = useState('');

  const { data, isLoading } = useStudentComments(studentId, page, PAGE_SIZE);
  const { add, remove } = useStudentCommentMutations(studentId);

  useEffect(() => {
    setPage(1);
    setRows([]);
  }, [studentId]);

  useEffect(() => {
    if (!data) return;
    setRows((prev) => (page === 1 ? data.rows : [...prev, ...data.rows]));
  }, [data, page]);

  const resetToFirstPage = () => {
    setPage(1);
    setRows([]);
  };

  const handleAdd = () => {
    const body = text.trim();
    if (!body) return;
    add.mutate(body, { onSuccess: () => { setText(''); resetToFirstPage(); } });
  };

  const handleDelete = (commentId: number) => {
    remove.mutate(commentId, { onSuccess: resetToFirstPage });
  };

  const hasMore = !!data && rows.length < data.total;

  return (
    <div className="student-comments">
      <div className="student-comments__section-title">Добавить комментарий</div>
      <Textarea
        className="student-comments__input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Написать комментарий об ученике…"
        rows={3}
      />
      <button
        type="button"
        className="btn-secondary"
        disabled={!text.trim() || add.isPending}
        onClick={handleAdd}
      >
        Добавить
      </button>

      <ul className="student-comments__list">
        {rows.map((c) => (
          <li key={c.id} className="student-comments__item">
            <div className="student-comments__meta">
              <span>{c.author_name || 'Неизвестный автор'}</span>
              <span>{fmtDateTime(c.created_at)}</span>
              {canDelete && (
                <button
                  type="button"
                  className="student-comments__delete"
                  onClick={() => handleDelete(c.id)}
                  disabled={remove.isPending}
                >
                  Удалить
                </button>
              )}
            </div>
            <div className="student-comments__body">{c.body}</div>
          </li>
        ))}
        {!isLoading && rows.length === 0 && (
          <li className="student-comments__empty">Пока нет комментариев</li>
        )}
      </ul>

      {hasMore && (
        <button
          type="button"
          className="btn-secondary"
          onClick={() => setPage((p) => p + 1)}
          disabled={isLoading}
        >
          Показать ещё
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add styles**

Append to `journal_django/frontend/admin-src/src/styles/pages/detail.css`:

```css
.student-comments {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  max-width: 640px;
}

.student-comments__section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.student-comments__input {
  width: 100%;
  resize: vertical;
}

.student-comments__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.student-comments__item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  color: var(--text2);
}

.student-comments__meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 11px;
  color: var(--text3);
}

.student-comments__delete {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--text3);
  cursor: pointer;
  font-size: 11px;
  text-decoration: underline;
}

.student-comments__empty {
  font-size: 13px;
  color: var(--text3);
}
```

- [ ] **Step 3: Typecheck**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/students/StudentCommentsBlock.tsx journal_django/frontend/admin-src/src/styles/pages/detail.css
git commit -m "feat(admin-spa): add StudentCommentsBlock component"
```

---

### Task 7: Frontend — wire the "Комментарии" tab into `StudentDetailPage`

**Files:**
- Modify: `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx`

- [ ] **Step 1: Add the tab**

In `journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx`:

Change the import block (add the new component import) — after the existing:

```tsx
import { StudentBalanceBlock } from './StudentBalanceBlock';
```

add:

```tsx
import StudentCommentsBlock from './StudentCommentsBlock';
```

Change:

```tsx
const STUDENT_TABS = ['learning', 'finance'] as const;
```

to:

```tsx
const STUDENT_TABS = ['learning', 'finance', 'comments'] as const;
```

In the `tabs` array (after the `finance` entry), add:

```tsx
    {
      value: 'comments',
      label: 'Комментарии',
      content: <StudentCommentsBlock studentId={student.id} />,
    },
```

so the full `tabs` array reads:

```tsx
  const tabs: TabItem[] = [
    {
      value: 'learning',
      label: 'Обучение',
      content: (
        <div className="student-learning-grid">
          <div className="student-learning-grid__main">
            <div className="sub-header">Статистика посещаемости</div>
            <StudentStatsBlock studentId={student.id} />
          </div>
          <div className="student-learning-grid__side">
            <EntityCard title="Данные ученика" row={student} fields={fields} />
            <div className="sub-header">Группы ученика</div>
            <MembershipsBlock
              config={{
                mode: 'byStudent',
                studentId: student.id,
                pickerOptions: groupOptions,
                pickerLabel: 'Выберите группу',
              }}
              emptyText="Не записан ни в одну группу"
              renderCard={(m) => {
                const g = groups.find((x) => x.id === m.group_id);
                const dir = g ? directions.find((d) => d.id === g.direction_id) : null;
                return {
                  title: m.group_name || `#${m.group_id}`,
                  meta: (
                    <>
                      {dir && <DirTag direction={dir} />}
                      {g && !g.active && <span className="archive-tag">Архив</span>}
                    </>
                  ),
                  navigateTo: `/admin/groups/${m.group_id}`,
                };
              }}
            />
          </div>
        </div>
      ),
    },
    {
      value: 'finance',
      label: 'Финансы',
      content: <StudentBalanceBlock studentId={student.id} />,
    },
    {
      value: 'comments',
      label: 'Комментарии',
      content: <StudentCommentsBlock studentId={student.id} />,
    },
  ];
```

- [ ] **Step 2: Typecheck and build**

Run: `cd journal_django/frontend/admin-src && npx tsc --noEmit`
Expected: no errors

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: build succeeds

- [ ] **Step 3: Commit**

```bash
git add journal_django/frontend/admin-src/src/pages/students/StudentDetailPage.tsx
git commit -m "feat(admin-spa): wire Комментарии tab into StudentDetailPage"
```

---

### Task 8: Final verification

- [ ] **Step 1: Full backend test suite**

Run: `cd journal_django && .venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass, no regressions (in particular `apps/changelog/tests/test_api_registry.py`-style coverage tests, if any, stay green since `StudentComment` is deliberately not registered)

- [ ] **Step 2: Frontend build**

Run: `cd journal_django/frontend/admin-src && npm run build`
Expected: build succeeds, no TypeScript errors

- [ ] **Step 3: Manual smoke test**

Start the dev server (`cd journal_django && .venv/Scripts/python.exe manage.py runserver`) and the admin SPA dev flow per the project's local nginx setup. Open a student detail page, switch to the "Комментарии" tab, add a comment as a manager account, verify author name + timestamp show up, verify a manager account cannot see a delete button, verify an admin account can delete.

- [ ] **Step 4: Commit (if any fixups were needed)**

Only if Steps 1–3 required changes; otherwise this task produces no commit.
