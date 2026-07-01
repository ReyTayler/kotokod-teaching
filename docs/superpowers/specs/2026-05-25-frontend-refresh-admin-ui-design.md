# Frontend Refresh + Admin UI — Design

**Дата:** 2026-05-25
**Статус:** Design approved, готов к написанию плана реализации (Phase 4.1 — Visual system)
**Связан с:** [`2026-05-25-postgres-migration-v2-design.md`](./2026-05-25-postgres-migration-v2-design.md) — Phase 4 миграции расширен до этого документа.

## Цель

1. Обновить визуальный язык существующего teacher-SPA (`public/Index.html`) до refined dark стилистики уровня Linear/Vercel.
2. Добавить admin-SPA (`public/admin.html`) с полным CRUD по 6 сущностям БД — заменить ручное редактирование Google Sheets.

Функциональность teacher-SPA не меняется. Архитектурно — vanilla HTML/CSS/JS без bundler'ов и framework'ов.

## Ключевые решения

| Решение | Выбор |
|---------|-------|
| Тип обновления | Визуальный лифтинг (не UX-перестройка, не framework-миграция) |
| Визуальное направление | Refined dark — Linear/Vercel-стиль, OKLCH-палитра, spring-анимации |
| Архитектура фронтенда | Два независимых HTML-файла + общий `styles.css` |
| Admin доступ | Отдельный URL `/admin`, логин + пароль |
| Auth механизм | Cookie-based session (HMAC, без серверного storage), bcrypt пароли |
| Admin scope MVP | Полный CRUD по всем 6 сущностям |
| Mobile/desktop | Teacher SPA — mobile-first как сейчас; admin — desktop-first (≥1024px) |
| Тёмная/светлая тема | Только тёмная (light не поддерживаем) |

## Visual system (общая основа)

Живёт в `public/styles.css`, подключается из обоих HTML-файлов.

### Палитра — OKLCH

```css
/* фоны */
--bg:         oklch(0.16 0.015 260);
--surface-1:  oklch(0.20 0.018 260);
--surface-2:  oklch(0.24 0.020 260);
--surface-3:  oklch(0.28 0.022 260);
--border:     oklch(0.32 0.020 260);
--border-strong: oklch(0.40 0.022 260);

/* текст */
--text:       oklch(0.96 0.005 260);
--text-2:     oklch(0.72 0.010 260);
--text-3:     oklch(0.50 0.010 260);

/* акценты */
--accent:     oklch(0.70 0.18 250);
--accent-hi:  oklch(0.78 0.20 250);
--accent-soft: oklch(0.30 0.10 250 / 0.4);

/* семантика */
--ok:    oklch(0.74 0.16 150);
--warn:  oklch(0.78 0.15  85);
--err:   oklch(0.65 0.20  25);
```

OKLCH вместо HEX: оттенки с равной воспринимаемой светлотой → палитра сразу сбалансированная.

### Типография

| Уровень | Шрифт | Размер | Weight | Tracking | Применение |
|---------|-------|--------|--------|----------|------------|
| Display | Manrope | 36px | 700 | -0.02em | Главные заголовки экранов |
| H1 | Manrope | 24px | 600 | -0.015em | Заголовки секций |
| H2 | Manrope | 18px | 600 | -0.01em | Карточки |
| Body | Manrope | 15px | 500 | -0.005em | Основной текст |
| Small | Manrope | 13px | 500 | 0 | Подписи |
| Code/num | JetBrains Mono | 14px | 500 | 0 | Числа, IDs |

### Радиусы и тени

```css
--r-sm: 6px;  --r-md: 10px;  --r-lg: 14px;  --r-xl: 20px;
--shadow-1: 0 1px 0 rgb(255 255 255 / 0.04) inset, 0 1px 2px rgb(0 0 0 / 0.3);
--shadow-2: 0 1px 0 rgb(255 255 255 / 0.06) inset, 0 4px 12px rgb(0 0 0 / 0.4);
```

Inset-белая линия сверху — Linear-style halo, имитация «света сверху».

### Motion

```css
--ease-out:    cubic-bezier(0.16, 1, 0.3, 1);
--ease-spring: cubic-bezier(0.5, 1.5, 0.3, 1);
--dur-fast: 120ms;  --dur-base: 200ms;  --dur-slow: 360ms;
```

