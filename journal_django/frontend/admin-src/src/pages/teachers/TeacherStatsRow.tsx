import { StatTiles, type StatTile } from '../../components/detail/StatTiles';
import { MONTHS_RU } from '../../lib/slots';
import type { Group } from '../../lib/types';
import type { TeacherStats } from '../../hooks/useTeacherStats';

interface Props {
  month: string;
  onMonthChange: (month: string) => void;
  stats: TeacherStats | undefined;
  groups: Group[];
}

/** 'YYYY-MM' + сдвиг в месяцах → 'YYYY-MM'. */
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number);
  const zero = y * 12 + (m - 1) + delta;
  return `${Math.floor(zero / 12)}-${String((zero % 12) + 1).padStart(2, '0')}`;
}

/** 'YYYY-MM' → 'Июль 2026'. */
function monthLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  return `${MONTHS_RU[m - 1]} ${y}`;
}

/** 3750 → '62,5'. Часы астрономические: 45/60/90 мин не делятся на академчас ровно. */
function hours(minutes: number): string {
  return (minutes / 60).toFixed(1).replace('.', ',');
}

/** [{minutes:90,sessions:34}, …] → '90 мин ×34 · 45 мин ×8'. */
function durationsLabel(rows: TeacherStats['by_duration']): string {
  if (rows.length === 0) return 'занятий не было';
  return rows.map((r) => `${r.minutes} мин ×${r.sessions}`).join(' · ');
}

/**
 * Ключевые числа преподавателя.
 *
 * Месяцем управляются ТОЛЬКО «Занятий» и «Часов» — «Учеников» и «Группы» это
 * текущий срез, и подписи это проговаривают: иначе рядом стоят четыре числа,
 * из которых два за период, а два нет, и разницу никто не заметит.
 */
export default function TeacherStatsRow({ month, onMonthChange, stats, groups }: Props) {
  const active = groups.filter((g) => g.active);
  const archived = groups.length - active.length;
  const students = active.reduce((sum, g) => sum + (g.members_count ?? 0), 0);
  const avgSize = active.length ? (students / active.length).toFixed(1).replace('.', ',') : '0';

  const total = stats?.total;

  const tiles: StatTile[] = [
    {
      label: 'Занятий',
      value: total?.sessions ?? '—',
      sub: total && total.substitutions > 0
        ? `из них ${total.substitutions} замен`
        : 'курсовых, без доп.уроков',
    },
    {
      label: 'Часов',
      value: total ? hours(total.minutes) : '—',
      sub: stats ? durationsLabel(stats.by_duration) : '',
    },
    {
      label: 'Учеников',
      value: students,
      sub: active.length ? `в среднем ${avgSize} на группу` : 'активных групп нет',
    },
    {
      label: 'Групп',
      value: `${active.length}${archived ? ` / ${archived}` : ''}`,
      sub: archived ? 'активных / в архиве' : 'активных',
    },
  ];

  return (
    <div className="tstats">
      <div className="month-nav">
        <button
          type="button"
          className="month-nav__btn"
          onClick={() => onMonthChange(shiftMonth(month, -1))}
          aria-label="Предыдущий месяц"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <span className="month-nav__label">{monthLabel(month)}</span>
        <button
          type="button"
          className="month-nav__btn"
          onClick={() => onMonthChange(shiftMonth(month, 1))}
          aria-label="Следующий месяц"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      </div>
      <StatTiles items={tiles} />
    </div>
  );
}
