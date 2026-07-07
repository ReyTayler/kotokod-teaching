import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useGroupMutations, type GroupPayload } from '../../hooks/useGroups';
import { useTeachers } from '../../hooks/useTeachers';
import { useDirections } from '../../hooks/useDirections';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { TextInput } from '../../components/form/TextInput';
import { DateInput } from '../../components/form/DateInput';
import { Checkbox } from '../../components/form/Checkbox';
import { SelectInput } from '../../components/form/SelectInput';
import { DOW } from '../../lib/slots';
import type { Group, LessonDuration } from '../../lib/types';

interface Slot { day_of_week: number; start_time: string; }

// «N раз в неделю» с русским склонением (1 раз, 2 раза, 5 раз).
function timesPerWeekLabel(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  let word = 'раз';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) word = 'раза';
  return `${n} ${word} в неделю`;
}

// День недели даты 'YYYY-MM-DD' в конвенции day_of_week (0=Вс … 6=Сб).
function weekdayOfISO(ymd: string): number {
  const [y, m, d] = ymd.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();
}

interface Props { initial: Group | null; onClose: () => void; }

export default function GroupFormModal({ initial, onClose }: Props) {
  const isNew = !initial;
  const navigate = useNavigate();
  const muts = useGroupMutations();
  const { data: teachers = [] } = useTeachers(true);
  const { data: directions = [] } = useDirections(true);
  const { toast } = useToast();
  const showError = useApiError();

  const [name, setName] = useState(initial?.name || '');
  const [directionId, setDirectionId] = useState<string>(initial?.direction_id ? String(initial.direction_id) : '');
  const [teacherId, setTeacherId] = useState<string>(initial?.teacher_id ? String(initial.teacher_id) : '');
  const [vkChat, setVkChat] = useState(initial?.vk_chat || '');
  const [duration, setDuration] = useState<LessonDuration>(initial?.lesson_duration_minutes || 90);
  const [startDate, setStartDate] = useState((initial?.group_start_date || '').slice(0, 10));
  // Новая группа по умолчанию — индивидуальный формат; при редактировании берём значение группы.
  const [isIndividual, setIsIndividual] = useState(initial ? initial.is_individual : true);
  const [active, setActive] = useState(initial?.active ?? true);
  const [slots, setSlots] = useState<Slot[]>(() =>
    (initial?.slots || []).map((s) => ({
      day_of_week: s.day_of_week,
      start_time: String(s.start_time).slice(0, 5),
    })),
  );

  const teacherOptions = [{ value: '', label: '— выберите —' }, ...teachers
    .filter((t) => t.active || (initial && initial.teacher_id === t.id))
    .map((t) => ({ value: t.id, label: t.name }))];
  const directionOptions = [{ value: '', label: '— выберите —' }, ...directions
    .filter((d) => d.active || (initial && initial.direction_id === d.id))
    .map((d) => ({ value: d.id, label: d.name }))];

  const updateSlot = (i: number, key: 'day_of_week' | 'start_time', value: string) => {
    setSlots((arr) => {
      const next = [...arr];
      next[i] = { ...next[i], [key]: key === 'day_of_week' ? Number(value) : value };
      return next;
    });
  };

  // Групповой формат — максимум один слот; при переключении обрезаем лишние.
  // Формат закреплён за группой после создания — при редактировании смена запрещена.
  const chooseFormat = (individual: boolean) => {
    if (!isNew) return;
    setIsIndividual(individual);
    if (!individual) setSlots((arr) => arr.slice(0, 1));
  };
  const canAddSlot = isIndividual || slots.length < 1;

  // «Уроков в неделю» больше не вводится вручную — это число слотов.
  const lessonsPerWeek = slots.length;

  // Дни недели, покрытые слотами (для подсказки и проверки даты старта).
  const slotDays = useMemo(
    () => Array.from(new Set(slots.map((s) => s.day_of_week))).sort((a, b) => a - b),
    [slots],
  );
  // Дата старта обязана попадать на день одного из слотов.
  const startMismatch = startDate !== '' && slots.length > 0 && !slotDays.includes(weekdayOfISO(startDate));

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!directionId || !teacherId) {
      toast('Направление и преподаватель обязательны', 'error');
      return;
    }
    if (!isIndividual && slots.length > 1) {
      toast('Групповой формат допускает только один слот', 'error');
      return;
    }
    if (startMismatch) {
      toast('Дата старта должна попадать на день одного из слотов', 'error');
      return;
    }
    const payload: GroupPayload = {
      name,
      direction_id: Number(directionId),
      teacher_id: Number(teacherId),
      is_individual: isIndividual,
      lesson_duration_minutes: duration,
      lessons_per_week: lessonsPerWeek || 1,
      group_start_date: startDate || null,
      vk_chat: vkChat || null,
      slots: slots.map((s) => ({ day_of_week: s.day_of_week, start_time: s.start_time })),
    };
    if (!isNew) payload.active = active;

    try {
      if (isNew) {
        const created = await muts.create.mutateAsync(payload);
        toast('Создано', 'ok');
        onClose();
        navigate(`/admin/groups/${created.id}`);
      } else {
        await muts.update.mutateAsync({ id: initial!.id, body: payload });
        toast('Сохранено', 'ok');
        onClose();
      }
    } catch (err) { showError(err); }
  };

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      wide
      title={isNew ? 'Новая группа' : `Редактировать: ${initial!.name}`}
      footer={
        <button type="submit" form="group-form" className="btn-save" disabled={muts.create.isPending || muts.update.isPending || startMismatch}>
          Сохранить
        </button>
      }
    >
      <form id="group-form" className="modal-form" onSubmit={onSubmit}>
        <div className="modal-section-label">Основное</div>
        <Field label="Название группы" required full>
          <TextInput required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Направление" required>
          <SelectInput value={directionId} onChange={(e) => setDirectionId(e.target.value)} options={directionOptions} required />
        </Field>
        <Field label="Преподаватель" required>
          <SelectInput value={teacherId} onChange={(e) => setTeacherId(e.target.value)} options={teacherOptions} required />
        </Field>
        <Field label="Ссылка на чат ВК" full>
          <TextInput value={vkChat} onChange={(e) => setVkChat(e.target.value)} placeholder="https://vk.me/..." />
        </Field>

        <div className="modal-section-label">Параметры</div>
        <Field label="Формат занятия" full>
          {/* Формат жёстко закреплён за группой после создания — при редактировании только чтение. */}
          <div className="format-toggle" role="radiogroup" aria-label="Формат занятия">
            <button
              type="button"
              role="radio"
              aria-checked={isIndividual}
              disabled={!isNew}
              data-format="individual"
              className={`format-toggle__btn${isIndividual ? ' is-active' : ''}`}
              onClick={() => chooseFormat(true)}
            >
              <span className="format-toggle__dot" />
              <span className="format-toggle__title">Индивидуальный формат</span>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={!isIndividual}
              disabled={!isNew}
              data-format="group"
              className={`format-toggle__btn${!isIndividual ? ' is-active' : ''}`}
              onClick={() => chooseFormat(false)}
            >
              <span className="format-toggle__dot" />
              <span className="format-toggle__title">Групповой формат</span>
            </button>
          </div>
          {!isNew && (
            <span className="field-hint">Формат нельзя изменить после создания группы</span>
          )}
        </Field>
        {!isNew && (
          <Field label="Группа активна">
            <Checkbox checked={active} onChange={(e) => setActive(e.target.checked)} />
          </Field>
        )}

        <div className="modal-section-label">Дни и время занятий</div>
        <Field label="Длительность">
          <SelectInput
            value={String(duration)}
            onChange={(e) => setDuration(Number(e.target.value) as LessonDuration)}
            options={[
              { value: 45, label: '45 мин' },
              { value: 60, label: '60 мин' },
              { value: 90, label: '90 мин' },
            ]}
          />
        </Field>
        <Field label="Дата начала" error={startMismatch ? 'Дата старта не попадает ни в один слот' : undefined}>
          <DateInput value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          {slots.length > 0 && (
            <span className="field-hint">Дни слотов: {slotDays.map((d) => DOW[d]).join(', ')}</span>
          )}
        </Field>

        <div className="slots-block">
          <div className="slots-block__head">
            <span className="slots-block__label">Слоты</span>
            {slots.length > 0 && (
              <span className="slots-frequency">{timesPerWeekLabel(lessonsPerWeek)}</span>
            )}
          </div>
          <div id="slots-list">
            {slots.map((s, i) => (
              <div key={i} className="slot-row">
                <SelectInput
                  value={String(s.day_of_week)}
                  onChange={(e) => updateSlot(i, 'day_of_week', e.target.value)}
                  options={DOW.map((d, idx) => ({ value: idx, label: d }))}
                />
                <input
                  type="time"
                  value={s.start_time}
                  onChange={(e) => updateSlot(i, 'start_time', e.target.value)}
                />
                <button
                  type="button"
                  className="slot-row__remove"
                  onClick={() => setSlots((arr) => arr.filter((_, idx) => idx !== i))}
                  aria-label="Удалить слот"
                >×</button>
              </div>
            ))}
            {slots.length === 0 && (
              <div className="slots-block__empty">Слоты не заданы</div>
            )}
          </div>
          {canAddSlot ? (
            <button
              type="button"
              className="slot-add"
              onClick={() => setSlots((arr) => [...arr, { day_of_week: 1, start_time: '18:00' }])}
            >+ Добавить слот</button>
          ) : (
            <span className="slots-block__hint">Групповой формат — только один слот</span>
          )}
        </div>
      </form>
    </Dialog>
  );
}
