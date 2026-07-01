const { parseTimeSlots, parseLessonDuration } = require('./lib/parse-time');
const { parseStartDate } = require('./backfill-students');

function extractGroups(studentRows) {
  const seen = new Map();
  for (const row of studentRows) {
    const teacher = String(row[11] || '').trim();
    const group = String(row[12] || '').trim();
    const vk = String(row[15] || '').trim();
    const direction = String(row[18] || '').trim();
    const startDate = parseStartDate(row[13]);

    if (!teacher || !group || !direction) continue;
    if ([teacher, group, direction].some((v) => v.includes('УЧЕНИКА НЕТ'))) continue;

    if (!seen.has(group)) {
      const isIndividual = direction.includes('ИНДИВ');
      const slots = parseTimeSlots(group);
      seen.set(group, {
        name: group,
        direction_name: direction,
        teacher_name: teacher,
        is_individual: isIndividual,
        lesson_duration_minutes: parseLessonDuration(group),
        lessons_per_week: slots.length || 1,
        vk_chat: vk,
        group_start_date: startDate,
        slots,
      });
    } else {
      // если у первой строки группы не было даты, подхватим из последующих
      const g = seen.get(group);
      if (!g.group_start_date && startDate) g.group_start_date = startDate;
    }
  }
  return [...seen.values()];
}

async function runBackfill({ dryRun = false } = {}) {
  const t0 = Date.now();
  const result = { entity: 'groups', read: 0, inserted: 0, updated: 0, skipped: 0, slots_replaced: 0, duration_ms: 0, dry_run: dryRun };

  const sheets = require('../services/sheets');
  const rows = await sheets.readStudentsRange('Список всех детей', 'A3:T');
  const groups = extractGroups(rows);
  result.read = groups.length;
  process.stderr.write(`groups: extracted ${groups.length} unique groups\n`);

  if (dryRun) {
    groups.slice(0, 20).forEach((g) =>
      process.stderr.write(`[dry-run] ${g.name} | dir=${g.direction_name} | teacher=${g.teacher_name} | dur=${g.lesson_duration_minutes} | slots=${JSON.stringify(g.slots)}\n`),
    );
    if (groups.length > 20) process.stderr.write(`[dry-run] ... and ${groups.length - 20} more\n`);
    result.duration_ms = Date.now() - t0;
    return result;
  }

  const { pool, tx } = require('../services/db');
  for (const g of groups) {
    await tx(async (client) => {
      const upsert = await client.query(
        `WITH d AS (SELECT id FROM directions WHERE name = $2),
              te AS (SELECT id FROM teachers WHERE name = $3)
         INSERT INTO groups (name, direction_id, teacher_id, is_individual,
                             lesson_duration_minutes, lessons_per_week, vk_chat, group_start_date)
         SELECT $1, d.id, te.id, $4, $5, $6, NULLIF($7, ''), $8 FROM d, te
         ON CONFLICT (name) DO UPDATE SET
            direction_id            = EXCLUDED.direction_id,
            teacher_id              = EXCLUDED.teacher_id,
            is_individual           = EXCLUDED.is_individual,
            lesson_duration_minutes = EXCLUDED.lesson_duration_minutes,
            lessons_per_week        = EXCLUDED.lessons_per_week,
            vk_chat                 = EXCLUDED.vk_chat,
            group_start_date        = EXCLUDED.group_start_date
         WHERE
            groups.direction_id            IS DISTINCT FROM EXCLUDED.direction_id
         OR groups.teacher_id              IS DISTINCT FROM EXCLUDED.teacher_id
         OR groups.is_individual           IS DISTINCT FROM EXCLUDED.is_individual
         OR groups.lesson_duration_minutes IS DISTINCT FROM EXCLUDED.lesson_duration_minutes
         OR groups.lessons_per_week        IS DISTINCT FROM EXCLUDED.lessons_per_week
         OR (groups.vk_chat IS DISTINCT FROM NULLIF(EXCLUDED.vk_chat, ''))
         OR groups.group_start_date        IS DISTINCT FROM EXCLUDED.group_start_date
         RETURNING id, (xmax = 0) AS inserted`,
        [g.name, g.direction_name, g.teacher_name, g.is_individual,
         g.lesson_duration_minutes, g.lessons_per_week, g.vk_chat, g.group_start_date],
      );

      let groupId;
      if (upsert.rowCount === 0) {
        const r = await client.query('SELECT id FROM groups WHERE name = $1', [g.name]);
        if (r.rowCount === 0) {
          process.stderr.write(`[warn] group "${g.name}": direction "${g.direction_name}" or teacher "${g.teacher_name}" not found, skipped\n`);
          result.skipped++;
          return;
        }
        groupId = r.rows[0].id;
        result.skipped++;
      } else {
        groupId = upsert.rows[0].id;
        if (upsert.rows[0].inserted) result.inserted++;
        else result.updated++;
      }

      await client.query('DELETE FROM group_schedule_slots WHERE group_id = $1', [groupId]);
      for (const s of g.slots) {
        await client.query(
          `INSERT INTO group_schedule_slots (group_id, day_of_week, start_time) VALUES ($1, $2, $3)`,
          [groupId, s.day_of_week, s.start_time],
        );
        result.slots_replaced++;
      }
    });
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

module.exports = { extractGroups, runBackfill };
