import type { LessonStatus, OccStatus } from '../../lib/types';

/** Объединённый статус: старый /api/report (LessonStatus) + новый /api/calendar (OccStatus). */
export type AnyStatus = LessonStatus | OccStatus;

const LABEL: Record<AnyStatus, string> = {
  done: 'Заполнено',
  overdue: 'Надо заполнить',
  pending: 'Ещё не было',
  notime: 'Без времени',
  cancelled: 'Отменён',
  moved: 'Перенесён',
};

/** Статус-пилюля урока (tone-based, цвет только для смысла). */
export function StatusPill({ status, label }: { status: AnyStatus; label?: string }) {
  return (
    <span className={`st st--${status}`}>
      <span className="st-dot" />
      {label ?? LABEL[status]}
    </span>
  );
}
