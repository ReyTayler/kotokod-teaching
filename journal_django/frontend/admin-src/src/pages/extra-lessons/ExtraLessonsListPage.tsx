import { useDeferredValue, useState } from 'react';
import { useListSearchParams } from '../../hooks/useListSearchParams';
import { useExtraLessons, useExtraLessonMutations } from '../../hooks/useExtraLessons';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { DataTable, type Column } from '../../components/table/DataTable';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { AssignExtraLessonModal } from '../../components/lessons/AssignExtraLessonModal';
import { ManualExtraLessonModal } from '../../components/lessons/ManualExtraLessonModal';
import { fmtDate } from '../../lib/format';
import type { AbsenceResolution } from '../../lib/types';
import { PageHeader } from '../../components/shell/PageHeader';

const STATUS_LABELS: Record<string, string> = {
  pending: 'Ждёт решения',
  makeup_scheduled: 'Назначен',
  makeup_done: 'Проведён',
  burned: 'Сгорел',
  // Действие «закрыть без денег» снято, но статус остаётся: в БД есть старые
  // waived-записи, которые надо отображать и фильтровать. Новых не создать.
  waived: 'Закрыт без денег',
};

const STATUS_OPTIONS = Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }));

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
  // pending → назначить доп.урок (модалка); makeup_scheduled → отмена (сразу,
  // возврат в «ждёт решения»); makeup_done → откат факта (разрушительно —
  // откатывает Payroll/посещаемость исходного урока), поэтому по подтверждению.
  const [assigning, setAssigning] = useState<AbsenceResolution | null>(null);
  // Ручной доп.урок сверх курса (kind='extra') — открывается кнопкой в шапке.
  const [manualOpen, setManualOpen] = useState(false);
  const [confirmingRollbackId, setConfirmingRollbackId] = useState<number | null>(null);
  const [confirmingBurnId, setConfirmingBurnId] = useState<number | null>(null);

  const rows: AbsenceResolution[] = data?.rows || [];
  const total = data?.total || 0;

  const handleCancel = async (id: number) => {
    try {
      await muts.cancel.mutateAsync(id);
      toast('Назначение отменено, пропуск снова ждёт решения', 'ok');
    } catch (err) { showError(err); }
  };

  const handleRollback = async (id: number) => {
    if (confirmingRollbackId !== id) {
      setConfirmingRollbackId(id);
      return;
    }
    try {
      // remove = DELETE /extra-lessons/:id — на бэке (1c-2) откатывает и
      // проведённый доп.урок (makeup_done), и сгорание (burned).
      await muts.remove.mutateAsync(id);
      toast('Факт удалён, пропуск снова ждёт решения', 'ok');
    } catch (err) { showError(err); }
    setConfirmingRollbackId(null);
  };

  const handleBurn = async (id: number) => {
    if (confirmingBurnId !== id) {
      setConfirmingBurnId(id);
      return;
    }
    try {
      await muts.burn.mutateAsync(id);
      toast('Пропуск сожжён, урок списан с баланса', 'ok');
    } catch (err) { showError(err); }
    setConfirmingBurnId(null);
  };

  const columns: Column<AbsenceResolution>[] = [
    { key: 'scheduled_date', label: 'Дата доп.урока', sortable: true, searchable: false, cell: (r) => (r.scheduled_date ? fmtDate(r.scheduled_date) : '—') },
    {
      key: 'missed_lesson_group_name', label: 'Группа', sortable: false, searchable: true,
      cell: (r) => r.resolution_group_name || r.missed_lesson_group_name || '—',
    },
    {
      key: 'missed_lesson', label: 'За какой урок', sortable: false, searchable: false,
      cell: (r) => {
        // extra (сверх курса): пропуска нет — показываем выбранный номер (или «—»)
        // с пометкой «доп.»; makeup — номер+дата пропущенного урока.
        if (r.kind === 'extra') {
          return r.target_lesson_number != null
            ? `Урок №${Number(r.target_lesson_number)} · доп.`
            : 'Доп.урок сверх курса';
        }
        return `Урок №${Number(r.missed_lesson_number)} · ${fmtDate(r.missed_lesson_date ?? '')}`;
      },
    },
    { key: 'teacher_name', label: 'Преподаватель', sortable: true, searchable: false, cell: (r) => r.teacher_name || '—' },
    { key: 'student_name', label: 'Ученик', sortable: true, searchable: true },
    {
      key: 'status', label: 'Статус', sortable: true, searchable: true,
      searchOptions: STATUS_OPTIONS,
      cell: (r) => STATUS_LABELS[r.status] || r.status,
    },
    {
      key: 'actions', label: '', sortable: false, searchable: false,
      cell: (r) => {
        if (r.status === 'pending') {
          const burning = confirmingBurnId === r.id;
          return (
            <div className="table-actions">
              <button type="button" className="btn-primary" onClick={() => setAssigning(r)}>
                Назначить
              </button>
              <button
                type="button"
                className={`btn-delete${burning ? ' is-confirming' : ''}`}
                onClick={() => { void handleBurn(r.id); }}
              >
                {burning ? 'Точно сжечь?' : 'Сжечь'}
              </button>
            </div>
          );
        }
        if (r.status === 'makeup_scheduled') {
          return (
            <button type="button" className="btn-secondary" onClick={() => { void handleCancel(r.id); }}>
              Отменить
            </button>
          );
        }
        if (r.status === 'makeup_done') {
          const confirming = confirmingRollbackId === r.id;
          return (
            <button
              type="button"
              className={`btn-delete${confirming ? ' is-confirming' : ''}`}
              onClick={() => { void handleRollback(r.id); }}
            >
              {confirming ? 'Точно откатить?' : 'Откатить'}
            </button>
          );
        }
        if (r.status === 'burned') {
          const confirming = confirmingRollbackId === r.id;
          return (
            <button
              type="button"
              className={`btn-delete${confirming ? ' is-confirming' : ''}`}
              onClick={() => { void handleRollback(r.id); }}
            >
              {confirming ? 'Точно откатить?' : 'Откат сгорания'}
            </button>
          );
        }
        return null;
      },
    },
  ];

  // Шапка рисуется и во время загрузки: раньше страница возвращала
  // скелетон ДО неё, и заголовок пропадал при каждом переходе.
  const header = (
    <PageHeader
      title="Доп.уроки"
      count={isLoading ? undefined : total}
      sub="Незакрытые пропуски: назначить отработку или сжечь урок."
      actions={
        <button type="button" className="btn-add" onClick={() => setManualOpen(true)}>
          + Назначить вручную
        </button>
      }
    />
  );

  if (isLoading) return <>{header}<TableSkeleton rows={8} cols={columns.length} /></>;

  return (
    <>
      {header}
      <DataTable<AbsenceResolution>
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
      {assigning && assigning.missed_lesson_id != null && (
        <AssignExtraLessonModal
          missedLessonId={assigning.missed_lesson_id}
          candidates={[{ student_id: assigning.student_id, student_name: assigning.student_name }]}
          defaultTeacherId={assigning.assigned_teacher_id ?? 0}
          onClose={() => setAssigning(null)}
        />
      )}
      {manualOpen && <ManualExtraLessonModal onClose={() => setManualOpen(false)} />}
    </>
  );
}
