import { useCallback, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { useDirections } from '../../hooks/useDirections';
import { useRenewalAssignees, useRenewalUnassigned } from '../../hooks/useRenewals';
import { useRenewalStages } from '../../hooks/useRenewalStages';
import { RenewalUnassignedDialog } from './RenewalUnassignedDialog';
import { SelectInput } from '../../components/form/SelectInput';
import { Checkbox } from '../../components/form/Checkbox';
import { canWriteRenewalStages, type Role } from '../../lib/permissions';
import { RenewalBoard } from './RenewalBoard';
import { RenewalList } from './RenewalList';
import { RenewalDrawer } from './RenewalDrawer';
import type { RenewalFilters } from '../../lib/renewals';
import { PageHeader } from '../../components/shell/PageHeader';

type ViewMode = 'board' | 'list';

export default function RenewalsPage() {
  const { me } = useAuth();
  const [sp, setSp] = useSearchParams();
  const view: ViewMode = sp.get('view') === 'list' ? 'list' : 'board';
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const { data: assignees } = useRenewalAssignees();
  const { data: directions } = useDirections();
  const { data: stages } = useRenewalStages();
  const { data: unassigned } = useRenewalUnassigned();
  const [showUnassigned, setShowUnassigned] = useState(false);
  const unassignedCount = unassigned?.length ?? 0;

  // Ключи фильтров, живущие в URL: общие (доска+список) + списочные.
  const FILTER_KEYS = ['assignee_id', 'direction_id', 'student', 'cycle_no', 'stage_id', 'include_closed'];
  const hasActiveFilters = FILTER_KEYS.some((k) => sp.get(k));

  // Список-специфичные фильтры (student/cycle_no/stage_id) отправляются только
  // в списочном виде — в канбане они не применяются (board их игнорирует).
  const filters: RenewalFilters = {
    assignee_id: sp.get('assignee_id') ?? undefined,
    direction_id: sp.get('direction_id') ?? undefined,
    ...(view === 'list' ? {
      student: sp.get('student') ?? undefined,
      cycle_no: sp.get('cycle_no') ?? undefined,
      stage_id: sp.get('stage_id') ?? undefined,
      include_closed: sp.get('include_closed') ?? undefined,
    } : {}),
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

  const resetFilters = () => {
    const next = new URLSearchParams(sp);
    FILTER_KEYS.forEach((k) => next.delete(k));
    setSp(next, { replace: true });
  };

  const closeDrawer = useCallback(() => setSelectedId(null), []);

  return (
    <div className="renewals-page">
      <PageHeader
        title="Продления"
        actions={
          <>
            <div className="segmented" role="group" aria-label="Вид раздела">
              <button
                type="button"
                className={`segmented__btn${view === 'board' ? ' is-active' : ''}`}
                aria-pressed={view === 'board'}
                onClick={() => setView('board')}
              >Канбан</button>
              <button
                type="button"
                className={`segmented__btn${view === 'list' ? ' is-active' : ''}`}
                aria-pressed={view === 'list'}
                onClick={() => setView('list')}
              >Список</button>
            </div>
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
          </>
        }
      />

      <div className="rnl-toolbar">
        <div className="rnl-toolbar__fields">
          <label className="rnl-field">
            <span className="rnl-field__label">Ответственный</span>
            <SelectInput
              className="rnl-field__select"
              value={sp.get('assignee_id') ?? ''}
              onChange={(e) => setFilter('assignee_id', e.target.value)}
              options={[
                { value: '', label: 'Все' },
                ...(assignees || []).map((a) => ({ value: String(a.id), label: a.full_name })),
              ]}
            />
          </label>
          <label className="rnl-field">
            <span className="rnl-field__label">Направление</span>
            <SelectInput
              className="rnl-field__select"
              value={sp.get('direction_id') ?? ''}
              onChange={(e) => setFilter('direction_id', e.target.value)}
              options={[
                { value: '', label: 'Все' },
                ...(directions || []).map((d) => ({ value: String(d.id), label: d.name })),
              ]}
            />
          </label>

          {/* Фильтры только для списочного вида. */}
          {view === 'list' && (
            <>
              <label className="rnl-field rnl-field--grow">
                <span className="rnl-field__label">Ученик</span>
                <input
                  type="text"
                  className="rnl-field__input"
                  placeholder="Поиск по имени…"
                  value={sp.get('student') ?? ''}
                  onChange={(e) => setFilter('student', e.target.value)}
                />
              </label>
              <label className="rnl-field rnl-field--sm">
                <span className="rnl-field__label">Цикл</span>
                <input
                  type="number"
                  min={1}
                  className="rnl-field__input"
                  placeholder="№"
                  value={sp.get('cycle_no') ?? ''}
                  onChange={(e) => setFilter('cycle_no', e.target.value)}
                />
              </label>
              <label className="rnl-field">
                <span className="rnl-field__label">Стадия</span>
                <SelectInput
                  className="rnl-field__select"
                  value={sp.get('stage_id') ?? ''}
                  onChange={(e) => setFilter('stage_id', e.target.value)}
                  options={[
                    { value: '', label: 'Все' },
                    ...(stages || []).map((s) => ({ value: String(s.id), label: s.label })),
                  ]}
                />
              </label>
            </>
          )}
        </div>

        <div className="rnl-toolbar__aside">
          {view === 'list' && (
            <Checkbox
              label="Закрытые"
              checked={sp.get('include_closed') === 'true'}
              onChange={(e) => setFilter('include_closed', e.target.checked ? 'true' : '')}
            />
          )}
          {hasActiveFilters && (
            <button type="button" className="btn-reset-filters" onClick={resetFilters}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
              Сбросить
            </button>
          )}
        </div>
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
