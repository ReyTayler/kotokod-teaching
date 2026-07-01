function parseLessonDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  const s = String(value).trim();
  if (!s) return null;
  const m = s.match(/^(\d{1,2})[.\/-](\d{1,2})[.\/-](\d{2,4})/);
  if (m) {
    const dd = String(m[1]).padStart(2, '0');
    const mm = String(m[2]).padStart(2, '0');
    const yyyy = m[3].length === 2 ? '20' + m[3] : m[3];
    return `${yyyy}-${mm}-${dd}`;
  }
  return null;
}

function lessonTypeFromLabel(label) {
  const s = String(label || '').trim();
  if (s === 'Замена')  return 'substitution';
  if (s === 'Перенос') return 'reschedule';
  return 'regular';
}

function extractLessons(rows) {
  const lessonsMap = new Map();
  const attendance = [];

  for (const r of rows) {
    if (!r) continue;
    const date = parseLessonDate(r[0]);
    const teacher = String(r[1] || '').trim();
    const group = String(r[2] || '').trim();
    const lessonNum = parseFloat(r[3]);
    const student = String(r[4] || '').trim();
    const status = String(r[5] || '').trim();
    const token = String(r[7] || '').trim();
    const record = String(r[8] || '').trim();
    const typeLabel = String(r[9] || '').trim();
    const original = String(r[10] || '').trim();

    if (!date || !teacher || !group || !Number.isFinite(lessonNum) || !student) continue;
    if (!token) continue;

    const key = `${date}|${group}|${lessonNum}|${token}`;
    if (!lessonsMap.has(key)) {
      lessonsMap.set(key, {
        lesson_date: date,
        teacher_name: teacher,
        group_name: group,
        lesson_number: lessonNum,
        submitted_by_token: token,
        record_url: record || null,
        lesson_type: lessonTypeFromLabel(typeLabel),
        original_teacher_name: original || null,
      });
    }

    attendance.push({
      lesson_key: key,
      student_name: student,
      present: status === 'Был',
    });
  }

  return { lessons: [...lessonsMap.values()], attendance };
}

async function runBackfill({ dryRun = false } = {}) {
  const t0 = Date.now();
  const result = {
    entity: 'lessons+attendance',
    lessons_read: 0, lessons_inserted: 0, lessons_skipped: 0,
    attendance_read: 0, attendance_inserted: 0, attendance_skipped: 0,
    duration_ms: 0, dry_run: dryRun,
  };

  const sheets = require('../services/sheets');
  const [groupRows, indivRows] = await Promise.all([
    sheets.readJournalRange('Журнал группы', 'A2:K'),
    sheets.readJournalRange('Журнал индивы', 'A2:K'),
  ]);
  const all = [...groupRows, ...indivRows];
  const { lessons, attendance } = extractLessons(all);
  result.lessons_read = lessons.length;
  result.attendance_read = attendance.length;
  process.stderr.write(`lessons: ${lessons.length}, attendance: ${attendance.length} (from ${all.length} raw rows)\n`);

  if (dryRun) {
    lessons.slice(0, 3).forEach((l) => process.stderr.write(`[dry-run] lesson ${JSON.stringify(l)}\n`));
    result.duration_ms = Date.now() - t0;
    return result;
  }

  const { pool } = require('../services/db');
  const lessonIdByKey = new Map();

  for (const l of lessons) {
    const res = await pool.query(
      `WITH g AS (SELECT id, lesson_duration_minutes FROM groups WHERE name = $3),
            te AS (SELECT id FROM teachers WHERE name = $2),
            ot AS (SELECT id FROM teachers WHERE name = NULLIF($8, ''))
       INSERT INTO lessons
         (lesson_date, teacher_id, group_id, lesson_number,
          lesson_duration_minutes, lesson_type, record_url,
          submitted_by_token, original_teacher_id, submitted_at)
       SELECT $1, te.id, g.id, $4, g.lesson_duration_minutes, $5,
              NULLIF($6, ''), $7,
              (SELECT id FROM ot),
              ($1::date)::timestamptz
       FROM g, te
       ON CONFLICT (lesson_date, group_id, lesson_number, submitted_by_token) DO NOTHING
       RETURNING id`,
      [l.lesson_date, l.teacher_name, l.group_name, l.lesson_number,
       l.lesson_type, l.record_url || '', l.submitted_by_token, l.original_teacher_name || ''],
    );

    let lessonId;
    if (res.rowCount === 0) {
      // Already exists or group/teacher missing — fetch existing id
      const lookup = await pool.query(
        `SELECT l.id FROM lessons l
         JOIN groups g ON g.id = l.group_id
         WHERE l.lesson_date = $1 AND g.name = $2 AND l.lesson_number = $3 AND l.submitted_by_token = $4`,
        [l.lesson_date, l.group_name, l.lesson_number, l.submitted_by_token],
      );
      if (lookup.rowCount === 0) {
        process.stderr.write(`[warn] lesson ${l.lesson_date}|${l.group_name}|${l.lesson_number}|${l.submitted_by_token}: group/teacher missing, skipped\n`);
        result.lessons_skipped++;
        continue;
      }
      lessonId = lookup.rows[0].id;
      result.lessons_skipped++;
    } else {
      lessonId = res.rows[0].id;
      result.lessons_inserted++;
    }

    const key = `${l.lesson_date}|${l.group_name}|${l.lesson_number}|${l.submitted_by_token}`;
    lessonIdByKey.set(key, lessonId);
  }

  for (const a of attendance) {
    const lessonId = lessonIdByKey.get(a.lesson_key);
    if (!lessonId) { result.attendance_skipped++; continue; }
    const res = await pool.query(
      `WITH s AS (SELECT id FROM students WHERE full_name = $2)
       INSERT INTO lesson_attendance (lesson_id, student_id, present)
       SELECT $1, s.id, $3 FROM s
       ON CONFLICT (lesson_id, student_id) DO NOTHING`,
      [lessonId, a.student_name, a.present],
    );
    if (res.rowCount > 0) result.attendance_inserted++;
    else result.attendance_skipped++;
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

module.exports = { extractLessons, parseLessonDate, runBackfill };
