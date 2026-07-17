import { useEffect, useMemo, useState } from 'react';
import {
  DndContext, DragOverlay, PointerSensor, useDroppable, useSensor, useSensors,
  type DragStartEvent, type DragEndEvent,
} from '@dnd-kit/core';
import { useQueryClient } from '@tanstack/react-query';
import { useRenewalBoard, useRenewalMutations } from '../../hooks/useRenewals';
import { useRenewalStages } from '../../hooks/useRenewalStages';
import { useApiError } from '../../hooks/useApiError';
import { useMemberships } from '../../hooks/useMemberships';
import { useGroupsAll } from '../../hooks/useGroups';
import { useToast } from '../../components/ui/Toast';
import { RenewalColumn } from './RenewalColumn';
import { RenewalCardContent } from './RenewalCardView';
import { RenewalCloseDialog, type CloseDialogTarget } from './RenewalCloseDialog';
import { StudentStatusModal } from '../students/StudentStatusModal';
import type { RenewalBoard as RenewalBoardData, RenewalCard, RenewalFilters } from '../../lib/renewals';
import type { EnrollmentStatus } from '../../lib/types';

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
  const { toast } = useToast();

  // Карточка, которую сейчас тащат — рендерится отдельно в DragOverlay (портал
  // в document.body), чтобы не обрезаться overflow колонки и не уезжать под неё.
  const [activeCard, setActiveCard] = useState<RenewalCard | null>(null);
  // Сделка, ожидающая подтверждения закрытия в диалоге (drop на зону закрытия).
  const [closeTarget, setCloseTarget] = useState<CloseDialogTarget | null>(null);
  // Ученик, для которого дроп на «Заморожен»/«Ушёл» открыл смену статуса —
  // сделка переедет в нужную стадию сама, каскадом (engine.freeze_deal/decline_deal).
  const [statusModalStudent, setStatusModalStudent] = useState<
    { id: number; initialStatus: EnrollmentStatus } | null
  >(null);

  // Мемберства ученика, на которого сейчас бросили карточку — тот же паттерн,
  // что и в StudentDetailPage. Хуки вызываются безусловно (правила хуков);
  // без выбранного ученика useMemberships отключён (enabled: !!student_id).
  const { data: groupsAll = [] } = useGroupsAll(true);
  const { data: statusRawMemberships = [], isSuccess: statusMembershipsReady, isError: statusMembershipsFailed } =
    useMemberships({ student_id: statusModalStudent?.id });
  const statusMemberships = useMemo(
    () => statusRawMemberships.map((m) => ({
      id: Number(m.id),
      group_name: m.group_name || `#${m.group_id}`,
      is_individual: groupsAll.find((g) => g.id === m.group_id)?.is_individual ?? false,
    })),
    [statusRawMemberships, groupsAll],
  );

  // Если запрос членств для брошенной карточки упал — не оставляем менеджера
  // с молчаливым «дроп в никуда»: закрываем ожидание и показываем тост.
  useEffect(() => {
    if (statusMembershipsFailed && statusModalStudent) {
      toast('Не удалось загрузить членства ученика — попробуйте ещё раз', 'error');
      setStatusModalStudent(null);
    }
  }, [statusMembershipsFailed, statusModalStudent, toast]);

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

    // Зона «Ушёл» — терминальная стадия 'churned' (kind='lost') не показана
    // колонкой на доске (board() её исключает), это единственный способ на
    // неё «бросить». Смену стадии сделки здесь больше не делаем сами — она
    // произойдёт каскадом внутри смены статуса ученика (engine.decline_deal),
    // поэтому вместо RenewalCloseDialog открываем StudentStatusModal.
    if (over.id === 'close-lost') {
      const card = dragCard(event);
      if (card) setStatusModalStudent({ id: card.student_id, initialStatus: 'declined' });
      return;
    }

    // Зона «Продлён» — по-прежнему ручное решение менеджера с диалогом
    // (оплата сама по себе не закрывает сделку, см. RenewalCloseDialog).
    if (over.id === 'close-won') {
      const card = dragCard(event);
      if (card) {
        setCloseTarget({
          dealId,
          studentId: card.student_id,
          studentName: card.student_name,
          mode: 'won',
        });
      }
      return;
    }

    const toStageId = Number(over.id);
    const fromStageId = dragFromStage(event);
    if (fromStageId === toStageId) return; // бросили в тот же столбец — не трогаем

    // Авто-стадии двигает только движок (transitions.is_allowed блокирует
    // ручной вход) — колонка «Урок 1–4» вообще не droppable (RenewalColumn),
    // но «Ждём оплату»/«Ждём продление»/«Заморожен» технически droppable.
    // 'frozen' — особый случай: каскад через смену статуса ученика, поэтому
    // открываем модалку вместо тихого no-op/ошибки 409.
    const targetStage = (stages || []).find((s) => s.id === toStageId);
    if (targetStage?.is_auto) {
      if (targetStage.key === 'frozen') {
        const card = dragCard(event);
        if (card) setStatusModalStudent({ id: card.student_id, initialStatus: 'frozen' });
      } else {
        toast('Эта стадия управляется системой', 'info');
      }
      return;
    }

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
      {statusModalStudent && statusMembershipsReady && (
        <StudentStatusModal
          studentId={statusModalStudent.id}
          open
          onClose={() => setStatusModalStudent(null)}
          memberships={statusMemberships}
          initialStatus={statusModalStudent.initialStatus}
        />
      )}
    </DndContext>
  );
}
