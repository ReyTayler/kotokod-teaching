import { useMemo, useState } from 'react';
import {
  useGroupSchedule,
  useScheduleChange,
  useCreateException,
  useDeleteException,
  type ExceptionPayload,
} from '../../hooks/useGroupSchedule';
import { useTeachers } from '../../hooks/useTeachers';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Field } from '../../components/form/Field';
import { SelectInput } from '../../components/form/SelectInput';
import { DateInput } from '../../components/form/DateInput';
import { TextInput } from '../../components/form/TextInput';
import { Textarea } from '../../components/form/Textarea';
import { Combobox } from '../../components/form/Combobox';
import { DOW, formatSlot } from '../../lib/slots';
import { fmtDate } from '../../lib/format';
import { SCHEDULE_EXCEPTION_KIND_LABELS, SCHEDULE_EXCEPTION_KIND_OPTIONS } from '../../lib/labels';
import type { ScheduleExceptionKind } from '../../lib/types';

interface Props {
  groupId: number;
}

interface SlotDraft {
  day_of_week: number;
  start_time: string;
}

const NEW_SLOT_DEFAULT: SlotDraft = { day_of_week: 1, start_time: '18:00' };

function fmtTime(t: string | null): string {
  return t ? String(t).slice(0, 5) : '';
}

