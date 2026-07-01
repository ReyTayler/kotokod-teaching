import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStudentMutations } from '../../hooks/useStudents';
import { useMemberships, useMembershipMutations } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { TextInput } from '../../components/form/TextInput';
import { NumberInput } from '../../components/form/NumberInput';
import { DateInput } from '../../components/form/DateInput';
import { SelectInput } from '../../components/form/SelectInput';
import { MONTHS_RU } from '../../lib/slots';
import { ENROLLMENT_STATUS_OPTIONS } from '../../lib/labels';
import type { Student, EnrollmentStatus } from '../../lib/types';

interface FormState {
  full_name: string;
  birth_date: string;
  phone: string;
  age: string;
  school_grade: string;
  parent_name: string;
  enrollment_status: EnrollmentStatus;
  frozen_until_month: string;
  first_purchase_date: string;
  pm: string;
  platform_id: string;
}

const toYMD = (v: string | null | undefined): string => (v ? String(v).slice(0, 10) : '');

function toForm(s: Student | null): FormState {
  return {
    full_name: s?.full_name || '',
    birth_date: toYMD(s?.birth_date),
    phone: s?.phone || '',
    age: s?.age != null ? String(s.age) : '',
    school_grade: s?.school_grade != null ? String(s.school_grade) : '',
    parent_name: s?.parent_name || '',
    enrollment_status: s?.enrollment_status || 'enrolled',
    frozen_until_month: s?.frozen_until_month != null ? String(s.frozen_until_month) : '',
    first_purchase_date: toYMD(s?.first_purchase_date),
    pm: s?.pm || '',
    platform_id: s?.platform_id || '',
  };
}

interface Props { initial: Student | null; onClose: () => void; }

export default function StudentFormModal({ initial, onClose }: Props) {
  const isNew = !initial;
  const navigate = useNavigate();
  const muts = useStudentMutations();
  const memberMuts = useMembershipMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [form, setForm] = useState<FormState>(() => toForm(initial));

  // Memberships ученика — чтобы очистить после статуса frozen/declined
  const { data: memberships = [] } = useMemberships(
    initial ? { student_id: initial.id } : { student_id: 0 },
  );

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();

    let frozenMonth: number | null = form.frozen_until_month === '' ? null : Number(form.frozen_until_month);
    let status: EnrollmentStatus = form.enrollment_status;
    if (frozenMonth != null) status = 'frozen';
    if (status !== 'frozen') frozenMonth = null;

    const body: Partial<Student> = {
      full_name: form.full_name,
      birth_date: form.birth_date || null,
      phone: form.phone || null,
      age: form.age === '' ? null : Number(form.age),
      school_grade: form.school_grade === '' ? null : Number(form.school_grade),
      parent_name: form.parent_name || null,
      enrollment_status: status,
      frozen_until_month: frozenMonth,
      first_purchase_date: form.first_purchase_date || null,
      pm: form.pm || null,
      platform_id: form.platform_id || null,
    };

    try {
      let resultId: number;
      if (isNew) {
        const created = await muts.create.mutateAsync(body);
        toast('Создано', 'ok');
        resultId = created.id;
      } else {
        const updated = await muts.update.mutateAsync({ id: initial!.id, body });
        toast('Сохранено', 'ok');
        resultId = updated.id;
      }

      if (status === 'frozen' || status === 'declined') {
        const targetMemberships = isNew ? [] : memberships;
        await Promise.all(targetMemberships.map((m) => memberMuts.remove.mutateAsync(m.id)));
      }

      onClose();
      if (isNew) navigate(`/admin/students/${resultId}`);
    } catch (err) {
      showError(err);
    }
  };

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      wide
      title={isNew ? 'Новый ученик' : `Редактировать: ${initial!.full_name}`}
      footer={
        <button
          type="submit"
          form="student-form"
          className="btn-add"
          disabled={muts.create.isPending || muts.update.isPending}
        >Сохранить</button>
      }
    >
      <form id="student-form" onSubmit={onSubmit}>
        <div className="modal-section-label">Личные данные</div>
        <Field label="ФИО" required>
          <TextInput required value={form.full_name} onChange={(e) => set('full_name', e.target.value)} placeholder="Иванов Иван Иванович" />
        </Field>
        <Field label="Дата рождения">
          <DateInput value={form.birth_date} onChange={(e) => set('birth_date', e.target.value)} />
        </Field>
        <Field label="Телефон">
          <TextInput value={form.phone} onChange={(e) => set('phone', e.target.value)} placeholder="+7 (___) ___-__-__" />
        </Field>
        <Field label="Возраст">
          <NumberInput min={0} max={120} value={form.age} onChange={(e) => set('age', e.target.value)} placeholder="12" />
        </Field>
        <Field label="Класс школы">
          <NumberInput min={1} max={11} value={form.school_grade} onChange={(e) => set('school_grade', e.target.value)} placeholder="7" />
        </Field>
        <Field label="Имя родителя">
          <TextInput value={form.parent_name} onChange={(e) => set('parent_name', e.target.value)} />
        </Field>

        <div className="modal-section-label">Обучение</div>
        <Field label="Статус">
          <SelectInput
            value={form.enrollment_status}
            onChange={(e) => set('enrollment_status', e.target.value as EnrollmentStatus)}
            options={ENROLLMENT_STATUS_OPTIONS}
          />
        </Field>
        <Field label="Заморожен до">
          <SelectInput
            value={form.frozen_until_month}
            onChange={(e) => set('frozen_until_month', e.target.value)}
            options={[
              { value: '', label: '— не выбрано —' },
              ...MONTHS_RU.map((m, i) => ({ value: i + 1, label: m })),
            ]}
          />
        </Field>
        <Field label="Дата первой оплаты">
          <DateInput value={form.first_purchase_date} onChange={(e) => set('first_purchase_date', e.target.value)} />
        </Field>
        <Field label="Менеджер (PM)">
          <TextInput value={form.pm} onChange={(e) => set('pm', e.target.value)} />
        </Field>

        <div className="modal-section-label">Система</div>
        <Field label="Platform ID">
          <TextInput value={form.platform_id} onChange={(e) => set('platform_id', e.target.value)} placeholder="внешний идентификатор" />
        </Field>
      </form>
    </Dialog>
  );
}
