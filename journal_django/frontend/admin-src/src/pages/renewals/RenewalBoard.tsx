import { useState } from 'react';
import {
  DndContext, DragOverlay, PointerSensor, useDroppable, useSensor, useSensors,
  type DragStartEvent, type DragEndEvent,
} from '@dnd-kit/core';
import { useQueryClient } from '@tanstack/react-query';
import { useRenewalBoard, useRenewalMutations } from '../../hooks/useRenewals';
import { useRenewalStages } from '../../hooks/useRenewalStages';
import { useApiError } from '../../hooks/useApiError';
import { RenewalColumn } from './RenewalColumn';
import { RenewalCardContent } from './RenewalCardView';
import { RenewalCloseDialog, type CloseDialogTarget } from './RenewalCloseDialog';
import type { RenewalBoard as RenewalBoardData, RenewalCard, RenewalFilters } from '../../lib/renewals';

interface Props {
  filters: RenewalFilters;
  onOpen: (id: number) => void;
}

/**
 * Зона-мишень закрытия сделки («Продлён»/«Ушёл»). Показывается только пока
 * тащат карточку — вместо вечно пустых терминальных колонок на доске.
 */
function CloseZone({ id, label, tone }: { id: string; label: string; tone: 'won' | 'lost' }) {
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <div
      ref={setNodeRef}
      className={`renewal-close-zone renewal-close-zone--${tone}${isOver ? ' renewal-close-zone--over' : ''}`}
    >
      {label}
    </div>
  );
}

