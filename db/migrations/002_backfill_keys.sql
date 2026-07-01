-- 002_backfill_keys.sql
-- Натуральные ключи, необходимые для идемпотентного бэкфилла.

BEGIN;

ALTER TABLE students
  ADD CONSTRAINT students_full_name_key UNIQUE (full_name);

ALTER TABLE lessons
  ADD CONSTRAINT lessons_natural_key
  UNIQUE (lesson_date, group_id, lesson_number, submitted_by_token);

COMMIT;
