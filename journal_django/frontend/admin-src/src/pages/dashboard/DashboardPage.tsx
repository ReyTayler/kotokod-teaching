import { lazy, Suspense } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PageLoading } from '../../components/ui/Skeleton';
import FinanceView from './FinanceView';
import { PageHeader } from '../../components/shell/PageHeader';

// Реестр — отдельный чанк: таблица/сигналы грузятся только при открытии вкладки.
const RegistryTab = lazy(() => import('./registry/RegistryTab'));
const FillTab = lazy(() => import('./fill/FillTab'));

type Tab = 'finance' | 'registry' | 'fill';

export default function DashboardPage() {
  const [sp, setSp] = useSearchParams();
  const rawTab = sp.get('tab');
  const tab: Tab = rawTab === 'registry' ? 'registry' : rawTab === 'fill' ? 'fill' : 'finance';

  const setTab = (t: Tab) => {
    const next = new URLSearchParams(sp);
    if (t === 'finance') next.delete('tab');
    else next.set('tab', t);
    setSp(next, { replace: true });
  };

  return (
    <div className="dashboard">
      <PageHeader title="Дашборд" />

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
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'fill'}
          className={`dash-tab${tab === 'fill' ? ' dash-tab--active' : ''}`}
          onClick={() => setTab('fill')}
        >
          Заполнить
        </button>
      </nav>

      {tab === 'finance' && <FinanceView />}
      {tab === 'registry' && (
        <Suspense fallback={<PageLoading />}>
          <RegistryTab />
        </Suspense>
      )}
      {tab === 'fill' && (
        <Suspense fallback={<PageLoading />}>
          <FillTab />
        </Suspense>
      )}
    </div>
  );
}
