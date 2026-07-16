import { useDeferredValue, useState } from 'react';
import { useListSearchParams } from '../../hooks/useListSearchParams';
import { useExtraLessons, useExtraLessonMutations } from '../../hooks/useExtraLessons';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { DataTable, type Column } from '../../components/table/DataTable';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import type { ExtraLessonAssignment } from '../../lib/types';

const STATUS_LABELS: Record<string, string> = {
  scheduled: 'Запланирован',
  done: 'Проведён',
  cancelled: 'Отменён',
};

export default function ExtraLessonsListPage() {
  const search = useListSearchParams({ sortBy: 'scheduled_date', sortDir: 'desc' });
  const { page, pageSize, sortBy, sortDir, filters, setPage, setPageSize, setSort, setFilters } = search;
  const debouncedFilters = useDeferredValue(filters);

  const { data, isLoading, isFetching } = useExtraLessons({
    page, page_size: pageSize, sort_by: sortBy, sort_dir: sortDir, filters: debouncedFilters,
  });
  const muts = useExtraLessonMutations();
  const showError = useApiError();
  const { toast } = useToast();
  // Отмена (scheduled) — сразу; удаление факта (done) — разрушительно (откатывает
  // Payroll/посещаемость исходного урока), поэтому по клику подтверждения.
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<number | null>(null);

  const rows: ExtraLessonAssignment[] = data?.rows || [];
  const total = data?.total || 0;

  const handleCancel = async (id: number) => {
    try {
      await muts.cancel.mutateAsync(id);
      toast('Доп.урок отменён', 'ok');
    } catch (err) { showError(err); }
  };

  const handleDelete = async (id: number) => {
    if (confirmingDeleteId !== id) {
      setConfirmingDeleteId(id);
      return;
    }
    try {
      await muts.remove.mutateAsync(id);
      toast('Факт доп.урока удалён, назначение возвращено в «Запланирован»', 'ok');
    } catch (err) { showError(err); }
    setConfirmingDeleteId(null);
  };

  const columns: Column<ExtraLessonAssignment>[] = [
    { key: 'scheduled_date', label: 'Дата', sortable: true, searchable: false, cell: (r) => fmtDate(r.scheduled_date) },
    { key: 'missed_lesson_group_name', label: 'Группа (пропуск)', sortable: false, searchable: false },
    { key: 'teacher_name', label: 'Преподаватель', sortable: true, searchable: false },
    {
      key: 'participants', label: 'Ученики', sortable: false, searchable: false,
      cell: (r) => r.participants.map((p) => p.student_name).join(', '),
    },
    { key: 'status', label: 'Статус', sortable: true, searchable: false, cell: (r) => STATUS_LABELS[r.status] || r.status },
    {
      key: 'actions', label: '', sortable: false, searchable: false,
      cell: (r) => {
        if (r.status === 'scheduled') {
          return (
            <button type="button" className="btn-secondary" onClick={() => { void handleCancel(r.id); }}>
              Отменить
            </button>
          );
        }
        if (r.status === 'done') {
          const confirming = confirmingDeleteId === r.id;
          return (
            <button
              type="button"
              className={`btn-delete${confirming ? ' is-confirming' : ''}`}
              onClick={() => { void handleDelete(r.id); }}
            >
              {confirming ? 'Точно удалить?' : 'Удалить'}
            </button>
          );
        }
        return null;
      },
    },
  ];

  if (isLoading) return <TableSkeleton rows={8} cols={columns.length} />;

  return (
    <DataTable<ExtraLessonAssignment>
      data={rows}
      columns={columns}
      title="Доп.уроки"
      isLoading={isFetching}
      serverPagination={{
        page, pageSize, total, sortBy, sortDir, filters,
        onPageChange: setPage, onPageSizeChange: setPageSize,
        onSortChange: setSort, onFiltersChange: setFilters,
      }}
    />
  );
}
