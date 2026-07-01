import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTokens } from '../../hooks/useTokens';
import { useTeachers } from '../../hooks/useTeachers';
import { useTableColumns } from '../../hooks/useAdminSettings';
import { DataTable, type Column } from '../../components/table/DataTable';
import { Avatar } from '../../components/Avatar';
import { EntityLink } from '../../components/EntityLink';
import { MonoBadge } from '../../components/ui/MonoBadge';
import { TableSkeleton } from '../../components/ui/Skeleton';
import type { Token } from '../../lib/types';
import TokenFormModal from './TokenFormModal';

export default function TokensListPage() {
  const { data, isLoading } = useTokens();
  const { data: teachers = [] } = useTeachers(true);
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);

  const rows: Token[] = data || [];

  const columns: Column<Token>[] = [
    { key: 'token', label: 'Токен', searchable: true,
      cell: (r) => <MonoBadge value={r.token} active={r.active} /> },
    { key: 'teacher_id', label: 'Препод-ID', cell: (r) => `#${r.teacher_id}` },
    { key: 'teacher_name', label: 'Преподаватель', searchable: true,
      cell: (r) => {
        const t = teachers.find((x) => x.id === r.teacher_id);
        const name = r.teacher_name || t?.name || '';
        if (!name) return '—';
        return (
          <div className="person-cell">
            <Avatar name={name} size={26} />
            <EntityLink section="teachers" id={r.teacher_id} text={name} />
          </div>
        );
      }},
    { key: 'active', label: 'Статус',
      cell: (r) => r.active
        ? <span className="badge badge--ok">Активен</span>
        : <span className="badge badge--muted">Отозван</span> },
  ];
  const visibleColumns = useTableColumns('tokens', columns);

  if (isLoading) return <TableSkeleton rows={6} cols={4} />;

  return (
    <>
      <DataTable<Token>
        data={rows}
        columns={visibleColumns}
        title="Токены доступа"
        onRowClick={(row) => navigate(`/admin/tokens/${encodeURIComponent(row.token)}`)}
        headerActions={<button className="btn-add" onClick={() => setModalOpen(true)}>+ Новый</button>}
      />
      {modalOpen && (
        <TokenFormModal initial={null} onClose={() => setModalOpen(false)} />
      )}
    </>
  );
}
