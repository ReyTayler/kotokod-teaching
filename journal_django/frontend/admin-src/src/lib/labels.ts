import type { EnrollmentStatus, LessonType } from './types';

// ===== Enrollment status =====
// Подписи в Title Case — используются и в badge, и в формах, и в фильтрах.
// Бэк хранит коды (enrolled/frozen/not_enrolled/declined), UI показывает подписи.

export const ENROLLMENT_STATUS_LABELS: Record<EnrollmentStatus, string> = {
  enrolled:     'Учится',
  not_enrolled: 'Не учится',
  frozen:       'Заморожен',
  declined:     'Отказался',
};

export const ENROLLMENT_STATUS_OPTIONS: { value: EnrollmentStatus; label: string }[] =
  (Object.entries(ENROLLMENT_STATUS_LABELS) as [EnrollmentStatus, string][])
    .map(([value, label]) => ({ value, label }));

// ===== Lesson type =====

export const LESSON_TYPE_LABELS: Record<LessonType, string> = {
  regular:      'обычный',
  substitution: 'замена',
  reschedule:   'перенос',
};

export const LESSON_TYPE_OPTIONS: { value: LessonType; label: string }[] =
  (Object.entries(LESSON_TYPE_LABELS) as [LessonType, string][])
    .map(([value, label]) => ({ value, label }));
