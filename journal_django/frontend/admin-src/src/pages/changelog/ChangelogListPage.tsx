import { useState } from 'react';
import type { ReactElement } from 'react';
import { useChangelogList } from '../../hooks/useChangelog';
import { useListSearchParams } from '../../hooks/useListSearchParams';
import { useAuth } from '../../hooks/useAuth';
import { canRevertChangelog, type Role } from '../../lib/permissions';
import { DataTable, type Column } from '../../components/table/DataTable';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { SelectInput } from '../../components/form/SelectInput';
import { ChangelogDetailModal } from './ChangelogDetailModal';
import { RevertConfirmDialog } from './RevertConfirmDialog';
import { fmtDateTime, fmtDateTimeShort } from '../../lib/format';
import {
  CHANGELOG_ENTITY_LABELS,
  CHANGELOG_OPERATION_LABELS,
  CHANGELOG_OPERATION_OPTIONS,
} from '../../lib/labels';
import type { ChangelogOperation } from '../../lib/types';

// ─── Иконки действий (16px, по стилю NAV_ICONS) ──────────────────────────────

const svgProps = {
  width: 15, height: 15, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', strokeWidth: 1.8,
  strokeLinecap: 'round', strokeLinejoin: 'round',
} as const;

const ACTION_ICONS: Record<string, ReactElement> = {
  move:   <svg {...svgProps}><polyline points="17 11 21 7 17 3"/><line x1="21" y1="7" x2="9" y2="7"/><polyline points="7 13 3 17 7 21"/><line x1="3" y1="17" x2="15" y2="17"/></svg>,
  create: <svg {...svgProps}><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  edit:   <svg {...svgProps}><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/></svg>,
  remove: <svg {...svgProps}><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>,
  done:   <svg {...svgProps}><polyline points="20 6 9 17 4 12"/></svg>,
  cancel: <svg {...svgProps}><circle cx="12" cy="12" r="10"/><line x1="4.9" y1="4.9" x2="19.1" y2="19.1"/></svg>,
  revert: <svg {...svgProps}><polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/></svg>,
  other:  <svg {...svgProps}><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>,
};

function actionIcon(operation: string): ReactElement {
  if (operation === 'changelog.revert') return ACTION_ICONS.revert;
  if (operation === 'plan.reschedule' || operation.includes('schedule_change') ||
      operation === 'plan.permanent_change') return ACTION_ICONS.move;
  if (operation === 'plan.cancel') return ACTION_ICONS.cancel;
  if (operation === 'lesson.submit') return ACTION_ICONS.done;
  if (operation.endsWith('.create') || operation === 'plan.extra' ||
      operation === 'plan.generate' || operation === 'payment.create') return ACTION_ICONS.create;
  if (operation.endsWith('.delete')) return ACTION_ICONS.remove;
  if (operation.endsWith('.update') || operation.startsWith('plan.')) return ACTION_ICONS.edit;
  return ACTION_ICONS.other;
}

// ─── Роли по-русски (для колонки «Кто») ───────────────────────────────────────

const ROLE_SHORT: Record<string, string> = {
  teacher: 'преподаватель',
  manager: 'менеджер',
  admin:   'админ',
};

// ─── buildQuery: сортировка ленты фиксирована на бэке (occurred_at DESC) ──────

function buildQuery(page: number, pageSize: number, filters: Record<string, string>): string {
  const p = new URLSearchParams();
  p.set('page', String(page));
  p.set('page_size', String(pageSize));
  for (const [k, v] of Object.entries(filters)) {
    if (v) p.set(`filter[${k}]`, v);
  }
  return '?' + p.toString();
}

// ─── Главный компонент ────────────────────────────────────────────────────────

