import { Link } from 'react-router-dom';
import { EntityLink } from '../../components/EntityLink';
import { EmptyState } from '../../components/ui/EmptyState';
import { fmtLessons } from '../../lib/format';
import type { DashboardDebt } from '../../lib/types';

interface Props {
  debts: DashboardDebt[];
  total: number;
}

export function DebtsCard({ debts, total }: Props) {
  return (
    <section className="dash-card dash-debts">
      <header className="dash-card__head">
        <h2 className="dash-card__title">Долги</h2>
        <span className="dash-card__count">{total}</span>
      </header>
      {debts.length === 0 ? (
        <EmptyState>Долгов нет</EmptyState>
      ) : (
        <ul className="dash-debts__list">
          {debts.map((d) => (
            <li key={`${d.student_id}:${d.direction_id}`} className="dash-debts__row">
              <span className="dash-debts__name">
                <EntityLink section="students" id={d.student_id} text={d.student_name} />
              </span>
              <span className="dash-debts__balance mono">{fmtLessons(d.balance)}</span>
              <span className="dash-debts__dir">{d.direction_name}</span>
            </li>
          ))}
          {total > debts.length && (
            <li className="dash-debts__more">
              <Link to="/admin/students">… ещё {total - debts.length} → все ученики</Link>
            </li>
          )}
        </ul>
      )}
    </section>
  );
}
