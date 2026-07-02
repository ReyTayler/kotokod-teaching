import { useState } from 'react';
import { useParams, Navigate, useNavigate } from 'react-router-dom';
import { useGroup, useGroupMutations } from '../../hooks/useGroups';
import { useTeachers } from '../../hooks/useTeachers';
import { useDirections } from '../../hooks/useDirections';
import { DetailShell, type DetailField } from '../../components/detail/DetailShell';
import { Avatar } from '../../components/Avatar';
import { DirTag } from '../../components/ui/DirTag';
import { EntityLink } from '../../components/EntityLink';
import { PageLoading } from '../../components/ui/Skeleton';
import { LessonGrid } from '../../components/lessons/LessonGrid';
import { LessonEditor } from '../../components/lessons/LessonEditor';
import { directionColor } from '../../lib/direction-color';
import { fmtDate } from '../../lib/format';
import { formatSlot } from '../../lib/slots';
import { useToast } from '../../components/ui/Toast';
import { useApiError } from '../../hooks/useApiError';
import type { Group } from '../../lib/types';
import GroupFormModal from './GroupFormModal';
import GroupMembersBlock from './GroupMembersBlock';
import GroupScheduleBlock from './GroupScheduleBlock';

export default function GroupDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const navigate = useNavigate();
  const { data: group, isLoading } = useGroup(id);
  const { data: teachers = [] } = useTeachers(true);
  const { data: directions = [] } = useDirections(true);
  const muts = useGroupMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<{ slot: number; lessonId: number | null } | null>(null);

  if (isLoading) return <PageLoading />;
  if (!group) return <Navigate to="/admin/groups" replace />;

  const direction = directions.find((d) => d.id === group.direction_id) || null;
  const teacher = teachers.find((t) => t.id === group.teacher_id) || null;
  const color = directionColor(direction);

  const fields: DetailField<Group>[] = [
    { key: 'id', label: 'ID' },
    { key: 'name', label: 'Название' },
    { key: 'direction_id', label: 'Направление',
      cell: () => direction ? <DirTag direction={direction} /> : <>#{group.direction_id}</> },
    { key: 'teacher_id', label: 'Преподаватель',
      cell: () => <EntityLink section="teachers" id={group.teacher_id} text={teacher?.name || `#${group.teacher_id}`} /> },
    { key: 'is_individual', label: 'Индивидуальная', cell: (r) => r.is_individual ? 'да' : 'нет' },
    { key: 'lesson_duration_minutes', label: 'Длительность урока', cell: (r) => `${r.lesson_duration_minutes} мин` },
    { key: 'lessons_per_week', label: 'Уроков в неделю' },
    { key: 'group_start_date', label: 'Дата старта', cell: (r) => fmtDate(r.group_start_date) },
    { key: 'slots', label: 'Расписание', cell: (r) => (r.slots || []).map(formatSlot).join(', ') || '—' },
    { key: 'vk_chat', label: 'Чат ВК' },
    { key: 'active', label: 'Статус', cell: (r) => r.active ? 'Активна' : 'Архив' },
    { key: 'created_at', label: 'Создана', cell: (r) => fmtDate(r.created_at) },
  ];

  const handleDelete = async () => {
    try {
      await muts.remove.mutateAsync(group.id);
      toast('Архивировано', 'ok');
      navigate('/admin/groups');
    } catch (err) { showError(err); }
  };

  return (
    <>
      <DetailShell<Group>
        title={`Группа ${group.name}`}
        subtitle={`#${group.id} · ${group.is_individual ? 'Индивидуальная' : 'Групповая'} · ${group.lesson_duration_minutes} мин`}
        row={group}
        fields={fields}
        cardTitle="Данные группы"
        onEdit={() => setEditing(true)}
        onDelete={handleDelete}
        backTo="/admin/groups"
      >
        {teacher && (
          <div className="teacher-info-card">
            <Avatar name={teacher.name} size={42} />
            <div>
              <div style={{ fontSize: 13, color: 'var(--text3)', marginBottom: 3 }}>Преподаватель</div>
              <div style={{ fontWeight: 700, color: 'var(--text)' }}>{teacher.name}</div>
              {teacher.email && <div style={{ fontSize: 14, color: 'var(--text3)' }}>{teacher.email}</div>}
            </div>
          </div>
        )}

        <div className="detail__section">
          <h3 className="detail__section-title">Уроки группы</h3>
          <div className="lesson-grid-hint">
            Серые — не проведены, цветные — проведены. Клик по любому квадрату — открыть/создать.
          </div>
          <LessonGrid
            group={group}
            selectedSlot={selected?.slot ?? null}
            onSelectSlot={(slot, lessonId) => setSelected({ slot, lessonId })}
          />
          {selected && (
            <LessonEditor
              group={group}
              slot={selected.slot}
              lessonId={selected.lessonId}
              color={color}
              onClose={() => setSelected(null)}
            />
          )}
        </div>

        <div className="sub-header">Ученики группы</div>
        <GroupMembersBlock group={group} />

        <div className="sub-header">Расписание</div>
        <GroupScheduleBlock groupId={group.id} />
      </DetailShell>
      {editing && (
        <GroupFormModal initial={group} onClose={() => setEditing(false)} />
      )}
    </>
  );
}
