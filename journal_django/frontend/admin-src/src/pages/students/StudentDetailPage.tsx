import { useState } from 'react';
import { useParams, Navigate } from 'react-router-dom';
import { useStudent } from '../../hooks/useStudents';
import { useGroupsAll } from '../../hooks/useGroups';
import { useDirections } from '../../hooks/useDirections';
import { DetailShell, type DetailField } from '../../components/detail/DetailShell';
import { StatusBadge } from '../../components/StatusBadge';
import { MembershipsBlock } from '../../components/memberships/MembershipsBlock';
import { DirTag } from '../../components/ui/DirTag';
import { PageLoading } from '../../components/ui/Skeleton';
import { fmtDate } from '../../lib/format';
import type { Student } from '../../lib/types';
import StudentFormModal from './StudentFormModal';
import StudentStatsBlock from './StudentStatsBlock';
import { StudentBalanceBlock } from './StudentBalanceBlock';
import { ConsentBlock } from './ConsentBlock';

export default function StudentDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const { data: student, isLoading } = useStudent(id);
  const { data: groups = [] } = useGroupsAll(true);
  const { data: directions = [] } = useDirections(true);
  const [editing, setEditing] = useState(false);

  if (isLoading) return <PageLoading />;
  if (!student) return <Navigate to="/admin/students" replace />;

  const initials = (() => {
    const parts = String(student.full_name || '').trim().split(/\s+/);
    return (parts.length >= 2 ? parts[0][0] + parts[1][0] : (student.full_name || '??').slice(0, 2)).toUpperCase();
  })();
  const hue = [...String(student.full_name || '')].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;

  const pills: Array<{ label: string; value: string }> = [];
  if (student.age) pills.push({ label: 'Возраст', value: `${student.age} лет` });
  if (student.school_grade) pills.push({ label: 'Класс', value: `${student.school_grade}-й` });
  if (student.phone) pills.push({ label: 'Телефон', value: student.phone });
  if (student.parent_name) pills.push({ label: 'Родитель', value: student.parent_name });

  const customHero = (
    <div className="student-hero">
      <div
        className="student-hero__avatar"
        style={{
          background: `hsl(${hue},55%,92%)`,
          borderColor: `hsl(${hue},50%,80%)`,
          color: `hsl(${hue},55%,35%)`,
        }}
      >{initials}</div>
      <div className="student-hero__info">
        <div className="student-hero__name-row">
          <h2 className="student-hero__name">{student.full_name}</h2>
          <StatusBadge row={student} />
        </div>
        {student.parent_name && (
          <div className="student-hero__sub">Родитель: {student.parent_name}</div>
        )}
        <div className="student-hero__id">id {student.id}</div>
        <div className="student-hero__actions">
          <button type="button" className="edit-btn" onClick={() => setEditing(true)}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
            Редактировать
          </button>
        </div>
      </div>
      <div className="student-hero__pills">
        {pills.map((p) => (
          <div key={p.label} className="student-pill">
            <span className="student-pill__label">{p.label}:</span>{' '}
            <span className="student-pill__value">{p.value}</span>
          </div>
        ))}
      </div>
    </div>
  );

  const fields: DetailField<Student>[] = [
    { key: 'id', label: 'ID' },
    { key: 'full_name', label: 'ФИО' },
    { key: 'birth_date', label: 'Дата рожд.', cell: (r) => fmtDate(r.birth_date) },
    { key: 'age', label: 'Возраст', cell: (r) => r.age ? `${r.age} лет` : '—' },
    { key: 'school_grade', label: 'Класс' },
    { key: 'phone', label: 'Телефон' },
    { key: 'parent_name', label: 'Родитель' },
    { key: 'platform_id', label: 'Platform ID' },
    { key: 'pm', label: 'ПМ' },
    { key: 'first_purchase_date', label: 'Первая оплата', cell: (r) => fmtDate(r.first_purchase_date) },
    { key: 'enrollment_status', label: 'Статус', cell: (r) => <StatusBadge row={r} /> },
    { key: 'created_at', label: 'Создан', cell: (r) => fmtDate(r.created_at) },
  ];

  const groupOptions = groups.map((g) => ({ value: g.id, label: g.name, disabled: !g.active }));

  return (
    <>
      <DetailShell<Student>
        title={student.full_name}
        row={student}
        fields={fields}
        cardTitle="Данные ученика"
        customHero={customHero}
        backTo="/admin/students"
      >
        <div className="sub-header">Статистика посещаемости</div>
        <StudentStatsBlock studentId={student.id} />

        <StudentBalanceBlock studentId={student.id} />

        <div className="sub-header">Согласие на обработку ПДн</div>
        <ConsentBlock
          studentId={student.id}
          initial={{
            consent_given: student.consent_given,
            consent_at: student.consent_at,
            consent_by: student.consent_by,
            consent_note: student.consent_note,
          }}
        />

        <div className="sub-header">Группы ученика</div>
        <MembershipsBlock
          config={{
            mode: 'byStudent',
            studentId: student.id,
            pickerOptions: groupOptions,
            pickerLabel: 'Выберите группу',
          }}
          emptyText="Не записан ни в одну группу"
          renderCard={(m) => {
            const g = groups.find((x) => x.id === m.group_id);
            const dir = g ? directions.find((d) => d.id === g.direction_id) : null;
            return {
              title: m.group_name || `#${m.group_id}`,
              meta: (
                <>
                  {dir && <DirTag direction={dir} />}
                  {g && !g.active && <span className="archive-tag">Архив</span>}
                </>
              ),
              navigateTo: `/admin/groups/${m.group_id}`,
            };
          }}
        />
      </DetailShell>
      {editing && (
        <StudentFormModal initial={student} onClose={() => setEditing(false)} />
      )}
    </>
  );
}
