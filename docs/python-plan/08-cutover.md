# 08 — Cutover на nginx и снос Express

**Агенты:** `voltagent-qa-sec:architect-reviewer` (финальное ревью) + `voltagent-infra:network-engineer`/
`deployment-engineer` (nginx-маршрутизация), `security-auditor` (финальный аудит).
**Источник (Node):** `server.js` (middleware, mount-порядок, статика, error-handler), nginx.

## Что делает

1. **nginx маршрутизирует разделы на Django** по готовности. Порядок mount соблюсти:
   `/api/auth` → `/api/admin` → `/api/...` (teacher). Auth переключается **последним**.
2. **Статику SPA** (`public/login`, `public/teacher`, `public/admin-dist`) отдаёт nginx.
3. **Сквозное** (зеркалить `server.js`): CORS-whitelist (`django-cors-headers`), helmet-эквивалент (security-заголовки),
   rate-limit (глобальный `/api` 300/мин + строгий `/api/auth/login` 10/15мин) — на nginx или DRF-throttle.
4. После полного переноса и зелёных e2e — **удалить** Express, Nest-каркас (`src/`, `test/nest/`), Node-зависимости бэка.

## НЕ удалять до перехода компании на веб-приложение

- **Backfill-скрипты** (`scripts/backfill-*.js`) — dev-инструмент подтягивания данных из Google-таблиц в БД.
- **`services/sheets.js`** — нужен backfill-скриптам.
  Удаляются в самый последний момент, отдельным шагом, по явному решению пользователя.

## Verification (перед сносом)

- Полный прогон фронта (admin SPA + teacher SPA + страница логина) против Django — поведение идентично.
- Все разделы: `scripts/diff_express.py` → пусто.
- `architect-reviewer` — финальное ревью структуры.
- `security-auditor` — финальный аудит (auth, заголовки, rate-limit, отсутствие утечек).
- Бэкап БД (`pg_dump`) до переключения; план отката (восстановление БД + откат конфигурации nginx).
