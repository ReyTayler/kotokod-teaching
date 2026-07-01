import { useState } from 'react';
import { useParams, Navigate, useNavigate } from 'react-router-dom';
import { useTeacher, useTeacherMutations } from '../../hooks/useTeachers';
import { useTokens } from '../../hooks/useTokens';
import { useGroupsAll } from '../../hooks/useGroups';
import { useDirections } from '../../hooks/useDirections';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { DetailShell, type DetailField } from '../../components/detail/DetailShell';
import { EntityLink } from '../../components/EntityLink';
import { MonoBadge } from '../../components/ui/MonoBadge';
import { DirTag } from '../../components/ui/DirTag';
import { PageLoading } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import type { Teacher } from '../../lib/types';
import TeacherFormModal from './TeacherFormModal';

export default function TeacherDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const navigate = useNavigate();
  const { data: teacher, isLoading } = useTeacher(id);
  const { data: tokens = [] } = useTokens(true);
  const { data: groups = [] } = useGroupsAll(true);
  const { data: directions = [] } = useDirections(true);
  const muts = useTeacherMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [editing, setEditing] = useState(false);

  if (isLoading) return <PageLoading />;
  if (!teacher) return <Navigate to="/admin/teachers" replace />;

  const myTokens = tokens.filter((t) => t.teacher_id === teacher.id);
  const myGroups = groups.filter((g) => g.teacher_id === teacher.id);

  const fields: DetailField<Teacher>[] = [
    { key: 'id', label: 'ID' },
    { key: 'email', label: 'Email' },
    { key: 'phone', label: 'Телефон' },
    { key: 'active', label: 'Статус', cell: (r) => r.active ? 'Активен' : 'Архив' },
    { key: 'created_at', label: 'Добавлен', cell: (r) => fmtDate(r.created_at) },
  ];

  const handleDelete = async () => {
    try {
      await muts.remove.mutateAsync(teacher.id);
      toast('Архивировано', 'ok');
      navigate('/admin/teachers');
    } catch (err) { showError(err); }
  };

  return (
    <>
      <DetailShell<Teacher>
        title={teacher.name}
        subtitle={`${teacher.email || ''}${teacher.email && teacher.phone ? ' · ' : ''}${teacher.phone || ''}`}
        row={teacher}
        fields={fields}
        cardTitle="Данные преподавателя"
        onEdit={() => setEditing(true)}
        onDelete={handleDelete}
        backTo="/admin/teachers"
      >
        <div className="sub-header">Токены <span className="count-badge">{myTokens.length}</span></div>
        {myTokens.length === 0 ? (
          <div className="memberships__empty">Нет токенов</div>
        ) : myTokens.map((tk) => (
          <div key={tk.token} className="token-row">
            <EntityLink section="tokens" id={tk.token} text={tk.token} />
            <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: 'var(--text3)' }}>{fmtDate(tk.created_at)}</span>
              <MonoBadge value={tk.active ? 'Активен' : 'Отозван'} active={tk.active} />
            </div>
          </div>
        ))}

        <div className="sub-header">Группы <span className="count-badge">{myGroups.length}</span></div>
        {myGroups.length === 0 ? (
          <div className="memberships__empty">Нет групп</div>
        ) : myGroups.map((g) => {
          const dir = directions.find((d) => d.id === g.direction_id);
          return (
            <div
              key={g.id}
              className="link-card"
              tabIndex={0}
              role="button"
              onClick={() => navigate(`/admin/groups/${g.id}`)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(`/admin/groups/${g.id}`); } }}
            >
              <div className="link-card-head">
                <div>
                  <div className="link-card-title">{g.name}</div>
                  <div className="link-card-meta">
                    {dir && <DirTag direction={dir} />}
                    {!g.active && <span className="archive-tag">Архив</span>}
                  </div>
                </div>
                <span style={{ fontSize: 13, color: 'var(--text3)' }}>#{g.id}</span>
              </div>
            </div>
          );
        })}
      </DetailShell>
      {editing && (
        <TeacherFormModal initial={teacher} onClose={() => setEditing(false)} />
      )}
    </>
  );
}
