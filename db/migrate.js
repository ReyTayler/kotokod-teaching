// db/migrate.js
//
// ⚠️ DEPRECATED для провижининга схемы. Владелец схемы БД теперь — Django
// (journal_django/, managed=True модели + начальные миграции, manage.py migrate).
// Этот скрипт и db/migrations/*.sql оставлены как историческая справка и для
// обслуживания существующих SQL-инсталляций. Новые изменения схемы вести
// Django-миграциями. См. docs/superpowers/specs/2026-06-11-django-schema-ownership-design.md
require('dotenv').config();
const fs = require('fs');
const path = require('path');
const { Pool } = require('pg');

const MIGRATIONS_DIR = path.join(__dirname, 'migrations');

async function main() {
  const pool = new Pool({ connectionString: process.env.DATABASE_URL });
  const client = await pool.connect();

  try {
    await client.query(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        version    int PRIMARY KEY,
        applied_at timestamptz NOT NULL DEFAULT now()
      )
    `);

    const { rows: applied } = await client.query(
      'SELECT version FROM schema_migrations'
    );
    const appliedVersions = new Set(applied.map(r => r.version));

    const files = fs.readdirSync(MIGRATIONS_DIR)
      .filter(f => /^\d+_.*\.sql$/.test(f))
      .sort();

    let appliedCount = 0;

    for (const file of files) {
      const version = parseInt(file.match(/^(\d+)_/)[1], 10);
      if (appliedVersions.has(version)) {
        console.log(`-  ${file} (already applied)`);
        continue;
      }

      const sql = fs.readFileSync(path.join(MIGRATIONS_DIR, file), 'utf8');
      console.log(`>  ${file}`);

      try {
        await client.query(sql);
        await client.query(
          'INSERT INTO schema_migrations (version) VALUES ($1)',
          [version]
        );
        console.log(`OK ${file}`);
        appliedCount++;
      } catch (err) {
        console.error(`FAIL ${file}: ${err.message}`);
        throw err;
      }
    }

    console.log(`\nDone. Applied: ${appliedCount}. Total migrations: ${files.length}.`);
  } finally {
    client.release();
    await pool.end();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