export default function GroupScheduleBlock({ groupId }: Props) {
  const { data, isLoading } = useGroupSchedule(groupId);
  const { data: teachers = [] } = useTeachers(true);
  const scheduleChange = useScheduleChange(groupId);
  const createException = useCreateException(groupId);
  const deleteException = useDeleteException(groupId);
  const { toast } = useToast();
  const showError = useApiError();

  const teacherOptions = useMemo(
    () => [
      { value: '', label: '— не менять —' },
      ...teachers.filter((t) => t.active).map((t) => ({ value: String(t.id), label: t.name })),
    ],
    [teachers],
  );

  // ── Постоянная смена расписания ──
  const [effectiveFrom, setEffectiveFrom] = useState('');
  const [draftSlots, setDraftSlots] = useState<SlotDraft[]>([{ ...NEW_SLOT_DEFAULT }]);

  const updateDraftSlot = (i: number, key: keyof SlotDraft, value: string) => {
    setDraftSlots((arr) => {
      const next = [...arr];
      next[i] = { ...next[i], [key]: key === 'day_of_week' ? Number(value) : value };
      return next;
    });
  };

  const submitScheduleChange = async () => {
    if (!effectiveFrom) { toast('Укажите дату вступления в силу', 'error'); return; }
    if (draftSlots.length === 0) { toast('Добавьте хотя бы один слот', 'error'); return; }
    try {
      await scheduleChange.mutateAsync({
        effective_from: effectiveFrom,
        slots: draftSlots.map((s) => ({ day_of_week: s.day_of_week, start_time: s.start_time })),
      });
      toast('Расписание изменено', 'ok');
      setEffectiveFrom('');
      setDraftSlots([{ ...NEW_SLOT_DEFAULT }]);
    } catch (err) { showError(err); }
  };

  // ── Разовое изменение (исключение) ──
  const [kind, setKind] = useState<ScheduleExceptionKind>('reschedule');
  const [originalDate, setOriginalDate] = useState('');
  const [originalTime, setOriginalTime] = useState('');
  const [newDate, setNewDate] = useState('');
  const [newTime, setNewTime] = useState('');
  const [exTeacherId, setExTeacherId] = useState('');
  const [note, setNote] = useState('');
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<number | null>(null);

  const resetExceptionForm = () => {
    setOriginalDate(''); setOriginalTime(''); setNewDate(''); setNewTime('');
    setExTeacherId(''); setNote('');
  };

  const submitException = async () => {
    if (kind === 'reschedule' && (!originalDate || !newDate)) {
      toast('Для переноса укажите исходную и новую дату', 'error');
      return;
    }
    if (kind === 'cancel' && !originalDate) {
      toast('Для отмены укажите исходную дату', 'error');
      return;
    }
    if (kind === 'extra' && !newDate) {
      toast('Для доп. занятия укажите дату', 'error');
      return;
    }

    const body: ExceptionPayload = {
      kind,
      note: note.trim() || null,
      new_teacher_id: exTeacherId ? Number(exTeacherId) : null,
    };
    if (kind === 'reschedule') {
      body.original_date = originalDate;
      body.original_time = originalTime || null;
      body.new_date = newDate;
      body.new_start_time = newTime || null;
    } else if (kind === 'cancel') {
      body.original_date = originalDate;
      body.original_time = originalTime || null;
    } else {
      body.new_date = newDate;
      body.new_start_time = newTime || null;
    }

    try {
      await createException.mutateAsync(body);
      toast('Исключение добавлено', 'ok');
      resetExceptionForm();
    } catch (err) { showError(err); }
  };

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

      <div className="schedule-block__forms">
        <div className="schedule-form">
          <div className="schedule-block__subtitle">Постоянная смена расписания</div>
          <div className="schedule-form__hint">
            Текущие активные слоты закроются датой вступления в силу, новые начнут действовать с неё.
          </div>
          <Field label="Дата вступления в силу" required>
            <DateInput value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
          </Field>
          <div className="slot-row-list">
            {draftSlots.map((s, i) => (
              <div key={i} className="slot-row">
                <SelectInput
                  className="schedule-day-select"
                  value={String(s.day_of_week)}
                  onChange={(e) => updateDraftSlot(i, 'day_of_week', e.target.value)}
                  options={DOW.map((d, idx) => ({ value: idx, label: d }))}
                />
                <TextInput
                  type="time"
                  value={s.start_time}
                  onChange={(e) => updateDraftSlot(i, 'start_time', e.target.value)}
                />
                <button
                  type="button"
                  className="slot-row__remove"
                  onClick={() => setDraftSlots((arr) => arr.filter((_, idx) => idx !== i))}
                  aria-label="Удалить слот"
                  disabled={draftSlots.length <= 1}
                >×</button>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="slot-add"
            onClick={() => setDraftSlots((arr) => [...arr, { ...NEW_SLOT_DEFAULT }])}
          >+ Добавить слот</button>
          <button
            type="button"
            className="btn-save schedule-form__submit"
            onClick={() => { void submitScheduleChange(); }}
            disabled={scheduleChange.isPending}
          >Применить</button>
        </div>

        <div className="schedule-form">
          <div className="schedule-block__subtitle">Разовое изменение</div>
          <Field label="Тип">
            <SelectInput
              value={kind}
              onChange={(e) => setKind(e.target.value as ScheduleExceptionKind)}
              options={SCHEDULE_EXCEPTION_KIND_OPTIONS}
            />
          </Field>

          {(kind === 'reschedule' || kind === 'cancel') && (
            <div className="schedule-form__row">
              <Field label="Исходная дата" required>
                <DateInput value={originalDate} onChange={(e) => setOriginalDate(e.target.value)} />
              </Field>
              <Field label="Исходное время">
                <TextInput type="time" value={originalTime} onChange={(e) => setOriginalTime(e.target.value)} />
              </Field>
            </div>
          )}

          {(kind === 'reschedule' || kind === 'extra') && (
            <div className="schedule-form__row">
              <Field label="Новая дата" required>
                <DateInput value={newDate} onChange={(e) => setNewDate(e.target.value)} />
              </Field>
              <Field label="Новое время">
                <TextInput type="time" value={newTime} onChange={(e) => setNewTime(e.target.value)} />
              </Field>
            </div>
          )}

          <Field label="Преподаватель">
            <Combobox
              value={exTeacherId}
              onChange={setExTeacherId}
              options={teacherOptions}
              placeholder="Не менять"
            />
          </Field>
          <Field label="Заметка">
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
          </Field>
          <button
            type="button"
            className="btn-save schedule-form__submit"
            onClick={() => { void submitException(); }}
            disabled={createException.isPending}
          >Добавить</button>
        </div>
      </div>
    </div>
  );
}
