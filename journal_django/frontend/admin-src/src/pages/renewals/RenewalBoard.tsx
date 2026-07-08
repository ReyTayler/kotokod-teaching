import type { RenewalFilters } from '../../lib/renewals';

// Заглушка Фазы 5.3 — сам Канбан (drag&drop колонок/карточек через @dnd-kit)
// строится в следующей фазе. Здесь только контракт пропсов.
export function RenewalBoard(_props: { filters: RenewalFilters; onOpen: (id: number) => void }) {
  return <div className="renewals-placeholder">Канбан скоро появится</div>;
}
