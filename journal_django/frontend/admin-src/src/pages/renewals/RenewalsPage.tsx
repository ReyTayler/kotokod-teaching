import { useCallback, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { useDirections } from '../../hooks/useDirections';
import { useRenewalAssignees, useRenewalUnassigned } from '../../hooks/useRenewals';
import { RenewalUnassignedDialog } from './RenewalUnassignedDialog';
import { Field } from '../../components/form/Field';
import { SelectInput } from '../../components/form/SelectInput';
import { Checkbox } from '../../components/form/Checkbox';
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

  const { data: assignees } = useRenewalAssignees();
  const { data: directions } = useDirections();
  const { data: unassigned } = useRenewalUnassigned();
  const [showUnassigned, setShowUnassigned] = useState(false);
  const unassignedCount = unassigned?.length ?? 0;

  const filters: RenewalFilters = {
    assignee_id: sp.get('assignee_id') ?? undefined,
    direction_id: sp.get('direction_id') ?? undefined,
    overdue: sp.get('overdue') ?? undefined,
    include_closed: view === 'list' ? (sp.get('include_closed') ?? undefined) : undefined,
  };

  const setView = (v: ViewMode) => {
    const next = new URLSearchParams(sp);
    next.set('view', v);
    setSp(next, { replace: true });
  };

  // Фильтры живут в URL — состояние доски/списка можно шарить ссылкой.
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(sp);
    if (value) next.set(key, value); else next.delete(key);
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
          <button
            type="button"
            className={`btn-secondary${unassignedCount > 0 ? ' renewals-page__unassigned-btn--attention' : ''}`}
            onClick={() => setShowUnassigned(true)}
          >
            Без сделок{unassignedCount > 0 ? ` (${unassignedCount})` : ''}
          </button>
          <Link to="/admin/renewals/analytics" className="btn-secondary">Аналитика</Link>
          {canWriteRenewalStages(me?.role as Role) && (
            <Link to="/admin/renewals/stages" className="btn-secondary">Настройка стадий</Link>
          )}
        </div>
      </header>

      <div className="renewals-page__filters">
        <Field label="Ответственный">
          <SelectInput
            value={sp.get('assignee_id') ?? ''}
            onChange={(e) => setFilter('assignee_id', e.target.value)}
            options={[
              { value: '', label: 'Все' },
              ...(assignees || []).map((a) => ({ value: String(a.id), label: a.full_name })),
            ]}
          />
        </Field>
        <Field label="Направление">
          <SelectInput
            value={sp.get('direction_id') ?? ''}
            onChange={(e) => setFilter('direction_id', e.target.value)}
            options={[
              { value: '', label: 'Все' },
              ...(directions || []).map((d) => ({ value: String(d.id), label: d.name })),
            ]}
          />
        </Field>
        <Checkbox
          label="Просроченное касание"
          checked={sp.get('overdue') === 'true'}
          onChange={(e) => setFilter('overdue', e.target.checked ? 'true' : '')}
        />
        {view === 'list' && (
          <Checkbox
            label="Показать закрытые"
            checked={sp.get('include_closed') === 'true'}
            onChange={(e) => setFilter('include_closed', e.target.checked ? 'true' : '')}
          />
        )}
      </div>

      {view === 'board'
        ? <RenewalBoard filters={filters} onOpen={setSelectedId} />
        : <RenewalList filters={filters} onOpen={setSelectedId} />}

      {selectedId != null && (
        <RenewalDrawer id={selectedId} onClose={closeDrawer} />
      )}

      {showUnassigned && (
        <RenewalUnassignedDialog onClose={() => setShowUnassigned(false)} />
      )}
    </div>
  );
}
