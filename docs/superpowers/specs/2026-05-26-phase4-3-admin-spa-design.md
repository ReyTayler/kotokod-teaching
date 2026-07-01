# Phase 4.3 — Admin SPA (delta-spec)

**Дата:** 2026-05-26
**Статус:** Design approved, готов к writing-plans
**Базовый spec:** [`2026-05-25-frontend-refresh-admin-ui-design.md`](./2026-05-25-frontend-refresh-admin-ui-design.md) — раздел «Admin SPA», все визуальные решения и поля сущностей. Этот документ — **только дельта**.

## Что фиксирует этот документ

База в spec'е 2026-05-25 описывает «что» (палитра, sidebar с 6 разделами, поля по сущностям, login-карточка). Дельта фиксирует «как» — структуру кода и оперативные UX-решения, которые там не уточнены.

## Решения

| # | Вопрос | Решение |
|---|--------|---------|
| 1 | Где живёт JS | Отдельный файл `public/admin-app.js`, подключается `<script defer src="/admin-app.js">` |
| 2 | State | Module-scoped объект внутри `admin-app.js`. Без шины событий — разделы изолированные. |
| 3 | Загрузка данных | Лениво по клику на раздел. Первый клик → fetch + рендер; последующие — из кеша в `state.cache.<section>` до явного refresh. |
| 4 | Read-only «Состав» (overview всех memberships) | **Вне MVP.** Memberships редактируются только внутри карточки Student. Если по факту понадобится — добавляем в 4.4. |
| 5 | Валидация | Только серверная. PG CHECK + UNIQUE + явные `400` от endpoint'ов. Клиент шлёт raw form data; ошибку показывает тостом. Клиентская валидация — в 4.4 при необходимости. |
| 6 | Ошибки | Тосты в правом верхнем углу. Auto-dismiss 4с, hover — pause. Стек до 3 одновременно. |
| 7 | Маршрут | `app.get('/admin', (req, res) => res.sendFile(...admin.html))` **до** `express.static('public')`. Без расширения в URL. |

## Файловая структура

```
public/
├── admin.html        ← layout: login-card OR sidebar+main; модалка; toast-host
├── admin-app.js      ← вся логика (auth state, fetch, render, modal, toast)
└── styles.css        ← существующий, дополняется admin-specific классами
```

`server.js` — одна новая строка:
```js
app.get('/admin', (_req, res) => res.sendFile(path.join(__dirname, 'public', 'admin.html')));
```

## Auth flow на клиенте

Cookie `admin_session` — `HttpOnly`, читать из JS нельзя. Поэтому состояние авторизации проверяем «оптимистически» через первый запрос:

```
on DOMContentLoaded:
  hide everything
  fetch GET /api/admin/teachers (любой защищённый ping)
    → 200  : мы авторизованы, рендерим main layout
    → 401  : рендерим login-карточку
    → 5xx  : тост «Сервер недоступен», retry-кнопка
```

После успешного login (`POST /api/admin/login` → 200) — перезапускаем тот же flow (cookie уже стоит).

Logout: `POST /api/admin/logout` → location.reload (cookie очищена, страница пересоберёт layout).

## Структура `admin-app.js`

```
// state
const state = {
  authChecked: false,
  authenticated: false,
  activeSection: 'teachers',          // дефолт первого экрана
  cache: {                            // null = не загружено; [] = загружено и пусто
    teachers: null, tokens: null, directions: null,
    groups: null, students: null,
  },
};

// api wrapper
async function api(method, path, body)          // fetch + JSON + auto-toast on error
async function checkAuth()                       // ping /api/admin/teachers

// auth UI
function renderLogin()
async function handleLoginSubmit(e)
async function handleLogout()

// main layout
function renderShell()                           // sidebar + main-empty
function setActiveSection(name)                  // загружает кеш если нужно, вызывает renderer

// per-section renderers
function renderTeachers()    // плюс openTeacherModal(id?)
function renderTokens()
function renderDirections()
function renderGroups()      // самый большой: slots-редактор внутри модалки
function renderStudents()    // содержит memberships sub-таблицу

// shared: modal + toast
function openModal({ title, body, onSubmit, onDelete? })
function closeModal()
function toast(msg, kind = 'error')              // kind: 'error' | 'ok'
```

## Шаблон работы раздела (универсальный)

Каждый раздел экспортирует один публичный entry `renderXxx()`. Внутри:

