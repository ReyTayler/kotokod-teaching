require('dotenv').config();

// Пересчитывает group_memberships.lessons_done из реальных отметок в
// lesson_attendance. Шаг — 0.5 для 45-минутных уроков, иначе 1.
// Запуск: npm run counters:rebuild [-- --dry-run]

async function run({ dryRun = false } = {}) {
  const t0 = Date.now();
  const result = {
    entity: 'counters-rebuild',
    memberships_total: 0,
    updated: 0,
    unchanged: 0,
    duration_ms: 0,
    dry_run: dryRun,
    drifts: [],
  };

  const { pool } = require('../services/db');

  // Считаем calculated_done = SUM(step) по присутствовавшим урокам каждой пары
  // (group_id, student_id). LEFT JOIN на lesson_attendance чтобы memberships
  // без уроков тоже учитывались (calculated = 0).
  const q = await pool.query(`
    SELECT gm.id,
           gm.group_id,
           gm.student_id,
           gm.lessons_done AS stored,
           COALESCE(SUM(
             CASE WHEN la.present THEN
               CASE WHEN l.lesson_duration_minutes = 45 THEN 0.5 ELSE 1 END
             ELSE 0 END
           ), 0)::numeric(6,1) AS calculated,
           s.full_name AS student_name,
           g.name AS group_name
      FROM group_memberships gm
      JOIN students s ON s.id = gm.student_id
      JOIN groups   g ON g.id = gm.group_id
      LEFT JOIN lessons l
             ON l.group_id = gm.group_id
      LEFT JOIN lesson_attendance la
             ON la.lesson_id = l.id AND la.student_id = gm.student_id
     GROUP BY gm.id, gm.group_id, gm.student_id, gm.lessons_done, s.full_name, g.name
     ORDER BY gm.id
  `);
  result.memberships_total = q.rowCount;

  for (const row of q.rows) {
    const stored = Number(row.stored);
    const calculated = Number(row.calculated);
    if (stored === calculated) { result.unchanged++; continue; }

    result.drifts.push({
      membership_id: row.id,
      student: row.student_name,
      group: row.group_name,
      stored,
      calculated,
      delta: Number((calculated - stored).toFixed(1)),
    });

    if (!dryRun) {
      await pool.query(
        `UPDATE group_memberships SET lessons_done = $1 WHERE id = $2`,
        [calculated, row.id],
      );
      result.updated++;
    }
  }

  // Сводка по top-расхождениям, не больше 20 в выводе чтобы не шумно
  result.drifts.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
  const top = result.drifts.slice(0, 20);
  result.top_drifts = top;
  result.drifts = undefined;

  result.duration_ms = Date.now() - t0;
  await pool.end();
  return result;
}

async function main() {
  const dryRun = process.argv.includes('--dry-run');
  const result = await run({ dryRun });
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
}

if (require.main === module) {
  main().catch((err) => { console.error(err); process.exit(1); });
}

module.exports = { run };
