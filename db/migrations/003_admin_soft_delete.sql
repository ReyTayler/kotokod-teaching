BEGIN;

ALTER TABLE teachers   ADD COLUMN active boolean NOT NULL DEFAULT true;
ALTER TABLE groups     ADD COLUMN active boolean NOT NULL DEFAULT true;
ALTER TABLE directions ADD COLUMN active boolean NOT NULL DEFAULT true;

CREATE INDEX teachers_active_idx   ON teachers(active)   WHERE active = true;
CREATE INDEX groups_active_idx     ON groups(active)     WHERE active = true;
CREATE INDEX directions_active_idx ON directions(active) WHERE active = true;

COMMIT;
