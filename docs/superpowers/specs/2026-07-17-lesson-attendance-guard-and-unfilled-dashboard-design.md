# Блокировка урока без присутствующих + виджет «Незаполненные уроки» в admin-дашборде

Дата: 2026-07-17

## Проблема (аудит)

Урок можно записать, не отметив присутствующим ни одного ученика — ни фронт,
ни бэкенд это не проверяют.

- **teacher SPA** (`LessonForm.tsx`): если в группе 0 учеников
  (`groupData.students.length === 0`), кнопка «Сохранить урок» ничем не
  блокируется (`disabled={limitExceeded || submitLesson.isPending}` — строка
  256), и `students: []` уходит на сервер. (Отдельно: если группа непуста, но
  ВСЕ ученики заблокированы по оплате, `present` для всех останется `false` —
  это НЕ баг, а уже протестированный легитимный кейс фиксации отсутствия, см.
  «Семантика правила» ниже — не блокируется этим фиксом.)
- **backend** (`apps/lessons/services.py::record_lesson` — единое ядро и для
  teacher SPA, и для admin SPA): не проверяет непустоту `present_student_ids`.
  `SubmitLessonSerializer.students` (DRF `ListSerializer`, `allow_empty=True`
  по умолчанию) и `LessonCreateSerializer.attendance` (`required=False`) тоже
  пропускают пустой список без ошибки. `calculate_payment` при `present=0`
  просто возвращает `0` — урок с нулевой посещаемостью и нулевой зарплатой
  благополучно создаётся.
- **admin SPA**: `LessonEditor.tsx` (`components/lessons/LessonEditor.tsx:74-81`)
  уже блокирует и 0 учеников в группе, и 0 присутствующих — это внутри плана
  группы (`GroupDetailPage` → вкладка «Уроки»). Но отдельная модалка
  `pages/lessons/LessonFormModal.tsx` (роут `/admin/lessons`) валидирует
  ТОЛЬКО `!groupId || !teacherId` (строка 58) — защиты от пустой посещаемости
  нет вообще.

Отдельно: на admin-дашборде (`DashboardPage.tsx`, вкладки «Финансы»/«Реестр»)
нет виджета «незаполненные уроки» — ближайший аналог, `today_stream` в
«Реестре», показывает расписание ТОЛЬКО на сегодня, без статуса заполнения.
В teacher SPA такой список есть (`ReportPage.tsx`, фильтр `status==='overdue'`
поверх `GET /api/calendar`), но он скоупится по одному преподавателю.

## Часть 1 — блокировка записи урока без присутствующих учеников

### Семантика правила

Запретить сохранение, только если список `attendance` ПУСТ (`len(attendance)
== 0`) — то есть в группе физически нет ни одного ученика, привязанного к
уроку. НЕ блокировать случай, когда `attendance` непустой, но все записи
`present=false` — это легитимный, уже протестированный кейс фиксации
отсутствия (`apps/teacher_spa/tests/test_teacher_spa_api.py::
test_absent_student_not_incremented`,
`::test_absent_allowed_without_paid_balance`: единственный ученик группы
отмечен отсутствующим → урок успешно создаётся, `success: true`). Блокировка
по «0 present» сломала бы эту уже одобренную функциональность (фиксация того,
что урок состоялся, даже если никто/не все ученики пришли).

Эталон для ПЕРВОЙ (а не второй) проверки — уже одобренная логика
`LessonEditor.handleSave` (строка 74 файла `LessonEditor.tsx`):

```ts
if (totalStudents === 0) { toast('В группе нет учеников — урок зафиксировать нельзя', 'error'); return; }
```

Вторую проверку `LessonEditor` (`presentCount === 0`, строка 78) НЕ тиражируем
на остальные точки входа — это самостоятельная, более строгая UX-политика
именно этой формы (admin по умолчанию открывает новый урок со всеми
«не присутствовал», так что чек защищает от «забыл отметить»), она не
является бизнес-правилом всего приложения и конфликтует с legitimate-кейсом
teacher SPA выше. `LessonEditor` не трогаем — его текущее поведение остаётся
как есть (см. «Вне охвата»).

### Backend — единая точка правды

`apps/lessons/services.py::record_lesson` — используется и `submit_lesson`
(teacher SPA), и `create_lesson_full` (admin SPA). Правка:

```python
if not attendance:
    raise EmptyAttendanceBlocked()
present_student_ids = [a['student_id'] for a in attendance if a['present']]
repository.assert_students_paid(present_student_ids)
```

Проверка — ДО открытия транзакции (как существующий `assert_students_paid`),
ничего не пишется при ошибке.

Новое исключение в `apps/lessons/exceptions.py` (по образцу
`UnpaidAttendanceBlocked`):

```python
class EmptyAttendanceBlocked(Exception):
    """Попытка записать урок для группы без единого ученика (attendance=[])."""
    def __init__(self) -> None:
        super().__init__('Нельзя записать урок без учеников.')
```

Ловится в двух местах, где уже ловится `UnpaidAttendanceBlocked` (тот же
паттерн «доменное исключение → 400/success:false», без нового HTTP-статуса):

