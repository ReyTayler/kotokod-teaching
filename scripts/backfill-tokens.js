function extractTokens(rows) {
  const out = [];
  for (let i = 1; i < rows.length; i++) {
    const row = rows[i] || [];
    const token = String(row[4] || '').trim();
    const teacher = String(row[5] || '').trim();
    if (!token || !teacher) continue;
    out.push({ token, teacher_name: teacher });
  }
  return out;
}

async function runBackfill({ dryRun = false } = {}) {
  const t0 = Date.now();
  const result = { entity: 'tokens', read: 0, inserted: 0, updated: 0, skipped: 0, duration_ms: 0, dry_run: dryRun };

  const sheets = require('../services/sheets');
  const rows = await sheets.readJournalRange('Токены', 'A:F');
  const tokens = extractTokens(rows);
  result.read = tokens.length;
  process.stderr.write(`tokens: extracted ${tokens.length} entries\n`);

  if (dryRun) {
    tokens.forEach((t) => process.stderr.write(`[dry-run] ${t.token} → ${t.teacher_name}\n`));
    result.duration_ms = Date.now() - t0;
    return result;
  }

  const { pool } = require('../services/db');
  for (const t of tokens) {
    const res = await pool.query(
      `WITH te AS (SELECT id FROM teachers WHERE name = $2)
       INSERT INTO tokens (token, teacher_id, active)
       SELECT $1, te.id, true FROM te
       ON CONFLICT (token) DO UPDATE
         SET teacher_id = EXCLUDED.teacher_id
       WHERE tokens.teacher_id IS DISTINCT FROM EXCLUDED.teacher_id
       RETURNING (xmax = 0) AS inserted`,
      [t.token, t.teacher_name],
    );
    if (res.rowCount === 0) {
      const lookup = await pool.query('SELECT 1 FROM teachers WHERE name = $1', [t.teacher_name]);
      if (lookup.rowCount === 0) {
        process.stderr.write(`[warn] token ${t.token}: teacher "${t.teacher_name}" not found, skipped\n`);
      }
      result.skipped++;
    } else if (res.rows[0].inserted) {
      result.inserted++;
    } else {
      result.updated++;
    }
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

module.exports = { extractTokens, runBackfill };
