const { parseLessonDate } = require('./backfill-lessons');

function extractPayroll(rows) {
  const out = [];
  for (const r of rows) {
    if (!r) continue;
    const date = parseLessonDate(r[0]);
    const group = String(r[2] || '').trim();
    const lessonNum = parseFloat(r[3]);
    const total = parseInt(r[4], 10);
    const present = parseInt(r[5], 10);
    const payment = parseFloat(r[6]);
    const token = String(r[8] || '').trim();
    const penaltyRaw = String(r[9] || '').trim();

    if (!date || !group || !Number.isFinite(lessonNum) || !token) continue;
    if (!Number.isFinite(total) || !Number.isFinite(present) || !Number.isFinite(payment)) continue;

    out.push({
      lesson_date: date,
      group_name: group,
      lesson_number: lessonNum,
      submitted_by_token: token,
      total_students: total,
      present_count: present,
      payment,
      penalty: penaltyRaw ? parseFloat(penaltyRaw) || 0 : 0,
    });
  }
  return out;
}

async function runBackfill({ dryRun = false } = {}) {
  const t0 = Date.now();
  const result = { entity: 'payroll', read: 0, inserted: 0, updated: 0, skipped: 0, no_lesson: 0, duration_ms: 0, dry_run: dryRun };

  const sheets = require('../services/sheets');
  const rows = await sheets.readJournalRange('Зарплата', 'A2:L');
  const payroll = extractPayroll(rows);
  result.read = payroll.length;
  process.stderr.write(`payroll: ${payroll.length} entries\n`);

  if (dryRun) {
    payroll.slice(0, 5).forEach((p) => process.stderr.write(`[dry-run] ${JSON.stringify(p)}\n`));
    result.duration_ms = Date.now() - t0;
    return result;
  }

  const { pool } = require('../services/db');
  for (const p of payroll) {
    const res = await pool.query(
      `WITH l AS (
         SELECT l.id, l.teacher_id FROM lessons l
         JOIN groups g ON g.id = l.group_id
         WHERE l.lesson_date = $1 AND g.name = $2
           AND l.lesson_number = $3 AND l.submitted_by_token = $4
       )
       INSERT INTO payroll (lesson_id, teacher_id, total_students, present_count, payment, penalty)
       SELECT l.id, l.teacher_id, $5, $6, $7, $8 FROM l
       ON CONFLICT (lesson_id) DO UPDATE SET
         total_students = EXCLUDED.total_students,
         present_count  = EXCLUDED.present_count,
         payment        = EXCLUDED.payment,
         penalty        = EXCLUDED.penalty
       WHERE payroll.total_students IS DISTINCT FROM EXCLUDED.total_students
          OR payroll.present_count  IS DISTINCT FROM EXCLUDED.present_count
          OR payroll.payment        IS DISTINCT FROM EXCLUDED.payment
          OR payroll.penalty        IS DISTINCT FROM EXCLUDED.penalty
       RETURNING (xmax = 0) AS inserted`,
      [p.lesson_date, p.group_name, p.lesson_number, p.submitted_by_token,
       p.total_students, p.present_count, p.payment, p.penalty],
    );
    if (res.rowCount === 0) {
      const exists = await pool.query(
        `SELECT 1 FROM lessons l JOIN groups g ON g.id = l.group_id
         WHERE l.lesson_date = $1 AND g.name = $2 AND l.lesson_number = $3 AND l.submitted_by_token = $4`,
        [p.lesson_date, p.group_name, p.lesson_number, p.submitted_by_token],
      );
      if (exists.rowCount === 0) result.no_lesson++;
      else result.skipped++;
    } else if (res.rows[0].inserted) result.inserted++;
    else result.updated++;
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

module.exports = { extractPayroll, runBackfill };
