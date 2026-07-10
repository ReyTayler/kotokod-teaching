const MONTHS = ['январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь'];

function parseStartDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  const s = String(value).trim();
  if (!s) return null;
  const m = s.match(/^(\d{1,2})[.\/-](\d{1,2})[.\/-](\d{2,4})$/);
  if (m) {
    const dd = String(m[1]).padStart(2, '0');
    const mm = String(m[2]).padStart(2, '0');
    const yyyy = m[3].length === 2 ? '20' + m[3] : m[3];
    return `${yyyy}-${mm}-${dd}`;
  }
  return null;
}

function mapEnrollmentFromSheets(raw, hasMembership) {
  const s = String(raw || '').trim().toLowerCase();
  const fallback = hasMembership
    ? { enrollment_status: 'enrolled',     frozen_until_month: null }
    : { enrollment_status: 'not_enrolled', frozen_until_month: null };

  if (!s)          return fallback;
  if (s === 'да')  return { enrollment_status: 'enrolled',     frozen_until_month: null };
  if (s === 'нет') return { enrollment_status: 'not_enrolled', frozen_until_month: null };
  if (s.includes('отказ')) return { enrollment_status: 'declined', frozen_until_month: null };

  // «нет январь», «нет февраль», ... — frozen с месяцем
  const rest = s.replace(/^нет\s*/, '').trim();
  const monthIdx = MONTHS.findIndex((m) => rest.startsWith(m));
  if (monthIdx >= 0) {
    return { enrollment_status: 'frozen', frozen_until_month: monthIdx + 1 };
  }
  return fallback;
}

function extractStudentsAndMemberships(rows) {
  const studentsMap = new Map();
  const memberships = [];

  for (const row of rows) {
    const name        = String(row[0]  || '').trim();
    const ageRaw      = String(row[2]  || '').trim();
    const platform    = String(row[4]  || '').trim();
    const parent      = String(row[5]  || '').trim();
    const phone       = String(row[6]  || '').trim();
    const birthRaw    = row[7];
    const firstPurRaw = row[8];
    const pm          = String(row[9]  || '').trim();
    const teacher     = String(row[11] || '').trim();
    const group       = String(row[12] || '').trim();
    const startRaw    = row[13];
    const sheetRow    = parseInt(row[14], 10) || null;
    const done        = Math.round((parseFloat(row[16]) || 0) * 10) / 10;
    const enrollRaw   = row[19];

    if (!name) continue;
    if (name.includes('УЧЕНИКА НЕТ')) continue;

    const teacherOk = teacher && !teacher.includes('УЧЕНИКА НЕТ');
    const groupOk   = group   && !group.includes('УЧЕНИКА НЕТ');
    const hasMembership = teacherOk && groupOk;

    if (!studentsMap.has(name)) {
      const age = ageRaw ? parseInt(ageRaw, 10) || null : null;
      const enroll = mapEnrollmentFromSheets(enrollRaw, hasMembership);
      studentsMap.set(name, {
        full_name: name,
        age,
        pm: pm || null,
        birth_date: parseStartDate(birthRaw),
        parent1_phone: phone || null,
        platform_id: platform || null,
        parent1_name: parent || null,
        first_purchase_date: parseStartDate(firstPurRaw),
        enrollment_status: enroll.enrollment_status,
        frozen_until_month: enroll.frozen_until_month,
      });
    }

    if (hasMembership) {
      memberships.push({
        student_name: name,
        group_name: group,
        lessons_done: done,
        start_date: parseStartDate(startRaw),
        sheet_row: sheetRow,
      });
    }
  }

  return { students: [...studentsMap.values()], memberships };
}

