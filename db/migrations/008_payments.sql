-- 008_payments.sql
-- Финансовые записи оплат. Immutable по содержимому (никакого UPDATE из бэка).
-- total_amount пересчитывается на сервере и закрепляется CHECK'ом.
-- ON DELETE RESTRICT защищает от хард-удаления student/direction с историей оплат.

BEGIN;

CREATE TABLE payments (
  id                   serial PRIMARY KEY,
  student_id           int NOT NULL REFERENCES students(id)   ON DELETE RESTRICT,
  direction_id         int NOT NULL REFERENCES directions(id) ON DELETE RESTRICT,
  subscriptions_count  int NOT NULL CHECK (subscriptions_count > 0),
  unit_price           numeric(10,2) NOT NULL CHECK (unit_price >= 0),
  total_amount         numeric(10,2) NOT NULL,
  paid_at              date NOT NULL,
  note                 text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  created_by           text,
  CHECK (total_amount = unit_price * subscriptions_count)
);

CREATE INDEX payments_student_idx   ON payments(student_id);
CREATE INDEX payments_direction_idx ON payments(direction_id);
CREATE INDEX payments_paid_at_idx   ON payments(paid_at);

COMMIT;
