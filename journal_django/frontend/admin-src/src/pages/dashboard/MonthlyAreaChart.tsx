import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { fmtRub } from '../../lib/format';

export interface ChartRow {
  monthLabel: string;
  [year: string]: number | string;
}

export interface ComparisonSeries {
  year: number;
  color: string;
}

interface Props {
  data: ChartRow[];
  primaryYear: number;            // основной год — accent-area
  comparisons: ComparisonSeries[]; // доп. года — линии своего цвета
  title: string;
  gradientId: string;             // уникальный id для <linearGradient>
}

/** Короткий формат оси: 380000 → "380k" */
function fmtAxis(v: number | string): string {
  const n = Number(v);
  return Math.abs(n) >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
}

interface TooltipRow { dataKey?: string | number; value?: number; color?: string }
function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: TooltipRow[]; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{label}</div>
      {payload.map((p) => (
        <div key={String(p.dataKey)} className="chart-tooltip__row">
          <span className="chart-tooltip__swatch" style={{ background: p.color }} />
          <span className="chart-tooltip__year">{p.dataKey}</span>
          <span className="chart-tooltip__value">{fmtRub(Number(p.value))}</span>
        </div>
      ))}
    </div>
  );
}

export function MonthlyAreaChart({ data, primaryYear, comparisons, title, gradientId }: Props) {
  return (
    <section className="chart-card">
      <div className="chart-card__head">
        <h3 className="chart-card__title">{title}</h3>
        <div className="chart-legend">
          <span className="chart-legend__item">
            <span className="chart-legend__swatch chart-legend__swatch--primary" />
            {primaryYear}
          </span>
          {comparisons.map((c) => (
            <span key={c.year} className="chart-legend__item chart-legend__item--muted">
              <span className="chart-legend__swatch" style={{ borderTopColor: c.color }} />
              {c.year}
            </span>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.22} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis
            dataKey="monthLabel"
            tick={{ fill: 'var(--text3)', fontSize: 12 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border)' }}
          />
          <YAxis
            tickFormatter={fmtAxis}
            tick={{ fill: 'var(--text3)', fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            width={48}
          />
          <Tooltip content={<ChartTooltip />} cursor={{ stroke: 'var(--border)' }} />
          {/* Доп. года — линии выбранного цвета (рисуем под основным) */}
          {comparisons.map((c) => (
            <Line
              key={c.year}
              type="monotone"
              dataKey={String(c.year)}
              stroke={c.color}
              strokeWidth={1.75}
              dot={false}
              name={String(c.year)}
            />
          ))}
          {/* Основной год — accent с заливкой */}
          <Area
            type="monotone"
            dataKey={String(primaryYear)}
            stroke="var(--accent)"
            strokeWidth={2.5}
            fill={`url(#${gradientId})`}
            dot={false}
            name={String(primaryYear)}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </section>
  );
}
