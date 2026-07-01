-- 015_students_consent.sql — фиксация факта согласия на обработку ПДн (152-ФЗ).
BEGIN;

ALTER TABLE students
  ADD COLUMN consent_given bool NOT NULL DEFAULT false,
  ADD COLUMN consent_at    timestamptz,
  ADD COLUMN consent_by    text,
  ADD COLUMN consent_note  text;

COMMIT;
