import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTeachers } from '../../hooks/useTeachers';
import { useAdminCalendar } from '../../hooks/useAdminCalendar';
import { CalendarView } from '../../shared/calendar/CalendarView';
import { Field } from '../../components/form/Field';
import { Combobox } from '../../components/form/Combobox';
import { currentMondayMsk, addDays, isoDate } from '../../shared/calendar/lib';
import type { Occurrence } from '../../shared/calendar/types';

/**
 * Раздел «Календарь» admin SPA — read-only расписание ОДНОГО выбранного
 * преподавателя (RequireRole manager/admin/superadmin в App.tsx). Обёртка
 * над презентационным CalendarView (см. teacher-src CalendarPage.tsx для
 * оригинального паттерна) — без onAction/onLessonAction, попап занятия
 * строго read-only, с кнопкой перехода в план группы (onOpenGroup).
 */
export default function AdminCalendarPage() {
  const navigate = useNavigate();
  const teachers = useTeachers();
  const [teacherId, setTeacherId] = useState<number | null>(null);
  const [range, setRange] = useState(() => {
    const monday = currentMondayMsk();
    return { from: isoDate(monday), to: isoDate(addDays(monday, 6)) };
  });

  const teacherOptions = useMemo(
    () => (teachers.data || []).slice().sort((a, b) => a.name.localeCompare(b.name))
      .map((t) => ({ value: String(t.id), label: t.name })),
    [teachers.data],
  );

  const { data, isLoading, isError, isFetching } = useAdminCalendar(teacherId, range.from, range.to);

  const onVisibleRangeChange = useCallback((from: string, to: string) => {
    setRange((prev) => (prev.from === from && prev.to === to ? prev : { from, to }));
  }, []);

  const onOpenGroup = useCallback((occ: Occurrence) => {
    if (occ.groupId != null) navigate(`/admin/groups/${occ.groupId}`);
  }, [navigate]);

  return (
    <div className="admin-calendar-page">
      <div className="admin-calendar-page__filter">
        <Field label="Преподаватель">
          <Combobox
            value={teacherId != null ? String(teacherId) : ''}
            onChange={(v) => setTeacherId(v ? Number(v) : null)}
            options={teacherOptions}
            placeholder="Выберите преподавателя"
          />
        </Field>
      </div>

      {teacherId == null ? (
        <div className="cal-empty">Выберите преподавателя, чтобы увидеть расписание.</div>
      ) : (
        <CalendarView
          occurrences={data?.occurrences ?? []}
          unscheduled={data?.unscheduled ?? []}
          isLoading={isLoading}
          isError={isError}
          isFetching={isFetching}
          onVisibleRangeChange={onVisibleRangeChange}
          role="admin"
          onOpenGroup={onOpenGroup}
        />
      )}
    </div>
  );
}
