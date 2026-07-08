import { useCallback, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { canWriteRenewalStages, type Role } from '../../lib/permissions';
import { RenewalBoard } from './RenewalBoard';
import { RenewalList } from './RenewalList';
import { RenewalDrawer } from './RenewalDrawer';
import type { RenewalFilters } from '../../lib/renewals';

type ViewMode = 'board' | 'list';

export default function RenewalsPage() {
  const { me } = useAuth();
  const [sp, setSp] = useSearchParams();
  const view: ViewMode = sp.get('view') === 'list' ? 'list' : 'board';
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Фильтры прокидываются пустыми на этом шаге (инфраструктура/оболочка) —
  // полноценные SelectInput-фильтры по менеджеру/направлению/просрочке
  // добавятся вместе с реализацией Канбана/Списка в следующей фазе.
  const filters: RenewalFilters = {
    assignee_id: sp.get('assignee_id') ?? undefined,
    direction_id: sp.get('direction_id') ?? undefined,
    overdue: sp.get('overdue') ?? undefined,
  };

  const setView = (v: ViewMode) => {
    const next = new URLSearchParams(sp);
    next.set('view', v);
    setSp(next, { replace: true });
  };

  const closeDrawer = useCallback(() => setSelectedId(null), []);

  return (
    <div className="renewals-page">
      <header className="renewals-page__head">
        <h1 className="renewals-page__title">Продления</h1>
        <div className="view-toggle" role="tablist" aria-label="Вид раздела">
          <button
            type="button"
            role="tab"
            aria-selected={view === 'board'}
            className={`view-toggle__btn${view === 'board' ? ' active' : ''}`}
            onClick={() => setView('board')}
          >
            Канбан
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === 'list'}
            className={`view-toggle__btn${view === 'list' ? ' active' : ''}`}
            onClick={() => setView('list')}
          >
            Список
          </button>
        </div>
        <div className="renewals-page__head-links">
          <Link to="/admin/renewals/analytics" className="btn-secondary">Аналитика</Link>
          {canWriteRenewalStages(me?.role as Role) && (
            <Link to="/admin/renewals/stages" className="btn-secondary">Настройка стадий</Link>
          )}
        </div>
      </header>

      {view === 'board'
        ? <RenewalBoard filters={filters} onOpen={setSelectedId} />
        : <RenewalList filters={filters} onOpen={setSelectedId} />}

      {selectedId != null && (
        <RenewalDrawer id={selectedId} onClose={closeDrawer} />
      )}
    </div>
  );
}
