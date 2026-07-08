import { Link } from 'react-router-dom';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LabelList } from 'recharts';
import { useRenewalAnalytics } from '../../hooks/useRenewalAnalytics';
import { KpiCard } from '../dashboard/KpiCard';
import { fmtRub } from '../../lib/format';

interface TooltipRow { payload?: { label?: string; cnt?: number; sum_amt?: number } }
function FunnelTooltip({ active, payload }: { active?: boolean; payload?: TooltipRow[] }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{row.label}</div>
      <div className="chart-tooltip__row">
        <span className="chart-tooltip__value">{row.cnt} сделок</span>
      </div>
      {!!row.sum_amt && (
        <div className="chart-tooltip__row">
          <span className="chart-tooltip__value">{fmtRub(row.sum_amt)}</span>
        </div>
      )}
    </div>
  );
}

export default function RenewalAnalyticsPage() {
  const { data, isLoading } = useRenewalAnalytics();

  return (
    <div className="renewals-page">
      <header className="renewals-page__head">
        <h1 className="renewals-page__title">Аналитика продлений</h1>
        <Link to="/admin/renewals" className="btn-secondary">← К воронке</Link>
      </header>

      {isLoading || !data ? (
        <div className="renewal-board--loading">Загружаем аналитику…</div>
      ) : (
        <>
          <div className="renewals-page__kpis">
            <KpiCard
              label="Renewal rate (30 дн.)"
              value={data.renewal_rate_30d != null ? `${data.renewal_rate_30d}%` : '—'}
              tone={data.renewal_rate_30d != null && data.renewal_rate_30d >= 70 ? 'info' : 'default'}
            />
            <KpiCard label="Продлили за 30 дн." value={String(data.won_30d)} />
            <KpiCard label="Ушли за 30 дн." value={String(data.lost_30d)} tone={data.lost_30d > 0 ? 'warning' : 'default'} />
          </div>

          <section className="chart-card">
            <div className="chart-card__head">
              <h3 className="chart-card__title">Открытые сделки по стадиям</h3>
            </div>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={data.stages} margin={{ top: 16, right: 8, left: 8, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="label"
                  tick={{ fill: 'var(--text3)', fontSize: 12 }}
                  tickLine={false}
                  axisLine={{ stroke: 'var(--border)' }}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fill: 'var(--text3)', fontSize: 12 }}
                  tickLine={false}
                  axisLine={false}
                  width={32}
                />
                <Tooltip content={<FunnelTooltip />} cursor={{ fill: 'var(--bg3)' }} />
                <Bar dataKey="cnt" fill="var(--accent)" radius={[4, 4, 0, 0]} maxBarSize={48}>
                  <LabelList dataKey="cnt" position="top" style={{ fill: 'var(--text3)', fontSize: 12 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </section>
        </>
      )}
    </div>
  );
}
