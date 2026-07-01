const { pool } = require('../db');
const { paginate, F } = require('../pagination');

// ===== Accounts (RBAC / унифицированный вход) =====
//
// Доменный репозиторий учёток. CHECK-инварианты схемы (см. 013_accounts.sql):
//   - (role = 'teacher') ⟺ (teacher_id IS NOT NULL)
//   - twofa_method ∈ (totp, email)
//   - twofa_method = 'totp' ⟹ twofa_secret IS NOT NULL
// Соблюдать на уровне валидации вызывающего кода — здесь только запросы.

const ACCOUNTS_PAGINATION = {
  sortable: { email: 'a.email', role: 'a.role', active: 'a.active', created_at: 'a.created_at' },
  defaultSortBy: 'email',
  defaultSortDir: 'asc',
  from: 'FROM accounts a LEFT JOIN teachers t ON t.id = a.teacher_id',
  selectColumns: 'a.id, a.email, a.role, a.teacher_id, a.active, a.twofa_enabled, a.twofa_method, a.last_login_at, t.name AS teacher_name',
  secondarySort: 'a.id DESC',
  filters: {
    email: F.like('a.email'),
    role: F.exact('a.role'),
    active: F.bool('a.active'),
    teacher_name: F.likeNullable('t.name'), // фильтр колонки «Преподаватель» в AccountsPage
  },
};

async function listAccounts(request) { return paginate(ACCOUNTS_PAGINATION, request); }

async function findByEmail(email) {
  const { rows } = await pool.query('SELECT * FROM accounts WHERE email = $1', [email]);
  return rows[0] || null;
}

async function getById(id) {
  const { rows } = await pool.query('SELECT * FROM accounts WHERE id = $1', [id]);
  return rows[0] || null;
}

async function getByIdWithTeacher(id) {
  const { rows } = await pool.query(
    `SELECT a.*, t.name AS teacher_name FROM accounts a
       LEFT JOIN teachers t ON t.id = a.teacher_id WHERE a.id = $1`, [id]);
  return rows[0] || null;
}

async function createAccount({ email, password_hash, role, teacher_id }) {
  const { rows } = await pool.query(
    `INSERT INTO accounts (email, password_hash, role, teacher_id)
     VALUES ($1,$2,$3,$4) RETURNING *`,
    [email, password_hash, role, teacher_id ?? null],
  );
  return rows[0];
}

async function updateAccount(id, { email, role, active }) {
  const { rows } = await pool.query(
    `UPDATE accounts SET
       email  = COALESCE($2, email),
       role   = COALESCE($3, role),
       active = COALESCE($4, active)
     WHERE id = $1 RETURNING *`,
    [id, email ?? null, role ?? null, active ?? null],
  );
  return rows[0] || null;
}

async function setPassword(id, password_hash) {
  const { rowCount } = await pool.query('UPDATE accounts SET password_hash = $2 WHERE id = $1', [id, password_hash]);
  return rowCount > 0;
}

async function softDelete(id) {
  const { rowCount } = await pool.query('UPDATE accounts SET active = false WHERE id = $1', [id]);
  return rowCount > 0;
}

async function setTwofa(id, { method, secret, enabled, confirmed }) {
  const { rows } = await pool.query(
    `UPDATE accounts SET
       twofa_method = $2, twofa_secret = $3, twofa_enabled = $4,
       twofa_confirmed_at = CASE WHEN $5 THEN now() ELSE twofa_confirmed_at END
     WHERE id = $1 RETURNING *`,
    [id, method ?? null, secret ?? null, !!enabled, !!confirmed],
  );
  return rows[0] || null;
}

async function resetTwofa(id) {
  await pool.query('DELETE FROM account_recovery_codes WHERE account_id = $1', [id]);
  const { rows } = await pool.query(
    `UPDATE accounts SET twofa_method=NULL, twofa_secret=NULL, twofa_enabled=false, twofa_confirmed_at=NULL
     WHERE id=$1 RETURNING *`, [id]);
  return rows[0] || null;
}

async function registerLoginSuccess(id) {
  await pool.query('UPDATE accounts SET failed_login_count=0, locked_until=NULL, last_login_at=now() WHERE id=$1', [id]);
}

async function registerLoginFailure(id, maxFails = 5, lockMs = 15 * 60 * 1000) {
  const { rows } = await pool.query(
    `UPDATE accounts SET
       failed_login_count = failed_login_count + 1,
       locked_until = CASE WHEN failed_login_count + 1 >= $2 THEN now() + ($3 || ' milliseconds')::interval ELSE locked_until END
     WHERE id=$1 RETURNING failed_login_count, locked_until`,
    [id, maxFails, String(lockMs)],
  );
  return rows[0] || null;
}

async function replaceRecoveryCodes(accountId, hashes) {
  await pool.query('DELETE FROM account_recovery_codes WHERE account_id=$1', [accountId]);
  for (const h of hashes) {
    await pool.query('INSERT INTO account_recovery_codes (account_id, code_hash) VALUES ($1,$2)', [accountId, h]);
  }
}

async function listRecoveryCodes(accountId) {
  const { rows } = await pool.query('SELECT * FROM account_recovery_codes WHERE account_id=$1 ORDER BY id', [accountId]);
  return rows;
}

async function markRecoveryUsed(id) {
  await pool.query('UPDATE account_recovery_codes SET used_at=now() WHERE id=$1', [id]);
}

module.exports = {
  listAccounts, findByEmail, getById, getByIdWithTeacher, createAccount, updateAccount,
  setPassword, softDelete, setTwofa, resetTwofa, registerLoginSuccess, registerLoginFailure,
  replaceRecoveryCodes, listRecoveryCodes, markRecoveryUsed,
};
