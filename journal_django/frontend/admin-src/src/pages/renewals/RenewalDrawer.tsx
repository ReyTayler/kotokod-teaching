import { useEffect, useState, type ReactNode } from 'react';
import { EntityLink } from '../../components/EntityLink';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import { useRenewalActivity, useRenewalDeal, useRenewalMutations } from '../../hooks/useRenewals';
import { fmtDateTime, fmtLessons, fmtRub } from '../../lib/format';
import { RENEWAL_STAGE_LABELS } from '../../lib/labels';
import { StageBadge } from './StageBadge';
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
      body = <>💰 Оплата #{item.payment_id}</>;
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
  const { comment } = useRenewalMutations();
  const { open: openPayment } = usePaymentModal();
  const [text, setText] = useState('');

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const handleAddComment = () => {
    const body = text.trim();
    if (!body) return;
    comment.mutate({ id, body }, { onSuccess: () => setText('') });
  };

  const stageLabel = deal?.stage_label || (deal ? RENEWAL_STAGE_LABELS[deal.stage_key] : undefined);

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
              <span style={deal.direction_color ? { color: deal.direction_color } : undefined}>
                {deal.direction_name}
              </span>
              <span> · Мес. {deal.cycle_no}</span>
              {stageLabel && <StageBadge label={stageLabel} kind={deal.stage_kind} />}
            </div>

            <div className="renewal-drawer__section renewal-drawer__balance">
              <span className="renewal-drawer__balance-label">Баланс</span>
              <span className="renewal-drawer__balance-value">{fmtLessons(deal.balance)} ур.</span>
              {deal.expected_amount && (
                <span className="renewal-drawer__balance-hint">Ожидаемая сумма: {fmtRub(deal.expected_amount)}</span>
              )}
            </div>

            <button
              type="button"
              className="btn-secondary renewal-drawer__pay-btn"
              onClick={() => openPayment({ studentId: deal.student_id, directionId: deal.direction_id })}
            >
              Внести оплату
            </button>

            <div className="renewal-drawer__section">
              <div className="renewal-drawer__section-title">Комментарий</div>
              <textarea
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
          </>
        )}
      </aside>
    </div>
  );
}
