import { useState } from 'react';
import { useStudentBalance } from '../../hooks/useStudentBalance';
import { usePaymentMutations } from '../../hooks/usePayments';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { fmtRub, fmtLessons, fmtDate } from '../../lib/format';

interface Props {
  studentId: number;
}

export function StudentBalanceBlock({ studentId }: Props) {
  const balance = useStudentBalance(studentId);
  const muts = usePaymentMutations();
  const { open } = usePaymentModal();
  const showError = useApiError();
  const { toast } = useToast();

  const [confirmingId, setConfirmingId] = useState<number | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [paidOpen, setPaidOpen] = useState(false);
  const [attendedOpen, setAttendedOpen] = useState(false);

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
        <h3>Баланс</h3>
        <button type="button" className="btn-save" onClick={() => open({ studentId })}>
          + Внести оплату
        </button>
      </div>

      <div className="balance-block__totals">
        <div>Оплачено всего: <strong>{fmtRub(data.total_paid_amount)}</strong></div>
        <div>
          Осталось оплаченных уроков:&nbsp;
          <strong className={data.total_balance < 0 ? 'balance-neg' : ''}>
            {fmtLessons(data.total_balance)}
          </strong>
        </div>
      </div>

      {data.paid_by_direction.length > 0 && (
        <>
          <button
            type="button"
            className="balance-block__history-toggle"
            onClick={() => setPaidOpen((o) => !o)}
            aria-expanded={paidOpen}
          >
            <span className={`balance-block__chevron${paidOpen ? ' is-open' : ''}`}>▸</span>
            Оплачено по направлениям
          </button>
          {paidOpen && (
            <div className="balance-block__directions">
              {data.paid_by_direction.map((d) => (
                <div key={d.direction_id} className="balance-block__direction-row">
                  <span className="dir-tag" style={{ background: d.direction_color || '#999' }} />
                  <span className="balance-block__direction-name">{d.direction_name}</span>
                  <span>{fmtRub(d.total_paid_amount)}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {data.attended_by_direction.length > 0 && (
        <>
          <button
            type="button"
            className="balance-block__history-toggle"
            onClick={() => setAttendedOpen((o) => !o)}
            aria-expanded={attendedOpen}
          >
            <span className={`balance-block__chevron${attendedOpen ? ' is-open' : ''}`}>▸</span>
            Отработано по направлениям
          </button>
          {attendedOpen && (
            <div className="balance-block__directions">
              {data.attended_by_direction.map((d) => (
                <div key={d.direction_id} className="balance-block__direction-row">
                  <span className="dir-tag" style={{ background: d.direction_color || '#999' }} />
                  <span className="balance-block__direction-name">{d.direction_name}</span>
                  <span>{fmtLessons(d.attended_lessons)} уроков</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {data.payments.length > 0 && (
        <>
          <button
            type="button"
            className="balance-block__history-toggle"
            onClick={() => setHistoryOpen((o) => !o)}
            aria-expanded={historyOpen}
          >
            <span className={`balance-block__chevron${historyOpen ? ' is-open' : ''}`}>▸</span>
            История оплат <span className="muted">({data.payments.length})</span>
          </button>
          {historyOpen && (
          <ul className="balance-block__history">
            {data.payments.map((p) => (
              <li key={p.id} className="balance-block__history-row">
                <div className="balance-block__history-main">
                  <span>{fmtDate(p.paid_at)}</span>
                  <span> · </span>
                  <span>{p.direction_name || <em className="muted">Архив</em>}</span>
                  <span> · </span>
                  {p.subscriptions_count != null ? (
                    <>
                      <span>{p.subscriptions_count} аб.</span>
                      <span> · </span>
                      <span>{fmtRub(p.unit_price)}/аб = <strong>{fmtRub(p.total_amount)}</strong></span>
                    </>
                  ) : (
                    <span><strong>{fmtRub(p.total_amount)}</strong></span>
                  )}
                  {p.note && <span className="muted"> — «{p.note}»</span>}
                </div>
                <button
                  type="button"
                  className={`btn-delete${confirmingId === p.id ? ' is-confirming' : ''}`}
                  onClick={() => { void handleDelete(p.id); }}
                  title="Удалить оплату"
                  aria-label="Удалить"
                >
                  {confirmingId === p.id ? 'Точно удалить?' : '🗑'}
                </button>
              </li>
            ))}
          </ul>
          )}
        </>
      )}
    </section>
  );
}
