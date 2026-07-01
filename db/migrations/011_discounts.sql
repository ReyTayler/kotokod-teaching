-- 011_discounts.sql
-- Скидки как справочник. Применяются в форме внесения оплаты как UI-helper
-- (рассчитывают финальный unit_price). Не FK от payments — скидки могут
-- удаляться, оплаты остаются с расчётной ценой.

BEGIN;

CREATE TABLE discounts (
  id         serial PRIMARY KEY,
  name       text NOT NULL,
  amount     numeric(5,4) NOT NULL CHECK (amount >= 0 AND amount <= 1),
  active     bool NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX discounts_active_idx ON discounts(active);

COMMIT;