export function RenewalBoard({ filters, onOpen }: Props) {
  const qc = useQueryClient();
  const { data, isLoading } = useRenewalBoard(filters);
  const { data: stages } = useRenewalStages();
  const { move, comment } = useRenewalMutations();
  const showError = useApiError();

  // Карточка, которую сейчас тащат — рендерится отдельно в DragOverlay (портал
  // в document.body), чтобы не обрезаться overflow колонки и не уезжать под неё.
  const [activeCard, setActiveCard] = useState<RenewalCard | null>(null);
  // Сделка, ожидающая подтверждения закрытия в диалоге (drop на зону закрытия).
  const [closeTarget, setCloseTarget] = useState<CloseDialogTarget | null>(null);

  // Терминальные стадии больше не колонки — их id нужны только для move при закрытии.
  const wonStage = (stages || []).find((s) => s.kind === 'won');
  const lostStage = (stages || []).find((s) => s.kind === 'lost');

  // Небольшой порог перед стартом драга — иначе клик по карточке (открытие
  // drawer'а) будет постоянно перехватываться сенсором как начало drag'а.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  // Ключ должен совпадать с queryKey внутри useRenewalBoard (['renewals','board',filters]).
  const queryKey = ['renewals', 'board', filters] as const;

  // Данные карточки едут в event.active.data (см. RenewalCardView) — поэтому
  // перенос работает и для карточек из «Показать ещё»/поиска, которых нет в кэше доски.
  const dragCard = (event: DragStartEvent | DragEndEvent): RenewalCard | undefined =>
    (event.active.data.current as { card?: RenewalCard } | undefined)?.card;
  const dragFromStage = (event: DragEndEvent): number | undefined =>
    (event.active.data.current as { fromStageId?: number } | undefined)?.fromStageId;

  const handleDragStart = (event: DragStartEvent) => {
    setActiveCard(dragCard(event) ?? null);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveCard(null);
    const { active, over } = event;
    if (!over) return;
    const dealId = Number(active.id);

    // Бросили в зону закрытия — НЕ закрываем молча, открываем диалог
    // (причина для «Ушёл», выбор «оплата/без оплаты» для «Продлён»).
    if (over.id === 'close-won' || over.id === 'close-lost') {
      const card = dragCard(event);
      if (card) {
        setCloseTarget({
          dealId,
          studentId: card.student_id,
          studentName: card.student_name,
          mode: over.id === 'close-won' ? 'won' : 'lost',
        });
      }
      return;
    }

    const toStageId = Number(over.id);
    const fromStageId = dragFromStage(event);
    if (fromStageId === toStageId) return; // бросили в тот же столбец — не трогаем

    const prev = qc.getQueryData<RenewalBoardData>(queryKey);
    const movedCard = dragCard(event);

    // Оптимистично правим кэш доски: колонки-стадии в нём есть всегда, поэтому
    // счётчики и целевая колонка обновятся сразу. Сама карточка могла быть из
    // «хвоста»/поиска (нет в cards исходной колонки) — тогда она визуально уедет
    // после инвалидации; лишний «фантом» в источнике снимает сброс extraCards.
    if (prev) {
      const next: RenewalBoardData = {
        columns: prev.columns.map((col) => {
          if (col.stage_id === fromStageId) {
            return { ...col, count: Math.max(0, col.count - 1), cards: col.cards.filter((c) => c.id !== dealId) };
          }
          if (col.stage_id === toStageId && movedCard && !col.cards.some((c) => c.id === dealId)) {
            return { ...col, count: col.count + 1, cards: [{ ...movedCard, days_in_stage: 0 }, ...col.cards] };
          }
          return col;
        }),
      };
      qc.setQueryData(queryKey, next);
    }

    // move сам инвалидирует ['renewals'] onSuccess — здесь откат + сообщение об ошибке
    // (409 «переход запрещён» и т.п. — бэк уже возвращает человекочитаемый текст в error).
    move.mutate(
      { id: dealId, to_stage_id: toStageId },
      {
        onError: (err) => {
          if (prev) qc.setQueryData(queryKey, prev);
          showError(err, 'Не удалось переместить сделку');
        },
      },
    );
  };

  // Подтверждение диалога закрытия: move в терминальную стадию,
  // комментарий (если ввели) — отдельной записью таймлайна.
  const handleCloseConfirm = ({ reason_code, comment: text }: { reason_code?: string; comment?: string }) => {
    if (!closeTarget) return;
    const stage = closeTarget.mode === 'won' ? wonStage : lostStage;
    if (!stage) {
      setCloseTarget(null);
      return;
    }
    move.mutate(
      { id: closeTarget.dealId, to_stage_id: stage.id, reason_code },
      {
        onSuccess: () => {
          if (text) comment.mutate({ id: closeTarget.dealId, body: text });
          setCloseTarget(null);
        },
        onError: (err) => {
          setCloseTarget(null);
          showError(err, 'Не удалось закрыть сделку');
        },
      },
    );
  };

  if (isLoading) {
    return <div className="renewal-board renewal-board--loading">Загружаем доску…</div>;
  }

  const columns = data?.columns || [];

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={() => setActiveCard(null)}
    >
      <div className="renewal-board">
        {columns.map((col) => (
          <RenewalColumn key={col.stage_id} col={col} filters={filters} onOpen={onOpen} />
        ))}
      </div>
      {activeCard && (
        <div className="renewal-close-zones">
          {/* Пока цикл (4 урока) не завершён — «Продлён» вручную недоступен
              (move всё равно ответит 409, см. transitions.py), поэтому зону
              для такой сделки не показываем вовсе — нечего бросать мимо. */}
          {activeCard.cycle_completed && (
            <CloseZone id="close-won" label="✓ Продлён" tone="won" />
          )}
          <CloseZone id="close-lost" label="✕ Ушёл" tone="lost" />
        </div>
      )}
      <DragOverlay>
        {activeCard && (
          <div className="renewal-card renewal-card--overlay">
            <RenewalCardContent card={activeCard} />
          </div>
        )}
      </DragOverlay>
      {closeTarget && (
        <RenewalCloseDialog
          target={closeTarget}
          pending={move.isPending}
          onClose={() => setCloseTarget(null)}
          onConfirm={handleCloseConfirm}
        />
      )}
    </DndContext>
  );
}
