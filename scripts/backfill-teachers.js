function extractTeachers(studentRows, tokenRows) {
  const set = new Set();

  for (const row of studentRows) {
    const teacher = String(row[11] || '').trim();
    const group = String(row[12] || '').trim();
    if (!teacher || !group) continue;
    if (teacher.includes('УЧЕНИКА НЕТ') || group.includes('УЧЕНИКА НЕТ')) continue;
    set.add(teacher);
  }

  for (let i = 1; i < tokenRows.length; i++) {
    const teacher = String((tokenRows[i] || [])[5] || '').trim();
    if (teacher) set.add(teacher);
  }

  return [...set];
}

async function runBackfill({ dryRun = false } = {}) {
  const t0 = Date.now();
  const result = { entity: 'teachers', read: 0, inserted: 0, updated: 0, skipped: 0, duration_ms: 0, dry_run: dryRun };

  const sheets = require('../services/sheets');
  const [studentRows, tokenRows] = await Promise.all([
    sheets.readStudentsRange('Список всех детей', 'A3:S'),
    sheets.readJournalRange('Токены', 'A:F'),
  ]);

  const teachers = extractTeachers(studentRows, tokenRows);
  result.read = teachers.length;
  process.stderr.write(`teachers: extracted ${teachers.length} unique names\n`);

  if (dryRun) {
    teachers.forEach((n) => process.stderr.write(`[dry-run] ${n}\n`));
    result.duration_ms = Date.now() - t0;
    return result;
  }

  const { pool } = require('../services/db');
  for (const name of teachers) {
    const res = await pool.query(
      `INSERT INTO teachers (name) VALUES ($1)
       ON CONFLICT (name) DO NOTHING
       RETURNING (xmax = 0) AS inserted`,
      [name],
    );
    if (res.rowCount === 0) result.skipped++;
    else result.inserted++;
  }

  result.duration_ms = Date.now() - t0;
  return result;
}

async function main() {
  require('dotenv').config();
  const dryRun = process.argv.includes('--dry-run');
  const result = await runBackfill({ dryRun });
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  if (!dryRun) {
    const { pool } = require('../services/db');
    await pool.end();
  }
}

if (require.main === module) {
  main().catch((err) => { console.error(err); process.exit(1); });
}

module.exports = { extractTeachers, runBackfill };
