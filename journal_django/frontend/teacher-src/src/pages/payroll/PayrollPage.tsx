import { useMemo, useState } from 'react';
import { useMyPayroll } from '../../hooks/useMyPayroll';
import { addMonths, firstOfMonthMsk, isoMonth, monthLabel, weekdayShortOfIso } from '../../lib/dates';
import { formatDeduction, formatMoney, isPositive } from '../../lib/money';
import { resolveDirectionColor } from '../../lib/subjects';
import type { PayrollEntry, PayrollLessonKind } from '../../lib/types';

/** Подпись типа урока. Обычный урок бейджа не получает — это шум. */
const KIND_LABEL: Partial<Record<PayrollLessonKind, string>> = {
  substitution: 'Замена',
  reschedule: 'Перенос',
  extra: 'Доп. занятие',
  burned: 'Сгоревшее занятие',
};

const PLURAL_LESSONS = ['урок', 'урока', 'уроков'];
const PLURAL_PRESENCES = ['присутствие', 'присутствия', 'присутствий'];

function plural(count: number, forms: string[]): string {
  const mod100 = count % 100;
  if (mod100 >= 11 && mod100 <= 14) return forms[2];
  const mod10 = count % 10;
  if (mod10 === 1) return forms[0];
  if (mod10 >= 2 && mod10 <= 4) return forms[1];
  return forms[2];
}

/** «03.07» из 'YYYY-MM-DD' — год в списке за месяц избыточен. */
function dayMonthOfIso(iso: string): string {
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
}

function PayrollRow({ entry }: { entry: PayrollEntry }) {
  const kindLabel = KIND_LABEL[entry.kind];
  const hasPenalty = isPositive(entry.penalty);

  return (
    <div
      className="pr-row"
      style={{ ['--subject-color' as string]: resolveDirectionColor(entry.directionColor, entry.direction ?? entry.group) }}
    >
      <div className="pr-date">
        <span className="pr-date-day">{dayMonthOfIso(entry.date)}</span>
        <span className="pr-date-dow">{weekdayShortOfIso(entry.date)}</span>
      </div>

      <div className="pr-main">
        <div className="pr-title">
          <span className="pr-group">{entry.group}</span>
          {kindLabel && (
            <span className={`pr-badge pr-badge--${entry.kind}`}>{kindLabel}</span>
          )}
        </div>

        <div className="pr-formula">
          <span className="pr-attendance">
            пришли {entry.presentCount} из {entry.totalStudents}
          </span>
          <span className="pr-sep">·</span>
          <span className="pr-rule" title={entry.rule.note}>{entry.rule.text}</span>
        </div>

        {entry.excludedNote && <div className="pr-note">{entry.excludedNote}</div>}
        {hasPenalty && (
          <div className="pr-penalty">
            {formatDeduction(entry.penalty)} · {entry.penaltyNote}
          </div>
        )}
        {entry.adjusted && <div className="pr-note">{entry.rule.note}</div>}
      </div>

      <div className="pr-amount">
        <span className="pr-net">{formatMoney(entry.net)}</span>
        {hasPenalty && (
          <span className="pr-gross">начислено {formatMoney(entry.payment)}</span>
        )}
      </div>
    </div>
  );
}

/**
 * Зарплата преподавателя за месяц.
 *
 * Задача экрана — не «показать сумму», а сделать её проверяемой: рядом с каждой
 * выплатой стоит правило, по которому она получилась, а удержания и не учтённые
 * в оплате ученики названы явно. Суммы считает сервер (apps/payroll), фронт
 * ничего не пересчитывает — иначе появился бы второй источник правды о деньгах.
 */
export default function PayrollPage() {
  const [month, setMonth] = useState<Date>(() => firstOfMonthMsk());
  const currentMonth = useMemo(() => firstOfMonthMsk(), []);
  const isCurrentMonth = month.getTime() >= currentMonth.getTime();

  const { data, isLoading, isError, isFetching } = useMyPayroll(isoMonth(month));

  const totals = data?.totals;
  const hasPenalty = totals ? isPositive(totals.penalty) : false;

  return (
    <div className="pr-page">
      <div className="cal-head">
        <div className="cal-title">Зарплата</div>
        <div className="cal-week-nav">
          <button
            type="button"
            className="cal-nav-btn"
            onClick={() => setMonth((m) => addMonths(m, -1))}
            aria-label="Предыдущий месяц"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6" /></svg>
          </button>
          <span className="cal-week-label">{monthLabel(month)}</span>
          <button
            type="button"
            className="cal-nav-btn"
            onClick={() => setMonth((m) => addMonths(m, 1))}
            disabled={isCurrentMonth}
            aria-label="Следующий месяц"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg>
          </button>
          {!isCurrentMonth && (
            <button type="button" className="cal-today-btn" onClick={() => setMonth(currentMonth)}>
              Текущий месяц
            </button>
          )}
        </div>
        {isFetching && <span className="ml-updating">обновление…</span>}
      </div>

      {isLoading ? (
        <div className="cal-skel" style={{ height: 320 }} />
      ) : isError ? (
        <div className="cal-error">Не удалось загрузить зарплату.</div>
      ) : (
        <>
          <div className="pr-summary">
            <div className="pr-summary-main">
              <div className="pr-summary-label">К выплате</div>
              <div className="pr-summary-value">{formatMoney(totals?.net ?? '0')}</div>
            </div>
            <div className="pr-summary-side">
              <div className="pr-summary-line">
                начислено <b>{formatMoney(totals?.payment ?? '0')}</b>
                {hasPenalty && (
                  <>
                    <span className="pr-sep">·</span>
                    штрафы <b className="pr-summary-penalty">{formatDeduction(totals!.penalty)}</b>
                  </>
                )}
              </div>
              <div className="pr-summary-count">
                {totals?.lessons ?? 0} {plural(totals?.lessons ?? 0, PLURAL_LESSONS)}
                <span className="pr-sep">·</span>
                {totals?.presences ?? 0} {plural(totals?.presences ?? 0, PLURAL_PRESENCES)}
              </div>
            </div>
          </div>

          {data && data.rows.length === 0 ? (
            <div className="cal-empty">В этом месяце проведённых уроков ещё нет.</div>
          ) : (
            <div className="pr-list">
              {data?.rows.map((entry) => (
                <PayrollRow key={entry.lessonId} entry={entry} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
