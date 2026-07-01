interface Props {
  label: string;
  value: string;
  hint?: string;
  tone?: 'default' | 'info' | 'warning';
}

export function KpiCard({ label, value, hint, tone = 'default' }: Props) {
  return (
    <div className={`kpi-card kpi-card--${tone}`}>
      <div className="kpi-card__label">{label}</div>
      <div className="kpi-card__value">{value}</div>
      {hint && <div className="kpi-card__hint">{hint}</div>}
    </div>
  );
}
