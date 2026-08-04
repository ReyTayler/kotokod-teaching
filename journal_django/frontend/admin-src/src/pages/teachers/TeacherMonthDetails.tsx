import { plural } from '../../lib/labels';
import { DOW } from '../../lib/slots';
import type { TeacherStats } from '../../hooks/useTeacherStats';

interface Props {
  stats: TeacherStats | undefined;
}

/** Вс=0 в данных, но неделя показывается с понедельника — так её читают. */
const WEEK_ORDER = [1, 2, 3, 4, 5, 6, 0];

/**
 * Нижний ряд вкладки «Обзор»: когда преподаватель занят и чем закончились
 * пропуски в его группах за месяц.
 *
 * Дни недели считаются по ФАКТУ проведённых занятий, а не по шаблону
 * расписания: шаблон говорит, когда занятия должны быть, а переносы и замены
 * он не показывает вовсе. Вопрос «в какие дни он занят» — про то, как вышло.
 */
export default function TeacherMonthDetails({ stats }: Props) {
  const load = stats?.weekday_load ?? [];
  const byDay = new Map(load.map((r) => [r.day, r.sessions]));
  const max = load.reduce((acc, r) => Math.max(acc, r.sessions), 0);
  const abs = stats?.absences;
  const ren = stats?.renewals;

  return (
    <div className="tbreak tbreak--three">
      <section className="tbreak__col">
        <h3 className="sub-header">Дни недели</h3>
        {max === 0 ? (
          <p className="tmd__empty">Занятий за этот месяц не было.</p>
        ) : (
          <div className="tweek" role="img" aria-label="Занятий по дням недели">
            {WEEK_ORDER.map((day) => {
              const sessions = byDay.get(day) ?? 0;
              return (
                <div key={day} className="tweek__day">
                  <div className="tweek__track">
                    <div
                      className="tweek__fill"
                      style={{ height: max ? `${(sessions / max) * 100}%` : '0%' }}
                    />
                  </div>
                  <div className="tweek__n">{sessions || ''}</div>
                  <div className="tweek__label">{DOW[day]}</div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="tbreak__col">
        <h3 className="sub-header">Пропуски за месяц</h3>
        {!abs || abs.registered === 0 ? (
          <p className="tmd__empty">
            Пропусков в группах преподавателя за этот месяц не зарегистрировано.
          </p>
        ) : (
          <dl className="tmd">
            <div className="tmd__row">
              <dt>Зарегистрировано</dt>
              <dd>{abs.registered}</dd>
            </div>
            <div className="tmd__row">
              <dt>Отработано</dt>
              <dd>{abs.makeup_done}</dd>
            </div>
            <div className="tmd__row">
              <dt>Назначена отработка</dt>
              <dd>{abs.makeup_scheduled}</dd>
            </div>
            <div className="tmd__row">
              <dt>Сгорело</dt>
              <dd>{abs.burned}</dd>
            </div>
          </dl>
        )}
      </section>

      <section className="tbreak__col">
        <h3 className="sub-header">Продления за всё время</h3>
        {!ren || ren.won + ren.lost === 0 ? (
          <p className="tmd__empty">Закрытых сделок продления пока нет.</p>
        ) : (
          <>
            <dl className="tmd">
              <div className="tmd__row">
                <dt>Продлились</dt>
                <dd>{ren.won}</dd>
              </div>
              <div className="tmd__row">
                <dt>Ушли</dt>
                <dd>{ren.lost}</dd>
              </div>
              <div className="tmd__row">
                <dt>В работе сейчас</dt>
                <dd>{ren.open}</dd>
              </div>
            </dl>
            {/* Оговорка обязана быть на виду, а не только в коде: иначе долю
                прочтут как эксклюзивную заслугу преподавателя. */}
            <p className="tmd__note">
              Считаются все {ren.students}{' '}
              {plural(ren.students, 'ученик', 'ученика', 'учеников')}, кто когда-либо
              занимался в его группах. Сделка привязана к ученику, а не к направлению,
              поэтому занимающийся у двух преподавателей учитывается обоим.
            </p>
          </>
        )}
      </section>
    </div>
  );
}
