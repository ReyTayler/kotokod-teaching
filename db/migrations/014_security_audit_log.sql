-- 014_security_audit_log.sql — журнал событий безопасности (РСБ, Приказ ФСТЭК №21).
BEGIN;

CREATE TABLE security_audit_log (
  id          bigserial PRIMARY KEY,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  account_id  int REFERENCES accounts(id),
  actor_email text,
  event       text NOT NULL,
  ip          text,
  user_agent  text,
  target_id   int,
  meta        jsonb
);
CREATE INDEX security_audit_log_occurred_idx ON security_audit_log(occurred_at DESC);
CREATE INDEX security_audit_log_account_idx  ON security_audit_log(account_id, occurred_at DESC);

COMMIT;
