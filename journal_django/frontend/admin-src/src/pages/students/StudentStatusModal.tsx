import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { SelectInput } from '../../components/form/SelectInput';
import { DateInput } from '../../components/form/DateInput';
import { Checkbox } from '../../components/form/Checkbox';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { api, ApiError, extractErrorDetail, scheduledMakeupsBlockMessage } from '../../lib/api';
import { ScheduledMakeupsBlockModal } from '../../components/memberships/ScheduledMakeupsBlockModal';
import { fmtDate, todayMSK } from '../../lib/format';
import { ENROLLMENT_STATUS_OPTIONS } from '../../lib/labels';
import type { EnrollmentStatus, Student } from '../../lib/types';
import type { AffectedOp } from '../../hooks/useGroupPlan';

export interface StatusModalMembership {
  id: number;
  group_name: string;
  is_individual: boolean;
}

// Ответ POST .../status/preview: плоский словарь membership_id (строкой, т.к.
// ключи JSON-объекта всегда строки) → результат дран-превью сдвига расписания.
// affected — те же разовые операции хвоста (переносы/замены/отмены), что
// preview_affected уже отдаёт диалогу «Изменить расписание» (useGroupPlan.ts) —
// заморозка сбрасывает их точно так же, как permanent-change.
type FreezePreviewEntry = {
  lesson_on_frozen_from: boolean;
  first_lesson_after_resume: string | null;
  affected: AffectedOp[];
};
type FreezePreviewResponse = Record<string, FreezePreviewEntry>;

// Те же подписи, что AFFECTED_KIND_LABELS в GroupPlanActions.tsx (permanent-change
// preview) — держим текст одинаковым для одного и того же понятия в разных местах.
const AFFECTED_KIND_LABELS: Record<AffectedOp['kind'], string> = {
  reschedule: 'перенос',
  substitution: 'замена преподавателя',
  cancellation: 'отмена',
};

// Компактная агрегация для инлайн-подсказки под чекбоксом (не полный список —
// полный список показывается в диалоге подтверждения ниже).
function summarizeAffected(ops: AffectedOp[]): string {
  const counts: Record<AffectedOp['kind'], number> = { reschedule: 0, substitution: 0, cancellation: 0 };
  ops.forEach((op) => { counts[op.kind] += 1; });
  return (['reschedule', 'substitution', 'cancellation'] as const)
    .filter((k) => counts[k] > 0)
    .map((k) => `${AFFECTED_KIND_LABELS[k]} (${counts[k]})`)
    .join(', ');
}

