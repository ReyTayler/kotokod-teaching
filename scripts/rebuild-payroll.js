require('dotenv').config();

const { calculatePayment } = require('../services/calculator');

async function run({ dryRun = false, onlyMissing = false } = {}) {
  const t0 = Date.now();
  const result = {
    entity: 'payroll-rebuild',
    lessons_seen: 0,
    inserted: 0,
    updated: 0,
    unchanged: 0,
    skipped_no_attendance: 0,
    duration_ms: 0,
    dry_run: dryRun,
    only_missing: onlyMissing,
  };

  const { pool } = require('../services/db');

  const lessonsQ = await pool.query(`
    SELECT l.id, l.teacher_id, l.lesson_duration_minutes,
           to_char(l.lesson_date, 'YYYY-MM-DD') AS lesson_date_str,
           to_char((l.submitted_at AT TIME ZONE 'Europe/Moscow'), 'YYYY-MM-DD') AS submit_msk_date,
           COUNT(la.*)::int AS total_students,
           COALESCE(SUM(CASE WHEN la.present THEN 1 ELSE 0 END), 0)::int AS present_count
    FROM lessons l
    LEFT JOIN lesson_attendance la ON la.lesson_id = l.id
    ${onlyMissing ? 'WHERE NOT EXISTS (SELECT 1 FROM payroll p WHERE p.lesson_id = l.id)' : ''}
    GROUP BY l.id
    ORDER BY l.lesson_date, l.id
  `);
  result.lessons_seen = lessonsQ.rowCount;

  for (const row of lessonsQ.rows) {
    if (row.total_students === 0) {
      result.skipped_no_attendance++;
      continue;
    }

    const isHalf = row.lesson_duration_minutes === 45;
    const payment = calculatePayment(row.total_students, row.present_count, isHalf);
    const penalty = row.submit_msk_date === row.lesson_date_str ? 0 : 40;

    if (dryRun) continue;

    const res = await pool.query(
      `INSERT INTO payroll (lesson_id, teacher_id, total_students, present_count, payment, penalty)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (lesson_id) DO UPDATE SET
         teacher_id     = EXCLUDED.teacher_id,
         total_students = EXCLUDED.total_students,
         present_count  = EXCLUDED.present_count,
         payment        = EXCLUDED.payment,
         penalty        = EXCLUDED.penalty
       WHERE payroll.teacher_id     IS DISTINCT FROM EXCLUDED.teacher_id
          OR payroll.total_students IS DISTINCT FROM EXCLUDED.total_students
          OR payroll.present_count  IS DISTINCT FROM EXCLUDED.present_count
          OR payroll.payment        IS DISTINCT FROM EXCLUDED.payment
          OR payroll.penalty        IS DISTINCT FROM EXCLUDED.penalty
       RETURNING (xmax = 0) AS inserted`,
      [row.id, row.teacher_id, row.total_students, row.present_count, payment, penalty],
    );

    if (res.rowCount === 0) result.unchanged++;
    else if (res.rows[0].inserted) result.inserted++;
    else result.updated++;
  }

  // Сводка по преподам
  const summaryQ = await pool.query(`
    SELECT t.name AS teacher,
           COUNT(p.*)::int AS lessons,
           COALESCE(SUM(p.payment), 0)::numeric AS total_payment,
           COALESCE(SUM(p.penalty), 0)::numeric AS total_penalty
    FROM payroll p
    JOIN teachers t ON t.id = p.teacher_id
    GROUP BY t.name
    ORDER BY total_payment DESC
  `);

  result.duration_ms = Date.now() - t0;
  result.summary = summaryQ.rows.map((r) => ({
    teacher: r.teacher,
    lessons: r.lessons,
    payment: Number(r.total_payment),
    penalty: Number(r.total_penalty),
    net: Number(r.total_payment) - Number(r.total_penalty),
  }));

  await pool.end();
  return result;
}

async function main() {
  const dryRun = process.argv.includes('--dry-run');
  const onlyMissing = process.argv.includes('--only-missing');
  const result = await run({ dryRun, onlyMissing });
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
}

if (require.main === module) {
  main().catch((err) => { console.error(err); process.exit(1); });
}

module.exports = { run };
