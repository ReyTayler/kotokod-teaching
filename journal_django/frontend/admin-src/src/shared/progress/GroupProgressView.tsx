import { useMemo, useState, type MouseEvent } from 'react';
import { Avatar } from '../../components/Avatar';
import type { GroupProgress, ProgressSlot } from './types';

const WD = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
const MON = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

/** ISO 'YYYY-MM-DD' → 'Чт, 5 мар' (день недели + дд + месяц). */
function fmtLessonDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${WD[wd]}, ${d} ${MON[m - 1]}`;
}

type CellStatus = 'present' | 'absent' | 'planned' | 'transferred';

function cellStatus(cell: boolean | null): CellStatus {
  if (cell === true) return 'present';
  if (cell === false) return 'absent';
  return 'planned';
}

const STATUS_LABEL: Record<CellStatus, string> = {
  present: 'Был',
  absent: 'Не был',
  planned: 'Не проведён',
  transferred: 'Перевод',
};

/**
 * Статусы ленты ученика с учётом «бюджета» переведённых уроков: расходуется
 * слева направо только на cell === null, реальные true/false никогда не
 * перекрываются статусом transferred.
 */
function computeCellStatuses(cells: (boolean | null)[], transferredLessons: number): CellStatus[] {
  let transferredLeft = transferredLessons;
  return cells.map((cell) => {
    if (cell === null && transferredLeft > 0) { transferredLeft--; return 'transferred'; }
    return cellStatus(cell);
  });
}

/** Цвет процента посещаемости: ≥80 зелёный, ≥60 янтарный, иначе красный. */
function pctColor(pct: number): string {
  if (pct >= 80) return 'var(--success)';
  if (pct >= 60) return 'var(--warning)';
  return 'var(--danger)';
}

interface TipState {
  slot: number;
  status: CellStatus;
  date: string | null;
  transferredFromGroupName: string | null;
  x: number;
  y: number;
}

/**
 * Презентационная матрица посещаемости группы (Вариант 2 — лента плиток на
 * ученика + процент/счётчик справа). Общая для admin (вкладка «Прогресс»
 * Group detail) и teacher (страница группы): данные приходят пропсом, загрузку/
 * ошибки/пустое состояние обрабатывает вызывающая сторона. Стили —
 * shared/progress/progress.css.
 */
export function GroupProgressView({ data }: { data: GroupProgress }) {
  const [tip, setTip] = useState<TipState | null>(null);

  const avgPct = useMemo(() => {
    if (data.students.length === 0) return null;
    const withHeld = data.students.filter((s) => s.held > 0);
    if (withHeld.length === 0) return null;
    return Math.round(withHeld.reduce((a, s) => a + s.pct, 0) / withHeld.length);
  }, [data]);

  const slots: ProgressSlot[] = data.slots;

  const showTip = (
    e: MouseEvent<HTMLElement>, slot: ProgressSlot, status: CellStatus, transferredFromGroupName: string | null,
  ) => {
    const r = e.currentTarget.getBoundingClientRect();
    setTip({
      slot: slot.slot,
      status,
      date: slot.date,
      transferredFromGroupName,
      x: r.left + r.width / 2,
      y: r.top,
    });
  };

  return (
    <div className="progress-view">
      <div className="progress-view__head">
        <div className="progress-legend" role="group" aria-label="Обозначения">
          <span className="progress-legend__item"><span className="progress-chip is-present" />Был</span>
          <span className="progress-legend__item"><span className="progress-chip is-absent" />Не был</span>
          <span className="progress-legend__item"><span className="progress-chip is-planned" />Не проведён</span>
          <span className="progress-legend__item"><span className="progress-chip is-transferred" />Перевод</span>
        </div>
        <div className="progress-view__summary">
          {avgPct !== null && (
            <span className="progress-summary-pill">
              Средняя посещаемость <b style={{ color: pctColor(avgPct) }}>{avgPct}%</b>
            </span>
          )}
          <span className="progress-summary-pill">
            Проведено <b>{data.held_slots}</b> из {data.total_slots}
          </span>
        </div>
      </div>

      <div className="progress-rows" onMouseLeave={() => setTip(null)}>
        {data.students.map((s) => (
          <div key={s.student_id} className="progress-row">
            <div className="progress-row__who">
              <Avatar name={s.name} size={30} />
              <span className="progress-row__name" title={s.name}>{s.name}</span>
            </div>

            <div className="progress-ribbon">
              {computeCellStatuses(s.cells, s.transferred_lessons).map((st, i) => {
                const slot = slots[i];
                const label = st === 'transferred'
                  ? `Урок №${slot.slot}: Перевод из «${s.transferred_from_group_name}»`
                  : `Урок №${slot.slot}: ${STATUS_LABEL[st]}${slot.date ? `, ${fmtLessonDate(slot.date)}` : ''}`;
                return (
                  <span
                    key={slot.slot}
                    className={`progress-sq is-${st}`}
                    role="img"
                    aria-label={label}
                    onMouseEnter={(e) => showTip(e, slot, st, st === 'transferred' ? s.transferred_from_group_name : null)}
                  />
                );
              })}
            </div>

            <div className="progress-row__stat">
              <span className="progress-bar" aria-hidden>
                <i style={{ width: `${s.pct}%`, background: pctColor(s.pct) }} />
              </span>
              <span className="progress-pct" style={{ color: pctColor(s.pct) }}>{s.pct}%</span>
              <span className="progress-cnt">{s.present}/{s.held}</span>
            </div>
          </div>
        ))}
      </div>

      {tip && (
        <div
          className={`progress-tip is-${tip.status}`}
          style={{ left: tip.x, top: tip.y }}
          role="tooltip"
        >
          <span className="progress-tip__lesson">Урок №{tip.slot}</span>
          <span className="progress-tip__date">
            {tip.status === 'transferred'
              ? `из «${tip.transferredFromGroupName}»`
              : (tip.date ? fmtLessonDate(tip.date) : 'ещё не проведён')}
          </span>
          <span className="progress-tip__status">
            <span className="progress-tip__dot" />{STATUS_LABEL[tip.status]}
          </span>
        </div>
      )}
    </div>
  );
}
