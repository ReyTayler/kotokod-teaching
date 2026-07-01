# 04 — Дашборд (`apps/dashboard`)

**Агенты:** `voltagent-lang:sql-pro` (raw SQL) + `voltagent-lang:django-developer`,
`security-auditor`/`code-reviewer` на финансовых числах.
**Источник (Node):** `services/repo/dashboard.js`, `routes/admin/dashboard.js`.
**Зависит от:** `apps/finances` (FIFO), payments, lessons.

## Эндпоинты (`/api/admin/dashboard`, роли manager/admin)

| Метод | Путь | Поведение |
|-------|------|-----------|
| GET | `/` | Сводка: revenue_month (по payments), worked_off_month (через FIFO из `finances/`), top-долги, carryover. Параметры `from`/`to` (YYYY-MM-DD). |
| GET | `/monthly` | Year-over-year по месяцам: revenue + worked_off за каждый месяц. Параметры `year`/`years`. |

## Критичное

- worked_off считать **через единый `finances/fifo.py`**, не дублировать FIFO.
- Все денежные значения — Decimal→строка с масштабом.
- Месячные границы — МСК; переход Dec→Jan корректно.
- raw SQL через cursor, дословно из `services/repo/dashboard.js`.

## Verification

- golden-fixtures: revenue/worked_off/monthly до копейки против Express на реальных данных.
- Граничное: год с неполными месяцами, переход года.
