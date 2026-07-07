import { forwardRef, useImperativeHandle, useMemo, useState } from 'react';
import { useGroupPlan, type PlanRow } from '../../hooks/useGroupPlanCalendar';
import {
  useGeneratePlan, useReschedule, usePermanentChange, useCancelLesson, useAddExtra,
  useChangeTeacher, useChangeTeacherPermanent,
} from '../../hooks/useGroupPlan';
import { useTeachers } from '../../hooks/useTeachers';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Dialog } from '../../components/ui/Dialog';
import { Button } from '../../components/ui/Button';
import { Field } from '../../components/form/Field';
import { SelectInput } from '../../components/form/SelectInput';
import { DateInput } from '../../components/form/DateInput';
import { TimeInput } from '../../components/form/TimeInput';
import { Combobox } from '../../components/form/Combobox';
import { fmtDate } from '../../lib/format';
import type { LessonActionKind } from '../../shared/calendar/LessonPopup';
import type { Occurrence } from '../../shared/calendar/types';
import type { Group } from '../../lib/types';

/** День недели Monday-first в UI, значения — уже в конвенции проекта (Вс=0..Сб=6),
 * поэтому дополнительная конвертация индекса при отправке не нужна. */
const DOW_OPTIONS = [
  { value: 1, label: 'Понедельник' },
  { value: 2, label: 'Вторник' },
  { value: 3, label: 'Среда' },
  { value: 4, label: 'Четверг' },
  { value: 5, label: 'Пятница' },
  { value: 6, label: 'Суббота' },
  { value: 0, label: 'Воскресенье' },
];

function lessonLabel(r: PlanRow): string {
  const time = r.scheduled_time ? r.scheduled_time.slice(0, 5) : '';
  const pos = r.seq != null ? `Урок ${r.seq}` : 'Доп. занятие';
  return `${pos} — ${fmtDate(r.scheduled_date)}${time ? ` ${time}` : ''}`;
}

/** День недели ISO-даты в конвенции проекта (Вс=0..Сб=6), UTC-safe. */
function dowSun0(iso: string): number {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();
}

type TeacherScope = 'once' | 'permanent';

export interface GroupPlanActionsHandle {
  /** Вызывается из CalendarView.onAction (клик по быстрому действию в LessonPopup). */
  quickAction: (kind: LessonActionKind, occ: Occurrence) => void;
}

interface Props {
  group: Group;
}

type DialogKind = 'reschedule' | 'permanent' | 'change-teacher' | 'cancel' | 'extra' | null;

/**
 * Toolbar кнопок + модалки операций плана (planned_lessons) для вкладки
 * «Расписание» группы. Заменяет прежние всегда-развёрнутые инлайн-панели
 * GroupScheduleBlock (постоянная смена/разовое исключение) — те мутировали
 * group_schedule_slots/lesson_schedule_exceptions напрямую и не пересчитывали
 * planned_lessons. Операции здесь бьют в /api/admin/groups/<id>/plan/*
 * (docs/lesson-scheduling.md) и сами инвалидируют план+календарь.
 */
