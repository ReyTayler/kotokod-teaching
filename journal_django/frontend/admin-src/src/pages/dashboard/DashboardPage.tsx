import { lazy, Suspense } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PageLoading } from '../../components/ui/Skeleton';
import FinanceView from './FinanceView';

// Реестр — отдельный чанк: таблица/сигналы грузятся только при открытии вкладки.
const RegistryTab = lazy(() => import('./registry/RegistryTab'));

type Tab = 'finance' | 'registry';

export default function DashboardPage() {
  const [sp, setSp] = useSearchParams();
  const tab: Tab = sp.get('tab') === 'registry' ? 'registry' : 'finance';

  const setTab = (t: Tab) => {
    const next = new URLSearchParams(sp);
    if (t === 'finance') next.delete('tab');
    else next.set('tab', t);
    setSp(next, { replace: true });
  };

  return (
    <div className="dashboard">
      <header className="dashboard__head">
        <h1 className="dashboard__title">Дашборд</h1>
      </header>

      <nav className="dash-tabs" role="tablist" aria-label="Разделы дашборда">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'finance'}
          className={`dash-tab${tab === 'finance' ? ' dash-tab--active' : ''}`}
          onClick={() => setTab('finance')}
        >
          Финансы
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'registry'}
          className={`dash-tab${tab === 'registry' ? ' dash-tab--active' : ''}`}
          onClick={() => setTab('registry')}
        >
          Реестр
        </button>
      </nav>

      {tab === 'finance' ? (
        <FinanceView />
      ) : (
        <Suspense fallback={<PageLoading />}>
          <RegistryTab />
        </Suspense>
      )}
    </div>
  );
}
