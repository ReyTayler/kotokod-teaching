import { useDraggable } from '@dnd-kit/core';
import { fmtDate } from '../../lib/format';
import type { RenewalCard } from '../../lib/renewals';

// Порог «сделка зависла в стадии» — подсвечиваем SLA-бейдж красным.
const SLA_OVERDUE_DAYS = 5;

/**
 * Разметка карточки без drag-обвязки — переиспользуется и в самой колонке,
 * и в DragOverlay (там своя, немонтируемая копия, которую dnd-kit носит за курсором).
 */
export function RenewalCardContent({ card }: { card: RenewalCard }) {
  const overdue = card.days_in_stage > SLA_OVERDUE_DAYS;
  return (
    <>
      <div className="renewal-card__student">{card.student_name || '—'}</div>
      <div className="renewal-card__direction">
        {(card.directions || []).map((d, i) => (
          <span key={d.name} style={d.color ? { color: d.color } : undefined}>
            {i > 0 && ', '}{d.name}
          </span>
        ))}
        {(card.directions || []).length === 0 && '—'}
        {' · Цикл '}{card.cycle_no}
      </div>
      <div className="renewal-card__meta">
        <span
          className={`status-badge${overdue ? ' status-badge--negative' : ' status-badge--muted'}`}
          title="Дней в текущей стадии"
        >
          {card.days_in_stage} дн.
        </span>
        {card.debt && (
          <span className="status-badge status-badge--negative" title="Баланс ученика отрицательный">
            Долг
          </span>
        )}
        {card.next_touch_at && (
          <span className="renewal-card__touch">{fmtDate(card.next_touch_at)}</span>
        )}
      </div>
      <div className="renewal-card__footer">
        <span className="renewal-card__assignee">{card.assignee_name || '—'}</span>
      </div>
    </>
  );
}

interface Props {
  card: RenewalCard;
  stageId: number;
  onOpen: (id: number) => void;
}

export function RenewalCardView({ card, stageId, onOpen }: Props) {
  // Данные карточки едут вместе с drag'ом — так доска берёт их прямо из события
  // (event.active.data), а не ищет в кэше. Иначе карточки из «Показать ещё»
  // (локальный стейт) и из поиска (отдельный кэш) не перетаскивались бы.
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: card.id,
    data: { card, fromStageId: stageId },
  });

  return (
    <div
      ref={setNodeRef}
      className={`renewal-card${isDragging ? ' renewal-card--dragging' : ''}`}
      onClick={() => onOpen(card.id)}
      {...listeners}
      {...attributes}
    >
      <RenewalCardContent card={card} />
    </div>
  );
}
