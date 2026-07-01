import { Link } from 'react-router-dom';
import { useStudentStats } from '../../hooks/useStudents';
import { fmtDate } from '../../lib/format';

function pctColor(p: number | null | undefined): string {
  if (p == null) return 'var(--text3)';
  if (p >= 80) return 'var(--green)';
  if (p >= 50) return 'var(--amber)';
  return 'var(--red)';
}

export default function StudentStatsBlock({ studentId }: { studentId: number }) {
  const { data: stats, isLoading, error } = useStudentStats(studentId);

  if (isLoading) return <div className="memberships__empty" style={{ padding: 14 }}>Загружаем…</div>;
  if (error) return <div className="memberships__empty" style={{ padding: 14, color: 'var(--red)' }}>Не удалось загрузить статистику</div>;
  if (!stats) return null;

  const directions = stats.directions.filter((d) => d.lessons_recorded > 0);
  if (directions.length === 0 || stats.overall.lessons_recorded === 0) {
    return <div className="memberships__empty" style={{ padding: 14 }}>Нет данных о посещаемости</div>;
  }

  const overall = stats.overall;
  const overallPct = overall.attendance_pct ?? 0;
  const overallC = pctColor(overall.attendance_pct);
  const monthPct = overall.this_month.attendance_pct;
  const monthC = pctColor(monthPct);

  return (
    <>
      <div className="stats-overall">
        <div className="stats-overall__pct" style={{ color: overallC }}>{overallPct}%</div>
        <div className="stats-overall__detail">
          <div className="stats-overall__num">{overall.attended_count} / {overall.denominator}</div>
          <div className="stats-overall__label">
            Посещено уроков {overall.denominator !== overall.lessons_recorded ? '(к плану курса)' : ''}
          </div>
          {overall.denominator !== overall.lessons_recorded && (
            <div className="stats-overall__sub">проведено: {overall.lessons_recorded}</div>
          )}
        </div>
        {overall.this_month.lessons_recorded > 0 && (
          <>
            <div className="stats-overall__divider" />
            <div className="stats-overall__period">
              <div className="stats-overall__period-label">Этот месяц</div>
              <div className="stats-overall__period-row">
                <span className="stats-overall__period-pct" style={{ color: monthC }}>{monthPct ?? 0}%</span>
                <span className="stats-overall__period-num">{overall.this_month.attended_count} / {overall.this_month.lessons_recorded}</span>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="dir-cards">
        {directions.map((d) => {
          const pct = d.attendance_pct ?? 0;
          const pctC = pctColor(d.attendance_pct);
          const planLabel = d.course_total_lessons
            ? `план курса: ${d.course_total_lessons} уроков`
            : `проведено: ${d.lessons_recorded}`;
          const dirColor = d.direction_color || '#0d9488';
          const mLessons = d.this_month.lessons_recorded;
          const mAttended = d.this_month.attended_count;

          return (
            <div key={d.direction_id} className="dir-card" style={{ ['--dir-color' as string]: dirColor }}>
              <div className="dir-card__header">
                <div className="dir-card__name-row">
                  <div className="dir-card__name">{d.direction_name}</div>
                  <div className="dir-card__sub">{planLabel} · посл. {fmtDate(d.last_attended)}</div>
                </div>
                <div className="dir-card__pct" style={{ color: pctC }}>{pct}%</div>
              </div>
              <div className="dir-card__progress">
                <div className="dir-card__progress-bar">
                  <div
                    className="dir-card__progress-fill"
                    style={{ width: `${Math.min(pct, 100)}%`, background: pctC }}
                  />
                </div>
                <div className="dir-card__counts">
                  <span className="dir-card__num-value">{d.attended_count}</span>
                  <span className="dir-card__num-label">/ {d.denominator}</span>
                  {d.denominator !== d.lessons_recorded && (
                    <span className="dir-card__num-sub">(проведено {d.lessons_recorded})</span>
                  )}
                </div>
              </div>
              <div className="dir-card__chips">
                {mLessons > 0 ? (
                  <span className="dir-chip dir-chip--month" style={{ color: pctColor(d.this_month.attendance_pct) }}>
                    📅 этот месяц: {mAttended}/{mLessons}
                  </span>
                ) : (
                  <span className="dir-chip dir-chip--empty">📅 в этом месяце уроков не было</span>
                )}
              </div>
              <div className="dir-card__groups">
                <div className="dir-card__groups-label">В группах:</div>
                {[...d.groups]
                  .sort((a, b) => Number(b.membership_active) - Number(a.membership_active))
                  .map((g) => {
                    const archived = !g.membership_active;
                    return (
                      <div key={g.group_id} className={`dir-group ${archived ? 'is-archived' : ''}`}>
                        <div className="dir-group__head">
                          <span className="dir-group__name">
                            <Link to={`/admin/groups/${g.group_id}`} className="entity-link">{g.group_name}</Link>
                          </span>
                          {archived && <span className="archive-tag">Архив</span>}
                        </div>
                        <div className="dir-group__stats">
                          <span className="dir-group__num">
                            <b>{g.attended_count}</b> уроков посещено{g.lessons_recorded > 0 ? ` из ${g.lessons_recorded} проведённых` : ''}
                          </span>
                          <span className="dir-group__pct" style={{ color: pctColor(g.attendance_pct) }}>
                            {g.attendance_pct ?? 0}%
                          </span>
                        </div>
                      </div>
                    );
                  })}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
