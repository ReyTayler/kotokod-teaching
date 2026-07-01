// scripts/backfill-payments.js
// Импорт исторических оплат из листа «Свод оплат» (журнал-таблица) в таблицу payments.
// Не идемпотентен (нет натурального ключа). Используй --reset чтобы стереть прошлый backfill.

require('dotenv').config();

const SHEET_NAME = 'Свод оплат';
const RANGE = 'A2:E';

function normName(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/\s+/g, ' ')
    .trim();
}

function parseDate(raw) {
  const m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(String(raw || '').trim());
  if (!m) return null;
  const [, d, mo, y] = m;
  return `${y}-${mo}-${d}`;
}

function parseAmount(raw) {
  const s = String(raw || '').replace(/\s/g, '').replace(',', '.');
  const n = parseFloat(s);
  return Number.isFinite(n) && n > 0 ? n : null;
}

async function runBackfill({ dryRun = false, reset = false } = {}) {
  const t0 = Date.now();

  const sheets = require('../services/sheets');
  const { pool } = require('../services/db');

  // 1. Чтение листа
  const rows = await sheets.readJournalRange(SHEET_NAME, RANGE);
  process.stderr.write(`Read ${rows.length} rows from '${SHEET_NAME}'\n`);

  // 2. Индексы students и directions
  const { rows: stRows } = await pool.query(`SELECT id, full_name FROM students`);
  const studentIdx = new Map();
  for (const s of stRows) {
    const key = normName(s.full_name);
    if (!studentIdx.has(key)) studentIdx.set(key, []);
    studentIdx.get(key).push(s.id);
  }

  const { rows: dirRows } = await pool.query(
    `SELECT id, name, subscription_price FROM directions`,
  );
  const dirIdx = new Map();
  for (const d of dirRows) {
    dirIdx.set(normName(d.name), d);
  }

  // 3. Защита от случайного повторного запуска. Если в БД уже есть строки от прошлого
  // прогона backfill — требуем явный --reset, иначе отказываемся, чтобы не наплодить дубли.
  if (!reset) {
    const { rows: existing } = await pool.query(
      `SELECT COUNT(*)::int AS c FROM payments WHERE created_by = 'backfill-script'`,
    );
    if (existing[0].c > 0) {
      process.stderr.write(
        `Refuse: payments table already has ${existing[0].c} rows from previous backfill. ` +
        `Use --reset to wipe them and re-import, or skip this run.\n`,
      );
      return {
        name: 'payments',
        aborted: true,
        reason: 'duplicate_backfill',
        existing_backfill_rows: existing[0].c,
      };
    }
  }

  // 4. Optional reset
  if (reset && !dryRun) {
    const { rowCount } = await pool.query(
      `DELETE FROM payments WHERE created_by = 'backfill-script'`,
    );
    process.stderr.write(`--reset: deleted ${rowCount} previous backfill rows\n`);
  } else if (!dryRun && !reset) {
    process.stderr.write(
      `WARNING: running without --reset will create duplicates if backfill was run before.\n`,
    );
  }

  // 5. Обработка строк
  const skipped = [];
  let inserted = 0;
  let archivedCount = 0;
  let nonStandardCount = 0;

  for (let i = 0; i < rows.length; i++) {
    const row = rows[i] || [];
    const rowNum = i + 2; // 1-я строка — заголовок

    const cells = [0, 1, 2, 3, 4].map((j) =>
      row[j] == null ? '' : String(row[j]),
    );
    const [rawName, rawNote, rawAmount, rawDate, rawDir] = cells;

    // Пустая строка
    if (!rawName.trim() && !rawAmount.trim() && !rawDate.trim() && !rawDir.trim()) {
      continue;
    }

    // Имя
    const stKey = normName(rawName);
    const stMatches = studentIdx.get(stKey);
    if (!stMatches || stMatches.length === 0) {
      skipped.push({ row: rowNum, reason: `ученик '${rawName}' не найден` });
      continue;
    }
    if (stMatches.length > 1) {
      skipped.push({
        row: rowNum,
        reason: `ученик '${rawName}' — несколько матчей: ${stMatches.join(',')}`,
      });
      continue;
    }
    const studentId = stMatches[0];

    // Сумма
    const amount = parseAmount(rawAmount);
    if (amount == null) {
      skipped.push({ row: rowNum, reason: `невалидная сумма '${rawAmount}'` });
      continue;
    }

    // Дата
    const paidAt = parseDate(rawDate);
    if (!paidAt) {
      skipped.push({ row: rowNum, reason: `невалидная дата '${rawDate}'` });
      continue;
    }

    // Направление
    const dirKey = normName(rawDir);
    let directionId = null;
    let subscriptionsCount = null;
    let unitPrice = amount;

    if (dirKey === 'архив' || dirKey === '') {
      // Архив: оба NULL (см. CHECK payments_direction_count_match в миграции 009)
      archivedCount++;
    } else {
      const dir = dirIdx.get(dirKey);
      if (!dir) {
        skipped.push({
          row: rowNum,
          reason: `направление '${rawDir}' не найдено`,
        });
        continue;
      }
      directionId = dir.id;
      const price =
        dir.subscription_price != null ? Number(dir.subscription_price) : null;
      // Сравнение через копейки чтобы избежать float-погрешностей
      if (
        price &&
        price > 0 &&
        Math.round(amount * 100) % Math.round(price * 100) === 0
      ) {
        subscriptionsCount = Math.round(
          Math.round(amount * 100) / Math.round(price * 100),
        );
        unitPrice = price;
      } else {
        subscriptionsCount = 1;
        unitPrice = amount;
        nonStandardCount++;
      }
    }

    if (dryRun) {
      inserted++;
      continue;
    }

    const priceFinal = Math.round(Number(unitPrice) * 100) / 100;
    const totalFinal =
      subscriptionsCount != null
        ? (priceFinal * subscriptionsCount).toFixed(2)
        : priceFinal.toFixed(2);

    await pool.query(
      `INSERT INTO payments
         (student_id, direction_id, subscriptions_count, unit_price, total_amount, paid_at, note, created_by)
       VALUES ($1, $2, $3, $4, $5, $6, $7, 'backfill-script')`,
      [
        studentId,
        directionId,
        subscriptionsCount,
        priceFinal,
        totalFinal,
        paidAt,
        rawNote && rawNote.trim() ? rawNote.trim() : null,
      ],
    );
    inserted++;
  }

  return {
    name: 'payments',
    dry_run: dryRun,
    reset,
    rows_read: rows.length,
    inserted,
    skipped: skipped.length,
    archived: archivedCount,
    non_standard: nonStandardCount,
    skipped_details: skipped,
    duration_ms: Date.now() - t0,
  };
}

async function main() {
  const dryRun = process.argv.includes('--dry-run');
  const reset = process.argv.includes('--reset');
  const force = process.argv.includes('--yes');

  if (!dryRun && !force) {
    process.stderr.write(
      `About to INSERT into payments. Pass --dry-run for preview, or --yes to proceed.\n`,
    );
    process.exit(1);
  }

  const result = await runBackfill({ dryRun, reset });
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');

  const { pool } = require('../services/db');
  await pool.end();
}

if (require.main === module) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}

module.exports = { runBackfill, normName, parseDate, parseAmount };
