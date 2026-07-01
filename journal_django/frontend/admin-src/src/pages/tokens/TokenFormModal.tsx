import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTokenMutations } from '../../hooks/useTokens';
import { useTeachers } from '../../hooks/useTeachers';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { TextInput } from '../../components/form/TextInput';
import { SelectInput } from '../../components/form/SelectInput';
import { Checkbox } from '../../components/form/Checkbox';
import type { Token } from '../../lib/types';

interface Props { initial: Token | null; onClose: () => void; }

export default function TokenFormModal({ initial, onClose }: Props) {
  const isNew = !initial;
  const navigate = useNavigate();
  const muts = useTokenMutations();
  const { data: teachers = [] } = useTeachers(true);
  const { toast } = useToast();
  const showError = useApiError();
  const [tokenStr, setTokenStr] = useState(initial?.token || '');
  const [teacherId, setTeacherId] = useState<string>(initial?.teacher_id ? String(initial.teacher_id) : '');
  const [active, setActive] = useState(initial?.active ?? true);

  const teacherOptions = [{ value: '', label: '— выберите —' }, ...teachers
    .filter((t) => t.active || (initial && initial.teacher_id === t.id))
    .map((t) => ({ value: t.id, label: t.name }))];

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!teacherId) {
      toast('Выберите преподавателя', 'error');
      return;
    }
    try {
      if (isNew) {
        const created = await muts.create.mutateAsync({ token: tokenStr, teacher_id: Number(teacherId) });
        toast('Создано', 'ok');
        onClose();
        navigate(`/admin/tokens/${encodeURIComponent(created.token)}`);
      } else {
        await muts.update.mutateAsync({
          token: initial!.token,
          body: { teacher_id: Number(teacherId), active },
        });
        toast('Сохранено', 'ok');
        onClose();
      }
    } catch (err) { showError(err); }
  };

  const handleGenerate = async () => {
    try {
      const r = await muts.generate.mutateAsync();
      setTokenStr(r.token);
    } catch (err) { showError(err); }
  };

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={isNew ? 'Новый токен' : `Токен: ${initial!.token}`}
      footer={
        <button type="submit" form="token-form" className="btn-save"
          disabled={muts.create.isPending || muts.update.isPending}>Сохранить</button>
      }
    >
      <form id="token-form" onSubmit={onSubmit}>
        <Field label="Строка токена" required>
          <TextInput required value={tokenStr} onChange={(e) => setTokenStr(e.target.value)}
            placeholder="XXX-XXX-XXX" disabled={!isNew} />
          {isNew && (
            <button type="button" className="btn-secondary" style={{ marginTop: 6 }}
              onClick={() => { void handleGenerate(); }}
              disabled={muts.generate.isPending}
            >Сгенерировать</button>
          )}
        </Field>
        <Field label="Преподаватель" required>
          <SelectInput required value={teacherId} onChange={(e) => setTeacherId(e.target.value)} options={teacherOptions} />
        </Field>
        {!isNew && (
          <Field label="Активен">
            <Checkbox checked={active} onChange={(e) => setActive(e.target.checked)} />
          </Field>
        )}
      </form>
    </Dialog>
  );
}