async function runBackfill({ dryRun = false } = {}) {
  const t0 = Date.now();
  const result = {
    entity: 'students+memberships',
    students_read: 0, students_inserted: 0, students_updated: 0, students_skipped: 0,
    memberships_read: 0, memberships_inserted: 0, memberships_updated: 0, memberships_skipped: 0,
    duration_ms: 0, dry_run: dryRun,
  };

  const sheets = require('../services/sheets');
  const rows = await sheets.readStudentsRange('Список всех детей', 'A3:T');
  const { students, memberships } = extractStudentsAndMemberships(rows);
  result.students_read = students.length;
  result.memberships_read = memberships.length;
  process.stderr.write(`students: ${students.length}, memberships: ${memberships.length}\n`);

  if (dryRun) {
    students.slice(0, 5).forEach((s) => process.stderr.write(`[dry-run] student ${JSON.stringify(s)}\n`));
    memberships.slice(0, 5).forEach((m) => process.stderr.write(`[dry-run] membership ${JSON.stringify(m)}\n`));
    result.duration_ms = Date.now() - t0;
    return result;
  }

  const { pool } = require('../services/db');
  for (const s of students) {
    const res = await pool.query(
      `INSERT INTO students
         (full_name, age, pm, birth_date, parent1_phone, platform_id,
          parent1_name, first_purchase_date, enrollment_status, frozen_until_month)
       VALUES ($1, $2, $3, $4, NULLIF($5,''), NULLIF($6,''), NULLIF($7,''), $8, $9, $10)
       ON CONFLICT (full_name) DO UPDATE SET
         age                 = EXCLUDED.age,
         pm                  = EXCLUDED.pm,
         birth_date          = EXCLUDED.birth_date,
         parent1_phone       = EXCLUDED.parent1_phone,
         platform_id         = EXCLUDED.platform_id,
         parent1_name        = EXCLUDED.parent1_name,
         first_purchase_date = EXCLUDED.first_purchase_date,
         enrollment_status   = EXCLUDED.enrollment_status,
         frozen_until_month  = EXCLUDED.frozen_until_month
       WHERE students.age IS DISTINCT FROM EXCLUDED.age
          OR students.pm  IS DISTINCT FROM EXCLUDED.pm
          OR students.birth_date          IS DISTINCT FROM EXCLUDED.birth_date
          OR students.parent1_phone       IS DISTINCT FROM EXCLUDED.parent1_phone
          OR students.platform_id         IS DISTINCT FROM EXCLUDED.platform_id
          OR students.parent1_name        IS DISTINCT FROM EXCLUDED.parent1_name
          OR students.first_purchase_date IS DISTINCT FROM EXCLUDED.first_purchase_date
          OR students.enrollment_status   IS DISTINCT FROM EXCLUDED.enrollment_status
          OR students.frozen_until_month  IS DISTINCT FROM EXCLUDED.frozen_until_month
       RETURNING (xmax = 0) AS inserted`,
      [s.full_name, s.age, s.pm, s.birth_date, s.parent1_phone,
       s.platform_id, s.parent1_name, s.first_purchase_date, s.enrollment_status, s.frozen_until_month],
    );
    if (res.rowCount === 0) result.students_skipped++;
    else if (res.rows[0].inserted) result.students_inserted++;
    else result.students_updated++;
  }

  for (const m of memberships) {
    const res = await pool.query(
      `WITH g AS (SELECT id FROM groups   WHERE name = $1),
            s AS (SELECT id FROM students WHERE full_name = $2)
       INSERT INTO group_memberships
         (group_id, student_id, lessons_done, start_date, sheet_row, active)
       SELECT g.id, s.id, $3, $4, $5, true FROM g, s
       ON CONFLICT (group_id, student_id) DO UPDATE SET
         lessons_done = EXCLUDED.lessons_done,
         start_date   = EXCLUDED.start_date,
         sheet_row    = EXCLUDED.sheet_row
       WHERE group_memberships.lessons_done IS DISTINCT FROM EXCLUDED.lessons_done
          OR group_memberships.start_date   IS DISTINCT FROM EXCLUDED.start_date
          OR group_memberships.sheet_row    IS DISTINCT FROM EXCLUDED.sheet_row
       RETURNING (xmax = 0) AS inserted`,
      [m.group_name, m.student_name, m.lessons_done, m.start_date, m.sheet_row],
    );
    if (res.rowCount === 0) result.memberships_skipped++;
    else if (res.rows[0].inserted) result.memberships_inserted++;
    else result.memberships_updated++;
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

module.exports = {
  extractStudentsAndMemberships,
  parseStartDate,
  mapEnrollmentFromSheets,
  runBackfill,
};
