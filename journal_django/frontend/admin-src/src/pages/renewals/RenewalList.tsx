import { useDeferredValue } from 'react';
import { useListSearchParams } from '../../hooks/useListSearchParams';
import { useRenewalList } from '../../hooks/useRenewals';
import { DataTable, type Column } from '../../components/table/DataTable';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import { StageBadge } from './StageBadge';
import type { RenewalFilters, RenewalListRow } from '../../lib/renewals';

// Бэкенд принимает sort_by только из этого набора (см. план 5.4/задание) —
// остальные колонки рендерятся, но без сортировки.
const SORTABLE_KEYS = new Set(['next_touch_at', 'stage_entered_at', 'cycle_no', 'student_name']);

interface Props {
  filters: RenewalFilters;
  onOpen: (id: number) => void;
}

export function RenewalList({ filters, onOpen }: Props) {
  const search = useListSearchParams({ sortBy: 'stage_entered_at', sortDir: 'desc' });
  const { page, pageSize, sortBy, sortDir, setPage, setPageSize, setSort } = search;

  // Фильтры приходят сверху (assignee/direction/overdue) — не per-column,
  // поэтому просто прокидываем их в запрос, без searchOptions в DataTable.
  const debouncedFilters = useDeferredValue(filters);

  const { data, isLoading, isFetching } = useRenewalList({
    page,
    page_size: pageSize,
    sort_by: sortBy,
    sort_dir: sortDir,
    filters: debouncedFilters,
  });

  const rows: RenewalListRow[] = data?.rows || [];
  const total = data?.total || 0;

  const columns: Column<RenewalListRow>[] = [
    {
      key: 'student_name',
      label: 'Ученик',
      sortable: SORTABLE_KEYS.has('student_name'),
      searchable: false,
      cell: (r) => r.student_name || '—',
    },
    {
      key: 'direction_name',
      label: 'Направление',
      sortable: false,
      searchable: false,
      cell: (r) => (
        <span style={r.direction_color ? { color: r.direction_color } : undefined}>
          {r.direction_name || '—'}
        </span>
      ),
    },
    {
      key: 'cycle_no',
      label: 'Цикл',
      sortable: SORTABLE_KEYS.has('cycle_no'),
      searchable: false,
      cell: (r) => `Мес. ${r.cycle_no}`,
    },
    {
      key: 'stage_label',
      label: 'Стадия',
      sortable: false,
      searchable: false,
      cell: (r) => <StageBadge label={r.stage_label} kind={r.stage_kind} />,
    },
    {
      key: 'days_in_stage',
      label: 'Дней в стадии',
      sortable: false,
      searchable: false,
      cell: (r) => `${r.days_in_stage} дн.`,
    },
    {
      key: 'next_touch_at',
      label: 'След. касание',
      sortable: SORTABLE_KEYS.has('next_touch_at'),
      searchable: false,
      cell: (r) => (r.next_touch_at ? fmtDate(r.next_touch_at) : '—'),
    },
    {
      key: 'assignee_name',
      label: 'Ответственный',
      sortable: false,
      searchable: false,
      cell: (r) => r.assignee_name || '—',
    },
  ];

  if (isLoading) return <TableSkeleton rows={6} cols={columns.length} />;

  return (
    <DataTable<RenewalListRow>
      data={rows}
      columns={columns}
      title="Продления"
      onRowClick={(row) => onOpen(row.id)}
      isLoading={isFetching}
      serverPagination={{
        page,
        pageSize,
        total,
        sortBy,
        sortDir,
        filters: {},
        onPageChange: setPage,
        onPageSizeChange: setPageSize,
        onSortChange: setSort,
        onFiltersChange: () => {}, // per-column фильтров нет — фильтры приходят пропом сверху
      }}
    />
  );
}
