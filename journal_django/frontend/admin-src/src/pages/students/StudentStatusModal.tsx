import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { SelectInput } from '../../components/form/SelectInput';
import { DateInput } from '../../components/form/DateInput';
import { Checkbox } from '../../components/form/Checkbox';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { api, ApiError, extractErrorDetail } from '../../lib/api';
import { fmtDate, todayMSK } from '../../lib/format';
import { ENROLLMENT_STATUS_OPTIONS } from '../../lib/labels';
import type { EnrollmentStatus, Student } from '../../lib/types';

export interface StatusModalMembership {
  id: number;
  group_name: string;
  is_individual: boolean;
}

interface Props {
  studentId: number;
  open: boolean;
  onClose: () => void;
  memberships: StatusModalMembership[];
  initialStatus?: EnrollmentStatus;
}

// Короткие пояснения под селектом — снимают путаницу «Не учится» vs «Заморожен».
const STATUS_HELP: Record<EnrollmentStatus, string> = {
  enrolled: 'Ученик учится в обычном режиме — посещаемость и оплаты идут как раньше.',
  not_enrolled: 'Ученик отчислен без сохранения места. Это НЕ то же самое, что «Заморожен»: '
    + 'выбранные членства закрываются насовсем, а не приостанавливаются на срок.',
  frozen: 'Учёба приостановлена на период. Индивидуальные занятия сдвигаются на дату '
    + 'возврата, групповые членства закрываются на время заморозки — вернуть их можно '
    + 'кнопкой «Разморозить».',
  declined: 'Ученик отказался от обучения. Выбранные членства закрываются, сделка в '
    + 'воронке продлений помечается проигранной.',
};

export function StudentStatusModal({ studentId, open, onClose, memberships, initialStatus }: Props) {
  const qc = useQueryClient();
  const showError = useApiError();
  const { toast } = useToast();

  const [status, setStatus] = useState<EnrollmentStatus>(initialStatus || 'enrolled');
  const [frozenFrom, setFrozenFrom] = useState(todayMSK());
  const [frozenUntil, setFrozenUntil] = useState('');
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [dateError, setDateError] = useState<string | undefined>();

  useEffect(() => {
    if (open) {
      setStatus(initialStatus || 'enrolled');
      setFrozenFrom(todayMSK());
      setFrozenUntil('');
      setSelectedIds(memberships.map((m) => m.id));
      setDateError(undefined);
    }
    // memberships пересобирается на каждом рендере родителя — сравнивать нет смысла,
    // достаточно синхронизации по факту открытия модалки.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialStatus]);

  const needsDates = status === 'frozen';
  const needsMemberships = status === 'frozen' || status === 'declined' || status === 'not_enrolled';

  const individualMemberships = useMemo(
    () => memberships.filter((m) => m.is_individual), [memberships],
  );
  const groupMemberships = useMemo(
    () => memberships.filter((m) => !m.is_individual), [memberships],
  );

  const toggleMembership = (id: number) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const showIndividualNote = status === 'frozen'
    && individualMemberships.some((m) => selectedIds.includes(m.id));

  const mutation = useMutation({
    mutationFn: () => api<Student>('POST', `/api/admin/students/${studentId}/status`, {
      status,
      ...(needsDates ? { frozen_from: frozenFrom, frozen_until: frozenUntil } : {}),
      ...(needsMemberships ? { membership_ids: selectedIds } : {}),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['students'] });
      qc.invalidateQueries({ queryKey: ['memberships'] });
      // frozen/declined каскадом двигают сделку продления (engine.freeze_deal/
      // decline_deal) — без этого канбан-доска не отразит перенос карточки.
      qc.invalidateQueries({ queryKey: ['renewals'] });
      toast('Статус изменён', 'ok');
      onClose();
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        const detail = extractErrorDetail(err.details);
        showError(detail ? new Error(detail) : err, 'Не удалось изменить статус');
      } else {
        showError(err, 'Не удалось изменить статус');
      }
    },
  });

  const handleSubmit = () => {
    setDateError(undefined);
    if (needsDates) {
      if (!frozenFrom || !frozenUntil) {
        setDateError('Заполните обе даты');
        return;
      }
      if (frozenFrom > frozenUntil) {
        setDateError('Дата начала не может быть позже даты окончания');
        return;
      }
    }
    mutation.mutate();
  };

  const statusLabel = ENROLLMENT_STATUS_OPTIONS.find((o) => o.value === status)?.label || status;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="Изменить статус ученика">
      <div className="status-form">
        <Field label="Новый статус">
          <SelectInput
            value={status}
            onChange={(e) => setStatus(e.target.value as EnrollmentStatus)}
            options={ENROLLMENT_STATUS_OPTIONS}
          />
        </Field>
        <div className="status-form__hint">{STATUS_HELP[status]}</div>

        {needsDates && (
          <div className="field-row">
            <Field label="Заморозка с">
              <DateInput value={frozenFrom} onChange={(e) => { setFrozenFrom(e.target.value); setDateError(undefined); }} />
            </Field>
            <Field label="Заморозка до" error={dateError}>
              <DateInput value={frozenUntil} onChange={(e) => { setFrozenUntil(e.target.value); setDateError(undefined); }} />
            </Field>
          </div>
        )}

        {needsMemberships && memberships.length > 0 && (
          <div className="status-form__group">
            <div className="status-form__group-label">Какие группы закрыть</div>
            {individualMemberships.length > 0 && (
              <div className="status-form__subgroup">
                <div className="status-form__subgroup-label">Индивидуальные</div>
                {individualMemberships.map((m) => (
                  <Checkbox
                    key={m.id}
                    label={m.group_name}
                    checked={selectedIds.includes(m.id)}
                    onChange={() => toggleMembership(m.id)}
                  />
                ))}
              </div>
            )}
            {groupMemberships.length > 0 && (
              <div className="status-form__subgroup">
                <div className="status-form__subgroup-label">Групповые</div>
                {groupMemberships.map((m) => (
                  <Checkbox
                    key={m.id}
                    label={m.group_name}
                    checked={selectedIds.includes(m.id)}
                    onChange={() => toggleMembership(m.id)}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {showIndividualNote && (
          <div className="status-form__warn">
            Плановые уроки индива будут сдвинуты; доп.занятия и переносы в окне будут отменены.
          </div>
        )}

        <div className="status-form__summary">
          Статус изменится на «{statusLabel}»
          {needsDates && frozenFrom && frozenUntil && ` (${fmtDate(frozenFrom)} — ${fmtDate(frozenUntil)})`}.
        </div>

        <div className="status-form__footer">
          <button type="button" className="btn-cancel" onClick={onClose}>Отмена</button>
          <button
            type="button"
            className="btn-save"
            onClick={handleSubmit}
            disabled={mutation.isPending}
          >
            Сохранить
          </button>
        </div>
      </div>
    </Dialog>
  );
}