- `apps/lessons/views.py::LessonListCreateView.post` (строки 132-135) →
  добавить `except EmptyAttendanceBlocked as e: return Response({'error':
  str(e)}, status=400)` рядом с существующим `except UnpaidAttendanceBlocked`.
- `apps/teacher_spa/services.py::submit_lesson` (строки 201-216) → добавить
  `except EmptyAttendanceBlocked as e: return {'success': False, 'error':
  str(e)}` рядом с существующим `except UnpaidAttendanceBlocked`.

Докстрока `record_lesson` дополняется упоминанием нового исключения.

### Frontend — teacher SPA (`LessonForm.tsx`)

- `noStudents = groupData.students.length === 0` (группа без единого
  ученика — реальный, хоть и редкий кейс: все ученики архивированы/удалены
  из группы, группа осталась активной).
- Кнопка «Сохранить урок» (строка 256): `disabled={limitExceeded ||
  noStudents || submitLesson.isPending}`.
- `handleSubmit` (строка 100): ранний выход `if (limitExceeded || noStudents
  || submitLesson.isPending) return;`.
- Инлайн-предупреждение в стиле существующего блока `limitExceeded`/`lf-error`:
  «В группе нет учеников — урок зафиксировать нельзя.» (текст — как в
  `LessonEditor`, для единообразия формулировок в проекте).

### Frontend — admin SPA (`LessonFormModal.tsx`)

`LessonEditor.tsx` не трогаем — там правило уже есть (и более строгое —
осознанно не трогаем его политику). В `LessonFormModal.tsx` добавляем ТОЛЬКО
проверку пустой группы (не проверку `presentCount`):

- В `onSubmit` (строка 56), сразу после проверки `!groupId || !teacherId`:
  ```ts
  if (members.length === 0) { toast('В группе нет учеников — урок зафиксировать нельзя', 'error'); return; }
  ```
- Кнопка «Создать урок» (футер `Dialog`, строка 106): дополнительно
  дизейблится, если `groupId` выбран и `members.length === 0`.

### Тесты

- `apps/lessons/tests/test_lessons_repository.py` — сервисный тест:
  `services.create_lesson_full({..., 'attendance': []})` →
  `EmptyAttendanceBlocked`, ничего не создаётся.
- `apps/lessons/tests/test_lessons_api.py` — новый кейс: POST
  `/api/admin/lessons` с `attendance: []` → 400, тело содержит `{'error':
  ...}`, урок не создаётся.
- `apps/teacher_spa/tests/test_teacher_spa_api.py` — новый кейс: группа без
  единого ученика (`students: []` в payload) → `{'success': False, 'error':
  ...}`, ничего не создаётся в БД. ВАЖНО: существующие тесты
  `test_absent_student_not_incremented`/`test_absent_allowed_without_paid_balance`
  (единственный студент, `present: false`) должны остаться зелёными без
  изменений — они проверяют легитимный кейс, который это правило НЕ
  затрагивает.
- Frontend-тестов в проекте нет (только pytest на бэке) — фронтовую часть
  проверить вручную в браузере (dev server): teacher SPA и admin SPA —
  сценарий с группой без учеников (например, временно очистить `members` в
  дев-БД или проверить UI-логику точечно).

## Часть 2 — виджет «Незаполненные уроки» в admin-дашборде

### Решения (закреплены с пользователем)

- Место: новая вкладка на `DashboardPage.tsx` рядом с «Финансы»/«Реестр» —
  не перегружает существующие вкладки, пространство для роста.
- Объём: скользящее окно 30 дней (просроченные occurrences) + серверная
  пагинация, отсортировано по (date, time) — старые просрочки первыми.
  Окно фиксировано на бэкенде (не query-параметр) — граница защиты от
  неограниченного запроса, соответствует правилу проекта «не читать всё».

### Backend

`apps/scheduling/repository.py` — новая функция, по образцу уже
существующей school-wide (не per-teacher) `occurrences_on_date`
(секция «ЧТЕНИЕ planned_lessons для реестра куратора, вся школа»):

```python
def unfilled_planned_lessons(window_from: date, window_to: date) -> list[dict]:
    """
    Плановые занятия ВСЕХ активных групп в окне со status='pending'
    (done/cancelled/moved уже исключены хранимым статусом). Overdue —
    точный порог (время урока < now) проверяет вызывающий (services),
    как и в occurrences_on_date/build_calendar.
    """
    return list(
        PlannedLesson.objects
        .filter(group__active=True, status=PENDING,
                scheduled_date__gte=window_from, scheduled_date__lte=window_to)
        .order_by('scheduled_date', 'scheduled_time')
        .values(
            'scheduled_date', 'scheduled_time', 'teacher_id',
            group_pk=F('group_id'), group_name=F('group__name'),
            direction_name=F('group__direction__name'),
            direction_color=F('group__direction__color'),
        )
    )
```

`apps/scheduling/services.py` — новая функция (рядом с `build_calendar`,
переиспользует `msk_now()`/`MSK`, ту же логику определения overdue, что
`_planned_status`):

