import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTeachers } from '../../hooks/useTeachers';
import { useGroupsAll } from '../../hooks/useGroups';
import { useTableColumns } from '../../hooks/useAdminSettings';
import { DataTable, type Column } from '../../components/table/DataTable';
import { Avatar } from '../../components/Avatar';
import { Pill } from '../../components/ui/Pill';
import { TableSkeleton } from '../../components/ui/Skeleton';
import type { Teacher } from '../../lib/types';
import TeacherFormModal from './TeacherFormModal';

export default function TeachersListPage() {
  const { data, isLoading } = useTeachers();
  const { data: groups = [] } = useGroupsAll(true);
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);

  const rows: Teacher[] = data || [];

  const columns: Column<Teacher>[] = [
    { key: 'id', label: 'ID', cell: (r) => <span className="id-cell">#{r.id}</span> },
    { key: 'name', label: 'Преподаватель', searchable: true,
      cell: (r) => (
        <div className="person-cell">
          <Avatar name={r.name} size={34} />
          <div><div className="person-name">{r.name}</div></div>
        </div>
      ) },
    { key: 'email', label: 'Email', searchable: true, cell: (r) => r.email || '—' },
    { key: 'phone', label: 'Телефон', searchable: true, cell: (r) => r.phone || '—' },
    { key: 'groups_count', label: 'Групп',
      cell: (r) => {
        const cnt = groups.filter((g) => g.teacher_id === r.id && g.active).length;
        return <Pill>{cnt}</Pill>;
      }},
    { key: 'active', label: 'Статус',
      cell: (r) => r.active
        ? <span className="badge badge--ok">Активен</span>
        : <span className="badge badge--muted">Архив</span> },
  ];
  const visibleColumns = useTableColumns('teachers', columns);

  if (isLoading) return <TableSkeleton rows={6} cols={7} />;

  return (
    <>
      <DataTable<Teacher>
        data={rows}
        columns={visibleColumns}
        title="Преподаватели"
        onRowClick={(row) => navigate(`/admin/teachers/${row.id}`)}
        headerActions={<button className="btn-add" onClick={() => setModalOpen(true)}>+ Новый</button>}
      />
      {modalOpen && (
        <TeacherFormModal initial={null} onClose={() => setModalOpen(false)} />
      )}
    </>
  );
}
