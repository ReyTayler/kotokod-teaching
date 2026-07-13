# Раздел «Календарь» в admin SPA

## Цель

Дать менеджеру/админу/супер-админу отдельный раздел «Календарь» в admin SPA,
идентичный по виду и поведению календарю teacher SPA (неделя/месяц/список,
KPI, легенда направлений, unscheduled-бейдж), но с обязательным выбором
преподавателя — раздел показывает расписание **одного** выбранного
преподавателя за раз.

## Контекст (что уже есть)

- Презентационный календарь уже вынесен в общий модуль
  `journal_django/frontend/admin-src/src/shared/calendar/` (`CalendarView`,
  `WeekGrid`, `MonthGrid`, `DayList`, `LessonPopup`, `types.ts`, `lib.ts`) и
  используется ОБОИМИ SPA: teacher — через alias `@shared/shared/calendar/...`
  (`pages/calendar/CalendarPage.tsx` + `hooks/useCalendar.ts` →
  `GET /api/calendar`), admin — сейчас только для плана одной группы
  (`pages/groups/GroupDetailPage.tsx` + `hooks/useGroupPlanCalendar.ts` →
  `GET /api/admin/groups/<id>/plan`).
- Бэкенд-логика сборки календаря уже параметризована по `teacher_id`:
  `apps/scheduling/services.py::build_calendar(window_from, window_to,
  teacher_id=None)` читает `planned_lessons` через
  `repository.planned_lessons_in_window(...)`. Публичного admin-эндпоинта,
  принимающего произвольный `teacher_id`, сейчас нет — есть только
  `GET /api/calendar` (роль `teacher`, скоуп — `request.user.teacher_id`,
  `apps/scheduling/views.py::CalendarView`, `permission_classes=[IsTeacher]`).
- RBAC-примитив `IsManagerOrAdmin` уже существует
  (`apps/core/permissions.py`) и используется в `apps/scheduling/views.py` для
  admin-операций плана (`GroupPlanView` и т.д.).
- В admin SPA есть готовый паттерн «фильтр по преподавателю»: хук
  `hooks/useTeachers.ts` (`GET /api/admin/teachers`) + `Combobox`/`SelectInput`
  из `components/form/` (пример — `pages/groups/GroupsListPage.tsx`,
  `GroupFormModal.tsx`).
- Паттерн нового top-level раздела с RBAC-гейтом: `pages/renewals/RenewalsPage.tsx`
  + маршрут `/admin/renewals` в `App.tsx` под
  `<RequireRole roles={['manager','admin','superadmin']}>` + пункт в
  `components/shell/Sidebar.tsx` (`SECTIONS`).

## Backend

### Новый эндпоинт `GET /api/admin/calendar`

- Новый `AdminCalendarView(APIView)` в `apps/scheduling/views.py`,
  `permission_classes = [IsManagerOrAdmin]`.
- Query-параметры: `teacher_id` (обязателен, `int`), `from`, `to`
  (обязательны, `YYYY-MM-DD`, та же валидация окна, что в `CalendarView.get`:
  корректность дат, `to >= from`, ширина окна ≤ `_MAX_WINDOW_DAYS` (92 дня)).
  Валидацию дат вынести в приватную функцию `_parse_window(request)` в
  `views.py`, переиспользуемую обоими view (`CalendarView` и
  `AdminCalendarView`), чтобы не дублировать пять веток `if`.
- Отсутствие/некорректность `teacher_id` → `400 Bad Request` (не «пустой
  конверт»; фронт и так не даёт сделать запрос без выбранного учителя, но
  API обязан валидировать сам, а не полагаться на фронт).
- Тело обработчика: `services.build_calendar(d_from, d_to,
  teacher_id=teacher_id)` — та же функция, что и для teacher-эндпоинта,
  без изменений в `services.py`/`repository.py`.
- Регистрация: новый файл `apps/scheduling/admin_urls.py` с
  `path('', AdminCalendarView.as_view(), name='scheduling-admin-calendar')`,
  подключить в `config/urls.py` как
  `path('api/admin/calendar', include('apps.scheduling.admin_urls'))`,
  расположив в блоке `/api/admin/*` (до строки `Phase 10 — teacher SPA`),
  согласно правилу «Admin обязан стоять ДО teacher-guard».

### Аддитивное поле `groupId` в Occurrence

Чтобы попап занятия в админском календаре мог дать ссылку на карточку
группы, `_planned_occurrence_dict` в `services.py` начинает отдавать
`'groupId': r['group_pk']` (значение уже выбирается в `build_calendar` —
`group_ids = sorted({r['group_pk'] for r in rows})`, просто прокинуть в
dict). Это НЕ ломает контракт teacher `/api/calendar` — поле новое,
опциональное, лишний ключ в JSON teacher SPA игнорирует. В
`shared/calendar/types.ts` добавляется `groupId?: number | null;` в
`Occurrence` (аналогично уже существующему опциональному `id`).

### Изменённые/новые файлы (backend)

- `apps/scheduling/views.py` — `_parse_window()` (рефакторинг из тела
  `CalendarView.get`), новый класс `AdminCalendarView`.
- `apps/scheduling/services.py` — добавить `groupId` в
  `_planned_occurrence_dict`.
- `apps/scheduling/admin_urls.py` — новый файл.
- `config/urls.py` — новая строка `include`.
- `apps/scheduling/tests/` — новые тесты (см. раздел «Тестирование»).

