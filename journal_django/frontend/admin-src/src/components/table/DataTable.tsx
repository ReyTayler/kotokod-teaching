import { useState, useMemo, type ReactNode } from 'react';
import { Paginator } from './Paginator';
import { SelectInput } from '../form/SelectInput';

export interface Column<T> {
  key: string;
  label: string;
  cell?: (row: T) => ReactNode;
  searchable?: boolean | ((row: T, query: string) => boolean);
  /** Если задано в server-mode — фильтр-шапка рендерит <select> вместо текста.
   *  Пустой value = «все». */
  searchOptions?: Array<{ value: string; label: string }>;
  sortable?: boolean;
  sortKey?: string;
  width?: number | string;
}

export interface ServerPaginationState {
  page: number;
  pageSize: number;
  total: number;
  sortBy: string;
  sortDir: 'asc' | 'desc';
  filters: Record<string, string>;
}

export interface ServerPaginationCallbacks {
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  onSortChange: (col: string, dir: 'asc' | 'desc') => void;
  onFiltersChange: (filters: Record<string, string>) => void;
}

interface Props<T> {
  data: T[];
  columns: Column<T>[];
  title: string;
  onRowClick?: (row: T) => void;
  headerActions?: ReactNode;
  // если передан — переключение в server-mode
  serverPagination?: ServerPaginationState & ServerPaginationCallbacks;
  isLoading?: boolean;
}

