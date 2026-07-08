import { useDroppable } from '@dnd-kit/core';
import { RenewalCardView } from './RenewalCardView';
import type { RenewalColumn as RenewalColumnData } from '../../lib/renewals';

interface Props {
  col: RenewalColumnData;
  onOpen: (id: number) => void;
}

export function RenewalColumn({ col, onOpen }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: col.stage_id });
  const hasMore = col.count > col.cards.length;

  return (
    <div
      ref={setNodeRef}
      className={`renewal-col${isOver ? ' renewal-col--over' : ''}`}
      style={col.color ? { borderTopColor: col.color } : undefined}
    >
      <div className="renewal-col__head">
        <span className="renewal-col__label">{col.label}</span>
        <span className="renewal-col__stats">
          {col.count}
          {col.sum_potential > 0 && <> · {col.sum_potential.toLocaleString('ru')} ₽</>}
        </span>
      </div>
      <div className="renewal-col__body">
        {col.cards.map((card) => (
          <RenewalCardView key={card.id} card={card} onOpen={onOpen} />
        ))}
      </div>
      {hasMore && (
        // TODO: бэк пока не отдаёт постраничную подгрузку внутри колонки —
        // кнопка неактивна, до появления отдельного эндпоинта пагинации колонки.
        <button type="button" className="renewal-col__more" disabled>
          Показать ещё ({col.count - col.cards.length})
        </button>
      )}
    </div>
  );
}