### Spacing

Шкала 4/8/12/16/24/32/48/64 (степень 1.5), токены `--sp-1..--sp-7`.

### Компоненты (CSS-классы, нулевой JS)

- `.btn` + варианты `primary`/`secondary`/`ghost`, размеры `sm`/`md`/`lg`
- `.input` для text/number/select/textarea
- `.card` — `--surface-1` + бордер + `--shadow-1`
- `.pill` — статус-бейджи с цветовыми вариантами `ok`/`warn`/`err`
- `.modal` — диалог с overlay (используется в admin)
- `.table` — стилизованная таблица (sticky-шапка, чередование, hover)

## Файловая структура

```
public/
├── Index.html        ← teacher SPA (рефреш стиля)
├── admin.html        ← новый admin SPA
└── styles.css        ← общая визуальная система
```

`server.js`:
- `app.get('/admin', (req, res) => res.sendFile(path.join(__dirname, 'public', 'admin.html')));` перед `static`.
- Остальное Express уже отдаёт через `express.static('public')`.

**Что НЕ выносим в общий код:**
- Логика логина (на teacher SPA и admin разная, ~30 строк каждая — шарить ради 10 общих строк не стоит).
- Бизнес-функции (`switchPage`, `renderStudents` — только teacher; CRUD-функции — только admin).

## Teacher SPA — что меняется в `Index.html`

DOM-структура и JS **не меняются**. Меняется только CSS:
- Локальный `<style>`-блок переписывается: дубли цвета/шрифта/радиусов уезжают в `styles.css`.
- Старые HEX-переменные (`#0f1117`, `#4f8ef7` и т.п.) заменяются на OKLCH-токены.
- Все `box-shadow`, `border-radius`, `transition`, `font-size`/`font-weight` мигрируют на новые токены.

### Точечные полиш-правки по экранам

- **Login (ввод токена):** focus-кольцо в `--accent`, появление со spring-overshoot.
- **Главные табы:** активный — 1px underline `--accent`, без glow; inactive — `--text-2`, hover на `--surface-2`.
- **Журнал → выбор группы:** карточки на `--surface-1` с `--shadow-1`; hover поднимает до `--shadow-2` + `translateY(-1px)`; иконка-таймер в `--accent-soft` pill.
- **Журнал → выбор учеников:** `--touch=44px` сохраняется; кастомный CSS-only чекбокс; spring на toggle.
- **Журнал → отправка:** сводка как `.card` с разделителем перед итоговой суммой; success-экран с большим ✓ в `--ok`.
- **Расписание:** дни недели — горизонтальный chip-row; статусы через `--ok`/`--warn`/`--err`; pop-up деталей через общий `.modal`.
- **Отчёт:** фильтры — chip-стиль; строки таблицы компактные; цветовая полоса слева 4px `--warn` для overdue.

### Что НЕ меняем

- DOM-структуру и id (используется JS).
- Существующие JS-функции (`switchPage`, `populateGroups`, `submitLesson`, и т.п.).
- Mobile-first 640px max на desktop.
- Логику кеш-бейджа, retry, empty states, плейн PWA-теги.

**Ожидаемый размер:** локальный `<style>` ужмётся на 30–40%; файл из 3593 → ~2800–3000 строк.

## Admin SPA — `public/admin.html`

Desktop-first (≥1024px), без mobile-оптимизации.

### Layout

```
┌──────────────────────────────────────────────────────────────┐
│  Журнал · Admin                              admin · [Выход] │
├──────────┬───────────────────────────────────────────────────┤
│  Ученики │                                                   │
│  Группы  │     <main content area>                           │
│ Препод-и │                                                   │
│  Токены  │                                                   │
│ Направ-я │                                                   │
│  Состав  │                                                   │
└──────────┴───────────────────────────────────────────────────┘
```

- **Top bar:** название продукта, role-индикатор, кнопка «Выход».
- **Sidebar:** 6 разделов в порядке «часто правится → редко». Активный — `--accent-soft` фон.
- **Content area:** одна таблица + действия для текущего раздела.

### Login-экран

Если cookie сессии отсутствует/протухла — `/admin` отдаёт `admin.html`, JS видит отсутствие cookie и рендерит центрированную login-карточку:

