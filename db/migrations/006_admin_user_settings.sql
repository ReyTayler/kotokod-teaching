BEGIN;

-- Per-admin client settings (table column visibility/order и т.п.).
-- username — текстовый PK: подходит и для текущей env-based auth (ADMIN_USERNAME),
-- и для будущей таблицы admin_users без миграции данных.
CREATE TABLE admin_user_settings (
  username   text         PRIMARY KEY,
  settings   jsonb        NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz  NOT NULL DEFAULT now()
);

COMMIT;
