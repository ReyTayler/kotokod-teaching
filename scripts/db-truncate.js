// Удаляет данные всех таблиц кроме directions и schema_migrations

require('dotenv').config();

const TABLES = [
  'payments',          // ← новый, перед payroll
  'payroll',
  'lesson_attendance',
  'lessons',
  'group_memberships',
  'group_schedule_slots',
  'groups',
  'students',
  'teachers',
  'sync_failures',
  'discounts',
];

const KEEP = ['directions', 'schema_migrations'];

async function run({ keepDirections = true, force = false } = {}) {
  const targets = keepDirections ? TABLES : [...TABLES, 'directions'];

  if (!force) {
    process.stderr.write(
      `About to TRUNCATE: ${targets.join(', ')}\n` +
      `Keeping: ${keepDirections ? KEEP.join(', ') : 'schema_migrations'}\n` +
      `Pass --yes to proceed.\n`,
    );
    return { aborted: true };
  }

  const { pool } = require('../services/db');
  const sql = `TRUNCATE ${targets.join(', ')} RESTART IDENTITY CASCADE`;
  process.stderr.write(`${sql}\n`);
  await pool.query(sql);

  const counts = {};
  for (const t of [...targets, ...(keepDirections ? ['directions'] : [])]) {
    const r = await pool.query(`SELECT COUNT(*)::int AS n FROM ${t}`);
    counts[t] = r.rows[0].n;
  }
  await pool.end();
  return { truncated: targets, kept: keepDirections ? KEEP : ['schema_migrations'], counts };
}

async function main() {
  const force = process.argv.includes('--yes');
  const includeDirections = process.argv.includes('--include-directions');
  const result = await run({ keepDirections: !includeDirections, force });
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
}

if (require.main === module) {
  main().catch((err) => { console.error(err); process.exit(1); });
}

module.exports = { run, TABLES, KEEP };
