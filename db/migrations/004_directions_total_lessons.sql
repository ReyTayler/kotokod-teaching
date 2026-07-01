BEGIN;

ALTER TABLE directions ADD COLUMN total_lessons int CHECK (total_lessons IS NULL OR total_lessons >= 0);

COMMIT;
