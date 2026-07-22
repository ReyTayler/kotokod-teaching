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
import { fmtDate } from '../../lib/format';
import { ENROLLMENT_STATUS_OPTIONS } from '../../lib/labels';
import type { Student } from '../../lib/types';
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
      key: 'age',
      label: 'Возраст',
      sortable: true,
      searchable: true,
      cell: (r) => r.age ? `${r.age} лет` : '—',
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
      key: 'first_purchase_date',
      label: 'Первая оплата',
      sortable: true,
      searchable: false,
      cell: (r) => fmtDate(r.first_purchase_date),
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

  if (isLoading) return <TableSkeleton rows={6} cols={9} />;

  return (
    <>
      <DataTable<Student>
        data={rows}
        columns={visibleColumns}
        title="Ученики"
        onRowClick={(row) => navigate(`/admin/students/${row.id}`)}
        headerActions={<button className="btn-add" onClick={() => setModalOpen(true)}>+ Новый</button>}
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
