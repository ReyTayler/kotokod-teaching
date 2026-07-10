import { useEffect, useState } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { RenewalCardView } from './RenewalCardView';
import { fetchRenewalColumnCards } from '../../hooks/useRenewals';
import { useApiError } from '../../hooks/useApiError';
import type { RenewalCard, RenewalColumn as RenewalColumnData, RenewalFilters } from '../../lib/renewals';

interface Props {
  col: RenewalColumnData;
  filters: RenewalFilters;
  onOpen: (id: number) => void;
}

export function RenewalColumn({ col, filters, onOpen }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: col.stage_id });
  const showError = useApiError();
  const [extraCards, setExtraCards] = useState<RenewalCard[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);

  // Фильтры сменились (или доска перезагрузилась после хода/оплаты) — старая
  // догрузка больше не актуальна, начинаем с чистого листа.
  useEffect(() => {
    setExtraCards([]);
  }, [col.stage_id, JSON.stringify(filters)]);

  const cards = [...col.cards, ...extraCards];
  const hasMore = col.count > cards.length;

  const handleShowMore = async () => {
    setLoadingMore(true);
    try {
      const more = await fetchRenewalColumnCards(col.stage_id, cards.length, filters);
      setExtraCards((prev) => [...prev, ...more]);
    } catch (err) {
      showError(err, 'Не удалось догрузить карточки');
    } finally {
      setLoadingMore(false);
    }
  };

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
        {cards.map((card) => (
          <RenewalCardView key={card.id} card={card} onOpen={onOpen} />
        ))}
      </div>
      {hasMore && (
        <button
          type="button"
          className="renewal-col__more"
          disabled={loadingMore}
          onClick={handleShowMore}
        >
          {loadingMore ? 'Загружаем…' : `Показать ещё (${col.count - cards.length})`}
        </button>
      )}
    </div>
  );
}
