import type { Occurrence } from './types';
import { addDays, dayMonth, sameDay, columnIndexOfIsoDate } from './lib';

const ROW_H = 56;
const HOUR_START = 8;
const HOUR_END = 21;              // последний час-строка (включительно)
const N_ROWS = HOUR_END - HOUR_START + 1;
const DAY_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

function topPx(time: string): number {
  const [h, m] = time.split(':').map(Number);
  const hh = Math.min(Math.max(h, HOUR_START), HOUR_END);
  return (hh - HOUR_START) * ROW_H + (m / 60) * ROW_H;
}

/** Недельная time-grid (десктоп). Столбец дня = по occ.date, не по монотонной ссылке на report.day. */
export function WeekGrid({
  monday,
  occurrences,
  today,
  onSelect,
  resolveColor,
}: {
  monday: Date;
  occurrences: Occurrence[];
  today: Date;
  onSelect: (occ: Occurrence) => void;
  resolveColor: (occ: Occurrence) => string;
}) {
  const cols = Array.from({ length: 7 }, (_, c) => {
    const date = addDays(monday, c);
    return { c, date, isToday: sameDay(date, today) };
  });

  const byCol: Occurrence[][] = Array.from({ length: 7 }, () => []);
  for (const occ of occurrences) {
    if (!occ.time) continue;
    byCol[columnIndexOfIsoDate(occ.date)].push(occ);
  }

  const bodyHeight = N_ROWS * ROW_H;

  return (
    <div className="cal-grid-wrap">
      <div className="cal-grid-head">
        <div className="cal-col-head" />
        {cols.map(({ c, date, isToday }) => (
          <div key={c} className={`cal-col-head${isToday ? ' today' : ''}`}>
            <div className="cal-col-day">{DAY_SHORT[c]}</div>
            <div className="cal-col-date">{dayMonth(date)}</div>
          </div>
        ))}
      </div>

      <div className="cal-grid-body" style={{ ['--row-h' as any]: `${ROW_H}px` }}>
        <div className="cal-gutter" style={{ height: bodyHeight }}>
          {Array.from({ length: N_ROWS }, (_, i) => (
            <div key={i} className="cal-hour-label" style={{ top: i * ROW_H }}>
              {String(HOUR_START + i).padStart(2, '0')}
            </div>
          ))}
        </div>

        {cols.map(({ c, isToday }) => (
          <div
            key={c}
            className={`cal-col${isToday ? ' today' : ''}`}
            style={{ height: bodyHeight }}
          >
            {byCol[c].map((occ, i) => (
              <div
                key={`${occ.group}-${occ.date}-${occ.time}-${i}`}
                className={`lb${occ.status === 'overdue' ? ' overdue' : ''}${occ.status === 'cancelled' ? ' cancelled' : ''}`}
                style={{ top: topPx(occ.time!), height: ROW_H - 4, ['--subject-color' as any]: resolveColor(occ) }}
                onClick={() => onSelect(occ)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter') onSelect(occ); }}
                title={occ.status === 'moved' || occ.status === 'cancelled' ? occ.label : undefined}
              >
                {occ.movedFrom && <span className="cal-moved" title={`Перенесён с ${occ.movedFrom}`} aria-label="перенесён">↪</span>}
                <div className="lb-time">{occ.time}</div>
                <div className="lb-title">{occ.groupDisplay}</div>
                <div className="lb-meta">
                  {occ.status === 'moved' || occ.status === 'cancelled'
                    ? occ.label
                    : occ.isGroup ? `${occ.students.length} уч.` : occ.teacher}
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
