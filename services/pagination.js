const { pool: defaultPool } = require('./db');

/**
 * Универсальный server-side пагинатор.
 *
 * Конфиг описывает: какие колонки можно сортировать, какие фильтры принимаются,
 * откуда брать данные. Запрос — нормализованные параметры из HTTP.
 *
 * Контракт ответа: { rows, total, page, page_size }.
 */

/**
 * Готовые билдеры WHERE-условий. Каждый возвращает функцию
 * (value, addParam) => sqlFragment, которая добавляет параметр
 * через addParam и возвращает строку условия.
 */
const F = {
  /** LOWER(col) LIKE %val% (case-insensitive substring) */
  like: (col) => (v, p) => `LOWER(${col}) LIKE ${p('%' + String(v).toLowerCase() + '%')}`,

  /** LOWER(COALESCE(col, '')) LIKE %val% — для NULLable колонок */
  likeNullable: (col) => (v, p) => `LOWER(COALESCE(${col}, '')) LIKE ${p('%' + String(v).toLowerCase() + '%')}`,

  /** col = val (exact string/enum match) */
  exact: (col) => (v, p) => `${col} = ${p(v)}`,

  /** col = Number(val) (для integer-id и числовых полей) */
  num: (col) => (v, p) => `${col} = ${p(Number(v))}`,

  /** col = (val === 'true' || val === true) — boolean из query string */
  bool: (col) => (v, p) => `${col} = ${p(v === 'true' || v === true)}`,

  /** col >= val (для дат-from и числовых-min) */
  gte: (col) => (v, p) => `${col} >= ${p(v)}`,

  /** col <= val (для дат-to и числовых-max) */
  lte: (col) => (v, p) => `${col} <= ${p(v)}`,
};

/**
 * Парсит HTTP query → нормализованный pagination request.
 * Используется в Express-роутах.
 *
 * @param {object} query - req.query
 * @param {object} defaults - { sortBy: string, sortDir?: 'asc'|'desc', pageSize?: number, maxPageSize?: number }
 * @returns {{ page, page_size, sort_by, sort_dir, filters }}
 */
function parsePaginationRequest(query = {}, defaults = {}) {
  const pageSize = Math.min(
    defaults.maxPageSize || 500,
    Math.max(1, Number(query.page_size) || defaults.pageSize || 50),
  );
  const filters = (query.filter && typeof query.filter === 'object') ? { ...query.filter } : {};
  return {
    page: Math.max(1, Number(query.page) || 1),
    page_size: pageSize,
    sort_by: typeof query.sort_by === 'string' ? query.sort_by : (defaults.sortBy || 'id'),
    sort_dir: (query.sort_dir === 'asc' || query.sort_dir === 'desc')
      ? query.sort_dir
      : (defaults.sortDir || 'desc'),
    filters,
  };
}

/**
 * Выполняет paginated SQL-запрос.
 *
 * @param {object} config
 * @param {Record<string, string>} config.sortable
 *        Map sort_by-ключа в SQL-выражение. Если в request пришёл
 *        неизвестный sort_by — подставляется defaultSortBy. Защита от SQL injection.
 * @param {string} config.defaultSortBy
 * @param {'asc'|'desc'} [config.defaultSortDir='desc']
 * @param {Record<string, (val, addParam) => string>} [config.filters]
 *        Map filter-ключа в билдер WHERE-условия. Можно использовать F.like/exact/num/bool/gte/lte.
 *        Если в request filters[key] undefined/null/'' — фильтр игнорируется.
 * @param {string} config.from - 'FROM table t JOIN ... ON ...' (без слова SELECT)
 * @param {string} [config.countFrom] - другая FROM для COUNT, если основная имеет агрегаты.
 *        По умолчанию используется config.from.
 * @param {string} config.selectColumns - 'l.*, g.name AS group_name, ...'
 * @param {string} [config.groupBy] - 'g.id, d.id' (без слова GROUP BY)
 * @param {string} [config.secondarySort='id DESC'] - tie-breaker для ORDER BY.
 *        Должен быть с полным именем колонки если есть JOIN'ы (например 'l.id DESC').
 *
 * @param {object} request - { page, page_size, sort_by, sort_dir, filters }
 * @param {pg.Pool} [pool] - default из services/db
 * @returns {Promise<{ rows, total, page, page_size }>}
 */
async function paginate(config, request = {}, pool = defaultPool) {
  // Дефолты подставляются здесь, чтобы listXxx-обёртки могли быть однострочниками,
  // а прямые вызовы (тесты, скрипты) — работать с любым набором переданных полей.
  const page = Math.max(1, Number(request.page) || 1);
  const page_size = Math.max(1, Number(request.page_size) || 50);
  const sort_by = request.sort_by || config.defaultSortBy;
  const sort_dir = (request.sort_dir === 'asc' || request.sort_dir === 'desc')
    ? request.sort_dir
    : (config.defaultSortDir || 'desc');
  const filters = request.filters || {};

  // 1. Whitelist sort_by, защита от SQL injection.
  const sortCol = config.sortable[sort_by] || config.sortable[config.defaultSortBy];
  if (!sortCol) {
    throw new Error(`paginate: defaultSortBy '${config.defaultSortBy}' missing in sortable map`);
  }
  const sortOrder = sort_dir === 'asc' ? 'ASC' : 'DESC';

  // 2. WHERE из filters.
  const params = [];
  const addParam = (val) => { params.push(val); return `$${params.length}`; };
  const conds = [];
  for (const [key, builder] of Object.entries(config.filters || {})) {
    const val = filters[key];
    if (val === undefined || val === null || val === '') continue;
    const sql = builder(val, addParam);
    if (sql) conds.push(sql);
  }
  const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';
  const groupBy = config.groupBy ? `GROUP BY ${config.groupBy}` : '';
  const tieBreaker = config.secondarySort || 'id DESC';

  // 3. COUNT (если countFrom не задан — используем from). countParams = текущий snapshot params.
  const countFrom = config.countFrom || config.from;
  const countSql = `SELECT COUNT(*)::int AS total ${countFrom} ${where}`;
  const countParams = params.slice();

  // 4. Добавляем LIMIT/OFFSET к params для rows-запроса.
  const offset = Math.max(0, (page - 1) * page_size);
  const limitPh = addParam(page_size);
  const offsetPh = addParam(offset);

  const rowsSql = `
    SELECT ${config.selectColumns}
    ${config.from}
    ${where}
    ${groupBy}
    ORDER BY ${sortCol} ${sortOrder}, ${tieBreaker}
    LIMIT ${limitPh} OFFSET ${offsetPh}
  `;

  const [countRes, rowsRes] = await Promise.all([
    pool.query(countSql, countParams),
    pool.query(rowsSql, params),
  ]);

  return {
    rows: rowsRes.rows,
    total: countRes.rows[0].total,
    page,
    page_size,
  };
}

module.exports = { paginate, parsePaginationRequest, F };
