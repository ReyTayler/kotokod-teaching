import type { EnrollmentStatus } from '../lib/types';
import { ENROLLMENT_STATUS_LABELS } from '../lib/labels';

const MONTHS = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];

// Color stays on a single semantic axis: enrolled = positive, declined = negative,
// frozen = informational (info).
const STATUS_TONE: Record<EnrollmentStatus, 'positive' | 'negative' | 'info'> = {
  enrolled:     'positive',
  declined:     'negative',
  frozen:       'info',
};

interface StudentLike { enrollment_status?: string; frozen_until?: string | null; }

function formatFrozenUntil(iso: string): string {
  // iso = 'YYYY-MM-DD' (DateStringField). Форматируем «до 12 августа 2026».
  const [y, m, d] = iso.split('-').map(Number);
  return `до ${d} ${MONTHS[m - 1]} ${y}`;
}

export function StatusBadge({ row }: { row: StudentLike | string }) {
  const status = (typeof row === 'string' ? row : row.enrollment_status) as EnrollmentStatus;
  const safeStatus: EnrollmentStatus = STATUS_TONE[status] ? status : 'enrolled';
  const tone = STATUS_TONE[safeStatus];
  let label = ENROLLMENT_STATUS_LABELS[safeStatus];
  if (typeof row === 'object' && row.enrollment_status === 'frozen' && row.frozen_until) {
    label = `Заморожен · ${formatFrozenUntil(row.frozen_until)}`;
  }
  return (
    <span className={`status-badge status-badge--${tone}`}>
      {label}
    </span>
  );
}
