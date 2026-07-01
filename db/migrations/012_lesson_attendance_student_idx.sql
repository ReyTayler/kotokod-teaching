-- 012_lesson_attendance_student_idx.sql
-- Индекс на lesson_attendance(student_id).
--
-- PK таблицы — (lesson_id, student_id), поэтому поиск ТОЛЬКО по student_id
-- (карточка ученика, getStudentBalance, _balanceForDirection, studentStats)
-- не может использовать PK (leftmost-prefix) и делает seq scan.
-- На вырост (100–200k строк) это деградирует. Индекс держит такие запросы на
-- единицах мс. Заодно покрывает FK student_id → students (PG не индексирует FK сам).
--
-- На маленькой таблице CREATE INDEX внутри транзакции мгновенен. На большой
-- проде стоило бы CREATE INDEX CONCURRENTLY (без блокировки записи, но вне tx).

BEGIN;

CREATE INDEX IF NOT EXISTS lesson_attendance_student_idx
  ON lesson_attendance (student_id);

COMMIT;