export function DataTable<T>({ data, columns, title, onRowClick, headerActions, serverPagination, isLoading }: Props<T>) {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const hasFilters = Object.values(filters).some((v) => v && v.trim() !== '');

  const filtered = useMemo(() => {
    if (serverPagination) return data; // server-mode: data уже отфильтрована/срезана
    return data.filter((row) => {
      for (const col of columns) {
        if (!col.searchable) continue;
        const q = (filters[col.key] || '').trim().toLowerCase();
        if (!q) continue;
        if (typeof col.searchable === 'function') {
          if (!col.searchable(row, q)) return false;
        } else {
          const val = (row as Record<string, unknown>)[col.key];
          if (val == null) return false;
          if (!String(val).toLowerCase().includes(q)) return false;
        }
      }
      return true;
    });
  }, [data, filters, columns, serverPagination]);

  // ── SERVER MODE ──
  if (serverPagination) {
    const sp = serverPagination;

    const handleSortClick = (col: Column<T>) => {
      if (col.sortable === false) return;
      const sortKey = col.sortKey || col.key;
      const dir =
        sp.sortBy === sortKey && sp.sortDir === 'desc' ? 'asc' : 'desc';
      sp.onSortChange(sortKey, dir);
    };

    const handleFilterChange = (colKey: string, value: string) => {
      const next = { ...sp.filters };
      if (value) next[colKey] = value;
      else delete next[colKey];
      sp.onFiltersChange(next);
    };

    const hasServerFilters = Object.values(sp.filters).some((v) => v && v.trim() !== '');

    return (
      <div>
        <div className="section-header">
          <span className="section-title">{title}</span>
          <span className="count-badge">{sp.total}</span>
          <div className="section-actions">
            {hasServerFilters && (
              <button
                type="button"
                className="btn-reset-filters"
                onClick={() => sp.onFiltersChange({})}
                title="Сбросить все фильтры"
                aria-label="Сбросить все фильтры"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M19.4 20 9.4 10l1-3.5 3.5-1 10 10z"/>
                  <path d="M14 4 4 14l3 3 10-10z"/>
                  <path d="M3 22h7"/>
                </svg>
                Сбросить фильтры
              </button>
            )}
            {headerActions}
          </div>
        </div>
        <div className={`data-table-wrapper${isLoading ? ' data-table--loading' : ''}`}>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  {columns.map((c) => {
                    const sortKey = c.sortKey || c.key;
                    const isSortable = c.sortable !== false;
                    const isActive = sp.sortBy === sortKey;
                    return (
                      <th
                        key={c.key}
                        style={c.width ? { width: c.width } : undefined}
                        className={isSortable ? 'sortable' : undefined}
                        onClick={isSortable ? () => handleSortClick(c) : undefined}
                      >
                        {c.label}
                        {isActive && (
                          <span> {sp.sortDir === 'asc' ? '▲' : '▼'}</span>
                        )}
                      </th>
                    );
                  })}
                </tr>
                <tr>
                  {columns.map((c) => (
                    <th key={c.key + '-f'}>
                      {c.searchable !== false && c.searchable !== undefined ? (
                        c.searchOptions ? (
                          <SelectInput
                            className="search-input"
                            value={sp.filters[c.key] || ''}
                            onChange={(e) => handleFilterChange(c.key, e.target.value)}
                            options={[{ value: '', label: 'Все' }, ...c.searchOptions]}
                            placeholder="Все"
                          />
                        ) : (
                          <input
                            type="text"
                            className="search-input"
                            placeholder="…"
                            value={sp.filters[c.key] || ''}
                            onChange={(e) => handleFilterChange(c.key, e.target.value)}
                          />
                        )
                      ) : null}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.length === 0 ? (
                  <tr>
                    <td colSpan={columns.length} className="data-table__empty">
                      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.4 }}>
                        <circle cx="11" cy="11" r="8"/>
                        <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                      </svg>
                      <div>Ничего не найдено</div>
                      {Object.values(sp.filters).some((v) => v) && (
                        <div className="data-table__empty-hint">Попробуй сбросить фильтры</div>
                      )}
                    </td>
                  </tr>
                ) : data.map((row, i) => (
                  <tr
                    key={i}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    style={onRowClick ? { cursor: 'pointer' } : undefined}
                  >
                    {columns.map((c) => (
                      <td key={c.key}>
                        {c.cell ? c.cell(row) : String((row as Record<string, unknown>)[c.key] ?? '—')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Paginator
            page={sp.page}
            pageSize={sp.pageSize}
            total={sp.total}
            onPageChange={sp.onPageChange}
            onPageSizeChange={sp.onPageSizeChange}
          />
        </div>
      </div>
    );
  }

  // ── CLIENT MODE (без изменений) ──
  return (
    <div>
      <div className="section-header">
        <span className="section-title">{title}</span>
        <span className="count-badge">
          {filtered.length}{data.length !== filtered.length ? ` / ${data.length}` : ''}
        </span>
        <div className="section-actions">
          {hasFilters && (
            <button
              type="button"
              className="btn-reset-filters"
              onClick={() => setFilters({})}
              title="Сбросить все фильтры"
              aria-label="Сбросить все фильтры"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M19.4 20 9.4 10l1-3.5 3.5-1 10 10z"/>
                <path d="M14 4 4 14l3 3 10-10z"/>
                <path d="M3 22h7"/>
              </svg>
              Сбросить фильтры
            </button>
          )}
          {headerActions}
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} style={c.width ? { width: c.width } : undefined}>{c.label}</th>
              ))}
            </tr>
            <tr>
              {columns.map((c) => (
                <th key={c.key + '-f'}>
                  {c.searchable ? (
                    <input
                      type="text"
                      className="search-input"
                      placeholder="…"
                      value={filters[c.key] || ''}
                      onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                    />
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="data-table__empty">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.4 }}>
                    <circle cx="11" cy="11" r="8"/>
                    <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                  </svg>
                  <div>Ничего не найдено</div>
                  {hasFilters && (
                    <div className="data-table__empty-hint">Попробуй сбросить фильтры</div>
                  )}
                </td>
              </tr>
            ) : filtered.map((row, i) => (
              <tr
                key={i}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                style={onRowClick ? { cursor: 'pointer' } : undefined}
              >
                {columns.map((c) => (
                  <td key={c.key}>
                    {c.cell ? c.cell(row) : String((row as Record<string, unknown>)[c.key] ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
