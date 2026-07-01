import { useState } from 'react';
import { useParams, Navigate, useNavigate } from 'react-router-dom';
import { useTokens, useTokenMutations } from '../../hooks/useTokens';
import { useTeachers } from '../../hooks/useTeachers';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { DetailShell, type DetailField } from '../../components/detail/DetailShell';
import { EntityLink } from '../../components/EntityLink';
import { PageLoading } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import type { Token } from '../../lib/types';
import TokenFormModal from './TokenFormModal';

export default function TokenDetailPage() {
  const params = useParams();
  const tokenStr = params.id || '';
  const navigate = useNavigate();
  const { data: tokens = [], isLoading } = useTokens(true);
  const { data: teachers = [] } = useTeachers(true);
  const muts = useTokenMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [editing, setEditing] = useState(false);

  if (isLoading) return <PageLoading />;
  const token = tokens.find((t) => t.token === tokenStr);
  if (!token) return <Navigate to="/admin/tokens" replace />;

  const teacher = teachers.find((t) => t.id === token.teacher_id);
  const teacherName = token.teacher_name || teacher?.name || '';

  const fields: DetailField<Token>[] = [
    { key: 'token', label: 'Токен' },
    { key: 'teacher_id', label: 'ID преподавателя' },
    { key: 'teacher_name', label: 'Преподаватель',
      cell: () => <EntityLink section="teachers" id={token.teacher_id} text={teacherName} /> },
    { key: 'active', label: 'Статус', cell: (r) => r.active ? 'Активен' : 'Отозван' },
    { key: 'created_at', label: 'Создан', cell: (r) => fmtDate(r.created_at) },
  ];

  const handleDelete = async () => {
    try {
      await muts.remove.mutateAsync(token.token);
      toast('Отозвано', 'ok');
      navigate('/admin/tokens');
    } catch (err) { showError(err); }
  };

  return (
    <>
      <DetailShell<Token>
        title={token.token}
        subtitle={`Преподаватель: ${teacherName || `#${token.teacher_id}`}`}
        row={token}
        fields={fields}
        cardTitle="Данные токена"
        onEdit={() => setEditing(true)}
        onDelete={handleDelete}
        deleteLabel="Отозвать"
        backTo="/admin/tokens"
      />
      {editing && (
        <TokenFormModal initial={token} onClose={() => setEditing(false)} />
      )}
    </>
  );
}