## Frontend

### Новая страница `pages/calendar/AdminCalendarPage.tsx`

Тонкая обёртка (по образцу `teacher-src/.../CalendarPage.tsx`):

- Локальный стейт `teacherId: number | null` (изначально `null`).
- `useTeachers()` — список для `Combobox` выбора преподавателя (заголовок
  страницы/тулбар, всегда виден).
- Пока `teacherId === null` — пустое состояние-заглушка («Выберите
  преподавателя, чтобы увидеть расписание») ВМЕСТО `CalendarView` (значит,
  `useAdminCalendar` не вызывает fetch, пока учитель не выбран — `enabled:
  teacherId != null` в `useQuery`).
- После выбора — рендерится `CalendarView` с `role="admin"`, БЕЗ `onAction`
  и `onLessonAction` (эти пропы не передаются → `LessonPopup.canModifyPlan`
  всегда `false` → попап строго read-only, без кнопок «Перенести/Отменить/
  Сменить преподавателя/Отметить урок» — по решению пользователя).
- Новый проп `onOpenGroup` у `CalendarView`/`LessonPopup` (см. ниже) —
  `onOpenGroup={(occ) => occ.groupId && navigate(`/admin/groups/${occ.groupId}`)}`.
- `onVisibleRangeChange` обновляет `{from, to}` в стейте (как teacher),
  сбрасывает при смене `teacherId` не требуется — `useAdminCalendar`
  реагирует на оба ключа через `queryKey`.

### Новый хук `hooks/useAdminCalendar.ts`

По образцу `teacher-src/.../useCalendar.ts`:

```ts
export function useAdminCalendar(teacherId: number | null, from: string, to: string) {
  return useQuery<CalendarResponse>({
    queryKey: ['admin-calendar', teacherId, from, to],
    queryFn: () => api<CalendarResponse>(
      'GET',
      `/api/admin/calendar?teacher_id=${teacherId}&from=${from}&to=${to}`,
    ),
    enabled: teacherId != null,
    placeholderData: (prev) => prev,
    staleTime: 60_000,
  });
}
```

### Расширение `shared/calendar/LessonPopup.tsx` и `CalendarView.tsx`

Новый необязательный проп `onOpenGroup?: (occ: Occurrence) => void`,
пробрасываемый `CalendarView` → внутренний `LessonPopup` → рендерит кнопку
«Открыть группу» (видна, если проп передан и `lesson.groupId != null`,
независимо от `role`). Teacher SPA проп не передаёт — поведение не
регрессирует (as с `onAction`/`onLessonAction`).

### Маршрут и навигация

- `App.tsx`: `<Route path="/admin/calendar" element={<RequireRole
  roles={['manager','admin','superadmin']}><AdminCalendarPage /></RequireRole>} />`.
- `components/shell/Sidebar.tsx`: новый пункт `SECTIONS` `{ key: 'calendar',
  label: 'Календарь', path: '/admin/calendar' }`, видимый для
  manager/admin/superadmin (тем же способом, что и существующие
  ролезависимые пункты — через хелпер из `lib/permissions.ts`, например
  `isStaff(role)`, поскольку teacher в эту навигацию не заходит).

### Изменённые/новые файлы (frontend)

- `pages/calendar/AdminCalendarPage.tsx` — новый.
- `hooks/useAdminCalendar.ts` — новый.
- `shared/calendar/LessonPopup.tsx`, `CalendarView.tsx`, `types.ts` — проп
  `onOpenGroup` + поле `groupId`.
- `App.tsx`, `components/shell/Sidebar.tsx` — маршрут + пункт меню.

## Обработка ошибок

- Нет выбранного преподавателя → пустая заглушка, запрос не уходит (не
  ошибка).
- `400` от бэкенда (некорректные даты/окно) — тот же паттерн, что
  `CalendarView` уже показывает teacher (`cal-error` из `isError`).
- Смена преподавателя во время загрузки — `queryKey` включает `teacherId`,
  TanStack Query сам отменяет устаревший рендер через `placeholderData`.

## Тестирование

- Backend: новый файл `apps/scheduling/tests/test_admin_calendar.py` —
  403 без роли manager/admin/superadmin, 400 без `teacher_id`/`from`/`to`,
  200 с корректными параметрами возвращает occurrences только выбранного
  преподавателя, `groupId` присутствует в каждом occurrence.
  `test_teacher_reassignment.py` (существующий) — проверить, что новое поле
  `groupId` не ломает существующие ассерты (объекты сравниваются не по
  строгому набору ключей — проверить явно).
- Frontend: ручная проверка через `/run` — открыть `/admin/calendar` под
  ролью manager/admin/superadmin (пусто без выбора → выбор преподавателя →
  сетка недели/месяца → клик по занятию → попап read-only → кнопка «Открыть
  группу» ведёт на `/admin/groups/:id`); под ролью teacher — редирект
  (`RequireRole`); пункт меню не виден teacher.

## Вне рамок

- Никаких мутаций (перенос/отмена/смена преподавателя) из нового календаря
  — управление планом остаётся в `GroupDetailPage` → вкладка «Расписание».
  `onAction`/`onLessonAction` в новую страницу не прокидываются.
- Просмотр «все преподаватели сразу» не реализуется (см. решение
  пользователя — фильтр обязателен, один преподаватель за раз).
