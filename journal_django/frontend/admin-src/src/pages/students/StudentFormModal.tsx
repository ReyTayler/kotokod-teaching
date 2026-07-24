import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStudentMutations } from '../../hooks/useStudents';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { TextInput } from '../../components/form/TextInput';
import { DateInput } from '../../components/form/DateInput';
import type { Student } from '../../lib/types';

interface FormState {
  full_name: string;
  birth_date: string;
  parent1_name: string;
  parent1_phone: string;
  parent1_email: string;
  parent2_name: string;
  parent2_phone: string;
  parent2_email: string;
  platform_id: string;
  bitrix24_link: string;
}

const toYMD = (v: string | null | undefined): string => (v ? String(v).slice(0, 10) : '');

function toForm(s: Student | null): FormState {
  return {
    full_name: s?.full_name || '',
    birth_date: toYMD(s?.birth_date),
    parent1_name: s?.parent1_name || '',
    parent1_phone: s?.parent1_phone || '',
    parent1_email: s?.parent1_email || '',
    parent2_name: s?.parent2_name || '',
    parent2_phone: s?.parent2_phone || '',
    parent2_email: s?.parent2_email || '',
    platform_id: s?.platform_id || '',
    bitrix24_link: s?.bitrix24_link || '',
  };
}

interface Props { initial: Student | null; onClose: () => void; }

export default function StudentFormModal({ initial, onClose }: Props) {
  const isNew = !initial;
  const navigate = useNavigate();
  const muts = useStudentMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [form, setForm] = useState<FormState>(() => toForm(initial));

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();

    const body: Partial<Student> = {
      full_name: form.full_name,
      birth_date: form.birth_date || null,
      parent1_name: form.parent1_name || null,
      parent1_phone: form.parent1_phone || null,
      parent1_email: form.parent1_email || null,
      parent2_name: form.parent2_name || null,
      parent2_phone: form.parent2_phone || null,
      parent2_email: form.parent2_email || null,
      platform_id: form.platform_id || null,
      bitrix24_link: form.bitrix24_link || null,
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
      <form id="student-form" className="modal-form" onSubmit={onSubmit}>
        <div className="modal-section-label">Личные данные</div>
        <Field label="ФИО" required full>
          <TextInput required value={form.full_name} onChange={(e) => set('full_name', e.target.value)} placeholder="Иванов Иван Иванович" />
        </Field>
        {/* Возраст не вводится — он вычисляется из даты рождения. */}
        <Field label="Дата рождения">
          <DateInput value={form.birth_date} onChange={(e) => set('birth_date', e.target.value)} />
        </Field>

        <div className="modal-section-label">Родитель 1</div>
        <Field label="Имя родителя 1">
          <TextInput value={form.parent1_name} onChange={(e) => set('parent1_name', e.target.value)} />
        </Field>
        <Field label="Телефон родителя 1">
          <TextInput value={form.parent1_phone} onChange={(e) => set('parent1_phone', e.target.value)} placeholder="+7 (___) ___-__-__" />
        </Field>
        <Field label="Почта родителя 1">
          <TextInput type="email" value={form.parent1_email} onChange={(e) => set('parent1_email', e.target.value)} placeholder="parent@example.com" />
        </Field>

        <div className="modal-section-label">Родитель 2</div>
        <Field label="Имя родителя 2">
          <TextInput value={form.parent2_name} onChange={(e) => set('parent2_name', e.target.value)} />
        </Field>
        <Field label="Телефон родителя 2">
          <TextInput value={form.parent2_phone} onChange={(e) => set('parent2_phone', e.target.value)} placeholder="+7 (___) ___-__-__" />
        </Field>
        <Field label="Почта родителя 2">
          <TextInput type="email" value={form.parent2_email} onChange={(e) => set('parent2_email', e.target.value)} placeholder="parent@example.com" />
        </Field>

        <div className="modal-section-label">Система</div>
        <Field label="Platform ID">
          <TextInput value={form.platform_id} onChange={(e) => set('platform_id', e.target.value)} placeholder="внешний идентификатор" />
        </Field>
        <Field label="Ссылка на Bitrix24">
          <TextInput type="url" value={form.bitrix24_link} onChange={(e) => set('bitrix24_link', e.target.value)} placeholder="https://..." />
        </Field>
      </form>
    </Dialog>
  );
}
