import { useDraggable } from '@dnd-kit/core';
import { fmtRub, fmtDate } from '../../lib/format';
import type { RenewalCard } from '../../lib/renewals';

// Порог «сделка зависла в стадии» — подсвечиваем SLA-бейдж красным.
const SLA_OVERDUE_DAYS = 5;

interface Props {
  card: RenewalCard;
  onOpen: (id: number) => void;
}

export function RenewalCardView({ card, onOpen }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: card.id });

  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
    : undefined;

  const overdue = card.days_in_stage > SLA_OVERDUE_DAYS;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`renewal-card${isDragging ? ' renewal-card--dragging' : ''}`}
      onClick={() => onOpen(card.id)}
      {...listeners}
      {...attributes}
    >
      <div className="renewal-card__student">{card.student_name || '—'}</div>
      <div
        className="renewal-card__direction"
        style={card.direction_color ? { color: card.direction_color } : undefined}
      >
        {card.direction_name || '—'} · Мес. {card.cycle_no}
      </div>
      <div className="renewal-card__meta">
        <span
          className={`status-badge${overdue ? ' status-badge--negative' : ' status-badge--muted'}`}
          title="Дней в текущей стадии"
        >
          {card.days_in_stage} дн.
        </span>
        {card.next_touch_at && (
          <span className="renewal-card__touch">{fmtDate(card.next_touch_at)}</span>
        )}
      </div>
      <div className="renewal-card__footer">
        <span className="renewal-card__assignee">{card.assignee_name || '—'}</span>
        {card.expected_amount && (
          <span className="renewal-card__amount">{fmtRub(card.expected_amount)}</span>
        )}
      </div>
    </div>
  );
}
