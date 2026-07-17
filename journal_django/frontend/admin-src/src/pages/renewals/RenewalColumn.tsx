import { useDeferredValue, useEffect, useState } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { RenewalCardView } from './RenewalCardView';
import { TextInput } from '../../components/form/TextInput';
import { fetchRenewalColumnCards, useRenewalColumnSearch } from '../../hooks/useRenewals';
import { useApiError } from '../../hooks/useApiError';
import type { RenewalCard, RenewalColumn as RenewalColumnData, RenewalFilters } from '../../lib/renewals';

interface Props {
  col: RenewalColumnData;
  filters: RenewalFilters;
  onOpen: (id: number) => void;
}

export function RenewalColumn({ col, filters, onOpen }: Props) {
  // Прогресс-стадии («Не было урока», «Урок 1–3») двигает только движок по
  // событиям посещаемости/оплаты — вручную перетащить карточку СЮДА нельзя
  // (droppable отключён), бэк на move в такую стадию тоже ответит 409.
  // Забрать карточку ИЗ такой колонки (заморозить, отметить ушедшим) можно —
  // здесь не ограничено, драг карточки из колонки не завязан на useDroppable.
  const isAutoOnly = col.kind === 'progress';
  const { setNodeRef, isOver } = useDroppable({ id: col.stage_id, disabled: isAutoOnly });
  const showError = useApiError();

  // Поиск по имени ученика в этой колонке. deferred — как в списках (не гоним
  // запрос на каждый символ). Ищем на сервере (ILIKE), а не по загруженным
  // карточкам — иначе ученик из непрогруженного «хвоста» колонки не найдётся.
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search.trim());
  const searching = deferredSearch.length > 0;

  const colFilters: RenewalFilters = searching
    ? { ...filters, student: deferredSearch }
    : filters;

  const { data: searchData, isFetching: searchFetching } =
    useRenewalColumnSearch(col.stage_id, colFilters, searching);

  // Источник карточек: результат поиска либо данные доски.
  const baseCards = searching ? (searchData?.cards ?? []) : col.cards;
  const count = searching ? (searchData?.count ?? 0) : col.count;

  const [extraCards, setExtraCards] = useState<RenewalCard[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);

  // Фильтры/поиск сменились, либо счётчик колонки изменился (карточку перенесли
  // в неё/из неё, добавили оплату) — старая догрузка «Показать ещё» больше не
  // актуальна (иначе перенесённая карточка осталась бы «фантомом»), начинаем с нуля.
  const colFiltersKey = JSON.stringify(colFilters);
  useEffect(() => {
    setExtraCards([]);
  }, [col.stage_id, colFiltersKey, col.count]);

  const cards = [...baseCards, ...extraCards];
  const hasMore = count > cards.length;

  const handleShowMore = async () => {
    setLoadingMore(true);
    try {
      const more = await fetchRenewalColumnCards(col.stage_id, cards.length, colFilters);
      setExtraCards((prev) => [...prev, ...more.cards]);
    } catch (err) {
      showError(err, 'Не удалось догрузить карточки');
    } finally {
      setLoadingMore(false);
    }
  };

  const showSearchSpinner = searching && searchFetching && cards.length === 0;

  return (
    <div
      ref={setNodeRef}
      className={`renewal-col${isOver ? ' renewal-col--over' : ''}`}
      style={col.color ? { borderTopColor: col.color } : undefined}
    >
      <div className="renewal-col__head">
        <span className="renewal-col__label">
          {col.label}
          {isAutoOnly && (
            <span className="renewal-col__auto-badge" title="Двигает только система по событиям — вручную перенести сделку сюда нельзя">
              авто
            </span>
          )}
        </span>
        <span className="renewal-col__stats">{count}</span>
      </div>

      <div className="renewal-col__search">
        <TextInput
          className="renewal-col__search-input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Поиск по имени…"
          aria-label={`Поиск ученика в стадии «${col.label}»`}
        />
        {search && (
          <button
            type="button"
            className="renewal-col__search-clear"
            onClick={() => setSearch('')}
            aria-label="Очистить поиск"
          >
            ×
          </button>
        )}
      </div>

      <div className="renewal-col__body">
        {showSearchSpinner ? (
          <div className="renewal-col__empty">Ищем…</div>
        ) : cards.length === 0 ? (
          <div className="renewal-col__empty">{searching ? 'Никого не найдено' : 'Пусто'}</div>
        ) : (
          cards.map((card) => (
            <RenewalCardView key={card.id} card={card} stageId={col.stage_id} onOpen={onOpen} />
          ))
        )}
      </div>

      {hasMore && (
        <button
          type="button"
          className="renewal-col__more"
          disabled={loadingMore}
          onClick={handleShowMore}
        >
          {loadingMore ? 'Загружаем…' : `Показать ещё (${count - cards.length})`}
        </button>
      )}
    </div>
  );
}