```
┌──────────────────────────┐
│  Admin · Журнал          │
│  Логин   [____________]  │
│  Пароль  [____________]  │
│  [          Войти      ] │
└──────────────────────────┘
```

### Универсальная структура раздела

```
[ Ученики ]                          [ Поиск... ]  [ + Новый ]
─────────────────────────────────────────────────────────────
Имя              Группа           Возраст   Статус   Преподаватель
─────────────────────────────────────────────────────────────
Иванов Петя      Python вт 18:00   12       ●enrolled  Анна П.
Петров Саша      Scratch ср 17:00  10       ●frozen 02 Мария И.
...                                                   (clickable)
```

- **Поиск:** клиентская фильтрация по `full_name`/`name`.
- **«+ Новый»:** модалка с пустой формой.
- **Клик по строке:** модалка с прелейфилом + кнопки «Сохранить» / «Удалить».
- **Удаление:** двухшаговое; для сущностей с FK-зависимостями — soft delete (`active=false` / `archived_at`), не hard delete.

### Поля по сущностям (формы в модалках)

- **Students:** full_name, birth_date, phone, school_grade (1–11), platform_id, parent_name, first_purchase_date, age, pm, enrollment_status (radio + если frozen, селект месяца), таблица групп ученика с кнопкой «Добавить в группу».
- **Groups:** name, direction (select), teacher (select), is_individual, lesson_duration_minutes (radio 45/60/90), lessons_per_week, group_start_date, vk_chat, динамический список слотов времени (день недели + время).
- **Teachers:** name, email, phone.
- **Tokens:** token (text/«Сгенерировать»), teacher (select), active.
- **Directions:** name, sheet_name (advanced/hidden), is_individual.
- **Memberships:** редактируется внутри карточки Students (не отдельным разделом). В sidebar пункт «Состав» — read-only обзор «Все ученики по группам».

### Backend admin endpoints

Все требуют admin-cookie. Без cookie / с протухшим → `401`.

```
POST /api/admin/login              { username, password }    → Set-Cookie
POST /api/admin/logout                                       → clear cookie

GET    /api/admin/students                                   → list
POST   /api/admin/students         { ...fields }             → create
PATCH  /api/admin/students/:id     { ...updated }            → update
DELETE /api/admin/students/:id                               → soft delete

# То же для /groups, /teachers, /tokens, /directions

POST   /api/admin/group-memberships  { student_id, group_id, lessons_done, remaining }
PATCH  /api/admin/group-memberships/:id  { lessons_done, remaining, active }
DELETE /api/admin/group-memberships/:id

POST   /api/admin/tokens/generate                            → { token: "<random 16 chars>" }
```

### Authentication

**Cookie-based session, без серверного storage:**

```
.env:
  ADMIN_USERNAME=ilya
  ADMIN_PASSWORD_HASH=<bcrypt-hash>
  ADMIN_COOKIE_SECRET=<random-64-bytes-hex>
```

- **Логин:** сравниваем пароль с bcrypt-hash → формируем cookie `admin_session=<base64(payload)>.<hmac-sha256(payload, secret)>`, где `payload = { iat, exp: iat+24h, user }`. Cookie `HttpOnly`, `SameSite=Strict`, `Path=/api/admin`, `Secure` на проде.
- **Middleware `requireAdmin`:** парсит cookie, проверяет HMAC + exp. Ставит `req.admin = { user }` или возвращает `401`.
- **Logout:** `Set-Cookie: admin_session=; Max-Age=0`.

**Новые зависимости:** `bcrypt` (или fallback `bcryptjs`, если bcrypt не ставится под Windows), `cookie-parser`. HMAC — через node:crypto, без сторонних либ.

## Декомпозиция Phase 4

### Phase 4.1 — Visual system foundation

- `public/styles.css` с полным набором токенов и компонентов.
- Подключение в `Index.html` + переписывание локального `<style>`-блока под новые токены.
- Acceptance: все экраны teacher SPA в новой стилистике; `docs/smoke-tests.md` зелёный.
- **Зависимости:** нет. Можно делать сразу после Phase 1 миграции PG.

### Phase 4.2 — Backend admin endpoints + auth