// Сколько ждать после последнего изменения дат/чекбоксов, прежде чем дёрнуть
// превью — не гоняем запрос на каждое нажатие клавиши/чекбокс.
const PREVIEW_DEBOUNCE_MS = 450;

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
  // Дата frozen_from, для которой админ уже подтвердил совпадение урока с
  // датой заморозки в диалоге-предупреждении. Сбрасывается при любом изменении
  // frozen_from — старое подтверждение не должно молча «прилипать» к новой дате.
  const [coincidenceConfirmedFor, setCoincidenceConfirmedFor] = useState<string | null>(null);
  const [showCoincidenceConfirm, setShowCoincidenceConfirm] = useState(false);
  // Сигнатура previewInput (см. ниже), для которой админ уже подтвердил сброс
  // разовых операций хвоста — сбрасывается при любом изменении дат/выбора индива.
  const [affectedConfirmedFor, setAffectedConfirmedFor] = useState<string | null>(null);
  const [showAffectedConfirm, setShowAffectedConfirm] = useState(false);
  // Блок «есть назначенные доп.уроки» при снятии членства (заморозка/уход) — модалка.
  const [blockMsg, setBlockMsg] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setStatus(initialStatus || 'enrolled');
      setFrozenFrom(todayMSK());
      setFrozenUntil('');
      setSelectedIds(memberships.map((m) => m.id));
      setDateError(undefined);
      setCoincidenceConfirmedFor(null);
      setShowCoincidenceConfirm(false);
      setAffectedConfirmedFor(null);
      setShowAffectedConfirm(false);
    }
    // memberships пересобирается на каждом рендере родителя — сравнивать нет смысла,
    // достаточно синхронизации по факту открытия модалки.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialStatus]);

  // Смена даты начала заморозки обнуляет ранее полученное подтверждение
  // совпадения — иначе смена даты «задним числом» проскочит без вопроса.
  useEffect(() => {
    setCoincidenceConfirmedFor(null);
  }, [frozenFrom]);

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

  // Выбранные индив-членства — единственные, для которых дран-превью
  // расписания вообще имеет смысл (у групповых расписание не сдвигается).
  const selectedIndividualIds = useMemo(
    () => individualMemberships
      .filter((m) => selectedIds.includes(m.id))
      .map((m) => m.id)
      .sort((a, b) => a - b),
    [individualMemberships, selectedIds],
  );
  const selectedIndividualIdsKey = selectedIndividualIds.join(',');

  // Дебаунс входных данных превью — не дёргаем сервер на каждое нажатие
  // клавиши в поле даты или переключение чекбокса.
  const [previewInput, setPreviewInput] = useState({
    from: frozenFrom, until: frozenUntil, idsKey: selectedIndividualIdsKey,
  });
  useEffect(() => {
    const t = setTimeout(() => {
      setPreviewInput({ from: frozenFrom, until: frozenUntil, idsKey: selectedIndividualIdsKey });
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [frozenFrom, frozenUntil, selectedIndividualIdsKey]);

  // Сигнатура текущего (дебаунснутого) превью-запроса — по ней и сбрасываем
  // ранее данное подтверждение сброса разовых операций (см. affectedConfirmedFor).
  const previewInputSignature = `${previewInput.from}|${previewInput.until}|${previewInput.idsKey}`;
  useEffect(() => {
    setAffectedConfirmedFor(null);
  }, [previewInputSignature]);

  const previewEnabled = open && status === 'frozen'
    && !!previewInput.from && !!previewInput.until && previewInput.from <= previewInput.until
    && previewInput.idsKey.length > 0;

  const previewQuery = useQuery({
    queryKey: ['student-freeze-preview', studentId, previewInput.from, previewInput.until, previewInput.idsKey],
    queryFn: () => api<FreezePreviewResponse>('POST', `/api/admin/students/${studentId}/status/preview`, {
      frozen_from: previewInput.from,
      frozen_until: previewInput.until,
      membership_ids: previewInput.idsKey.split(',').map(Number),
    }),
    enabled: previewEnabled,
    staleTime: 30_000,
    retry: false,
  });

  // Индив-членства из выбранных, у которых на дату frozen_from стоит урок —
  // требуют явного подтверждения перед сохранением (урок будет отменён).
  const coincidentMemberships = useMemo(() => {
    if (status !== 'frozen' || !previewQuery.data) return [];
    return individualMemberships.filter(
      (m) => selectedIds.includes(m.id) && previewQuery.data?.[String(m.id)]?.lesson_on_frozen_from,
    );
  }, [status, previewQuery.data, individualMemberships, selectedIds]);

  const hasUnconfirmedCoincidence = coincidentMemberships.length > 0
    && coincidenceConfirmedFor !== frozenFrom;

  // Разовые операции хвоста (переносы/замены/отмены) в окне заморозки по всем
  // выбранным индив-членствам — сплющены в один список с привязкой к группе,
  // для диалога подтверждения ниже (мультичленства показываются одним списком).
  const allAffectedOps = useMemo(() => {
    if (status !== 'frozen' || !previewQuery.data) return [];
    return selectedIndividualIds.flatMap((id) => {
      const preview = previewQuery.data?.[String(id)];
      if (!preview?.affected.length) return [];
      const groupName = individualMemberships.find((m) => m.id === id)?.group_name || '';
      return preview.affected.map((op) => ({ ...op, membershipId: id, groupName }));
    });
  }, [status, previewQuery.data, selectedIndividualIds, individualMemberships]);

  const hasUnconfirmedAffected = allAffectedOps.length > 0
    && affectedConfirmedFor !== previewInputSignature;

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
      const block = scheduledMakeupsBlockMessage(err);
      if (block) { setBlockMsg(block); return; }
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
    if (hasUnconfirmedCoincidence) {
      setShowCoincidenceConfirm(true);
      return;
    }
    if (hasUnconfirmedAffected) {
      setShowAffectedConfirm(true);
      return;
    }
    mutation.mutate();
  };

  const confirmCoincidenceAndSubmit = () => {
    setCoincidenceConfirmedFor(frozenFrom);
    setShowCoincidenceConfirm(false);
    // Оба диалога — последовательные гейты: если после подтверждения
    // совпадения ещё остались неподтверждённые разовые операции, спрашиваем
    // и про них, а не проваливаемся молча сразу к сохранению.
    if (hasUnconfirmedAffected) {
      setShowAffectedConfirm(true);
      return;
    }
    mutation.mutate();
  };

  const confirmAffectedAndSubmit = () => {
    setAffectedConfirmedFor(previewInputSignature);
    setShowAffectedConfirm(false);
    mutation.mutate();
  };

  const statusLabel = ENROLLMENT_STATUS_OPTIONS.find((o) => o.value === status)?.label || status;
  // Прямой frozen→enrolled запрещён бэком (ValueError, 400) — выход из заморозки
  // только через отдельную кнопку «Разморозить». Если этот модал открыт для уже
  // замороженного ученика (initialStatus==='frozen'), не предлагаем тупиковый вариант.
  const statusOptions = initialStatus === 'frozen'
    ? ENROLLMENT_STATUS_OPTIONS.filter((o) => o.value !== 'enrolled')
    : ENROLLMENT_STATUS_OPTIONS;

  const coincidenceMessage = coincidentMemberships.length === 1
    ? `На ${fmtDate(frozenFrom)} стоит урок в группе «${coincidentMemberships[0].group_name}». `
      + 'Заморозка точно с этой даты (урок будет отменён)?'
    : `На ${fmtDate(frozenFrom)} стоит урок в группах: ${coincidentMemberships.map((m) => m.group_name).join(', ')}. `
      + 'Заморозка точно с этой даты (уроки будут отменены)?';

  return (
    <>
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="Изменить статус ученика">
      <div className="status-form">
        <Field label="Новый статус">
          <SelectInput
            value={status}
            onChange={(e) => setStatus(e.target.value as EnrollmentStatus)}
            options={statusOptions}
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
                {individualMemberships.map((m) => {
                  const selected = selectedIds.includes(m.id);
                  const preview = previewQuery.data?.[String(m.id)];
                  return (
                    <div key={m.id}>
                      <Checkbox
                        label={m.group_name}
                        checked={selected}
                        onChange={() => toggleMembership(m.id)}
                      />
                      {status === 'frozen' && selected && (
                        <div className="status-form__membership-preview">
                          {preview
                            ? (preview.first_lesson_after_resume
                              ? `Первый урок после разморозки: ${fmtDate(preview.first_lesson_after_resume)}`
                              : 'Нет запланированных уроков в этом периоде')
                            : previewQuery.isFetching
                              ? 'Проверяем расписание…'
                              : (previewQuery.isError && previewEnabled
                                ? 'Не удалось проверить расписание — совпадение с уроком не проверено'
                                : null)}
                        </div>
                      )}
                      {status === 'frozen' && selected && preview && preview.affected.length > 0 && (
                        <div className="status-form__membership-preview">
                          Будут сброшены разовые операции: {summarizeAffected(preview.affected)}
                        </div>
                      )}
                    </div>
                  );
                })}
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

    {showCoincidenceConfirm && (
      <Dialog
        open={showCoincidenceConfirm}
        onOpenChange={(o) => { if (!o) setShowCoincidenceConfirm(false); }}
        title="Урок в день начала заморозки"
      >
        <div className="status-form">
          <p className="status-form__hint">{coincidenceMessage}</p>
          <div className="status-form__footer">
            <button type="button" className="btn-cancel" onClick={() => setShowCoincidenceConfirm(false)}>
              Изменить дату
            </button>
            <button
              type="button"
              className="btn-save"
              onClick={confirmCoincidenceAndSubmit}
              disabled={mutation.isPending}
            >
              Да, продолжить
            </button>
          </div>
        </div>
      </Dialog>
    )}

    {showAffectedConfirm && (
      <Dialog
        open={showAffectedConfirm}
        onOpenChange={(o) => { if (!o) setShowAffectedConfirm(false); }}
        title="Разовые операции будут сброшены"
      >
        <div className="status-form">
          <p className="status-form__hint">
            В периоде заморозки есть разовые операции по расписанию — при заморозке
            они будут сброшены:
          </p>
          <ul className="affected-ops-list">
            {allAffectedOps.map((op, i) => (
              <li key={`${op.membershipId}-${i}`} className="affected-ops-list__item">
                <span className="status-badge status-badge--negative">{AFFECTED_KIND_LABELS[op.kind]}</span>
                <span>«{op.groupName}»</span>
                {op.seq != null && <span>урок {op.seq}</span>}
                <span>— {fmtDate(op.date)}</span>
                {op.time && <span>{op.time.slice(0, 5)}</span>}
                {op.from_date && <span>(было {fmtDate(op.from_date)})</span>}
              </li>
            ))}
          </ul>
          <div className="status-form__footer">
            <button type="button" className="btn-cancel" onClick={() => setShowAffectedConfirm(false)}>
              Отмена
            </button>
            <button
              type="button"
              className="btn-save"
              onClick={confirmAffectedAndSubmit}
              disabled={mutation.isPending}
            >
              Заморозить и сбросить
            </button>
          </div>
        </div>
      </Dialog>
    )}

    {blockMsg && (
      <ScheduledMakeupsBlockModal message={blockMsg} onClose={() => setBlockMsg(null)} />
    )}
    </>
  );
}
