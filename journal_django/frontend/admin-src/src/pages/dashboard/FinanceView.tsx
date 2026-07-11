import { lazy, Suspense } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useDashboard } from '../../hooks/useDashboard';
import { fmtRub, fmtDate } from '../../lib/format';
import { PageLoading } from '../../components/ui/Skeleton';
import { DateInput } from '../../components/form/DateInput';
import { KpiCard } from './KpiCard';
import { DebtsCard } from './DebtsCard';

// Lazy: Recharts грузится отдельным чанком, не блокирует первый показ дашборда.
const FinanceCharts = lazy(() =>
  import('./FinanceCharts').then((m) => ({ default: m.FinanceCharts })),
);

const MONTHS_RU = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

function monthLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  return `${MONTHS_RU[m - 1]} ${y}`;
}

function signedRub(v: number): string {
  return v > 0 ? `+${fmtRub(v)}` : fmtRub(v);
}

// Финансовая вкладка дашборда (прежнее тело DashboardPage — без изменений логики).
export default function FinanceView() {
  const [params, setParams] = useSearchParams();
  const from = params.get('from') || '';
  const to = params.get('to') || '';
  const hasRange = Boolean(from || to);

  const setParam = (key: 'from' | 'to', value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const reset = () => {
    const next = new URLSearchParams(params);
    next.delete('from');
    next.delete('to');
    setParams(next, { replace: true });
  };

  const { data, isLoading, isError } = useDashboard({ from: from || undefined, to: to || undefined });

  const suffix = hasRange ? 'за период' : 'за месяц';
  const periodLabel = hasRange
    ? `${from ? fmtDate(from) : '…'} — ${to ? fmtDate(to) : '…'}`
    : data ? monthLabel(data.month) : '';

  return (
    <>
      <div className="payroll-range">
        <label>Период:</label>
        <DateInput value={from} onChange={(e) => setParam('from', e.target.value)} placeholder="от" />
        <span className="payroll-range__sep">—</span>
        <DateInput value={to} onChange={(e) => setParam('to', e.target.value)} placeholder="до" />
        <button className="btn-secondary" onClick={reset} disabled={!hasRange}>Сбросить</button>
        {periodLabel && <span className="dashboard__month">{periodLabel}</span>}
      </div>

      {isLoading ? (
        <PageLoading />
      ) : isError || !data ? (
        <div className="page-error">Не удалось загрузить дашборд</div>
      ) : (
        <>
          <div className="dashboard__kpis">
            <KpiCard label={`Выручка ${suffix}`} value={fmtRub(data.revenue_month)} hint="собрано" />
            <KpiCard label={`Отработано ${suffix}`} value={fmtRub(data.worked_off_month)} hint="FIFO" />
            <KpiCard
              label={`Авансы ${suffix}`}
              value={signedRub(data.carryover_month)}
              hint="выручка − отработано"
              tone={data.carryover_month < 0 ? 'warning' : 'info'}
            />
            <KpiCard label="Остаток всего" value={fmtRub(data.deferred_total)} hint="сейчас, не отработано" />
          </div>

          <Suspense fallback={<PageLoading />}>
            <FinanceCharts />
          </Suspense>

          <DebtsCard debts={data.debts} total={data.debts_total} />
        </>
      )}
    </>
  );
}
