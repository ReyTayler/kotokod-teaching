import { useMemo, useState, useCallback } from 'react';
import { useAuth } from '@shared/hooks/useAuth';
import { Field } from '@shared/components/form/Field';
import { Combobox } from '@shared/components/form/Combobox';
import { useTeacherData, useAllData } from '../../hooks/useTeacherData';
import { useGroupDirections } from '../../hooks/useGroupDirections';
import { subjectColor, resolveDirectionColor } from '../../lib/subjects';
import { LessonForm } from '../../components/lessons/LessonForm';
import { GroupCard } from './GroupCard';
import type { GroupData } from '../../lib/types';

type Tab = 'mine' | 'sub';

interface ActiveLesson {
  group: string;
  data: GroupData;
  isSubstitution?: boolean;
  originalTeacher?: string;
}

/** Мои группы — справочник групп/индивов + запись урока + замена (Фаза 2). */
export default function GroupsPage() {
  const { me } = useAuth();
  const [tab, setTab] = useState<Tab>('mine');
  const [subTeacher, setSubTeacher] = useState('');
  const [active, setActive] = useState<ActiveLesson | null>(null);

  const mineQuery = useTeacherData();
  const allQuery = useAllData(tab === 'sub');
  const { data: dirData } = useGroupDirections();
  const dirMap = useMemo(() => dirData?.groups ?? {}, [dirData]);

  /** Точный цвет направления по карте; фолбэк — эвристика по имени группы (см. GroupCard раньше). */
  const colorOf = useCallback((name: string, data: GroupData): string => {
    const dir = dirMap[name];
    if (dir) return resolveDirectionColor(dir.color, dir.direction ?? name);
    return subjectColor({ group: name, isGroup: data.isGroup });
  }, [dirMap]);

  const teacherOptions = useMemo(() => {
    const data = allQuery.data?.data ?? {};
    return Object.keys(data)
      .filter((t) => t !== me?.name)
      .sort((a, b) => a.localeCompare(b, 'ru'))
      .map((t) => ({ value: t, label: t }));
  }, [allQuery.data, me]);

  const subGroups = subTeacher ? allQuery.data?.data?.[subTeacher] ?? {} : null;

  return (
    <div className="grp-page">
      <div className="cal-head">
        <div className="cal-title">Мои группы</div>
        <div className="cal-toolbar">
          <div className="seg">
            <button className={`seg-btn${tab === 'mine' ? ' active' : ''}`} onClick={() => setTab('mine')}>
              Мои занятия
            </button>
            <button className={`seg-btn${tab === 'sub' ? ' active' : ''}`} onClick={() => setTab('sub')}>
              Замена
            </button>
          </div>
        </div>
      </div>

      {tab === 'mine' ? (
        mineQuery.isLoading ? (
          <div className="cal-skel" />
        ) : mineQuery.isError ? (
          <div className="cal-error">Не удалось загрузить группы. Попробуйте обновить страницу.</div>
        ) : Object.keys(mineQuery.data?.data ?? {}).length === 0 ? (
          <div className="cal-empty">Группы не найдены.</div>
        ) : (
          <div className="grp-grid">
            {Object.entries(mineQuery.data!.data).map(([name, data]) => (
              <GroupCard
                key={name}
                name={name}
                data={data}
                color={colorOf(name, data)}
                limit={dirMap[name]?.totalLessons}
                onSubmit={() => setActive({ group: name, data })}
              />
            ))}
          </div>
        )
      ) : (
        <div className="grp-sub">
          <Field label="Преподаватель, за которого замена">
            <Combobox
              value={subTeacher}
              onChange={setSubTeacher}
              options={teacherOptions}
              placeholder="Выберите преподавателя"
            />
          </Field>

          {allQuery.isLoading ? (
            <div className="cal-skel" />
          ) : allQuery.isError ? (
            <div className="cal-error">Не удалось загрузить группы других преподавателей.</div>
          ) : !subTeacher ? (
            <div className="cal-empty">Выберите преподавателя, чтобы увидеть его группы.</div>
          ) : Object.keys(subGroups ?? {}).length === 0 ? (
            <div className="cal-empty">У этого преподавателя нет групп.</div>
          ) : (
            <div className="grp-grid">
              {Object.entries(subGroups!).map(([name, data]) => (
                <GroupCard
                  key={name}
                  name={name}
                  data={data}
                  color={colorOf(name, data)}
                  limit={dirMap[name]?.totalLessons}
                  onSubmit={() => setActive({ group: name, data, isSubstitution: true, originalTeacher: subTeacher })}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {active && (
        <LessonForm
          group={active.group}
          groupData={active.data}
          isSubstitution={active.isSubstitution}
          originalTeacher={active.originalTeacher}
          onClose={() => setActive(null)}
        />
      )}
    </div>
  );
}
