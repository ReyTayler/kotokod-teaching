import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { useQueryClient } from '@tanstack/react-query';
import { useRenewalBoard, useRenewalMutations } from '../../hooks/useRenewals';
import { RenewalColumn } from './RenewalColumn';
import type { RenewalBoard as RenewalBoardData, RenewalFilters } from '../../lib/renewals';

interface Props {
  filters: RenewalFilters;
  onOpen: (id: number) => void;
}

export function RenewalBoard({ filters, onOpen }: Props) {
  const qc = useQueryClient();
  const { data, isLoading } = useRenewalBoard(filters);
  const { move } = useRenewalMutations();

  // Небольшой порог перед стартом драга — иначе клик по карточке (открытие
  // drawer'а) будет постоянно перехватываться сенсором как начало drag'а.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  // Ключ должен совпадать с queryKey внутри useRenewalBoard (['renewals','board',filters]).
  const queryKey = ['renewals', 'board', filters] as const;

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over) return;
    const dealId = Number(active.id);
    const toStageId = Number(over.id);

    const prev = qc.getQueryData<RenewalBoardData>(queryKey);
    if (!prev) return;

    let movedCard = null;
    let fromColIdx = -1;
    for (let i = 0; i < prev.columns.length; i += 1) {
      const found = prev.columns[i].cards.find((c) => c.id === dealId);
      if (found) { movedCard = found; fromColIdx = i; break; }
    }
    if (!movedCard || fromColIdx === -1) return;

    const toColIdx = prev.columns.findIndex((c) => c.stage_id === toStageId);
    if (toColIdx === -1 || toColIdx === fromColIdx) return; // бросили в тот же столбец — не трогаем

    // Оптимистично: убрать карточку из исходной колонки, вставить в начало целевой.
    const next: RenewalBoardData = {
      columns: prev.columns.map((col, idx) => {
        if (idx === fromColIdx) {
          return { ...col, count: Math.max(0, col.count - 1), cards: col.cards.filter((c) => c.id !== dealId) };
        }
        if (idx === toColIdx) {
          return { ...col, count: col.count + 1, cards: [{ ...movedCard!, days_in_stage: 0 }, ...col.cards] };
        }
        return col;
      }),
    };
    qc.setQueryData(queryKey, next);

    // move сам инвалидирует ['renewals'] onSuccess — здесь только откат при ошибке.
    move.mutate(
      { id: dealId, to_stage_id: toStageId },
      { onError: () => qc.setQueryData(queryKey, prev) },
    );
  };

  if (isLoading) {
    return <div className="renewal-board renewal-board--loading">Загружаем доску…</div>;
  }

  const columns = data?.columns || [];

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <div className="renewal-board">
        {columns.map((col) => (
          <RenewalColumn key={col.stage_id} col={col} onOpen={onOpen} />
        ))}
      </div>
    </DndContext>
  );
}
