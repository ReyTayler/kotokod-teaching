-- 007_directions_subscription_price.sql
-- Цена одного абонемента (4 урока) на направление.
-- NULL = «не настроено» — продажу не блокируем, но форма открывается
-- с раскрытым полем «своя сумма».

BEGIN;

ALTER TABLE directions
  ADD COLUMN subscription_price numeric(10,2)
  CHECK (subscription_price IS NULL OR subscription_price >= 0);

COMMIT;
