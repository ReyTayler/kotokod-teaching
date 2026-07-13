import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { EntityLink } from '../../components/EntityLink';
import { Dialog } from '../../components/ui/Dialog';
import { Field } from '../../components/form/Field';
import { SelectInput } from '../../components/form/SelectInput';
import { DateInput } from '../../components/form/DateInput';
import { Textarea } from '../../components/form/Textarea';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import {
  useRenewalActivity, useRenewalAssignees, useRenewalDeal, useRenewalMutations,
} from '../../hooks/useRenewals';
import { useRenewalStages } from '../../hooks/useRenewalStages';
import { useApiError } from '../../hooks/useApiError';
import { fmtDate, fmtDateTime, fmtLessons } from '../../lib/format';
import { RENEWAL_STAGE_LABELS } from '../../lib/labels';
import { StageBadge } from './StageBadge';
import { RenewalCloseDialog, type CloseDialogTarget } from './RenewalCloseDialog';
import type { RenewalActivityItem } from '../../lib/renewals';

interface Props {
  id: number;
  onClose: () => void;
}

function ActivityLine({ item }: { item: RenewalActivityItem }) {
  let body: ReactNode;
  switch (item.kind) {
    case 'stage_change':
      body = <>{item.from_label ?? '—'} → {item.to_label ?? '—'}</>;
      break;
    case 'comment':
      body = <>💬 {item.body}</>;
      break;
    case 'payment_linked':
      body = <>💰 Оплата #{item.payment_id ?? '—'}</>;
      break;
    default:
      body = <>{item.body}</>;
  }
  return (
    <li className="renewal-timeline__item">
      <div className="renewal-timeline__body">{body}</div>
      <div className="renewal-timeline__meta">
        {item.author_name && <span>{item.author_name}</span>}
        {item.created_at && <span>{fmtDateTime(item.created_at)}</span>}
      </div>
    </li>
  );
}

