-- 013_accounts.sql — единая модель учёток (email-логин) + 2FA + recovery codes.
BEGIN;

CREATE TABLE accounts (
  id            serial PRIMARY KEY,
  email         text NOT NULL UNIQUE,        -- ЛОГИН (нормализованный: lowercase + trim)
  password_hash text NOT NULL,               -- bcrypt
  role          text NOT NULL CHECK (role IN ('teacher','manager','admin')),
  teacher_id    int REFERENCES teachers(id),
  active        bool NOT NULL DEFAULT true,
  twofa_method      text CHECK (twofa_method IN ('totp','email')),
  twofa_secret      text,
  twofa_enabled     bool NOT NULL DEFAULT false,
  twofa_confirmed_at timestamptz,
  failed_login_count int NOT NULL DEFAULT 0,
  locked_until       timestamptz,
  last_login_at      timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CHECK ((role = 'teacher') = (teacher_id IS NOT NULL)),
  CHECK (twofa_method <> 'totp' OR twofa_secret IS NOT NULL)
);
CREATE UNIQUE INDEX accounts_teacher_id_uq ON accounts(teacher_id) WHERE teacher_id IS NOT NULL;

CREATE TABLE account_recovery_codes (
  id         serial PRIMARY KEY,
  account_id int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  code_hash  text NOT NULL,
  used_at    timestamptz
);
CREATE INDEX account_recovery_codes_account_idx ON account_recovery_codes(account_id);

COMMIT;
