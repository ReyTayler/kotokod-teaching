export function TableSkeleton({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="table-wrap">
      <table>
        <tbody>
          {Array.from({ length: rows }).map((_, i) => (
            <tr key={i}>
              {Array.from({ length: cols }).map((_, j) => (
                <td key={j}><div className="skeleton-cell" /></td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PageLoading() {
  return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text3)' }}>Загружаем…</div>;
}
