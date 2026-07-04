import { useCallback, useState } from 'react';
import { useCalendar } from '../../hooks/useCalendar';
import { CalendarView } from '@shared/shared/calendar/CalendarView';
import { currentMondayMsk, addDays, isoDate } from '../../lib/dates';

/**
 * Тонкая обёртка над презентационным CalendarView (shared/calendar) — грузит
 * /api/calendar сама (useCalendar), CalendarView владеет UI-состоянием
 * (вид/навигация/KPI/легенда/попап) и сообщает видимое окно через
 * onVisibleRangeChange. Начальный range сидируется той же логикой, что
 * CalendarView использует по умолчанию (view='week', текущая неделя МСК) —
 * без этого первый рендер запросил бы устаревший диапазон до первого
 * эффекта CalendarView.
 */
export default function CalendarPage() {
  const [range, setRange] = useState(() => {
    const monday = currentMondayMsk();
    return { from: isoDate(monday), to: isoDate(addDays(monday, 6)) };
  });

  const { data, isLoading, isError, isFetching } = useCalendar(range.from, range.to);

  const onVisibleRangeChange = useCallback((from: string, to: string) => {
    setRange((prev) => (prev.from === from && prev.to === to ? prev : { from, to }));
  }, []);

  return (
    <CalendarView
      occurrences={data?.occurrences ?? []}
      unscheduled={data?.unscheduled ?? []}
      isLoading={isLoading}
      isError={isError}
      isFetching={isFetching}
      onVisibleRangeChange={onVisibleRangeChange}
      role="teacher"
    />
  );
}
