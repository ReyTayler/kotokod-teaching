import { useEffect, useState } from 'react';
import { EntityLink } from '../../../components/EntityLink';
import { minutesNowMSK, parseHHMM } from '../../../lib/format';
import type { TodayStreamItem } from '../../../lib/types';

/**
 * Состояние строки потока. Из БД приходит только «записан или нет»
 * (PlannedLesson.status), остальное — вопрос текущего времени, поэтому
 * считается здесь, а не на сервере: сводка кэшируется на 2 минуты и
 * серверный ярлык «идёт урок» протух бы, не успев появиться.
 */
type StreamState = 'pending' | 'running' | 'unmarked' | 'done';

const STATE_LABEL: Record<StreamState, string> = {
  pending: 'ожидается',
  running: 'идёт урок',
  unmarked: 'не отмечен',
  done: 'проведено',
};

const DAY_MINUTES = 24 * 60;
const DEFAULT_DURATION = 90;
// Раз в полминуты: занятие начинается и заканчивается с точностью до минуты,
// и статус должен переключиться сам, без перезагрузки страницы.
const TICK_MS = 30_000;

function minutesToHHMM(total: number): string {
  const m = Math.max(0, Math.min(total, DAY_MINUTES));
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
}

function resolveState(it: TodayStreamItem, nowMin: number): StreamState {
  if (it.status === 'done') return 'done';
  const start = parseHHMM(it.time);
  // Без времени начала часы бесполезны — верим серверу.
  if (start === null) return it.status === 'overdue' ? 'unmarked' : 'pending';
  const end = Math.min(start + (it.duration_minutes || DEFAULT_DURATION), DAY_MINUTES);
  if (nowMin < start) return 'pending';
  if (nowMin < end) return 'running';
  return 'unmarked';
}

/** Подсказка при наведении: почему статус именно такой. */
function hintFor(state: StreamState, it: TodayStreamItem): string | undefined {
  const start = parseHHMM(it.time);
  if (start === null) return undefined;
  const end = minutesToHHMM(start + (it.duration_minutes || DEFAULT_DURATION));
  if (state === 'running') return `Идёт до ${end}`;
  if (state === 'unmarked') return `Занятие закончилось в ${end}, урок ещё не записан`;
  return undefined;
}

// Текущее время по МСК в минутах, само обновляющееся, пока карточка на экране.
function useMskMinutes(): number {
  const [now, setNow] = useState(minutesNowMSK);
  useEffect(() => {
    const id = setInterval(() => setNow(minutesNowMSK()), TICK_MS);
    return () => clearInterval(id);
  }, []);
  return now;
}

// «Поток дня» — плановые занятия всех групп на сегодня: время · группа · препод · статус.
export function TodayStreamCard({ items }: { items: TodayStreamItem[] }) {
  const nowMin = useMskMinutes();

  return (
    <section className="dash-card">
      <div className="dash-card__head">
        <span className="dash-card__title">Поток дня</span>
        <span className="dash-card__count">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <div className="reg-stream__empty">Сегодня занятий нет</div>
      ) : (
        <ul className="reg-stream">
          {items.map((it, i) => {
            const state = resolveState(it, nowMin);
            return (
              <li key={i} className={`reg-stream__row reg-stream__row--${state}`}>
                <span className="reg-stream__time">{it.time || '—'}</span>
                <span className="reg-stream__code">
                  <EntityLink section="groups" id={it.group_id} text={it.group_code} />
                </span>
                <span className="reg-stream__teacher">{it.teacher_name || '—'}</span>
                <span
                  className={`reg-stream__status reg-stream__status--${state}`}
                  title={hintFor(state, it)}
                >
                  {STATE_LABEL[state]}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
