import { useCallback, useEffect, useMemo, useState } from 'react';
import { resolveDirectionColor, NO_DIRECTION_COLOR } from './lib';
import type { Occurrence, UnscheduledGroup, UnscheduledReason } from './types';
import {
  currentMondayMsk, todayMsk, addWeeks, isoDate, sameDay, weekRangeLabel,
  firstOfMonthMsk, monthOf, addMonths, mondayOfWeek, monthLabel, addDays,
} from './lib';
import { WeekGrid } from './WeekGrid';
import { MonthGrid } from './MonthGrid';
import { DayList } from './DayList';
import { LessonPopup, type LessonActionKind } from './LessonPopup';

function useIsNarrow(bp = 768): boolean {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.innerWidth < bp);
  useEffect(() => {
    const on = () => setNarrow(window.innerWidth < bp);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, [bp]);
  return narrow;
}

/** Спец-значение directionFilter для «уроков без направления» (null / группа не найдена в карте). */
const NO_DIRECTION_KEY = '__no-direction__';

/** Человекочитаемые причины отсутствия плана (тултип бейджа unscheduled). */
const UNSCHEDULED_REASON_LABEL: Record<UnscheduledReason, string> = {
  no_start_date: 'нет даты старта',
  no_total_lessons: 'не задана длина курса',
  no_slots: 'нет слотов расписания',
  not_generated: 'план ещё не сгенерирован',
};

/** Русское склонение «группа/группы/групп» для бейджа unscheduled. */
function pluralizeGroups(n: number): string {
  const mod10 = n % 10, mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 'группа';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'группы';
  return 'групп';
}

function Kpi({ value, label, tone }: { value: number | string; label: string; tone?: 'accent' | 'warn' | 'ok' }) {
  return (
    <div className="kpi-card">
      <div className={`kpi-value${tone ? ` kpi-value--${tone}` : ''}`}>{value}</div>
      <div className="kpi-label">{label}</div>
    </div>
  );
}

export interface CalendarViewProps {
  /** Занятия видимого окна (уже загруженные вызывающей стороной). */
  occurrences: Occurrence[];
  /** Группы без расписания/даты старта — бейдж data-quality в легенде. */
  unscheduled: UnscheduledGroup[];
  isLoading: boolean;
  isError: boolean;
  /** Фоновое обновление (перелистывание при уже показанных прежних данных). */
  isFetching: boolean;
  /**
   * Вызывается при изменении видимого окна (смена вида/навигация недели-месяца),
   * включая первый рендер. teacher использует это, чтобы перезапросить
   * /api/calendar под нужный диапазон; admin (план группы целиком) может
   * игнорировать — окно не обязательно рефетчить.
   */
  onVisibleRangeChange: (fromIso: string, toIso: string) => void;
  /** Используется для ветвления быстрых действий в LessonPopup (см. onAction). */
  role?: 'teacher' | 'admin';
  /**
   * Если передан, добавляет кнопку «Отметить урок» в LessonPopup — по
   * умолчанию не передаётся (не путать с onAction — операциями плана).
   */
  onLessonAction?: (occ: Occurrence) => void;
  /**
   * Шаг 7: быстрые действия admin по клику на урок (перенести/отменить/
   * сменить преподавателя) — кнопки в LessonPopup, видны только при
   * role='admin'. Вызывающая сторона (GroupDetailPage) открывает
   * соответствующую модалку операции плана, предзаполненную по occ.
   * teacher не передаёт — регресс исключён (LessonPopup гейтит по role).
   */
  onAction?: (kind: LessonActionKind, occ: Occurrence) => void;
}

/**
 * Презентационный календарь (view week/month/list, KPI, легенда/фильтр
 * направлений, адаптив narrow→list, LessonPopup). Данные — пропсами, загрузку
 * делает каждый SPA сам (teacher: useCalendar+/api/calendar; admin:
 * useGroupPlanCalendar+/api/admin/groups/<id>/plan). Перенесено 1:1 из
 * teacher-src CalendarPage — поведение/вид не должны регрессировать.
 */