1. Если `state.cache.xxx == null` → показать spinner-плейсхолдер, `await api('GET', '/api/admin/xxx')`, положить в `state.cache.xxx`.
2. Отрисовать таблицу: фильтр в шапке (client-side `String.includes`), строки с onClick → `openXxxModal(row.id)`, кнопка `+ Новый` → `openXxxModal(null)`.
3. Modal submit: `POST` или `PATCH` → при успехе обновить кеш (мутировать массив, не перетягивать) → `renderXxx()` заново.
4. Modal delete (только при edit): двухшаговая (вторая кнопка появляется после клика на «Удалить»). `DELETE` → пометить `active=false` в кеше, перерисовать.

## Specifics по разделам

- **Teachers / Tokens / Directions** — повторяют шаблон 1-в-1.
- **Tokens** — кнопка «Сгенерировать» рядом с полем `token` в модалке: `POST /api/admin/tokens/generate` → подставить в input.
- **Groups** — в модалке вложенный slot-редактор: список строк `[day-select] [time-input] [×]` + кнопка `+ слот`. Submit отправляет весь массив `slots` целиком; бэк делает DELETE+INSERT в транзакции (уже реализовано в Phase 4.2).
- **Students** — в модалке Edit под основными полями таблица memberships ученика: `[группа] [уроков пройдено] [осталось] [×]` + строка «Добавить в группу: [group-select] [Сохранить]». Каждое действие — отдельный fetch к `/api/admin/group-memberships`. Это нарушает «один submit», но обходит N+1 при отправке огромного diff'а. Допустимо для MVP.

## Toast

```html
<div id="toast-host" style="position:fixed;top:16px;right:16px;display:flex;flex-direction:column;gap:8px;z-index:9999"></div>
```

`toast(msg, kind)`:
- создать `<div class="toast toast--{kind}">msg</div>`
- prepend в host (не больше 3 видимых)
- setTimeout 4с → remove; pause/resume on `mouseenter`/`mouseleave`

Стили `.toast`, `.toast--error`, `.toast--ok` — в `styles.css` (используем существующие `--err`/`--ok` токены).

## Mapping серверных ошибок → текст тоста

| Код | Текст |
|-----|-------|
| 400 | "Заполните обязательные поля" (или `body.error` если он информативный) |
| 401 | "Сессия истекла" + `location.reload()` через 1.5с |
| 404 | "Запись не найдена" |
| 409 | "Уже существует" (или `body.error`) |
| 5xx | "Серверная ошибка" + log в console |

## YAGNI для MVP Phase 4.3

- Состав (overview всех memberships).
- Клиентская валидация (красные рамки, формат phone и пр.).
- Pagination таблиц (~500 учеников помещаются).
- Сортировка колонок (только дефолтный ORDER BY с бэка).
- Undo / истории изменений.
- Bulk-операции.
- Inline-редактирование в таблицах (всё через модалку).

## Acceptance

- `/admin` без cookie показывает login-карточку; с протухшим cookie — тоже.
- После login виден sidebar с 5 разделами (Состав скрыт): Ученики · Группы · Преподаватели · Токены · Направления.
- В каждом из 5 разделов можно: создать запись (`+ Новый`), отредактировать (клик по строке → модалка → Сохранить), мягко удалить (двухшаговая кнопка в модалке Edit).
- Tokens: кнопка «Сгенерировать» подставляет рандом из бэка.
- Groups: slot-редактор внутри модалки сохраняет произвольный набор слотов; повторное открытие группы показывает их же.
- Students: memberships редактируются внутри Edit-модалки.
- Любая ошибка бэка → тост с понятным текстом.
- Logout: `POST /api/admin/logout` + `location.reload` → снова login-карточка.
- `docs/admin-smoke-tests.md` дополнен кликовым чеклистом для всех CRUD-сценариев.

## Что НЕ входит в Phase 4.3

- Раздел «Состав» — отдельной задачей в 4.4 при необходимости.
- Клиентская валидация — 4.4.
- Audit log — 4.4 опционально.
- Phase 3 cutover — отдельная фаза после 4.3.

## Откат

Удалить:
- `public/admin.html`, `public/admin-app.js`
- Строку `app.get('/admin', ...)` в `server.js`
- Кликовый блок в `docs/admin-smoke-tests.md`

Backend (Phase 4.2) — остаётся работать; admin доступен через curl.

## Следующий шаг

Передать spec в `superpowers:writing-plans` для составления implementation plan по Phase 4.3.
