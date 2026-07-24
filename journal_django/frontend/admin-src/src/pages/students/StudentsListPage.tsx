import { useDeferredValue } from 'react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useListSearchParams } from '../../hooks/useListSearchParams';
import { useStudents } from '../../hooks/useStudents';
import { useRenewalAssignees } from '../../hooks/useRenewals';
import { useTableColumns } from '../../hooks/useAdminSettings';
import { DataTable, type Column } from '../../components/table/DataTable';
import { Avatar } from '../../components/Avatar';
import { StatusBadge } from '../../components/StatusBadge';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { fmtDate, fmtAge } from '../../lib/format';
import { ENROLLMENT_STATUS_OPTIONS } from '../../lib/labels';
import type { Student } from '../../lib/types';
import { PageHeader } from '../../components/shell/PageHeader';
import StudentFormModal from './StudentFormModal';

export default function StudentsListPage() {
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);

  // URL-синхронизированный стейт пагинации и сортировки.
  const search = useListSearchParams({ sortBy: 'full_name', sortDir: 'asc' });
  const { page, pageSize, sortBy, sortDir, filters, setPage, setPageSize, setSort, setFilters } = search;
  const { data: assignees } = useRenewalAssignees();

  // Debounce фильтров — не гоним запрос на каждый символ.
  const debouncedFilters = useDeferredValue(filters);

  const { data, isLoading, isFetching } = useStudents({
    page,
    page_size: pageSize,
    sort_by: sortBy,
    sort_dir: sortDir,
    filters: debouncedFilters,
  });

  const rows: Student[] = data?.rows || [];
  const total = data?.total || 0;

  // Whitelist sortable/searchable строго по тому, что поддерживает бэкенд.
  // Client-side searchable: function удалена — бэк фильтрует сам.
  const columns: Column<Student>[] = [
    {
      key: 'id',
      label: 'ID',
      sortable: false,
      searchable: false,
      cell: (r) => <span className="id-cell">#{r.id}</span>,
    },
    {
      key: 'full_name',
      label: 'Ученик',
      sortable: true,
      searchable: true,
      cell: (r) => (
        <div className="person-cell">
          <Avatar name={r.full_name} size={32} />
          <div><div className="person-name">{r.full_name}</div></div>
        </div>
      ),
    },
    {
      key: 'birth_date',
      label: 'Дата рожд.',
      sortable: false,
      searchable: false,
      cell: (r) => fmtDate(r.birth_date),
    },
    {
      // Возраст вычисляется из даты рождения (поле age удалено). Сортируем по
      // birth_date — он монотонно связан с возрастом; фильтра нет (вычисляемое
      // поле нельзя фильтровать на сервере без пересчёта в диапазон дат).
      key: 'age',
      label: 'Возраст',
      sortKey: 'birth_date',
      sortable: true,
      searchable: false,
      cell: (r) => fmtAge(r.birth_date),
    },
    {
      key: 'parent1_phone',
      label: 'Телефон родителя 1',
      sortable: false,
      searchable: true,
      cell: (r) => r.parent1_phone || '—',
    },
    {
      key: 'parent1_name',
      label: 'Родитель 1',
      sortable: false,
      searchable: true,
      cell: (r) => r.parent1_name || '—',
    },
    {
      key: 'platform_id',
      label: 'Platform ID',
      sortable: false,
      searchable: true,
      cell: (r) => r.platform_id || '—',
    },
    {
      key: 'manager_id',
      label: 'Менеджер',
      sortable: false,
      searchable: true,
      searchOptions: (assignees || []).map((a) => ({ value: String(a.id), label: a.full_name })),
      cell: (r) => r.manager_name || '—',
    },
    {
      key: 'enrollment_status',
      label: 'Статус',
      sortable: true,
      searchable: true,
      searchOptions: ENROLLMENT_STATUS_OPTIONS,
      cell: (r) => <StatusBadge row={r} />,
    },
  ];
  const visibleColumns = useTableColumns('students', columns);

  // Шапка рисуется и во время загрузки: раньше страница возвращала скелетон
  // ДО неё, и при каждом переходе между разделами заголовок пропадал и
  // появлялся заново — экран «моргал» названием.
  const header = (
    <PageHeader
      title="Ученики"
      count={isLoading ? undefined : total}
      actions={<button type="button" className="btn-add" onClick={() => setModalOpen(true)}>+ Новый</button>}
    />
  );

  if (isLoading) return <>{header}<TableSkeleton rows={6} cols={9} /></>;

  return (
    <>
      {header}
      <DataTable<Student>
        data={rows}
        columns={visibleColumns}
        title="Ученики"
        onRowClick={(row) => navigate(`/admin/students/${row.id}`)}
        isLoading={isFetching}
        serverPagination={{
          page,
          pageSize,
          total,
          sortBy,
          sortDir,
          filters,
          onPageChange: setPage,
          onPageSizeChange: setPageSize,
          onSortChange: setSort,
          onFiltersChange: setFilters,
        }}
      />
      {modalOpen && (
        <StudentFormModal
          initial={null}
          onClose={() => setModalOpen(false)}
        />
      )}
    </>
  );
}
