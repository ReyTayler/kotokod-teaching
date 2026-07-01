import type { EnrollmentStatus } from '../lib/types';
import { ENROLLMENT_STATUS_LABELS } from '../lib/labels';

const MONTHS = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];

// Color stays on a single semantic axis: enrolled = positive, declined = negative,
// frozen = informational (info), not_enrolled = muted (neutral).
const STATUS_TONE: Record<EnrollmentStatus, 'positive' | 'negative' | 'info' | 'muted'> = {
  enrolled:     'positive',
  declined:     'negative',
  frozen:       'info',
  not_enrolled: 'muted',
};

interface StudentLike { enrollment_status?: string; frozen_until_month?: number | null; }

export function StatusBadge({ row }: { row: StudentLike | string }) {
  const status = (typeof row === 'string' ? row : row.enrollment_status) as EnrollmentStatus;
  const safeStatus: EnrollmentStatus = STATUS_TONE[status] ? status : 'enrolled';
  const tone = STATUS_TONE[safeStatus];
  let label = ENROLLMENT_STATUS_LABELS[safeStatus];
  if (typeof row === 'object' && row.enrollment_status === 'frozen' && row.frozen_until_month) {
    label = `Заморожен · до ${MONTHS[row.frozen_until_month - 1]}`;
  }
  return (
    <span className={`status-badge status-badge--${tone}`}>
      {label}
    </span>
  );
}