export function RenewalDrawer({ id, onClose }: Props) {
  const { data: deal, isLoading: dealLoading } = useRenewalDeal(id);
  const { data: activity, isLoading: activityLoading } = useRenewalActivity(id);
  const { data: stages } = useRenewalStages();
  const { data: assignees } = useRenewalAssignees();
  const { comment, patch, move, reopen } = useRenewalMutations();
  const { open: openPayment } = usePaymentModal();
  const showError = useApiError();
  const [text, setText] = useState('');
  const [closeTarget, setCloseTarget] = useState<CloseDialogTarget | null>(null);
  const [confirmReopen, setConfirmReopen] = useState(false);

  // onClose обычно приходит как новая инлайн-функция от родителя на каждый рендер —
  // без useCallback здесь listener пересоздавался бы при каждом ре-рендере RenewalDrawer.
  const handleEscape = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  }, [onClose]);

  useEffect(() => {
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [handleEscape]);

  const handleAddComment = () => {
    const body = text.trim();
    if (!body) return;
    comment.mutate({ id, body }, { onSuccess: () => setText('') });
  };

  const save = (body: Record<string, unknown>) =>
    patch.mutate({ id, body }, {
      onError: (err) => showError(err, 'Не удалось сохранить изменение'),
    });

  // Смена стадии из карточки: открытые стадии — сразу move; won/lost — через
  // тот же диалог закрытия, что и на доске (причина/оплата, ничего молча).
  const handleStageChange = (stageIdStr: string) => {
    if (!deal || !stageIdStr) return;
    const stageId = Number(stageIdStr);
    if (stageId === deal.stage_id) return;
    const target = (stages || []).find((s) => s.id === stageId);
    if (!target) return;
    if (target.kind === 'won' || target.kind === 'lost') {
      setCloseTarget({
        dealId: deal.id,
        studentId: deal.student_id,
        studentName: deal.student_name,
        mode: target.kind,
      });
      return;
    }
    move.mutate({ id: deal.id, to_stage_id: stageId }, {
      onError: (err) => showError(err, 'Не удалось сменить стадию'),
    });
  };

  const handleCloseConfirm = ({ reason_code, comment: dialogText }:
    { reason_code?: string; comment?: string }) => {
    if (!closeTarget) return;
    const stage = (stages || []).find((s) => s.kind === closeTarget.mode);
    if (!stage) {
      setCloseTarget(null);
      return;
    }
    move.mutate(
      { id: closeTarget.dealId, to_stage_id: stage.id, reason_code },
      {
        onSuccess: () => {
          if (dialogText) comment.mutate({ id: closeTarget.dealId, body: dialogText });
          setCloseTarget(null);
        },
        onError: (err) => {
          setCloseTarget(null);
          showError(err, 'Не удалось закрыть сделку');
        },
      },
    );
  };

  const stageLabel = deal?.stage_label || (deal ? RENEWAL_STAGE_LABELS[deal.stage_key] : undefined);
  const isClosed = deal?.outcome_at != null;
  const openStages = (stages || []).filter((s) => s.kind === 'progress' || s.kind === 'decision');
  const closeStages = (stages || []).filter((s) => s.kind === 'won' || s.kind === 'lost');

  return (
    <div className="renewal-drawer-overlay" onClick={onClose}>
      <aside
        className="renewal-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Карточка сделки"
        onClick={(e) => e.stopPropagation()}
      >
        {dealLoading || !deal ? (
          <div className="renewal-drawer__loading">Загружаем сделку…</div>
        ) : (
          <>
            <header className="renewal-drawer__head">
              <div className="renewal-drawer__title">
                <EntityLink section="students" id={deal.student_id} text={deal.student_name} />
              </div>
              <button
                type="button"
                className="renewal-drawer__close"
                onClick={onClose}
                aria-label="Закрыть"
              >
                ✕
              </button>
            </header>

            <div className="renewal-drawer__subhead">
              <span>
                {(deal.directions || []).map((d, i) => (
                  <span key={d.name} style={d.color ? { color: d.color } : undefined}>
                    {i > 0 && ', '}{d.name}
                  </span>
                ))}
                {(deal.directions || []).length === 0 && '—'}
              </span>
              <span> · Цикл {deal.cycle_no}</span>
              {stageLabel && <StageBadge label={stageLabel} kind={deal.stage_kind} />}
            </div>

            <div className="renewal-drawer__section renewal-drawer__progress">
              {!isClosed && (
                deal.cycle_completed
                  ? (
                    <span className="status-badge status-badge--info">
                      Цикл отработан{deal.due_at ? ` ${fmtDate(deal.due_at)}` : ''} — пора продлевать
                    </span>
                  )
                  : <span>Урок {deal.lesson_in_cycle} из 4</span>
              )}
              {deal.debt && (
                <span className="status-badge status-badge--negative" title="Баланс ученика отрицательный">
                  Долг
                </span>
              )}
            </div>

            <div className="renewal-drawer__section renewal-drawer__balance">
              <span className="renewal-drawer__balance-label">Баланс</span>
              <span className="renewal-drawer__balance-value">{fmtLessons(deal.balance)} ур.</span>
            </div>

            {isClosed ? (
              <div className="renewal-drawer__section renewal-drawer__closed">
                <span className={`status-badge${deal.stage_kind === 'won' ? ' status-badge--positive' : ' status-badge--negative'}`}>
                  {deal.stage_kind === 'won' ? 'Продлена' : 'Закрыта'} {fmtDateTime(deal.outcome_at!)}
                </span>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={reopen.isPending}
                  onClick={() => setConfirmReopen(true)}
                >
                  Переоткрыть
                </button>
              </div>
            ) : (
              <>
                <div className="renewal-drawer__section renewal-drawer__fields">
                  <Field label="Стадия">
                    <SelectInput
                      value={String(deal.stage_id)}
                      onChange={(e) => handleStageChange(e.target.value)}
                      options={[
                        ...openStages.map((s) => ({ value: String(s.id), label: s.label })),
                        ...closeStages.map((s) => ({
                          value: String(s.id),
                          label: s.kind === 'won' ? `✓ ${s.label}…` : `✕ ${s.label}…`,
                        })),
                      ]}
                    />
                  </Field>
                  <Field label="Ответственный">
                    <SelectInput
                      value={deal.assignee_id != null ? String(deal.assignee_id) : ''}
                      onChange={(e) => save({ assignee_id: e.target.value ? Number(e.target.value) : null })}
                      options={[
                        { value: '', label: '— не назначен —' },
                        ...(assignees || []).map((a) => ({ value: String(a.id), label: a.full_name })),
                      ]}
                    />
                  </Field>
                  <Field label="Следующее касание">
                    <DateInput
                      value={deal.next_touch_at ?? ''}
                      onChange={(e) => save({ next_touch_at: e.target.value || null })}
                    />
                  </Field>
                </div>

                <button
                  type="button"
                  className="btn-secondary renewal-drawer__pay-btn"
                  onClick={() => openPayment({ studentId: deal.student_id })}
                >
                  Внести оплату
                </button>
              </>
            )}

            <div className="renewal-drawer__section">
              <div className="renewal-drawer__section-title">Комментарий</div>
              <Textarea
                className="renewal-drawer__comment-input"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Добавить комментарий по сделке…"
                rows={3}
              />
              <button
                type="button"
                className="btn-secondary"
                disabled={!text.trim() || comment.isPending}
                onClick={handleAddComment}
              >
                Добавить
              </button>
            </div>

            <div className="renewal-drawer__section renewal-drawer__timeline-section">
              <div className="renewal-drawer__section-title">Активность</div>
              {activityLoading ? (
                <div className="renewal-drawer__loading">Загружаем активность…</div>
              ) : (
                <ul className="renewal-timeline">
                  {(activity || []).map((item) => (
                    <ActivityLine key={item.id} item={item} />
                  ))}
                  {(!activity || activity.length === 0) && (
                    <li className="renewal-timeline__empty">Пока нет активности</li>
                  )}
                </ul>
              )}
            </div>

            {closeTarget && (
              <RenewalCloseDialog
                target={closeTarget}
                pending={move.isPending}
                onClose={() => setCloseTarget(null)}
                onConfirm={handleCloseConfirm}
              />
            )}

            {confirmReopen && (
              <Dialog
                open
                onOpenChange={(o) => { if (!o) setConfirmReopen(false); }}
                title="Переоткрыть сделку?"
                footer={
                  <>
                    <button type="button" className="btn-secondary" onClick={() => setConfirmReopen(false)}>
                      Отмена
                    </button>
                    <button
                      type="button"
                      className="btn-primary"
                      disabled={reopen.isPending}
                      onClick={() => reopen.mutate({ id }, {
                        onSuccess: () => setConfirmReopen(false),
                        onError: (err) => {
                          setConfirmReopen(false);
                          showError(err, 'Не удалось переоткрыть сделку');
                        },
                      })}
                    >
                      Переоткрыть
                    </button>
                  </>
                }
              >
                <p className="renewal-close-dialog__text">
                  Сделка вернётся на доску в актуальную стадию по посещаемости и
                  балансу. Если при закрытии была создана нетронутая сделка
                  следующего месяца — она будет удалена.
                </p>
              </Dialog>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