export function CalendarView({
  occurrences: occAll,
  unscheduled,
  isLoading,
  isError,
  isFetching,
  onVisibleRangeChange,
  onLessonAction,
  role,
  onAction,
}: CalendarViewProps) {
  const [monday, setMonday] = useState(() => currentMondayMsk());
  const [monthAnchor, setMonthAnchor] = useState(() => firstOfMonthMsk());
  const [view, setView] = useState<'week' | 'month' | 'list'>('week');
  const [directionFilter, setDirectionFilter] = useState<string | null>(null);
  const [selected, setSelected] = useState<Occurrence | null>(null);

  const narrow = useIsNarrow();
  const today = useMemo(() => todayMsk(), []);
  const isCurrentWeek = sameDay(monday, currentMondayMsk());
  const effectiveView = narrow ? 'list' : view;
  const isCurrentMonth = sameDay(monthAnchor, firstOfMonthMsk());

  /**
   * Окно запроса зависит от вида: week/list — 7 дней выбранной недели;
   * month — 42-дневная сетка (6 недель), покрывающая весь месяц ОДНИМ
   * запросом (окно ≤92 дней укладывается с запасом).
   */
  const windowFrom = effectiveView === 'month' ? isoDate(mondayOfWeek(monthAnchor)) : isoDate(monday);
  const windowTo = effectiveView === 'month'
    ? isoDate(addDays(mondayOfWeek(monthAnchor), 41))
    : isoDate(addDays(monday, 6));

  // Сообщаем вызывающей стороне видимое окно (включая первый рендер) —
  // teacher рефетчит /api/calendar под него; admin может игнорировать.
  useEffect(() => {
    onVisibleRangeChange(windowFrom, windowTo);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onVisibleRangeChange стабилизирует вызывающая сторона (useCallback/инлайн-сеттер); включать её в deps даст лишний ререндер-луп при инлайн-функции.
  }, [windowFrom, windowTo]);

  /** Цвет — прямо из occurrence (direction/color с сервера), клиентская карта направлений не нужна. */
  const colorOf = useCallback(
    (occ: Occurrence): string => resolveDirectionColor(occ.color, occ.direction ?? occ.group),
    [],
  );

  const directionMatch = useCallback((occ: Occurrence) => {
    if (!directionFilter) return true;
    const d = occ.direction ?? null;
    return directionFilter === NO_DIRECTION_KEY ? d == null : d === directionFilter;
  }, [directionFilter]);

  // Занятия ВИДИМОГО окна: teacher уже получает данные под окно с сервера, но
  // admin грузит весь план группы разом (useGroupPlanCalendar), а сетки
  // раскладывают по дню недели (columnIndexOfIsoDate) — без этого фильтра
  // занятия ВСЕХ недель навалились бы на текущую (напр. каждая среда курса — в
  // одну видимую среду). Фильтруем по дате в [windowFrom, windowTo] (ISO-строки
  // сравниваются лексикографически). Для teacher фильтр — no-op.
  const lessons = useMemo(
    () => occAll.filter((o) => directionMatch(o) && o.date >= windowFrom && o.date <= windowTo),
    [occAll, directionMatch, windowFrom, windowTo],
  );
  const timedLessons = useMemo(() => lessons.filter((o) => o.time), [lessons]);
  const noTimeLessons = useMemo(() => lessons.filter((o) => !o.time), [lessons]);

  /** Вид «Месяц»: группировка по occ.date (включая уроки без времени — их некуда положить во time-grid). */
  const monthLessonsByDate = useMemo(() => {
    const map = new Map<string, Occurrence[]>();
    if (effectiveView !== 'month') return map;
    for (const occ of lessons) {
      const arr = map.get(occ.date);
      if (arr) arr.push(occ); else map.set(occ.date, [occ]);
    }
    for (const arr of map.values()) arr.sort((a, b) => (a.time ?? '99:99').localeCompare(b.time ?? '99:99'));
    return map;
  }, [lessons, effectiveView]);

  /** Переключение вида: month↔week/list синхронизирует «якорь» второго вида. */
  const changeView = useCallback((v: 'week' | 'month' | 'list') => {
    if (v === view) return;
    if (v === 'month') {
      setMonthAnchor(monthOf(monday));
    } else if (view === 'month') {
      const containsToday = today.getUTCFullYear() === monthAnchor.getUTCFullYear()
        && today.getUTCMonth() === monthAnchor.getUTCMonth();
      setMonday(containsToday ? currentMondayMsk() : mondayOfWeek(monthAnchor));
    }
    setView(v);
  }, [view, monday, monthAnchor, today]);

  const goPrev = useCallback(() => {
    if (effectiveView === 'month') setMonthAnchor((a) => addMonths(a, -1));
    else setMonday((m) => addWeeks(m, -1));
  }, [effectiveView]);

  const goNext = useCallback(() => {
    if (effectiveView === 'month') setMonthAnchor((a) => addMonths(a, 1));
    else setMonday((m) => addWeeks(m, 1));
  }, [effectiveView]);

  const goToday = useCallback(() => {
    if (effectiveView === 'month') setMonthAnchor(firstOfMonthMsk());
    else setMonday(currentMondayMsk());
  }, [effectiveView]);

  /** Динамическая легенда: реальные направления среди occurrences текущего окна, ДО фильтра направления. */
  const legendItems = useMemo(() => {
    const byName = new Map<string, string>(); // direction name -> color
    let hasNoDirection = false;
    for (const occ of occAll) {
      const name = occ.direction ?? null;
      if (name == null) { hasNoDirection = true; continue; }
      if (!byName.has(name)) byName.set(name, resolveDirectionColor(occ.color, name));
    }
    const items = Array.from(byName.entries())
      .map(([name, color]) => ({ key: name, label: name, color }))
      .sort((a, b) => a.label.localeCompare(b.label, 'ru'));
    if (hasNoDirection) items.push({ key: NO_DIRECTION_KEY, label: 'Без направления', color: NO_DIRECTION_COLOR });
    return items;
  }, [occAll]);

  /** total включает все статусы (в т.ч. cancelled/moved); в overdue/pending они не попадают — статус сравнивается строго. */
  const kpi = useMemo(() => {
    const todayIso = isoDate(today);
    const students = new Set<string>();
    let done = 0, overdue = 0, pending = 0, todayCount = 0;
    for (const occ of lessons) {
      if (occ.status === 'done') done++;
      else if (occ.status === 'overdue') overdue++;
      else if (occ.status === 'pending') pending++;
      if (occ.date === todayIso) todayCount++;
      for (const s of occ.students) students.add(s.name);
    }
    return { total: lessons.length, todayCount, done, overdue, pending, students: students.size };
  }, [lessons, today]);

  return (
    <div className="cal-page">
      {/* Заголовок + навигация недель/месяцев */}
      <div className="cal-head">
        <div className="cal-title">Календарь</div>
        <div className="cal-week-nav">
          <button className="cal-nav-btn" onClick={goPrev} aria-label={effectiveView === 'month' ? 'Предыдущий месяц' : 'Предыдущая неделя'}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6" /></svg>
          </button>
          <span className="cal-week-label">{effectiveView === 'month' ? monthLabel(monthAnchor) : weekRangeLabel(monday)}</span>
          <button className="cal-nav-btn" onClick={goNext} aria-label={effectiveView === 'month' ? 'Следующий месяц' : 'Следующая неделя'}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg>
          </button>
          {(effectiveView === 'month' ? !isCurrentMonth : !isCurrentWeek) && (
            <button className="cal-today-btn" onClick={goToday}>Сегодня</button>
          )}
        </div>

        <div className="cal-toolbar">
          {!narrow && (
            <div className="seg">
              <button className={`seg-btn${view === 'week' ? ' active' : ''}`} onClick={() => changeView('week')}>Неделя</button>
              <button className={`seg-btn${view === 'month' ? ' active' : ''}`} onClick={() => changeView('month')}>Месяц</button>
              <button className={`seg-btn${view === 'list' ? ' active' : ''}`} onClick={() => changeView('list')}>Список</button>
            </div>
          )}
        </div>
      </div>

      {/* KPI */}
      <div className="kpi-grid">
        <Kpi value={kpi.total} label={effectiveView === 'month' ? 'Уроков в месяце' : 'Уроков на неделе'} tone="accent" />
        <Kpi value={kpi.todayCount} label="Уроков сегодня" />
        <Kpi value={kpi.done} label="Заполнено" tone="ok" />
        <Kpi value={kpi.overdue} label="Надо заполнить" tone="warn" />
        <Kpi value={kpi.pending} label="Ещё не было" />
        <Kpi value={kpi.students} label="Учеников" />
      </div>

      {/* Легенда направлений (динамическая; клик = фильтр) + data-quality бейдж unscheduled */}
      <div className="legend">
        {legendItems.map((item) => (
          <span
            key={item.key}
            className={`legend-item${directionFilter && directionFilter !== item.key ? ' muted' : ''}`}
            onClick={() => setDirectionFilter((cur) => (cur === item.key ? null : item.key))}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter') setDirectionFilter((cur) => (cur === item.key ? null : item.key)); }}
          >
            <span className="legend-dot" style={{ background: item.color }} />
            {item.label}
          </span>
        ))}
        {unscheduled.length > 0 && (
          <span
            className="cal-unscheduled"
            title={unscheduled
              .map((u) => `${u.group} — ${UNSCHEDULED_REASON_LABEL[u.reason] ?? 'нет расписания'}`)
              .join('\n')}
          >
            <span className="cal-unscheduled-dot" />
            {unscheduled.length} {pluralizeGroups(unscheduled.length)} без расписания
          </span>
        )}
        {isFetching && <span style={{ fontSize: 12, color: 'var(--text4)', fontFamily: 'var(--font-mono)' }}>обновление…</span>}
      </div>

      {/* Тело */}
      {isLoading ? (
        <div className="cal-skel" />
      ) : isError ? (
        <div className="cal-error">Не удалось загрузить расписание. Попробуйте обновить страницу.</div>
      ) : (effectiveView === 'month' ? monthLessonsByDate.size === 0 : lessons.length === 0) ? (
        <div className="cal-empty">{effectiveView === 'month' ? 'В этом месяце занятий нет.' : 'На этой неделе занятий нет.'}</div>
      ) : (
        <>
          {effectiveView === 'week'
            ? <WeekGrid monday={monday} occurrences={timedLessons} today={today} onSelect={setSelected} resolveColor={colorOf} />
            : effectiveView === 'month'
            ? <MonthGrid monthAnchor={monthAnchor} lessonsByDate={monthLessonsByDate} today={today} onSelect={setSelected} resolveColor={colorOf} />
            : <DayList monday={monday} occurrences={lessons} today={today} onSelect={setSelected} resolveColor={colorOf} />}

          {effectiveView === 'week' && noTimeLessons.length > 0 && (
            <div className="notime-sec">
              <div className="notime-hdr">
                <span className="notime-title">Без указанного времени</span>
                <span className="notime-badge">{noTimeLessons.length}</span>
              </div>
              <div className="notime-grid">
                {noTimeLessons.map((occ, i) => (
                  <div
                    key={`${occ.group}-${occ.date}-${i}`}
                    className={`lrow${occ.status === 'cancelled' ? ' cancelled' : ''}`}
                    style={{ ['--subject-color' as any]: 'var(--text4)', borderTop: 'none' }}
                    onClick={() => setSelected(occ)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter') setSelected(occ); }}
                  >
                    <div className="lrow-time" style={{ fontSize: 12, color: 'var(--text4)' }}>—</div>
                    <div style={{ minWidth: 0 }}>
                      <div className="lrow-title">{occ.groupDisplay}</div>
                      <div className="lrow-meta">{occ.isGroup ? `${occ.students.length} уч.` : occ.teacher}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {selected && (
        <LessonPopup
          lesson={selected}
          onClose={() => setSelected(null)}
          onSubmit={onLessonAction ? () => onLessonAction(selected) : undefined}
          onAction={onAction ? (kind, occ) => { setSelected(null); onAction(kind, occ); } : undefined}
          role={role}
        />
      )}
    </div>
  );
}
