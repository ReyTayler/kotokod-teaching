function extractDirections(rows) {
  const seen = new Map();
  for (const row of rows) {
    const direction = String(row[18] || '').trim();
    if (!direction) continue;
    if (direction.includes('УЧЕНИКА НЕТ')) continue;
    if (seen.has(direction)) continue;

    const isIndividual = direction.includes('ИНДИВ');
    const sheet_name = isIndividual
      ? 'Индивидуальные'
      : direction.replace(/\s+ИНДИВ$/i, '').trim();

    seen.set(direction, { name: direction, sheet_name, is_individual: isIndividual });
  }
  return [...seen.values()];
}

async function runBackfill({ dryRun = false } = {}) {
  const t0 = Date.now();
  const result = { entity: 'directions', read: 0, inserted: 0, updated: 0, skipped: 0, duration_ms: 0, dry_run: dryRun };

  const sheets = require('../services/sheets');
  const rawRows = await sheets.readStudentsRange('Список всех детей', 'A3:S');
  const directions = extractDirections(rawRows);
  result.read = directions.length;
  process.stderr.write(`directions: extracted ${directions.length} from ${rawRows.length} rows\n`);

  if (dryRun) {
    directions.forEach((d) =>
      process.stderr.write(`[dry-run] ${d.name} → sheet=${d.sheet_name}, individual=${d.is_individual}\n`),
    );
    result.duration_ms = Date.now() - t0;
    return result;
  }

  const { pool } = require('../services/db');
  for (const d of directions) {
    const res = await pool.query(
      `INSERT INTO directions (name, sheet_name, is_individual)
       VALUES ($1, $2, $3)
       ON CONFLICT (name) DO UPDATE
         SET sheet_name    = EXCLUDED.sheet_name,
             is_individual = EXCLUDED.is_individual
       WHERE directions.sheet_name    IS DISTINCT FROM EXCLUDED.sheet_name
          OR directions.is_individual IS DISTINCT FROM EXCLUDED.is_individual
       RETURNING (xmax = 0) AS inserted`,
      [d.name, d.sheet_name, d.is_individual],
    );
    if (res.rowCount === 0)        result.skipped++;
    else if (res.rows[0].inserted) result.inserted++;
    else                           result.updated++;
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

module.exports = { extractDirections, runBackfill };