const GroupPlanActions = forwardRef<GroupPlanActionsHandle, Props>(function GroupPlanActions(
  { group },
  ref,
) {
  const groupId = group.id;
  const { data: plan = [], isLoading: planLoading } = useGroupPlan(groupId);
  const { data: teachers = [] } = useTeachers(true);
  const { toast } = useToast();
  const showError = useApiError();

  const generatePlan = useGeneratePlan(groupId);
  const reschedule = useReschedule(groupId);
  const permanentChange = usePermanentChange(groupId);
  const changeTeacher = useChangeTeacher(groupId);
  const changeTeacherPermanent = useChangeTeacherPermanent(groupId);
  const cancelLesson = useCancelLesson(groupId);
  const addExtra = useAddExtra(groupId);

  const [dialog, setDialog] = useState<DialogKind>(null);
  const closeDialog = () => setDialog(null);

  const teacherOptions = useMemo(
    () => teachers.filter((t) => t.active).map((t) => ({ value: String(t.id), label: t.name })),
    [teachers],
  );
  const teacherOptionsOptional = useMemo(
    () => [{ value: '', label: '— не менять —' }, ...teacherOptions],
    [teacherOptions],
  );

  // Разовый перенос / смена препода разово: доступны для активных строк (курсовых
  // и доп. занятий), но НЕ для проведённых ('done') и НЕ для маркеров отмены
  // ('cancelled') — двигать/переназначать пин отмены бессмысленно.
  const reschedulableRows = useMemo(
    () => plan.filter((r) => r.status !== 'done' && r.status !== 'cancelled'),
    [plan],
  );
  // Отмена / перенос-навсегда: бэкенд требует курсовую строку (seq != null)
  // в статусе pending/overdue (services.cancel/permanent_change) — done,
  // cancelled, moved и доп. занятия (seq=NULL) отклоняются 400/409.
  const courseRows = useMemo(
    () => plan.filter((r) => r.seq != null && (r.status === 'pending' || r.status === 'overdue')),
    [plan],
  );
  const permanentRows = useMemo(
    () => [...courseRows].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0)),
    [courseRows],
  );

  // ── Перенести занятие (reschedule) ──
  const [rLessonId, setRLessonId] = useState('');
  const [rDate, setRDate] = useState('');
  const [rTime, setRTime] = useState('');
  const [rTeacherId, setRTeacherId] = useState('');

  const openReschedule = (prefill?: PlanRow) => {
    setRLessonId(prefill ? String(prefill.id) : '');
    setRDate(prefill?.scheduled_date ?? '');
    setRTime(prefill?.scheduled_time?.slice(0, 5) ?? '');
    setRTeacherId(prefill?.teacher_id ? String(prefill.teacher_id) : '');
    setDialog('reschedule');
  };

  const selectRescheduleLesson = (id: string) => {
    setRLessonId(id);
    const row = reschedulableRows.find((r) => String(r.id) === id);
    if (row) {
      setRDate(row.scheduled_date);
      setRTime(row.scheduled_time?.slice(0, 5) ?? '');
      setRTeacherId(row.teacher_id ? String(row.teacher_id) : '');
    }
  };

  const submitReschedule = async () => {
    if (!rLessonId) { toast('Выберите занятие', 'error'); return; }
    if (!rDate) { toast('Укажите новую дату', 'error'); return; }
    try {
      await reschedule.mutateAsync({
        lessonId: Number(rLessonId),
        body: {
          new_date: rDate,
          new_time: rTime || null,
          new_teacher_id: rTeacherId ? Number(rTeacherId) : null,
        },
      });
      toast('Занятие перенесено', 'ok');
      closeDialog();
    } catch (err) { showError(err); }
  };

  // ── Изменить расписание навсегда (permanent-change) ──
  const [pFromSeq, setPFromSeq] = useState('');
  const [pDow, setPDow] = useState('1');
  const [pTime, setPTime] = useState('');

  const openPermanent = (prefill?: PlanRow) => {
    setPFromSeq(prefill?.seq != null ? String(prefill.seq) : '');
    // День недели по умолчанию — текущий день выбранного (или первого курсового)
    // занятия, а не жёстко понедельник: смена только времени не должна уводить
    // занятия на другой день.
    const anchorDate = prefill?.scheduled_date ?? permanentRows[0]?.scheduled_date;
    setPDow(anchorDate ? String(dowSun0(anchorDate)) : '1');
    setPTime(prefill?.scheduled_time?.slice(0, 5) ?? '');
    setDialog('permanent');
  };

  const submitPermanent = async () => {
    if (!pFromSeq) { toast('Выберите занятие, с которого меняем расписание', 'error'); return; }
    try {
      await permanentChange.mutateAsync({
        from_seq: Number(pFromSeq),
        new_day_of_week: Number(pDow),
        new_time: pTime || null,
      });
      toast('Расписание изменено', 'ok');
      closeDialog();
    } catch (err) { showError(err); }
  };

  // ── Сменить преподавателя (разово / навсегда) ──
  const [tScope, setTScope] = useState<TeacherScope>('once');
  const [tLessonId, setTLessonId] = useState('');
  const [tFromSeq, setTFromSeq] = useState('');
  const [tTeacherId, setTTeacherId] = useState('');

  const openChangeTeacher = (prefill?: PlanRow, scope: TeacherScope = 'once') => {
    setTScope(scope);
    setTLessonId(prefill ? String(prefill.id) : '');
    setTFromSeq(prefill?.seq != null ? String(prefill.seq) : '');
    setTTeacherId(prefill?.teacher_id ? String(prefill.teacher_id) : '');
    setDialog('change-teacher');
  };

  const submitChangeTeacher = async () => {
    if (!tTeacherId) { toast('Выберите преподавателя', 'error'); return; }
    try {
      if (tScope === 'permanent') {
        if (!tFromSeq) { toast('Выберите занятие, с которого меняем преподавателя', 'error'); return; }
        await changeTeacherPermanent.mutateAsync({
          from_seq: Number(tFromSeq), new_teacher_id: Number(tTeacherId),
        });
        toast('Преподаватель изменён для будущих занятий', 'ok');
      } else {
        if (!tLessonId) { toast('Выберите занятие', 'error'); return; }
        await changeTeacher.mutateAsync({
          lessonId: Number(tLessonId), newTeacherId: Number(tTeacherId),
        });
        toast('Преподаватель занятия изменён', 'ok');
      }
      closeDialog();
    } catch (err) { showError(err); }
  };

  // ── Отменить занятие (cancel) ──
  const [cLessonId, setCLessonId] = useState('');

  const openCancel = (prefill?: PlanRow) => {
    setCLessonId(prefill ? String(prefill.id) : '');
    setDialog('cancel');
  };

  const submitCancel = async () => {
    if (!cLessonId) { toast('Выберите занятие', 'error'); return; }
    try {
      await cancelLesson.mutateAsync(Number(cLessonId));
      toast('Занятие отменено, курс продлён на неделю', 'ok');
      closeDialog();
    } catch (err) { showError(err); }
  };

  // ── Доп. занятие (extra) ──
  const [eDate, setEDate] = useState('');
  const [eTime, setETime] = useState('');
  const [eTeacherId, setETeacherId] = useState('');

  const openExtra = () => {
    setEDate('');
    setETime('');
    setETeacherId(group.teacher_id ? String(group.teacher_id) : '');
    setDialog('extra');
  };

  const submitExtra = async () => {
    if (!eDate) { toast('Укажите дату', 'error'); return; }
    if (!eTime) { toast('Укажите время', 'error'); return; }
    try {
      await addExtra.mutateAsync({
        date: eDate,
        time: eTime,
        teacher_id: eTeacherId ? Number(eTeacherId) : null,
      });
      toast('Доп. занятие добавлено', 'ok');
      closeDialog();
    } catch (err) { showError(err); }
  };

  // ── Сгенерировать план (generate) ──
  const submitGenerate = async () => {
    try {
      await generatePlan.mutateAsync();
      toast('План сгенерирован', 'ok');
    } catch (err) { showError(err); }
  };

  // ── Быстрые действия из LessonPopup (CalendarView.onAction) ──
  useImperativeHandle(ref, () => ({
    quickAction(kind, occ) {
      const row = occ.id != null ? plan.find((r) => r.id === occ.id) : undefined;
      if (kind === 'cancel') {
        openCancel(row);
      } else if (kind === 'change-teacher') {
        openChangeTeacher(row, 'once');
      } else {
        openReschedule(row);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- plan из замыкания useImperativeHandle пересоздаётся при каждом изменении plan (deps ниже).
  }), [plan]);

  const rescheduleOptions = reschedulableRows.map((r) => ({ value: String(r.id), label: lessonLabel(r) }));
  const cancelOptions = courseRows.map((r) => ({ value: String(r.id), label: lessonLabel(r) }));
  const permanentOptions = permanentRows.map((r) => ({ value: String(r.seq), label: lessonLabel(r) }));
  const teacherScopeOptions = [
    { value: 'once', label: 'Только это занятие' },
    { value: 'permanent', label: 'Это и все последующие' },
  ];

  return (
    <div className="plan-actions">
      <div className="plan-actions__toolbar">
        {!planLoading && plan.length === 0 ? (
          <Button variant="primary" onClick={() => { void submitGenerate(); }} disabled={generatePlan.isPending}>
            Сгенерировать план
          </Button>
        ) : (
          <>
            <Button onClick={() => openReschedule()} disabled={reschedulableRows.length === 0}>
              Перенести занятие
            </Button>
            <Button onClick={() => openChangeTeacher()} disabled={reschedulableRows.length === 0}>
              Сменить преподавателя
            </Button>
            <Button onClick={() => openPermanent()} disabled={permanentRows.length === 0}>
              Изменить расписание
            </Button>
            <Button variant="danger" onClick={() => openCancel()} disabled={courseRows.length === 0}>
              Отменить занятие
            </Button>
            <Button onClick={openExtra}>Доп. занятие</Button>
          </>
        )}
      </div>

      {/* Перенести занятие */}
      <Dialog
        open={dialog === 'reschedule'}
        onOpenChange={(o) => !o && closeDialog()}
        title="Перенести занятие"
        footer={
          <Button variant="primary" onClick={() => { void submitReschedule(); }} disabled={reschedule.isPending}>
            Перенести
          </Button>
        }
      >
        <Field label="Занятие" required>
          <SelectInput
            value={rLessonId}
            onChange={(e) => selectRescheduleLesson(e.target.value)}
            options={rescheduleOptions}
            placeholder="Выберите занятие"
          />
        </Field>
        <Field label="Новая дата" required>
          <DateInput value={rDate} onChange={(e) => setRDate(e.target.value)} />
        </Field>
        <Field label="Новое время">
          <TimeInput value={rTime} onChange={(e) => setRTime(e.target.value)} />
        </Field>
        <Field label="Преподаватель">
          <Combobox value={rTeacherId} onChange={setRTeacherId} options={teacherOptionsOptional} placeholder="Не менять" />
        </Field>
      </Dialog>

      {/* Изменить расписание навсегда */}
      <Dialog
        open={dialog === 'permanent'}
        onOpenChange={(o) => !o && closeDialog()}
        title="Изменить расписание"
        footer={
          <Button variant="primary" onClick={() => { void submitPermanent(); }} disabled={permanentChange.isPending}>
            Применить
          </Button>
        }
      >
        <div className="schedule-form__hint">
          Меняет день недели и время для всех будущих занятий, начиная с выбранного.
          Преподавателя меняйте через «Сменить преподавателя».
          Доступно только для групп с одним занятием в неделю.
        </div>
        <Field label="С какого занятия" required>
          <SelectInput
            value={pFromSeq}
            onChange={(e) => setPFromSeq(e.target.value)}
            options={permanentOptions}
            placeholder="Выберите занятие"
          />
        </Field>
        <Field label="Новый день недели" required>
          <SelectInput value={pDow} onChange={(e) => setPDow(e.target.value)} options={DOW_OPTIONS} />
        </Field>
        <Field label="Новое время">
          <TimeInput value={pTime} onChange={(e) => setPTime(e.target.value)} />
        </Field>
      </Dialog>

      {/* Сменить преподавателя (разово / навсегда) */}
      <Dialog
        open={dialog === 'change-teacher'}
        onOpenChange={(o) => !o && closeDialog()}
        title="Сменить преподавателя"
        footer={
          <Button
            variant="primary"
            onClick={() => { void submitChangeTeacher(); }}
            disabled={changeTeacher.isPending || changeTeacherPermanent.isPending}
          >
            Применить
          </Button>
        }
      >
        <Field label="Область" required>
          <SelectInput
            value={tScope}
            onChange={(e) => setTScope(e.target.value as TeacherScope)}
            options={teacherScopeOptions}
          />
        </Field>
        {tScope === 'permanent' ? (
          <Field label="С какого занятия" required>
            <SelectInput
              value={tFromSeq}
              onChange={(e) => setTFromSeq(e.target.value)}
              options={permanentOptions}
              placeholder="Выберите занятие"
            />
          </Field>
        ) : (
          <Field label="Занятие" required>
            <SelectInput
              value={tLessonId}
              onChange={(e) => setTLessonId(e.target.value)}
              options={rescheduleOptions}
              placeholder="Выберите занятие"
            />
          </Field>
        )}
        <Field label="Преподаватель" required>
          <Combobox value={tTeacherId} onChange={setTTeacherId} options={teacherOptions} placeholder="Выберите преподавателя" />
        </Field>
      </Dialog>

      {/* Отменить занятие */}
      <Dialog
        open={dialog === 'cancel'}
        onOpenChange={(o) => !o && closeDialog()}
        title="Отменить занятие"
        footer={
          <Button variant="danger" onClick={() => { void submitCancel(); }} disabled={cancelLesson.isPending}>
            Отменить занятие
          </Button>
        }
      >
        <Field label="Занятие" required>
          <SelectInput
            value={cLessonId}
            onChange={(e) => setCLessonId(e.target.value)}
            options={cancelOptions}
            placeholder="Выберите занятие"
          />
        </Field>
        <div className="schedule-form__hint">
          Все последующие непроведённые занятия сдвинутся на неделю позже — курс продлевается,
          отменённое занятие не списывается с абонемента.
        </div>
      </Dialog>

      {/* Доп. занятие */}
      <Dialog
        open={dialog === 'extra'}
        onOpenChange={(o) => !o && closeDialog()}
        title="Доп. занятие"
        footer={
          <Button variant="primary" onClick={() => { void submitExtra(); }} disabled={addExtra.isPending}>
            Добавить
          </Button>
        }
      >
        <Field label="Дата" required>
          <DateInput value={eDate} onChange={(e) => setEDate(e.target.value)} />
        </Field>
        <Field label="Время" required>
          <TimeInput value={eTime} onChange={(e) => setETime(e.target.value)} />
        </Field>
        <Field label="Преподаватель">
          <Combobox value={eTeacherId} onChange={setETeacherId} options={teacherOptions} placeholder="Выберите преподавателя" />
        </Field>
      </Dialog>
    </div>
  );
});

export default GroupPlanActions;
