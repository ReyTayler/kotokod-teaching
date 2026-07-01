import { useSearchParams } from 'react-router-dom';
import { SubscriptionsView } from './SubscriptionsView';
import { DiscountsView } from './DiscountsView';

type Tab = 'subscriptions' | 'discounts';

export default function SubscriptionsPage() {
  const [sp, setSp] = useSearchParams();
  const tab: Tab = sp.get('tab') === 'discounts' ? 'discounts' : 'subscriptions';
  const setTab = (t: Tab) => {
    const next = new URLSearchParams(sp);
    if (t === 'subscriptions') next.delete('tab');
    else next.set('tab', t);
    setSp(next, { replace: true });
  };

  return (
    <section className="page">
      <div className="section-head">
        <h2>Абонементы и скидки</h2>
        <div className="section-actions">
          <button
            type="button"
            className="btn-secondary"
            style={tab === 'subscriptions' ? { background: 'var(--accent)', color: '#fff', borderColor: 'var(--accent)' } : undefined}
            onClick={() => setTab('subscriptions')}
          >Абонементы</button>
          <button
            type="button"
            className="btn-secondary"
            style={tab === 'discounts' ? { background: 'var(--accent)', color: '#fff', borderColor: 'var(--accent)' } : undefined}
            onClick={() => setTab('discounts')}
          >Скидки</button>
        </div>
      </div>

      {tab === 'subscriptions' ? <SubscriptionsView /> : <DiscountsView />}
    </section>
  );
}
