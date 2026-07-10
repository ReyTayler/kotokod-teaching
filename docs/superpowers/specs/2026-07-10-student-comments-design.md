# Комментарии к ученику — дизайн

Дата: 2026-07-10
Статус: утверждён, готов к написанию плана реализации

## Контекст

Нужен механизм оставления комментариев к сущности «Ученик» в admin SPA. Требования пользователя:
- история комментариев сохраняется;
- видно, кто из пользователей оставил комментарий (автор + дата).

В кодовой базе уже есть почти точный прецедент — комментарии к сделкам продления
(`apps/renewals/models.py: RenewalActivity`, kind='comment') с UI-паттерном в
`frontend/admin-src/src/pages/renewals/RenewalDrawer.tsx`. Дизайн ниже во многом
зеркалит этот паттерн, упрощая его (без stage-changes/payment-linked событий — только
чистые комментарии).

## Решения (зафиксированы с пользователем)

| Вопрос | Решение |
|---|---|
| Кто видит/пишет комментарии | Manager + Admin (`IsManagerOrAdmin`). Teacher — нет доступа. |
| Редактирование | Не поддерживается. Комментарии — append-only журнал. |
| Удаление | Только Admin (и superadmin). Manager не может удалить даже свой комментарий. |
| Список в UI | Отдельная вкладка «Комментарии» в карточке ученика (третий таб рядом с «Обучение»/«Финансы»). |
| Пагинация | Встроенная DRF-пагинация (`StandardPagination`, `{rows,total,page,page_size}`), в UI — «Показать ещё». |
| Журнал изменений (changelog/pghistory) | **Не трекается.** Осознанное исключение из общего правила CLAUDE.md («каждая новая модель → pghistory + registry») — комментарий уже self-audit: автор и дата видны прямо в UI, отдельный audit-trail избыточен. |
| Длина комментария | До 5000 символов, обычный текст (без вложений, @упоминаний, категорий/kind). |

## 1. Модель данных

Новый файл-дополнение в `journal_django/apps/students/models.py`:

```python
class StudentComment(models.Model):
    """
    Комментарий менеджера/админа к ученику. Append-only: без UpdateEvent/API редактирования.
    Не трекается pghistory — сам факт (author+created_at) уже виден в UI, отдельный
    changelog-след избыточен (решение зафиксировано в дизайне, отступление от общего
    правила CLAUDE.md "каждая новая модель → pghistory + registry").
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
        indexes = [models.Index(fields=['student', '-created_at'], name='student_comment_student_idx')]
```

Примечания:
- `on_delete=CASCADE` на `student` — ученики только soft-delete (`enrollment_status`), hard-delete не практикуется, но семантически комментарий бессмысленен без ученика.
- `author=SET_NULL` — при удалении учётки сотрудника комментарий не теряется, просто "автор неизвестен" (author_id=NULL).
- Обычная Django-миграция (`makemigrations students`), без pghistory event-таблицы.

## 2. Backend API

Права: `IsManagerOrAdmin` (`apps/core/permissions`) на список и создание. Удаление —
дополнительная проверка `request.user.role == Account.Role.ADMIN` (или superadmin)
внутри view; отдельного permission-класса не заводим, т.к. паттерна
"manager читает, admin пишет" в проекте для DELETE ещё нет — простая инлайн-проверка
достаточна для одного эндпоинта.

Маршруты (`journal_django/apps/students/urls.py`, монтируются под `/api/admin/students`):

```
GET    /:id/comments             — список, пагинация {rows,total,page,page_size}, sort: -created_at
POST   /:id/comments             — создать комментарий → 201
DELETE /:id/comments/:comment_id — удалить (только admin) → 204 | 403 | 404
```

Реализация (`apps/students/views.py`), по образцу `apps/teacher_spa/views.py: MyLessonsView`:

```python
class StudentCommentListView(ListAPIView):
    permission_classes = [IsManagerOrAdmin]
    pagination_class = StandardPagination
    serializer_class = StudentCommentSerializer

    def get_queryset(self):
        return (StudentComment.objects
                .filter(student_id=self.kwargs['pk'])
                .select_related('author')
                .order_by('-created_at'))

    def post(self, request, pk):
        ser = StudentCommentWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        comment = services.add_comment(pk, ser.validated_data['body'], request.user.id)
        return Response(StudentCommentSerializer(comment).data, status=201)


class StudentCommentDetailView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def delete(self, request, pk, comment_id):
        if request.user.role not in (Account.Role.ADMIN, Account.Role.SUPERADMIN):
            raise PermissionDenied()
        ok = services.delete_comment(pk, comment_id)
        if not ok:
            raise NotFound()
        return Response(status=204)
```

Серializers (`apps/students/serializers.py`):
- `StudentCommentWriteSerializer`: `body = CharField(required=True, allow_blank=False, max_length=5000)`.
- `StudentCommentSerializer` (чтение): `id, body, created_at, author_id, author_name` —
  `author_name` из `select_related('author')` (`SerializerMethodField` или explicit `source='author.full_name'`).

`apps/students/services.py` / `repository.py`: тонкие функции `add_comment(student_id, body, author_id)`,
`delete_comment(student_id, comment_id)` — прямой ORM (`.create()`, `.filter().delete()`),
без raw SQL — джойнов, требующих `connection.cursor()`, здесь нет.

## 3. Admin SPA (frontend)

- `pages/students/StudentDetailPage.tsx`: `STUDENT_TABS = ['learning', 'finance', 'comments']`,
  новый таб `{ value: 'comments', label: 'Комментарии', content: <StudentCommentsBlock studentId={student.id} /> }`.
- Новый компонент `pages/students/StudentCommentsBlock.tsx`, по образцу секции комментариев
  в `pages/renewals/RenewalDrawer.tsx`: `Textarea` (из `components/form/`) + кнопка «Добавить»
  сверху, под ней список — каждая строка показывает автора (`author_name`), дату
  (`fmtDateTime`) и текст. Пагинация — кнопка «Показать ещё» (накопительная подгрузка страниц,
  т.к. это лента, а не таблица).
- Кнопка удаления у строки видна только если `me.role === 'admin'` (`AuthProvider`, поле `me`).
- Новый хук-файл `hooks/useStudentComments.ts`:
  - `useStudentComments(studentId, page)` — query, `queryKey: ['students', 'comments', studentId, page]`.
  - `useAddStudentComment()` / `useDeleteStudentComment()` — mutations,
    `onSuccess: () => qc.invalidateQueries({ queryKey: ['students', 'comments', studentId] })`.
- Все элементы формы — `Textarea`/кнопки из `components/form/`, никаких native form-элементов
  (проектное правило).

## 4. Тесты

- `apps/students/tests/test_models.py` (или новый `test_comments.py`): `db_table` модели,
  индекс, `on_delete` поведение (`author=SET_NULL` при удалении Account).
- API-тесты (по образцу `apps/renewals/tests`): 403 для teacher, 201 для manager/admin
  при создании, корректная пагинация списка, 403 при удалении не-админом, 204 при удалении
  админом, 404 на несуществующий `comment_id`/`student_id`.

## Вне скоупа (осознанно исключено)

- Редактирование существующих комментариев.
- Доступ teacher (ни чтение, ни запись).
- Категории/типы комментариев (kind), @упоминания, вложения, форматирование текста.
- pghistory/changelog-трекинг модели (см. таблицу решений выше).
