import { useState } from 'react';
import type { CSSProperties } from 'react';

/**
 * Diff «поле → было → стало» для события журнала изменений.
 * diff — pgh_diff бэкенда: { field: [old, new] }.
 * Переиспользуем и для снапшотов insert/delete (см. snapshotToDiff ниже).
 */
export function DiffView({ diff }: { diff: Record<string, [unknown, unknown]> }) {
  const entries = Object.entries(diff);
  if (!entries.length) {
    return <div style={{ color: 'var(--text3)', fontSize: '0.8125rem' }}>Нет изменённых полей</div>;
  }
  return (
    <table className="diff-view" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8125rem' }}>
      <thead>
        <tr>
          {['Поле', 'Было', 'Стало'].map((h) => (
            <th
              key={h}
              style={{
                textAlign: 'left',
                padding: 'var(--space-1) var(--space-2)',
                color: 'var(--text3)',
                fontWeight: 500,
                borderBottom: '1px solid var(--border)',
              }}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {entries.map(([field, [before, after]]) => (
          <tr key={field}>
            <td style={cellStyle}><span className="mono" style={{ fontSize: '0.75rem' }}>{field}</span></td>
            <td style={{ ...cellStyle, color: 'var(--text2)' }}><Value v={before} /></td>
            <td style={cellStyle}><Value v={after} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const cellStyle: CSSProperties = {
  padding: 'var(--space-1) var(--space-2)',
  borderBottom: '1px solid var(--border)',
  verticalAlign: 'top',
  wordBreak: 'break-word',
};

const TRUNCATE_AT = 200;

function Value({ v }: { v: unknown }) {
  const [expanded, setExpanded] = useState(false);
  if (v === null || v === undefined || v === '') {
    return <span style={{ color: 'var(--text3)' }}>—</span>;
  }
  if (typeof v === 'boolean') {
    return <span>{v ? 'да' : 'нет'}</span>;
  }
  const s = typeof v === 'object' ? JSON.stringify(v) : String(v);
  if (s.length <= TRUNCATE_AT || expanded) {
    return <span className="mono" style={{ fontSize: '0.75rem' }}>{s}</span>;
  }
  return (
    <span className="mono" style={{ fontSize: '0.75rem' }}>
      {s.slice(0, TRUNCATE_AT)}…{' '}
      <button type="button" className="btn-link" onClick={() => setExpanded(true)}>
        показать полностью
      </button>
    </span>
  );
}

/**
 * Снапшот insert/delete → формат diff:
 *   insert: — → значение;  delete: значение → —.
 * null-поля опускаются (шум), pgh_* полей в data нет — бэкенд их не отдаёт.
 */
export function snapshotToDiff(
  data: Record<string, unknown>,
  kind: 'insert' | 'delete',
): Record<string, [unknown, unknown]> {
  const out: Record<string, [unknown, unknown]> = {};
  for (const [k, v] of Object.entries(data)) {
    if (v === null || v === undefined) continue;
    out[k] = kind === 'insert' ? [null, v] : [v, null];
  }
  return out;
}
