import { useState, type ReactNode } from 'react';
import { useStudentBalance } from '../../hooks/useStudentBalance';
import { usePaymentMutations } from '../../hooks/usePayments';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { useAuth } from '../../hooks/useAuth';
import { fmtRub, fmtLessons, fmtDate } from '../../lib/format';
import { RefundModal } from './RefundModal';
import type { Payment } from '../../lib/types';

interface Props {
  studentId: number;
}

/** Плюс/минус-иконка секции: вертикальная штриха гаснет при раскрытии → «−». */
function AccordionIcon() {
  return (
    <span className="fin-acc__icon" aria-hidden="true">
      <svg viewBox="0 0 16 16" width="16" height="16" fill="none"
           stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
        <line x1="3.5" y1="8" x2="12.5" y2="8" />
        <line x1="8" y1="3.5" x2="8" y2="12.5" className="fin-acc__icon-bar" />
      </svg>
    </span>
  );
}

interface SectionProps {
  title: string;
  meta?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}

function FinSection({ title, meta, defaultOpen = false, children }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`fin-acc${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="fin-acc__trigger"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <AccordionIcon />
        <span className="fin-acc__title">{title}</span>
        {meta != null && <span className="fin-acc__meta">{meta}</span>}
      </button>
      {open && <div className="fin-acc__body">{children}</div>}
    </div>
  );
}

/** Одна строка таблицы истории оплат. */
function HistoryRow({
  p,
  confirming,
  onDelete,
}: {
  p: Payment;
  confirming: boolean;
  onDelete: () => void;
}) {
  const isRefund = p.kind === 'refund';
  const subsCount = p.subscriptions_count ?? 0;
  const perUnit = isRefund || subsCount <= 0 ? null : Number(p.total_amount) / subsCount;

  return (
    <tr className={isRefund ? 'is-refund' : ''}>
      <td className="fin-history__date">{fmtDate(p.paid_at)}</td>
      <td className="fin-history__num">
        <span className="fin-history__amount">
          {isRefund ? '−' : ''}{fmtRub(p.total_amount)}
        </span>
        {perUnit != null && (
          <span className="fin-history__sub">{subsCount} × {fmtRub(perUnit)}</span>
        )}
      </td>
      <td className="fin-history__subs">
        {isRefund ? (
          <span className="fin-tag fin-tag--refund">Возврат</span>
        ) : p.subscriptions_count != null ? (
          <span className="fin-history__count">{p.subscriptions_count}</span>
        ) : (
          <span className="fin-tag fin-tag--prepay" title={`Предоплата, ${fmtLessons(p.lessons_count ?? 0)} уроков`}>
            предоплата
          </span>
        )}
      </td>
      <td>
        {p.direction_name
          ? <span className="fin-dir-name">{p.direction_name}</span>
          : <span className="muted">—</span>}
      </td>
      <td className="fin-history__author">{p.created_by || <span className="muted">—</span>}</td>
      <td className="fin-history__note">
        {p.note ? <span title={p.note}>{p.note}</span> : <span className="muted">—</span>}
      </td>
      <td className="fin-history__action">
        <button
          type="button"
          className={`btn-delete${confirming ? ' is-confirming' : ''}`}
          onClick={onDelete}
          title="Удалить оплату"
          aria-label="Удалить"
        >
          {confirming ? 'Точно?' : (
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
              <line x1="10" y1="11" x2="10" y2="17" /><line x1="14" y1="11" x2="14" y2="17" />
            </svg>
          )}
        </button>
      </td>
    </tr>
  );
}

export function StudentBalanceBlock({ studentId }: Props) {
  const balance = useStudentBalance(studentId);
  const muts = usePaymentMutations();
  const { open } = usePaymentModal();
  const showError = useApiError();
  const { toast } = useToast();
  const { me } = useAuth();
  const canRefund = me?.role === 'admin' || me?.role === 'superadmin';

  const [confirmingId, setConfirmingId] = useState<number | null>(null);
  const [refundOpen, setRefundOpen] = useState(false);

  if (balance.isLoading) return null;
  const data = balance.data;
  if (!data) return null;
  if (
    data.paid_by_direction.length === 0 &&
    data.attended_by_direction.length === 0 &&
    data.payments.length === 0
  ) return null;

  const handleDelete = async (id: number) => {
    if (confirmingId !== id) { setConfirmingId(id); return; }
    try {
      const res = await muts.remove.mutateAsync(id);
      toast('Оплата удалена', 'ok');
      if (res.warning === 'balance_negative') {
        toast(`Внимание: баланс стал ${fmtLessons(res.new_balance)}`, 'error');
      }
      setConfirmingId(null);
    } catch (err) {
      showError(err);
      setConfirmingId(null);
    }
  };

  return (
    <section className="balance-block">
      <div className="balance-block__head">
        <h3>Финансы</h3>
        <div className="balance-block__head-actions">
          {canRefund && data.total_balance > 0 && (
            <button type="button" className="btn-danger" onClick={() => setRefundOpen(true)}>
              Возврат средств
            </button>
          )}
          <button type="button" className="btn-save" onClick={() => open({ studentId })}>
            + Внести оплату
          </button>
        </div>
      </div>

      <div className="balance-summary">
        <div className="balance-tile">
          <span className="balance-tile__label">Оплачено всего</span>
          <span className="balance-tile__value">{fmtRub(data.total_paid_amount)}</span>
        </div>
        <div className="balance-tile">
          <span className="balance-tile__label">Остаток оплаченных уроков</span>
          <span className={`balance-tile__value${data.total_balance < 0 ? ' is-neg' : ''}`}>
            {fmtLessons(data.total_balance)}
          </span>
        </div>
      </div>

      <div className="fin-sections">
        {data.paid_by_direction.length > 0 && (
          <FinSection title="Оплачено по направлениям" meta={data.paid_by_direction.length}>
            <div className="fin-dir-list">
              {data.paid_by_direction.map((d) => (
                <div key={d.direction_id} className="fin-dir-row">
                  <span className="fin-dir-dot" style={{ background: d.direction_color || 'var(--text4)' }} />
                  <span className="fin-dir-name">{d.direction_name}</span>
                  <span className="fin-dir-value">{fmtRub(d.total_paid_amount)}</span>
                </div>
              ))}
            </div>
          </FinSection>
        )}

        {data.attended_by_direction.length > 0 && (
          <FinSection title="Отработано по направлениям" meta={data.attended_by_direction.length}>
            <div className="fin-dir-list">
              {data.attended_by_direction.map((d) => (
                <div key={d.direction_id} className="fin-dir-row">
                  <span className="fin-dir-dot" style={{ background: d.direction_color || 'var(--text4)' }} />
                  <span className="fin-dir-name">{d.direction_name}</span>
                  <span className="fin-dir-value">
                    {fmtLessons(d.attended_lessons)} <span className="fin-dir-unit">уроков</span>
                  </span>
                </div>
              ))}
            </div>
          </FinSection>
        )}

        {data.payments.length > 0 && (
          <FinSection title="История оплат" meta={data.payments.length} defaultOpen>
            <div className="table-wrap fin-history">
              <table>
                <thead>
                  <tr>
                    <th>Дата</th>
                    <th className="col-num">Сумма</th>
                    <th className="col-center">Абонементы</th>
                    <th>Направление</th>
                    <th>Внёс</th>
                    <th className="col-flex">Комментарий</th>
                    <th aria-label="Действия" />
                  </tr>
                </thead>
                <tbody>
                  {data.payments.map((p) => (
                    <HistoryRow
                      key={p.id}
                      p={p}
                      confirming={confirmingId === p.id}
                      onDelete={() => { void handleDelete(p.id); }}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </FinSection>
        )}
      </div>

      <RefundModal
        open={refundOpen}
        onClose={() => setRefundOpen(false)}
        studentId={studentId}
        remainingValue={data.remaining_value}
        remainingLessons={data.total_balance}
      />
    </section>
  );
}
