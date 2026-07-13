import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCalendar } from '../../hooks/useCalendar';
import { useTeacherData, useAllData } from '../../hooks/useTeacherData';
import { CalendarView } from '@shared/shared/calendar/CalendarView';
import { LessonPopup } from '@shared/shared/calendar/LessonPopup';
import { Modal } from '../../components/ui/Modal';
import { LessonForm } from '../../components/lessons/LessonForm';
import { OccurrenceMenu } from './OccurrenceMenu';
import { currentMondayMsk, addDays, isoDate } from '../../lib/dates';
import type { GroupData, Occurrence } from '../../lib/types';

interface MenuState {
  occ: Occurrence;
  x: number;
  y: number;
}

/**
 * Тонкая обёртка над презентационным CalendarView (shared/calendar) — грузит
 * /api/calendar сама (useCalendar), CalendarView владеет UI-состоянием
 * (вид/навигация/KPI/легенда) и сообщает видимое окно через
 * onVisibleRangeChange. Начальный range сидируется той же логикой, что
 * CalendarView использует по умолчанию (view='week', текущая неделя МСК) —
 * без этого первый рендер запросил бы устаревший диапазон до первого
 * эффекта CalendarView.
 *
 * Клик по занятию (onOccurrenceMenu) открывает контекстное меню: Отметить
 * урок (LessonForm с датой занятия) / Карточка группы / Чат / Подробности
 * (LessonPopup). Для чужой группы (замена, назначенная админом через «Сменить
 * преподавателя») данных в /api/getData нет — форма лениво тянет /api/getAllData.
 */
export default function CalendarPage() {
  const navigate = useNavigate();
  const [range, setRange] = useState(() => {
    const monday = currentMondayMsk();
    return { from: isoDate(monday), to: isoDate(addDays(monday, 6)) };
  });

  const { data, isLoading, isError, isFetching } = useCalendar(range.from, range.to);

  const [menu, setMenu] = useState<MenuState | null>(null);
  const [details, setDetails] = useState<Occurrence | null>(null);
  const [marking, setMarking] = useState<Occurrence | null>(null);

  const mine = useTeacherData();
  const needAll = !!marking && !(mine.data?.data ?? {})[marking.group];
  const all = useAllData(needAll);

  /** GroupData по имени: свои группы из /api/getData, чужие (замена) — из /api/getAllData. */
  const groupDataOf = (name: string): GroupData | null => {
    const own = (mine.data?.data ?? {})[name];
    if (own) return own;
    if (!all.data) return null;
    for (const groups of Object.values(all.data.data)) {
      if (groups[name]) return groups[name];
    }
    return null;
  };

  const onVisibleRangeChange = useCallback((from: string, to: string) => {
    setRange((prev) => (prev.from === from && prev.to === to ? prev : { from, to }));
  }, []);

  const onOccurrenceMenu = useCallback((occ: Occurrence, pos: { x: number; y: number }) => {
    setMenu({ occ, x: pos.x, y: pos.y });
  }, []);

  const markingData = marking ? groupDataOf(marking.group) : null;

  return (
    <>
      <CalendarView
        occurrences={data?.occurrences ?? []}
        unscheduled={data?.unscheduled ?? []}
        isLoading={isLoading}
        isError={isError}
        isFetching={isFetching}
        onVisibleRangeChange={onVisibleRangeChange}
        onOccurrenceMenu={onOccurrenceMenu}
        role="teacher"
      />

      {menu && (
        <OccurrenceMenu
          occ={menu.occ}
          x={menu.x}
          y={menu.y}
          onSubmitLesson={() => { setMarking(menu.occ); setMenu(null); }}
          onOpenGroup={() => { setMenu(null); navigate(`/groups/${encodeURIComponent(menu.occ.group)}`); }}
          onDetails={() => { setDetails(menu.occ); setMenu(null); }}
          onClose={() => setMenu(null)}
        />
      )}

      {details && (
        <LessonPopup lesson={details} onClose={() => setDetails(null)} role="teacher" />
      )}

      {marking && (markingData ? (
        <LessonForm
          group={marking.group}
          groupData={markingData}
          initialDate={marking.date}
          isSubstitution={!!marking.teacherOverride}
          onClose={() => setMarking(null)}
        />
      ) : (
        <Modal title={marking.group} subtitle="Запись урока" onClose={() => setMarking(null)}>
          {all.isError
            ? <div className="cal-error">Не удалось загрузить данные группы. Попробуйте ещё раз.</div>
            : <div className="cal-empty">Загружаем данные группы…</div>}
        </Modal>
      ))}
    </>
  );
}
