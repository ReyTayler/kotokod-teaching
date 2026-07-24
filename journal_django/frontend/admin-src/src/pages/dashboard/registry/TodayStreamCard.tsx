import { EntityLink } from '../../../components/EntityLink';
import type { TodayStreamItem } from '../../../lib/types';

const STATUS_LABEL: Record<string, string> = {
  pending: 'ожидается',
  overdue: 'просрочено',
  done: 'проведено',
};

// «Поток дня» — плановые занятия всех групп на сегодня (время · код · препод · статус).
export function TodayStreamCard({ items }: { items: TodayStreamItem[] }) {
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
          {items.map((it, i) => (
            <li key={i} className="reg-stream__row">
              <span className="reg-stream__time">{it.time || '—'}</span>
              <span className="reg-stream__code">
                <EntityLink section="groups" id={it.group_id} text={it.group_code} />
              </span>
              <span className={`reg-stream__status reg-stream__status--${it.status}`}>
                {STATUS_LABEL[it.status] || it.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
