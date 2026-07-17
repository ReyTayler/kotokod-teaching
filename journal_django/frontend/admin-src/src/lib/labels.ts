import type { EnrollmentStatus, LessonType, RegistryStatus } from './types';

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

// ===== Реестр куратора — статус ученика =====
// Подписи бейджа и строк сигналов. Коды приходят с бэка (registry_service.classify).

export const REGISTRY_STATUS_LABELS: Record<RegistryStatus, string> = {
  closed:  'Пакет закрыт',
  ending:  'Заканчивается',
  idle:    'Простой',
  no_plan: 'Нет плана',
  ok:      'Активен',
};

// ===== Lesson type =====

export const LESSON_TYPE_LABELS: Record<LessonType, string> = {
  regular:      'обычный',
  substitution: 'замена',
  reschedule:   'перенос',
};

export const LESSON_TYPE_OPTIONS: { value: LessonType; label: string }[] =
  (Object.entries(LESSON_TYPE_LABELS) as [LessonType, string][])
    .map(([value, label]) => ({ value, label }));

// ===== Changelog: операции журнала изменений =====
// Ключи — из apps/changelog/labels.py (бэкенд выводит их из method+url).

// Короткие названия действий — колонка «Действие» и dropdown «Все действия».
export const CHANGELOG_OPERATION_LABELS: Record<string, string> = {
  'group.create':                  'Новая группа',
  'group.update':                  'Правка группы',
  'group.delete':                  'Группа в архив',
  'group.schedule_change':         'Смена расписания',
  'plan.generate':                 'Генерация плана',
  'plan.permanent_change':         'Смена расписания (план)',
  'plan.change_teacher_permanent': 'Смена преподавателя',
  'plan.change_teacher':           'Замена преподавателя',
  'plan.extra':                    'Доп. занятие',
  'plan.reschedule':               'Перенос урока',
  'plan.cancel':                   'Отмена урока',
  'direction.create':              'Новое направление',
  'direction.update':              'Правка направления',
  'direction.delete':              'Направление в архив',
  'teacher.create':                'Новый преподаватель',
  'teacher.update':                'Правка преподавателя',
  'teacher.delete':                'Преподаватель в архив',
  'student.create':                'Новый ученик',
  'student.update':                'Правка ученика',
  'student.delete':                'Ученик в архив',
  'student.status':                'Смена статуса ученика',
  'student.resume':                'Выход из заморозки',
  'discount.create':               'Новая скидка',
  'discount.update':               'Правка скидки',
  'discount.delete':               'Скидка в архив',
  'membership.create':             'Зачисление',
  'membership.update':             'Правка членства',
  'membership.delete':             'Отчисление',
  'payment.create':                'Оплата',
  'payment.delete':                'Удаление оплаты',
  'lesson.submit':                 'Проведение урока',
  'lesson.create':                 'Создание урока',
  'lesson.update':                 'Правка урока',
  'lesson.delete':                 'Удаление урока',
  'lesson.attendance_update':      'Правка посещаемости',
  'extra_lesson.create':           'Назначение доп.урока',
  'extra_lesson.cancel':           'Отмена доп.урока',
  'extra_lesson.delete':           'Удаление доп.урока',
  'extra_lesson.record':           'Проведение доп.урока',
  'payroll.update':                'Правка начисления',
  'settings.update':               'Настройки',
  'account.create':                'Новая учётка',
  'account.update':                'Правка учётки',
  'account.delete':                'Учётка выключена',
  'account.reset_password':        'Сброс пароля',
  'account.reset_2fa':             'Сброс 2FA',
  'account.invite_create':         'Invite-ссылка',
  'account.invite_revoke':         'Отзыв invite',
  'account.invite_accept':         'Активация учётки',
  'account.twofa_enable':          'Включение 2FA',
  'account.twofa_disable':         'Выключение 2FA',
  'changelog.revert':              'Откат',
  other:                           'Другое действие',
};

export const CHANGELOG_OPERATION_OPTIONS: { value: string; label: string }[] =
  Object.entries(CHANGELOG_OPERATION_LABELS).map(([value, label]) => ({ value, label }));

// ===== Changelog: сущности (registry.py → entity) =====

export const CHANGELOG_ENTITY_LABELS: Record<string, string> = {
  direction:      'Направление',
  teacher:        'Преподаватель',
  student:        'Ученик',
  discount:       'Скидка',
  settings:       'Настройки',
  account:        'Учётка',
  group:          'Группа',
  schedule_slot:  'Слот расписания',
  membership:     'Членство',
  planned_lesson: 'Плановое занятие',
  lesson:         'Урок',
  attendance:     'Посещаемость',
  payment:        'Оплата',
  payroll:        'Начисление',
  extra_lesson_assignment:  'Доп.урок (назначение)',
  extra_lesson_participant: 'Доп.урок (участник)',
};

export const CHANGELOG_ENTITY_OPTIONS: { value: string; label: string }[] =
  Object.entries(CHANGELOG_ENTITY_LABELS).map(([value, label]) => ({ value, label }));

// ===== Продления: стадии воронки (fallback, если под рукой только key —
// основной источник истины — stage_label/label с бэка) =====

export const RENEWAL_STAGE_LABELS: Record<string, string> = {
  no_lesson_yet: 'Не было урока', lesson_1: 'Урок 1', lesson_2: 'Урок 2', lesson_3: 'Урок 3',
  awaiting_payment: 'Ждём оплату', awaiting_renewal: 'Ждём продление', thinking: 'Думает',
  frozen: 'Заморожен', ignoring: 'Игнорит', renewed: 'Продлён', churned: 'Ушёл',
};

// Причины ухода ученика (диалог закрытия сделки «Ушёл», reason_code сделки).
export const RENEWAL_LOST_REASON_LABELS: Record<string, string> = {
  price: 'Не устроила цена',
  schedule: 'Не подошло расписание',
  lost_interest: 'Потерял интерес',
  relocation: 'Переезд',
  other: 'Другое',
};
