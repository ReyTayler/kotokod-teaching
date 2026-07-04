import { Modal } from './Modal';
import { StatusPill } from './StatusPill';
import type { Occurrence } from './types';
import { parseIsoDate, columnIndexOfIsoDate, dayMonth } from './lib';

const DAY_FULL = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];

/**
 * Read-only детали занятия (Occurrence из /api/calendar или /plan) +
 * необязательная кнопка «Отметить урок» (шаг 7 подключит операции через
 * onSubmit/CalendarView.onLessonAction — сейчас проп остаётся, но без вызова
 * из CalendarView, т.к. этот шаг строго read-only).
 */
export function LessonPopup({
  lesson,
  onClose,
  onSubmit,
}: {
  lesson: Occurrence;
  onClose: () => void;
  onSubmit?: () => void;
}) {
  const dayName = DAY_FULL[columnIndexOfIsoDate(lesson.date)];
  const dateLabel = dayMonth(parseIsoDate(lesson.date));
  const when = lesson.time
    ? `${dayName}, ${dateLabel} · ${lesson.time}`
    : `${dayName}, ${dateLabel} · время не указано`;
  const displayTeacher = lesson.teacherOverride ?? lesson.teacher;

  return (
    <Modal title={lesson.groupDisplay} subtitle={when} onClose={onClose}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          <StatusPill status={lesson.status} label={lesson.label} />
        </div>
      </div>

      <div>
        <div className="t-sec-label">Информация</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <div className="t-info-row"><span className="t-info-ico">👤</span><span>Преподаватель: {displayTeacher}</span></div>
          {lesson.teacherOverride && lesson.teacherOverride !== lesson.teacher && (
            <div className="t-info-row"><span className="t-info-ico">🔁</span><span>Замена вместо: {lesson.teacher}</span></div>
          )}
          {lesson.direction && <div className="t-info-row"><span className="t-info-ico">🧭</span><span>Направление: {lesson.direction}</span></div>}
          {lesson.movedFrom && lesson.movedTo && (
            <div className="t-info-row"><span className="t-info-ico">📅</span><span>Перенесён: {lesson.movedFrom} → {lesson.movedTo}</span></div>
          )}
        </div>
      </div>

      {lesson.students.length > 0 && (
        <div>
          <div className="t-sec-label">Ученики · {lesson.students.length}</div>
          <div className="t-students">
            {lesson.students.map((s, i) => (
              <div key={`${s.name}-${i}`} className="t-student"><span>{s.name}</span></div>
            ))}
          </div>
        </div>
      )}

      {onSubmit && (
        <div className="lf-actions">
          <button type="button" className="btn-save grp-card-btn" onClick={onSubmit}>
            Отметить урок
          </button>
        </div>
      )}
    </Modal>
  );
}