```python
def build_unfilled_lessons(window_days: int = 30) -> list[dict]:
    now = msk_now()
    today = now.date()
    window_from = today - datetime.timedelta(days=window_days)
    rows = repository.unfilled_planned_lessons(window_from, today)
    tnames = repository.teacher_names()
    out = []
    for r in rows:
        occ_dt = datetime.datetime.combine(
            r['scheduled_date'], r['scheduled_time'] or datetime.time(0, 0), tzinfo=MSK,
        )
        if now < occ_dt:
            continue  # ещё не наступил
        out.append({
            'group_id': r['group_pk'],
            'group_name': r['group_name'],
            'teacher_name': tnames.get(r['teacher_id']),
            'direction_name': r['direction_name'],
            'direction_color': r['direction_color'],
            'date': r['scheduled_date'].isoformat(),
            'time': r['scheduled_time'].strftime('%H:%M') if r['scheduled_time'] else None,
        })
    out.sort(key=lambda x: (x['date'], x['time'] or ''))
    return out
```

`apps/dashboard/views.py` — новый тонкий `UnfilledLessonsView`
(`permission_classes = [IsManagerOrAdmin]`, как остальные вьюхи дашборда),
пагинация встроенным `StandardPagination` (контракт `{rows, total, page,
page_size}` — тот же, что везде в проекте; `PageNumberPagination` штатно
работает и с обычным Python-списком, не только с `QuerySet`):

```python
class UnfilledLessonsView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request: Request) -> Response:
        rows = scheduling_services.build_unfilled_lessons()
        paginator = StandardPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)
```

`apps/dashboard/urls.py` — добавить `path('/unfilled-lessons',
UnfilledLessonsView.as_view(), name='dashboard-unfilled-lessons')` рядом с
`''`/`'/monthly'`. Итоговый маршрут: `GET /api/admin/dashboard/unfilled-lessons`.

### Frontend

- `pages/dashboard/DashboardPage.tsx` — `type Tab = 'finance' | 'registry' |
  'unfilled'`, третья кнопка таба «Незаполненные», лениво загружаемый чанк
  (`lazy(() => import('./unfilled/UnfilledLessonsTab'))`, как уже сделано для
  `RegistryTab`).
- Новый `pages/dashboard/unfilled/UnfilledLessonsTab.tsx` — переиспользует
  существующий `components/table/DataTable` + встроенный `Paginator`
  (server-mode, как `RegistryTable`), никакого нового списочного компонента:
  - колонки: Дата+время (`date` + `time`), Группа (имя + цветной маркер
    `direction_color`), Преподаватель;
  - `onRowClick` → `navigate('/admin/groups/${row.group_id}?tab=lessons')`
    (существующий query-param-driven таб `GroupDetailPage`, вкладка «Уроки» с
    `LessonGrid`/`LessonEditor`) — без изобретения deep-link в конкретный слот;
  - пагинация через `useListSearchParams({ sortBy: 'date', sortDir: 'asc',
    pageSize: 30 })` (сортировка фактически не используется — колонки не
    sortable, — но хук требует defaults).
- Новый хук `hooks/useUnfilledLessons.ts` — `useQuery` +
  `placeholderData: keepPreviousData` (обязательное правило проекта для
  server-paginated хуков), по образцу `useRegistry.ts::useRegistryStudents`.
- Новый тип `UnfilledLesson` в `lib/shared-types.ts` (рядом с `Paginated<T>`):
  ```ts
  export interface UnfilledLesson {
    group_id: number;
    group_name: string;
    teacher_name: string | null;
    direction_name: string | null;
    direction_color: string | null;
    date: string;
    time: string | null;
  }
  ```

### Тесты

- `apps/scheduling/tests/` — новый файл или кейсы в существующем
  (`test_build_calendar.py`-подобный): `unfilled_planned_lessons`/
  `build_unfilled_lessons` — school-wide scope (несколько преподавателей),
  overdue-фильтр (будущие pending не попадают, done/cancelled/moved
  исключены), сортировка, обрезка окна 30 дней.
- `apps/dashboard/tests/` — API-тест: права (`IsManagerOrAdmin`, 403 для
  teacher), пагинация (`{rows, total, page, page_size}`).
- Frontend — проверка вручную в браузере (dev server): вкладка появляется,
  список показывает просроченные занятия, клик по строке ведёт в группу.

## Вне охвата (сознательно не трогаем)

- `LessonEditor.tsx` — правило там уже реализовано корректно.
- Изменение статуса `overdue` на materialized (хранимый) — остаётся
  вычисляемым на чтении, как и было (`_planned_status`); новый viewset не
  меняет эту модель, просто переиспользует тот же принцип school-wide.
- Deep-link в конкретный слот/урок группы с дашборда — переход на вкладку
  «Уроки» группы достаточен, точечный автооткрытие `LessonEditor` не входит
  в объём (YAGNI).
- Параметр окна (`window_days`) как query-параметр API — не нужен, виджет
  всегда показывает одно и то же скользящее окно.
