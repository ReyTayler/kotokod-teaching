require('dotenv').config();

const steps = [
  ['directions', require('./backfill-directions')],
  ['teachers',   require('./backfill-teachers')],
  ['tokens',     require('./backfill-tokens')],
  ['groups',     require('./backfill-groups')],
  ['students',   require('./backfill-students')],
  ['lessons',    require('./backfill-lessons')],
  ['payroll',    require('./backfill-payroll')],
];

async function main() {
  const dryRun = process.argv.includes('--dry-run');
  const t0 = Date.now();
  const results = [];

  for (const [name, mod] of steps) {
    process.stderr.write(`\n=== ${name} ===\n`);
    const result = await mod.runBackfill({ dryRun });
    results.push(result);
  }

  const summary = {
    total_duration_ms: Date.now() - t0,
    dry_run: dryRun,
    steps: results,
  };
  process.stdout.write(JSON.stringify(summary, null, 2) + '\n');

  if (!dryRun) {
    const { pool } = require('../services/db');
    await pool.end();
  }
}

if (require.main === module) {
  main().catch((err) => { console.error(err); process.exit(1); });
}