- `npm install bcrypt cookie-parser` (fallback на `bcryptjs` если bcrypt не собирается).
- Генерация `ADMIN_PASSWORD_HASH`, `ADMIN_COOKIE_SECRET`; добавление в `.env` / `.env.example`.
- Новые файлы: `services/admin-auth.js`, `services/admin-repository.js`.
- Admin endpoints в `server.js` (6 разделов + `/login`, `/logout`).
- Unit-тесты `services/admin-auth.test.js` (sign, verify, expire).
- Acceptance: curl-чеклист всех эндпоинтов; без cookie — 401; bcrypt-сравнение корректно.
- **Зависимости:** PG — источник правды (Phase 2 миграции выполнен).

### Phase 4.3 — Admin SPA

- `public/admin.html` (login + layout + 6 разделов + модалки).
- Express-роут `/admin` → `admin.html`.
- Vanilla JS, fetch к admin endpoint'ам.
- Acceptance: новый чеклист `docs/admin-smoke-tests.md` — клик-сценарий «вход → создание ученика → редактирование группы → выпуск токена → удаление direction → выход».
- **Зависимости:** Phase 4.2 готов.

### Phase 4.4 — Polish / dogfood

- После недели реальной работы — список мелких UX/visual фиксов.
- Опционально: `admin_audit_log` таблица + endpoint.
- Acceptance: subjective.

## Связь с PG-миграцией — финальный порядок фаз

С учётом этого spec, порядок всей миграции:

1. ✅ Phase 0 (foundation) — выполнено.
2. ✅ Phase 1 (repository layer) — выполнено.
3. **Phase 4.1 — Visual refresh teacher SPA** ← можно делать сейчас (не зависит от PG).
4. Phase 2 (Backfill) — exhaustive импорт Sheets → PG.
5. **Phase 4.2 — Backend admin endpoints + auth** ← после backfill, до cutover (чтобы admin API работал к моменту cutover).
6. **Phase 4.3 — Admin SPA** ← может идти параллельно с 4.2 (фронт без бэка имеет смысл проектировать и стилить вперёд).
7. Phase 3 (Cutover) — teacher SPA переключается на PG.
8. **Phase 4.4 — Polish / dogfood** ← после cutover.
9. Phase 5 (Cleanup) — удаление sheets.js, googleapis.

## Тестирование

- **Phase 4.1:** `docs/smoke-tests.md` (уже есть) + клик глазами по каждому экрану.
- **Phase 4.2:** unit-тесты `admin-auth.test.js` + curl-чеклист admin endpoints.
- **Phase 4.3:** новый чеклист `docs/admin-smoke-tests.md` — клик-сценарий каждой CRUD-операции.
- **Phase 4.4:** dogfood — реальная работа в admin неделю, фиксы по факту.

## Риски

1. **Visual refresh ломает невидимый функционал.** Митигация: smoke-tests + ручная проверка каждого экрана.
2. **bcrypt не ставится под Windows.** Митигация: fallback на `bcryptjs`.
3. **Cookie секрет меняется при рестарте → массовый logout.** Митигация: секрет фиксирован в `.env`, не регенерируется.
4. **N+1 в admin endpoints при перечислении группы с учениками.** Митигация: явные JOIN-запросы (не ORM), профайлинг по slow-query log.
5. **Удаление сущности с FK-связями (student → lesson_attendance, group → lessons).** Митигация: soft delete для всего, что может быть в логах истории; hard delete только для tokens/directions/teachers без зависимостей.

## Что НЕ делаем (явное YAGNI)

- Light theme / theme switcher.
- Mobile-оптимизация admin (≥1024px-only).
- Multi-user admin / роли.
- Двухфакторка.
- Pagination в admin-таблицах (~500 учеников помещаются).
- Undo / истории изменений (можно добавить через admin_audit_log позже).
- Bundler / npm-зависимости фронтенда / framework.
- SSR / шаблонизаторы.
- Иконка-библиотеки (inline SVG где нужно).
- Real-time / WebSocket (CRUD достаточно request-response).

## Следующий шаг

Передать этот spec в skill `superpowers:writing-plans` для составления implementation plan по **Phase 4.1 (Visual system foundation)** — это первый блок, не зависящий от PG-миграции, можно начинать сразу.

Phase 4.2/4.3/4.4 — отдельные планы, пишутся после стабилизации предыдущей подфазы и завершения нужных PG-фаз (см. финальный порядок выше).
