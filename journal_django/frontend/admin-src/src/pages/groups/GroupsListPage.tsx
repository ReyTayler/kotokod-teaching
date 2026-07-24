import { useDeferredValue, useMemo } from 'react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useListSearchParams } from '../../hooks/useListSearchParams';
import { useGroups } from '../../hooks/useGroups';
import { useDirections } from '../../hooks/useDirections';
import { useTeachers } from '../../hooks/useTeachers';
import { useTableColumns } from '../../hooks/useAdminSettings';
import { DataTable, type Column } from '../../components/table/DataTable';
import { Avatar } from '../../components/Avatar';
import { DirTag } from '../../components/ui/DirTag';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import { formatSlot } from '../../lib/slots';
import type { Group } from '../../lib/types';
import GroupFormModal from './GroupFormModal';
import { PageHeader } from '../../components/shell/PageHeader';

export default function GroupsListPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const navigate = useNavigate();

  // URL-синхронизированный стейт пагинации и сортировки.
  const search = useListSearchParams({ sortBy: 'name', sortDir: 'asc' });
  const { page, pageSize, sortBy, sortDir, filters, setPage, setPageSize, setSort, setFilters } = search;

  // Debounce фильтров — не гоним запрос на каждый символ.
  const debouncedFilters = useDeferredValue(filters);

  const { data, isLoading, isFetching } = useGroups({
    page,
    page_size: pageSize,
    sort_by: sortBy,
    sort_dir: sortDir,
    filters: debouncedFilters,
  });

  const rows: Group[] = data?.rows || [];
  const total = data?.total || 0;

  // Для dropdown-фильтров по direction_id и teacher_id — берём полные списки.
  const directions = useDirections(true);
  const teachers = useTeachers(true);
  const directionOptions = useMemo(
    () => (directions.data || []).slice().sort((a, b) => a.name.localeCompare(b.name))
      .map((d) => ({ value: String(d.id), label: d.name })),
    [directions.data],
  );
  const teacherOptions = useMemo(
    () => (teachers.data || []).slice().sort((a, b) => a.name.localeCompare(b.name))
      .map((t) => ({ value: String(t.id), label: t.name })),
    [teachers.data],
  );

  // Whitelist sortable/searchable строго по тому, что поддерживает бэкенд.
  // direction_id, teacher_id, is_individual, active — бэк ждёт коды/id/булевы,
  // поэтому в фильтр-шапке dropdown (searchOptions), а не текстовый input.
  const columns: Column<Group>[] = [
    {
      key: 'id',
      label: 'ID',
      sortable: false,
      searchable: false,
      cell: (r) => <span className="id-cell">#{r.id}</span>,
    },
    {
      key: 'name',
      label: 'Группа',
      sortable: true,
      searchable: true,
      cell: (r) => <div style={{ fontWeight: 600, color: 'var(--text)' }}>{r.name}</div>,
    },
    {
      key: 'direction_id',
      label: 'Направление',
      sortable: false,
      searchable: true,
      searchOptions: directionOptions,
      cell: (r) => r.direction_name
        ? <DirTag direction={{ id: r.direction_id, name: r.direction_name, color: r.direction_color ?? null, active: true, total_lessons: null, subscription_price: null }} />
        : <span className="id-cell">#{r.direction_id}</span>,
    },
    {
      key: 'teacher_id',
      label: 'Преподаватель',
      sortable: false,
      searchable: true,
      searchOptions: teacherOptions,
      cell: (r) => {
        if (!r.teacher_name) return <span className="id-cell">#{r.teacher_id}</span>;
        return (
          <div className="person-cell">
            <Avatar name={r.teacher_name} size={26} />
            <span style={{ fontSize: 14 }}>{r.teacher_name.split(' ').slice(0, 2).join(' ')}</span>
          </div>
        );
      },
    },
    {
      key: 'members_count',
      label: 'Состав группы',
      sortable: false,
      searchable: false,
      cell: (r) => (
        <span className="id-cell" title="Учеников в группе">{r.members_count ?? 0}</span>
      ),
    },
    {
      key: 'is_individual',
      label: 'Индив.',
      sortable: false,
      searchable: true,
      searchOptions: [
        { value: 'true',  label: 'да' },
        { value: 'false', label: 'нет' },
      ],
      cell: (r) => r.is_individual ? 'да' : 'нет',
    },
    {
      key: 'lesson_duration_minutes',
      label: 'Минут',
      sortable: false,
      searchable: false,
      cell: (r) => String(r.lesson_duration_minutes ?? '—'),
    },
    {
      key: 'lessons_per_week',
      label: 'В неделю',
      sortable: true,
      searchable: false,
      cell: (r) => String(r.lessons_per_week ?? '—'),
    },
    {
      key: 'group_start_date',
      label: 'Старт',
      sortable: true,
      searchable: false,
      cell: (r) => fmtDate(r.group_start_date),
    },
    {
      key: 'slots',
      label: 'Слоты',
      sortable: false,
      searchable: false,
      cell: (r) => (r.slots || []).map((s) => formatSlot(s)).join(', ') || '—',
    },
    {
      key: 'vk_chat',
      label: 'Чат ВК',
      sortable: false,
      searchable: false,
      cell: (r) => r.vk_chat || '—',
    },
    {
      key: 'active',
      label: 'Статус',
      sortable: true,
      searchable: true,
      searchOptions: [
        { value: 'true',  label: 'Активна' },
        { value: 'false', label: 'Архив' },
      ],
      cell: (r) => r.active
        ? <span className="badge badge--ok">Активна</span>
        : <span className="badge badge--muted">Архив</span>,
    },
  ];
  const visibleColumns = useTableColumns('groups', columns);

  // Шапка рисуется и во время загрузки: раньше страница возвращала
  // скелетон ДО неё, и заголовок пропадал при каждом переходе.
  const header = (
    <PageHeader
      title="Группы"
      count={isLoading ? undefined : total}
      actions={<button className="btn-add" onClick={() => setModalOpen(true)}>+ Новая</button>}
    />
  );

  if (isLoading) return <>{header}<TableSkeleton rows={6} cols={9} /></>;

  return (
    <>
      {header}
      <DataTable<Group>
        data={rows}
        columns={visibleColumns}
        title="Группы"
        onRowClick={(row) => navigate(`/admin/groups/${row.id}`)}
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
        <GroupFormModal initial={null} onClose={() => setModalOpen(false)} />
      )}
    </>
  );
}
