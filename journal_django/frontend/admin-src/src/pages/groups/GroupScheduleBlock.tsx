import { useState } from 'react';
import { useGroupSchedule, useDeleteException } from '../../hooks/useGroupSchedule';
import { useTeachers } from '../../hooks/useTeachers';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { formatSlot } from '../../lib/slots';
import { fmtDate } from '../../lib/format';
import { SCHEDULE_EXCEPTION_KIND_LABELS } from '../../lib/labels';

interface Props {
  groupId: number;
}

function fmtTime(t: string | null): string {
  return t ? String(t).slice(0, 5) : '';
}

/**
 * Read-only витрина старой модели расписания (group_schedule_slots как
 * recurrence-шаблон + историческая lesson_schedule_exceptions) — операции
 * теперь идут через planned_lessons (см. GroupPlanActions: toolbar кнопок +
 * модалки reschedule/permanent-change/cancel/extra). Инлайн-формы отсюда
 * убраны (шаг 7) — старые эндпоинты /schedule-change и /exceptions POST
 * дублировали бы работу с planned_lessons, не пересчитывая её; список
 * exceptions остаётся как история до вывода модели из употребления (шаг 9).
 */
export default function GroupScheduleBlock({ groupId }: Props) {
  const { data, isLoading } = useGroupSchedule(groupId);
  const { data: teachers = [] } = useTeachers(true);
  const deleteException = useDeleteException(groupId);
  const { toast } = useToast();
  const showError = useApiError();

  const [confirmingDeleteId, setConfirmingDeleteId] = useState<number | null>(null);

  const handleDeleteException = async (id: number) => {
    if (confirmingDeleteId !== id) { setConfirmingDeleteId(id); return; }
    try {
      await deleteException.mutateAsync(id);
      toast('Исключение удалено', 'ok');
    } catch (err) { showError(err); }
    finally { setConfirmingDeleteId(null); }
  };

  if (isLoading) {
    return <div className="memberships__empty">Загружаем расписание…</div>;
  }

  const slots = data?.slots || [];
  const exceptions = data?.exceptions || [];
  const activeSlots = slots.filter((s) => !s.effective_to);
  const historySlots = slots.filter((s) => s.effective_to);

  const teacherName = (id: number | null) => {
    if (!id) return null;
    return teachers.find((t) => t.id === id)?.name || `#${id}`;
  };

  return (
    <div className="schedule-block">
      <div className="schedule-block__subtitle">Текущее расписание</div>
      {activeSlots.length === 0 ? (
        <div className="memberships__empty">Активных слотов нет</div>
      ) : (
        <div className="schedule-slots">
          {activeSlots.map((s) => (
            <div key={s.id} className="schedule-slot-chip is-active">
              <span className="schedule-slot-chip__label">{formatSlot(s)}</span>
              <span className="schedule-slot-chip__period">с {fmtDate(s.effective_from)}</span>
            </div>
          ))}
        </div>
      )}
      {historySlots.length > 0 && (
        <details className="schedule-history">
          <summary>История слотов ({historySlots.length})</summary>
          <div className="schedule-slots">
            {historySlots.map((s) => (
              <div key={s.id} className="schedule-slot-chip is-history">
                <span className="schedule-slot-chip__label">{formatSlot(s)}</span>
                <span className="schedule-slot-chip__period">
                  {fmtDate(s.effective_from)} – {fmtDate(s.effective_to)}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}

      <div className="schedule-block__subtitle">Исключения</div>
      {exceptions.length === 0 ? (
        <div className="memberships__empty">Исключений нет</div>
      ) : (
        exceptions.map((e) => (
          <div key={e.id} className="schedule-exception-item">
            <div className="schedule-exception-item__main">
              <span className={`schedule-exception-item__kind schedule-exception-item__kind--${e.kind}`}>
                {SCHEDULE_EXCEPTION_KIND_LABELS[e.kind]}
              </span>
              <span className="schedule-exception-item__dates">
                {e.kind !== 'extra' && (
                  <>{fmtDate(e.original_date)}{e.original_time ? ` ${fmtTime(e.original_time)}` : ''}</>
                )}
                {e.kind === 'reschedule' && ' → '}
                {e.kind !== 'cancel' && (
                  <>{fmtDate(e.new_date)}{e.new_start_time ? ` ${fmtTime(e.new_start_time)}` : ''}</>
                )}
              </span>
              {e.new_teacher_id && (
                <span className="schedule-exception-item__teacher">{teacherName(e.new_teacher_id)}</span>
              )}
            </div>
            {e.note && <div className="schedule-exception-item__note">{e.note}</div>}
            <div className="schedule-exception-item__footer">
              <span className="schedule-exception-item__created">создано {fmtDate(e.created_at)}</span>
              <button
                type="button"
                className={`btn-delete${confirmingDeleteId === e.id ? ' is-confirming' : ''}`}
                onClick={() => { void handleDeleteException(e.id); }}
                disabled={deleteException.isPending}
              >{confirmingDeleteId === e.id ? 'Точно?' : 'Удалить'}</button>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
