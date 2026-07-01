-- 009_payments_legacy.sql
-- Разрешаем NULL в direction_id + subscriptions_count для исторических оплат,
-- где направление не известно (помечено «Архив» в источнике).
-- Инвариант: либо оба поля заданы (новые оплаты через API), либо оба NULL (легаси).
-- Новый CHECK total_amount активен только когда subscriptions_count NOT NULL.
-- paid_at остаётся NOT NULL — все легаси-строки с датой.

BEGIN;

ALTER TABLE payments ALTER COLUMN direction_id        DROP NOT NULL;
ALTER TABLE payments ALTER COLUMN subscriptions_count DROP NOT NULL;

ALTER TABLE payments ADD CONSTRAINT payments_direction_count_match CHECK (
  (direction_id IS NULL AND subscriptions_count IS NULL) OR
  (direction_id IS NOT NULL AND subscriptions_count IS NOT NULL AND subscriptions_count > 0)
);

ALTER TABLE payments DROP CONSTRAINT payments_check;
ALTER TABLE payments ADD CONSTRAINT payments_total_match CHECK (
  subscriptions_count IS NULL OR total_amount = unit_price * subscriptions_count
);

COMMIT;
