import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useMonthlyFinance } from '../../hooks/useMonthlyFinance';
import { SelectInput } from '../../components/form/SelectInput';
import { ColorInput } from '../../components/form/ColorInput';
import { PageLoading } from '../../components/ui/Skeleton';
import { MONTHS_RU } from '../../lib/slots';
import { toCsv, downloadCsv } from '../../lib/export-csv';
import { MonthlyAreaChart, type ChartRow, type ComparisonSeries } from './MonthlyAreaChart';
import type { MonthlyFinanceData } from '../../lib/types';

const CUR_YEAR = new Date().getFullYear();
// Дефолтные цвета новых линий сравнения (категориальные серии графика, не UI-акценты).
const PALETTE = ['#e0723f', '#8b5cf6', '#3b82f6', '#ec4899', '#f59e0b'];
const MAX_COMPARISONS = 5;

interface Comparison { id: number; year: number; color: string }

function buildRows(data: MonthlyFinanceData, years: number[], metric: 'revenue' | 'worked_off'): ChartRow[] {
  const rows: ChartRow[] = [];
  for (let m = 0; m < 12; m++) {
    const row: ChartRow = { monthLabel: MONTHS_RU[m].slice(0, 3) };
    for (const y of years) {
      const pts = data.byYear[String(y)];
      row[String(y)] = pts ? pts[m][metric] : 0;
    }
    rows.push(row);
  }
  return rows;
}

export function FinanceCharts() {
  const [params, setParams] = useSearchParams();
  const primaryYear = Number(params.get('chart_year')) || CUR_YEAR;

  const [comparisons, setComparisons] = useState<Comparison[]>([]);
  const [nextId, setNextId] = useState(1);

  // Все года для запроса (основной + сравнения, дедуп).
  const queryYears = [...new Set([primaryYear, ...comparisons.map((c) => c.year)])];
  const { data, isLoading } = useMonthlyFinance(queryYears);

  const availableYears = (data?.available_years ?? []).slice().sort((a, b) => b - a);
  const yearOptions = availableYears.map((y) => ({ value: String(y), label: String(y) }));

  const usedYears = new Set([primaryYear, ...comparisons.map((c) => c.year)]);

  const onPrimaryYear = (e: { target: { value: string } }) => {
    const next = new URLSearchParams(params);
    if (e.target.value) next.set('chart_year', e.target.value);
    else next.delete('chart_year');
    setParams(next, { replace: true });
  };

  const addComparison = () => {
    if (comparisons.length >= MAX_COMPARISONS) return;
    const free = availableYears.find((y) => !usedYears.has(y));
    const year = free ?? (primaryYear - 1 - comparisons.length);
    const color = PALETTE[comparisons.length % PALETTE.length];
    setComparisons((cs) => [...cs, { id: nextId, year, color }]);
    setNextId((n) => n + 1);
  };

  const updateComparison = (id: number, patch: Partial<Comparison>) =>
    setComparisons((cs) => cs.map((c) => (c.id === id ? { ...c, ...patch } : c)));

  const removeComparison = (id: number) =>
    setComparisons((cs) => cs.filter((c) => c.id !== id));

  // Серии сравнения для графика (только с валидным годом).
  const series: ComparisonSeries[] = comparisons.map((c) => ({ year: c.year, color: c.color }));
  const chartYears = [primaryYear, ...series.map((s) => s.year)];

  // Экспорт текущего набора в CSV (Месяц + Выручка/Отработано по каждому году + Итого).
  const exportCsv = () => {
    if (!data) return;
    const header: (string | number)[] = ['Месяц'];
    for (const y of chartYears) header.push(`Выручка ${y}`, `Отработано ${y}`);
    const rows: (string | number)[][] = [header];
    for (let m = 0; m < 12; m++) {
      const row: (string | number)[] = [MONTHS_RU[m]];
      for (const y of chartYears) {
        const pts = data.byYear[String(y)];
        row.push(pts ? Math.round(pts[m].revenue) : 0, pts ? Math.round(pts[m].worked_off) : 0);
      }
      rows.push(row);
    }
    const totals: (string | number)[] = ['Итого'];
    for (const y of chartYears) {
      const pts = data.byYear[String(y)] || [];
      totals.push(
        Math.round(pts.reduce((s, p) => s + p.revenue, 0)),
        Math.round(pts.reduce((s, p) => s + p.worked_off, 0)),
      );
    }
    rows.push(totals);
    downloadCsv(`finance-${chartYears.join('-')}.csv`, toCsv(rows));
  };

  return (
    <section className="finance-charts">
      <div className="finance-charts__controls">
        <div className="finance-charts__row">
          <span className="finance-charts__year-label">Год:</span>
          <SelectInput
            options={yearOptions}
            value={String(primaryYear)}
            onChange={onPrimaryYear}
            placeholder="Год"
            disabled={isLoading || yearOptions.length === 0}
            className="finance-charts__year-select"
          />
          {comparisons.length < MAX_COMPARISONS && (
            <button type="button" className="finance-charts__add" onClick={addComparison} title="Добавить год для сравнения">
              + сравнить
            </button>
          )}
          <button
            type="button"
            className="finance-charts__export"
            onClick={exportCsv}
            disabled={!data}
            title="Скачать данные в CSV"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="7 10 12 15 17 10"/>
              <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            CSV
          </button>
        </div>

        {comparisons.map((c) => {
          const opts = [...new Set([c.year, ...availableYears.filter((y) => !usedYears.has(y))])]
            .sort((a, b) => b - a)
            .map((y) => ({ value: String(y), label: String(y) }));
          return (
            <div key={c.id} className="finance-charts__row finance-charts__row--compare">
              <span className="finance-charts__compare-label">сравнить с</span>
              <SelectInput
                options={opts}
                value={String(c.year)}
                onChange={(e) => updateComparison(c.id, { year: Number(e.target.value) })}
                className="finance-charts__year-select"
              />
              <ColorInput
                className="finance-charts__color"
                value={c.color}
                onChange={(e) => updateComparison(c.id, { color: e.target.value })}
                title="Цвет линии"
              />
              <button
                type="button"
                className="finance-charts__remove"
                onClick={() => removeComparison(c.id)}
                aria-label="Убрать год"
                title="Убрать"
              >
                ×
              </button>
            </div>
          );
        })}
      </div>

      {isLoading || !data ? (
        <PageLoading />
      ) : (
        <div className="finance-charts__body">
          <MonthlyAreaChart
            data={buildRows(data, chartYears, 'revenue')}
            primaryYear={primaryYear}
            comparisons={series}
            title="Выручка по месяцам"
            gradientId="grad-revenue"
          />
          <MonthlyAreaChart
            data={buildRows(data, chartYears, 'worked_off')}
            primaryYear={primaryYear}
            comparisons={series}
            title="Отработано по месяцам"
            gradientId="grad-worked"
          />
        </div>
      )}
    </section>
  );
}
