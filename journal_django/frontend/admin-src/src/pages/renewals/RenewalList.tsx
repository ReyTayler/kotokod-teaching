import type { RenewalFilters } from '../../lib/renewals';

// Заглушка Фазы 5.3 — таблица через DataTable + useListSearchParams
// (аналогично GroupsListPage) строится в следующей фазе.
export function RenewalList(_props: { filters: RenewalFilters; onOpen: (id: number) => void }) {
  return <div className="renewals-placeholder">Список скоро появится</div>;
}
