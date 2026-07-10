import { useStudentStats } from '../../hooks/useStudents';
import { useStudentBalance } from '../../hooks/useStudentBalance';
import { fmtRub, fmtLessons } from '../../lib/format';

function pctColor(p: number | null | undefined): string {
  if (p == null) return 'var(--text3)';
  if (p >= 80) return 'var(--green)';
  if (p >= 50) return 'var(--amber)';
  return 'var(--red)';
}

interface Props {
  studentId: number;
}

export default function StudentKpiRow({ studentId }: Props) {
  const { data: stats } = useStudentStats(studentId);
  const { data: balance } = useStudentBalance(studentId);

  if (!stats && !balance) return null;

  const attendancePct = stats?.overall.attendance_pct ?? null;
  const activeDirections = stats?.directions.filter((d) => d.lessons_recorded > 0).length ?? 0;

  const cards: Array<{ label: string; value: string; color: string }> = [
    {
      label: 'Посещаемость',
      value: attendancePct != null ? `${attendancePct}%` : '—',
      color: pctColor(attendancePct),
    },
    {
      label: 'Баланс уроков',
      value: balance ? fmtLessons(balance.total_balance) : '—',
      color: balance && balance.total_balance < 0 ? 'var(--red)' : 'var(--text)',
    },
    {
      label: 'Оплачено всего',
      value: balance ? fmtRub(balance.total_paid_amount) : '—',
      color: 'var(--text)',
    },
    {
      label: 'Направлений',
      value: String(activeDirections),
      color: 'var(--text)',
    },
  ];

  return (
    <div className="kpi-grid">
      {cards.map((c) => (
        <div key={c.label} className="kpi-card">
          <div className="kpi-card__label">{c.label}</div>
          <div className="kpi-card__value" style={{ color: c.color }}>{c.value}</div>
        </div>
      ))}
    </div>
  );
}
