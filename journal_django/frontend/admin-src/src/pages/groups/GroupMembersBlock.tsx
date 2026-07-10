import { useStudentsAll } from '../../hooks/useStudents';
import { MembershipsBlock } from '../../components/memberships/MembershipsBlock';
import { StatusBadge } from '../../components/StatusBadge';
import type { Group } from '../../lib/types';

export default function GroupMembersBlock({ group }: { group: Group }) {
  const { data: students = [] } = useStudentsAll();
  const studentOptions = students
    .filter((s) => s.enrollment_status !== 'not_enrolled')
    .map((s) => ({ value: s.id, label: s.full_name }));

  return (
    <MembershipsBlock
      config={{
        mode: 'byGroup',
        groupId: group.id,
        pickerOptions: studentOptions,
        pickerLabel: 'Выберите ученика',
        // Индивидуальная группа — строго один ученик.
        capacity: group.is_individual ? 1 : undefined,
        capacityNote: group.is_individual ? 'Индивидуальная группа — только один ученик' : undefined,
      }}
      emptyText="В группе нет учеников"
      renderCard={(m) => {
        const s = students.find((x) => x.id === m.student_id);
        return {
          title: m.student_name || (s ? s.full_name : `#${m.student_id}`),
          meta: s ? (
            <>
              {s.age && <span className="link-card-meta-pill">{s.age} лет</span>}
              <StatusBadge row={s} />
            </>
          ) : null,
          navigateTo: `/admin/students/${m.student_id}`,
        };
      }}
    />
  );
}