export default function ChangelogListPage() {
  const { me } = useAuth();
  const {
    page, pageSize, sortBy, sortDir, filters,
    setPage, setPageSize, setSort, setFilters, getExtra, setExtras,
  } = useListSearchParams({ sortBy: 'occurred_at', sortDir: 'desc' });

  // Фильтр «история записи» приходит по deep-link из конфликта отката.
  const entity   = getExtra('entity')   ?? '';
  const entityId = getExtra('entity_id') ?? '';
  const operation = getExtra('op') ?? '';

  const [openedId, setOpenedId] = useState<string | null>(null);
  const [reverting, setReverting] = useState<ChangelogOperation | null>(null);

  const query = buildQuery(page, pageSize, {
    ...filters,
    operation,
    entity,
    entity_id: entity ? entityId : '',
  });
  const { data, isLoading, isFetching } = useChangelogList(query);

  const columns: Column<ChangelogOperation>[] = [
    {
      key: 'occurred_at',
      label: 'Время',
      width: '7rem',
      cell: (r) => (
        <span className="mono" style={{ color: 'var(--text2)', fontSize: '0.8125rem' }} title={fmtDateTime(r.occurred_at)}>
          {fmtDateTimeShort(r.occurred_at)}
        </span>
      ),
    },
    {
      key: 'operation',
      label: 'Действие',
      width: '14rem',
      cell: (r) => (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--text1)' }}>
          <span style={{ color: 'var(--text3)', display: 'inline-flex' }}>{actionIcon(r.operation)}</span>
          {CHANGELOG_OPERATION_LABELS[r.operation] ?? r.operation}
        </span>
      ),
    },
    {
      key: 'summary',
      label: 'Описание',
      cell: (r) => <span>{r.summary}</span>,
    },
    {
      key: 'actor',
      label: 'Кто',
      width: '13rem',
      cell: (r) =>
        r.actor ? (
          <span style={{ color: 'var(--text3)' }} title={r.actor.email ?? undefined}>
            {r.actor.name}
            {r.actor.role ? ` (${ROLE_SHORT[r.actor.role] ?? r.actor.role})` : ''}
          </span>
        ) : (
          <span style={{ color: 'var(--text3)' }}>Система</span>
        ),
    },
    {
      key: 'status',
      label: 'Статус',
      width: '8rem',
      cell: (r) =>
        r.reverted
          ? <span className="status-badge status-badge--muted">откачено</span>
          : r.operation === 'changelog.revert'
            ? <span className="status-badge status-badge--info">откат</span>
            : <span className="status-badge status-badge--positive">применено</span>,
    },
    {
      key: 'revert',
      label: '',
      width: '8rem',
      cell: (r) =>
        canRevertChangelog(me?.role as Role) && r.revertable ? (
          <button
            type="button"
            className="btn-cancel"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-1)', whiteSpace: 'nowrap' }}
            onClick={(e) => { e.stopPropagation(); setReverting(r); }}
          >
            {ACTION_ICONS.revert} Откатить
          </button>
        ) : null,
    },
  ];

  const rows  = data?.rows  ?? [];
  const total = data?.total ?? 0;

  if (isLoading) return <TableSkeleton rows={12} cols={6} />;

  const entityFilterLabel = entity
    ? `${CHANGELOG_ENTITY_LABELS[entity] ?? entity}${entityId ? ` #${entityId}` : ''}`
    : null;

  return (
    <>
      <DataTable<ChangelogOperation>
        data={rows}
        columns={columns}
        title="Журнал изменений"
        isLoading={isFetching}
        onRowClick={(r) => setOpenedId(r.id)}
        headerActions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
            <SelectInput
              options={[{ value: '', label: 'Все действия' }, ...CHANGELOG_OPERATION_OPTIONS]}
              value={operation}
              onChange={(e) => setExtras({ op: e.target.value || null })}
              style={{ minWidth: '13rem' }}
            />
            {entityFilterLabel && (
              <span className="status-badge status-badge--info" style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-1)' }}>
                {entityFilterLabel}
                <button
                  type="button"
                  className="btn-link"
                  aria-label="Сбросить фильтр записи"
                  style={{ lineHeight: 1 }}
                  onClick={() => setExtras({ entity: null, entity_id: null })}
                >
                  ×
                </button>
              </span>
            )}
            <span style={{ color: 'var(--text3)', fontSize: '0.8125rem', marginLeft: 'auto' }}>
              {total} записей · все правки сохраняются с возможностью отката
            </span>
          </div>
        }
        serverPagination={{
          page,
          pageSize,
          total,
          sortBy,
          sortDir,
          filters,
          onPageChange:     setPage,
          onPageSizeChange: setPageSize,
          onSortChange:     setSort,
          onFiltersChange:  setFilters,
        }}
      />

      {openedId && (
        <ChangelogDetailModal
          contextId={openedId}
          onClose={() => setOpenedId(null)}
          onRevert={(op) => { setOpenedId(null); setReverting(op); }}
        />
      )}
      {reverting && (
        <RevertConfirmDialog op={reverting} onClose={() => setReverting(null)} />
      )}
    </>
  );
}
