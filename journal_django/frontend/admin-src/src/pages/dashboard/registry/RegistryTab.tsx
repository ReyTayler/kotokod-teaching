import { useDeferredValue } from 'react';
import { useListSearchParams } from '../../../hooks/useListSearchParams';
import { useRegistrySummary, useRegistryStudents } from '../../../hooks/useRegistry';
import { KpiCard } from '../KpiCard';
import { TodayStreamCard } from './TodayStreamCard';
import { SignalsCard } from './SignalsCard';
import { RegistryTable } from './RegistryTable';
import { REGISTRY_STATUS_LABELS } from '../../../lib/labels';
import type { RegistrySegment, RegistrySummary } from '../../../lib/types';

const SEGMENTS: RegistrySegment[] = ['all', 'ending', 'closed', 'idle', 'no_plan'];

const EMPTY_SIGNALS: RegistrySummary['signals'] = {
  ending: { count: 0 },
  closed: { count: 0 },
  idle: { count: 0 },
  no_plan: { count: 0 },
};

export default function RegistryTab() {
  // page/sort/поиск (f.student_name) в URL; сегмент — extra-параметр seg.
  const s = useListSearchParams({ sortBy: 'urgency', sortDir: 'asc', pageSize: 30 });
  const {
    page, pageSize, sortBy, sortDir, filters,
    setPage, setPageSize, setSort, setFilters, getExtra, setExtra,
  } = s;

  const rawSeg = getExtra('seg');
  const segment: RegistrySegment = SEGMENTS.includes(rawSeg as RegistrySegment)
    ? (rawSeg as RegistrySegment)
    : 'all';

  const search = filters['student_name'] || '';
  const debouncedSearch = useDeferredValue(search);

  const summary = useRegistrySummary();
  const students = useRegistryStudents({
    page,
    page_size: pageSize,
    sort_by: sortBy,
    sort_dir: sortDir,
    segment,
    search: debouncedSearch,
  });

  const selectSegment = (seg: RegistrySegment) => setExtra('seg', seg === 'all' ? null : seg);

  const kpis = summary.data?.kpis;
  const dash = (v: number | undefined, fmt?: (n: number) => string) =>
    v === undefined ? '—' : fmt ? fmt(v) : String(v);

  return (
    <>
      <div className="dashboard__kpis dashboard__kpis--6">
        <KpiCard
          label="Активных учеников"
          value={dash(kpis?.active_students)}
          onClick={() => selectSegment('all')}
          active={segment === 'all'}
        />
        <KpiCard
          label="На продление / апсейл"
          value={dash(kpis?.renewal_upsell)}
          hint="≤2 урока + закрытые"
          tone="warning"
        />
        <KpiCard
          label="Простой"
          value={dash(kpis?.idle)}
          hint=">14 дней без урока"
          onClick={() => selectSegment('idle')}
          active={segment === 'idle'}
        />
        <KpiCard label="Средний прогресс" value={dash(kpis?.avg_progress, (n) => `${n}%`)} tone="info" />
        <KpiCard
          label="Впереди уроков"
          value={dash(kpis?.lessons_ahead, (n) => n.toLocaleString('ru-RU'))}
          hint="сумма остатков"
        />
        <KpiCard
          label="Отмены"
          value={dash(kpis?.cancellations)}
          hint="за месяц"
          tone={kpis && kpis.cancellations > 0 ? 'warning' : 'default'}
        />
      </div>

      <div className="reg-grid">
        <TodayStreamCard items={summary.data?.today_stream || []} />
        <SignalsCard
          signals={summary.data?.signals || EMPTY_SIGNALS}
          active={segment}
          onSelect={selectSegment}
        />
      </div>

      {segment !== 'all' && (
        <div className="reg-active-filter">
          <span className="reg-active-filter__label">Фильтр:</span>
          <button
            type="button"
            className="reg-chip"
            onClick={() => selectSegment('all')}
            title="Снять фильтр"
          >
            {REGISTRY_STATUS_LABELS[segment]}
            <span className="reg-chip__x" aria-hidden>✕</span>
          </button>
        </div>
      )}

      <RegistryTable
        rows={students.data?.rows || []}
        isLoading={students.isFetching}
        serverPagination={{
          page,
          pageSize,
          total: students.data?.total || 0,
          sortBy,
          sortDir,
          filters,
          onPageChange: setPage,
          onPageSizeChange: setPageSize,
          onSortChange: setSort,
          onFiltersChange: setFilters,
        }}
      />
    </>
  );
}
