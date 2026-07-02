import { useCallback, useMemo, useState } from 'react';
import { useCalendar } from '../../hooks/useCalendar';
import { useTeacherData } from '../../hooks/useTeacherData';
import { resolveDirectionColor } from '../../lib/subjects';
import { todayMsk, isoDate, dayMonth, columnIndexOfIsoDate } from '../../lib/dates';
import { StatusPill } from '../../components/ui/StatusPill';
import { LessonForm } from '../../components/lessons/LessonForm';
import { LessonPopup } from '../calendar/LessonPopup';
import type { GroupData, Occurrence } from '../../lib/types';

const DAY_FULL = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];

type Selection =
  | { kind: 'form'; group: string; data: GroupData }
  | { kind: 'popup'; lesson: Occurrence };

/**
 * Мои уроки — занятия, запланированные на СЕГОДНЯ у текущего преподавателя.
 * Источник — GET /api/calendar с окном ровно из одного дня (from=to=сегодня
 * по МСК), уже скоуплен на сервере на текущего преподавателя. Клик по
 * строке: если группа есть среди текущих групп преподавателя (useTeacherData)
 * — открывает форму записи урока, иначе — read-only попап (например, урок
 * подмены или у группы, которую он больше не ведёт).
 */
export default function MyLessonsPage() {
  const today = useMemo(() => todayMsk(), []);
  const todayIso = useMemo(() => isoDate(today), [today]);
  const todayCol = useMemo(() => columnIndexOfIsoDate(todayIso), [todayIso]);

  const [selection, setSelection] = useState<Selection | null>(null);

  const { data, isLoading, isError, isFetching } = useCalendar(todayIso, todayIso);
  const teacherData = useTeacherData();

  const colorOf = useCallback(
    (occ: Occurrence): string => resolveDirectionColor(occ.color, occ.direction ?? occ.group),
    [],
  );

  const todayLessons = useMemo(() => {
    const rows = data?.occurrences ?? [];
    return [...rows].sort((a, b) => (a.time ?? '99:99').localeCompare(b.time ?? '99:99'));
  }, [data]);

  const handleSelect = useCallback((occ: Occurrence) => {
    const groupData = teacherData.data?.data?.[occ.group];
    if (groupData) setSelection({ kind: 'form', group: occ.group, data: groupData });
    else setSelection({ kind: 'popup', lesson: occ });
  }, [teacherData.data]);

  return (
    <div className="ml-page">
      <div className="cal-head">
        <div>
          <div className="cal-title">Мои уроки</div>
          <div className="ml-subtitle">Сегодня, {DAY_FULL[todayCol]} · {dayMonth(today)}</div>
        </div>
        {isFetching && <span className="ml-updating">обновление…</span>}
      </div>

      {isLoading ? (
        <div className="cal-skel" style={{ height: 320 }} />
      ) : isError ? (
        <div className="cal-error">Не удалось загрузить уроки.</div>
      ) : todayLessons.length === 0 ? (
        <div className="cal-empty">На сегодня уроков нет.</div>
      ) : (
        <div className="day-list">
          <div className="day-block">
            <div className="day-hdr today">
              <span className="day-hdr-name">{DAY_FULL[todayCol]}</span>
              <span className="day-hdr-date">{dayMonth(today)}</span>
              <span className="day-hdr-cnt">{todayLessons.length}</span>
            </div>
            {todayLessons.map((occ, i) => (
              <div
                key={`${occ.group}-${occ.time}-${i}`}
                className={`lrow${occ.status === 'cancelled' ? ' cancelled' : ''}`}
                style={{ ['--subject-color' as any]: colorOf(occ) }}
                onClick={() => handleSelect(occ)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter') handleSelect(occ); }}
              >
                <div className="lrow-time">{occ.time ?? '—'}</div>
                <div style={{ minWidth: 0 }}>
                  <div className="lrow-title">{occ.groupDisplay}</div>
                  <div className="lrow-meta">{occ.isGroup ? `${occ.students.length} уч.` : occ.teacher}</div>
                </div>
                <StatusPill status={occ.status} label={occ.label} />
              </div>
            ))}
          </div>
        </div>
      )}

      {selection?.kind === 'form' && (
        <LessonForm group={selection.group} groupData={selection.data} onClose={() => setSelection(null)} />
      )}
      {selection?.kind === 'popup' && (
        <LessonPopup lesson={selection.lesson} onClose={() => setSelection(null)} />
      )}
    </div>
  );
}
