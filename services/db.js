// services/db.js
//
// Инфраструктура доступа к PG: пул соединений, обёртка транзакции, type-parser.
// Доменные запросы живут в репозиториях (services/repo/* для admin,
// services/teacher-repo.js для teacher SPA) — этот модуль их не знает.
const { Pool, types } = require('pg');

// PG DATE (OID 1082) → сырая строка YYYY-MM-DD, без конверсии в JS Date.
// Иначе pg создаёт Date с локальной полночью, а JSON.stringify сериализует
// её как UTC ISO, в MSK сдвигая дату на день назад.
types.setTypeParser(1082, (v) => v);

// Пул соединений к PG. Явные лимиты вместо дефолтов библиотеки pg:
//   max                   — потолок одновременных соединений (дефолт 10). 20 — под
//                           пик записи; держать ≤ PG max_connections (дефолт 100) и
//                           помнить про ~5-10 МБ ОЗУ на соединение (20 ≈ 160 МБ).
//   idleTimeoutMillis     — закрыть простаивающее соединение через 30с (не держать зря).
//   connectionTimeoutMillis — НЕ ждать свободное соединение вечно (дефолт 0): при
//                           перегрузке/зависшей БД запрос быстро падает (fail-fast),
//                           а не копится до OOM.
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: Number(process.env.PG_POOL_MAX) || 20,
  idleTimeoutMillis: 30_000,
  connectionTimeoutMillis: 5_000,
  // Серверный лимит на длительность одного запроса: зависший/тяжёлый SQL не держит
  // соединение и event-loop под нагрузкой, а падает через 30с (защита от self-DoS).
  statement_timeout: 30_000,
  // Позволяет процессу (тесты, backfill-скрипты) завершиться, как только все
  // соединения простаивают, не дожидаясь idleTimeoutMillis. Сервер это не трогает —
  // его держит живым app.listen.
  allowExitOnIdle: true,
});

async function tx(fn) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const result = await fn(client);
    await client.query('COMMIT');
    return result;
  } catch (err) {
    try { await client.query('ROLLBACK'); } catch (_) { /* ignore */ }
    throw err;
  } finally {
    client.release();
  }
}

async function shutdown() {
  await pool.end();
}

module.exports = {
  pool,
  tx,
  shutdown,
};
