// scripts/create-account.js <email> <role> [teacher_id]
// Создаёт учётку, печатает сгенерированный токен-пароль (один раз).
require('dotenv').config();
const auth = require('../services/auth');
const accountsRepo = require('../services/repo/accounts');
const { pool } = require('../services/db');

async function main() {
  const [, , rawEmail, role, teacherId] = process.argv;
  const email = auth.normalizeEmail(rawEmail);
  if (!email || !['teacher', 'manager', 'admin'].includes(role)) {
    console.error('usage: node scripts/create-account.js <email> <teacher|manager|admin> [teacher_id]');
    process.exit(1);
  }
  if ((role === 'teacher') !== (teacherId != null)) {
    console.error('teacher требует teacher_id; manager/admin — без него');
    process.exit(1);
  }
  if (await accountsRepo.findByEmail(email)) { console.error('email уже есть'); process.exit(1); }

  const password = auth.generateTokenPassword();
  const acc = await accountsRepo.createAccount({
    email, password_hash: await auth.hashPassword(password), role,
    teacher_id: teacherId ? Number(teacherId) : null,
  });
  console.log(JSON.stringify({ id: acc.id, email: acc.email, role: acc.role, password }, null, 2));
  console.log('\n⚠️  Пароль показан один раз — сохраните его.');
  await pool.end();
}
main().catch((e) => { console.error(e); process.exit(1); });
