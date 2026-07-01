BEGIN;

ALTER TABLE directions
  ADD COLUMN color text
  CHECK (color IS NULL OR color ~ '^#[0-9a-fA-F]{6}$');

COMMIT;
