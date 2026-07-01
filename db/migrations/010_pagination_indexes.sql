-- 010_pagination_indexes.sql
-- Индексы для server-side пагинации.

BEGIN;

-- Ускоряем ORDER BY lesson_date DESC, id DESC для пагинации.
CREATE INDEX IF NOT EXISTS lessons_date_desc_idx ON lessons (lesson_date DESC, id DESC);

-- Для payroll-пагинации (Unit P2 будет использовать).
CREATE INDEX IF NOT EXISTS payroll_lesson_id_idx ON payroll (lesson_id);

-- Для payments-пагинации (в будущем).
CREATE INDEX IF NOT EXISTS payments_paid_at_desc_idx ON payments (paid_at DESC, id DESC);

COMMIT;
