// Типы 8 сущностей админки. Маппятся 1-в-1 на PG-схему.
// Поля, помеченные `?`, могут отсутствовать в ответе (joined-only).

export type ID = number;

// ===== Teachers =====
export interface Teacher {
  id: ID;
  name: string;
  email: string | null;
  phone: string | null;
  active: boolean;
  created_at: string;
  // joined-only поля (когда запрашиваются с дополнительной информацией):
  groups_count?: number;
}

// ===== Directions =====
export interface Direction {
  id: ID;
  name: string;
  is_individual: boolean;
  active: boolean;
  total_lessons: number | null;
  color: string | null; // #RRGGBB
  subscription_price: number | string | null; // numeric от pg может прийти строкой
}

// ===== Groups =====
export type LessonDuration = 45 | 60 | 90;

export interface GroupScheduleSlot {
  id?: ID;
  group_id?: ID;
  day_of_week: number; // 0..6
  start_time: string;  // 'HH:MM' or 'HH:MM:SS'
}

export interface Group {
  id: ID;
  name: string;
  direction_id: ID;
  teacher_id: ID;
  is_individual: boolean;
  lesson_duration_minutes: LessonDuration;
  lessons_per_week: number;
  group_start_date: string | null;
  vk_chat: string | null;
  created_at: string;
  active: boolean;
  // joined-only:
  direction_name?: string;
  direction_color?: string | null;
  teacher_name?: string;
  slots?: GroupScheduleSlot[];
  members_count?: number;
}

// ===== Group schedule (GET .../groups/:id/schedule, POST /schedule-change) =====
// Слоты — recurrence-шаблон (group_schedule_slots). Операции над занятиями идут
// через planned_lessons (см. useGroupPlan). lesson_schedule_exceptions удалены (шаг 9).

// Слот с полной историей действия — отличается от GroupScheduleSlot (used в Group.slots / форме
// создания группы) наличием периода действия. id/effective_from здесь всегда заданы сервером.
export interface ScheduleSlot {
  id: ID;
  day_of_week: number;    // 0..6, Вс=0 (см. lib/slots DOW)
  start_time: string;     // 'HH:MM' or 'HH:MM:SS'
  effective_from: string; // 'YYYY-MM-DD'
  effective_to: string | null; // null = слот действует по сей день
}

export interface GroupScheduleData {
  slots: ScheduleSlot[];
}

// ===== Students =====
export type EnrollmentStatus = 'enrolled' | 'not_enrolled' | 'frozen' | 'declined';

export interface Student {
  id: ID;
  full_name: string;
  birth_date: string | null;
  platform_id: string | null;
  bitrix24_link: string | null;
  parent1_name: string | null;
  parent1_phone: string | null;
  parent1_email: string | null;
  parent2_name: string | null;
  parent2_phone: string | null;
  parent2_email: string | null;
  first_purchase_date: string | null;
  age: number | null;
  pm: string | null;
  enrollment_status: EnrollmentStatus;
  frozen_from: string | null;
  frozen_until: string | null;
  created_at: string;
}

// ===== Group memberships =====
export interface GroupMembership {
  id: ID;
  group_id: ID;
  student_id: ID;
  lessons_done: string | number; // numeric(6,1) от pg как string
  remaining: string | number;
  start_date: string | null;
  sheet_row: number | null;
  active: boolean;
  // joined-only:
  group_name?: string;
  student_name?: string;
  transferred_from_id?: ID | null;
  transferred_from_group_name?: string | null;
  transferred_from_lessons_done?: string | number | null;
}

// ===== Lessons =====
export type LessonType = 'regular' | 'substitution' | 'reschedule';

export interface Lesson {
  id: ID;
  group_id: ID;
  teacher_id: ID;
  original_teacher_id: ID | null;
  lesson_date: string;     // 'YYYY-MM-DD'
  lesson_number: number;   // numeric(5,1)
  lesson_duration_minutes: LessonDuration;
  lesson_type: LessonType;
  record_url: string | null;
  submitted_at: string;
  submitted_by_token: string;
  // joined-only:
  group_name?: string;
  teacher_name?: string;
  original_teacher_name?: string | null;
}

export interface LessonAttendance {
  lesson_id: ID;
  student_id: ID;
  present: boolean;
  student_name?: string;
}

export interface LessonFull extends Lesson {
  attendance: LessonAttendance[];
  payroll: PayrollEntry | null;
}

// ===== Extra lessons (доп. уроки / резолюции пропусков) =====

// Пер-ученик (1:1) резолюция пропуска — одна строка на (пропущенный урок ×
// ученик), заменила групповую ExtraLessonAssignment+participants (Фаза 1a).
export interface AbsenceResolution {
  id: ID;
  student_id: ID;
  student_name: string;
  assigned_teacher_id: ID | null;
  teacher_name: string | null;
  missed_lesson_id: ID;
  missed_lesson_group_id: ID;
  missed_lesson_group_name: string;
  missed_lesson_date: string;
  scheduled_date: string;
  scheduled_time: string;
  duration_minutes: number;
  status: 'scheduled' | 'done' | 'cancelled';
  fact_lesson_id: ID | null;
}

// Ответ POST /api/admin/extra-lessons — multi-select создаёт N резолюций.
export interface ExtraLessonCreateResult {
  created: number;
  resolution_ids: number[];
}

// ===== Payroll =====
export interface PayrollEntry {
  id: ID;
  lesson_id: ID;
  teacher_id: ID;
  total_students: number;
  present_count: number;
  payment: string | number;  // numeric(10,2) — базовая сумма ЭТОЙ строки (см. is_surcharge)
  penalty: string | number;
  // true — это не сам урок, а надбавка за посещаемость, отмеченную "сгоревшей"
  // задним числом (update_attendance_cell): payment здесь = сумма надбавки,
  // lesson_date = дата самой правки, а не дата урока (см. apps/payroll/repository.py).
  is_surcharge: boolean;
  // joined-only:
  lesson_date?: string;
  group_name?: string;
  lesson_number?: number;
  teacher_name?: string;
}

export interface PayrollSummaryRow {
  teacher_id: ID;
  teacher_name: string;
  lessons_count: number;
  sum_payment: string | number;
  sum_penalty: string | number;
}

// ===== Archive (sidebar shape) =====
export interface ArchivePayload {
  teachers: Teacher[];
  groups: Group[];
  directions: Direction[];
}

// ===== Common =====
export interface ApiErrorBody {
  error: string;
  details?: unknown;
}

// ===== Payments =====

export interface Payment {
  id: ID;
  student_id: ID;
  direction_id: ID | null;
  subscriptions_count: number | null;
  unit_price: number | string;   // numeric(10,2) → строка от pg
  total_amount: number | string;
  lessons_count: number | null;
  kind: 'purchase' | 'refund';
  paid_at: string;               // 'YYYY-MM-DD'
  note: string | null;
  created_at: string;
  created_by: string | null;
  // joined-only:
  student_name?: string;
  direction_name?: string;
}

// ===== Balance =====

export interface PaidByDirection {
  direction_id: ID;
  direction_name: string;
  direction_color: string | null;
  total_paid_amount: number | string;
}

export interface AttendedByDirection {
  direction_id: ID;
  direction_name: string;
  direction_color: string | null;
  attended_lessons: number;
}

export interface StudentBalance {
  total_balance: number;              // общий пул ученика, не по направлению
  total_paid_amount: number | string;
  remaining_value: number;            // неотработанный остаток в деньгах
  paid_by_direction: PaidByDirection[];
  attended_by_direction: AttendedByDirection[];
  payments: Payment[];
}

// ===== Discounts =====
export interface Discount {
  id: ID;
  name: string;
  amount: number | string;  // numeric(5,4) → строка от pg, 0..1
  active: boolean;
  created_at: string;
}

// ===== Pagination =====

export interface Paginated<T> {
  rows: T[];
  total: number;
  page: number;
  page_size: number;
}

// ===== Реестр куратора (вкладка дашборда) =====

export type RegistryStatus = 'closed' | 'ending' | 'idle' | 'no_plan' | 'ok';
export type RegistrySegment = 'all' | 'ending' | 'closed' | 'idle' | 'no_plan';

export interface RegistryKpis {
  active_students: number;
  renewal_upsell: number;
  idle: number;
  avg_progress: number;
  lessons_ahead: number;
  cancellations: number;
}

export interface TodayStreamItem {
  time: string | null;
  group_code: string;
  teacher_name: string | null;
  student_names: string[];
  status: string;
}

export interface RegistrySignal {
  count: number;
}

export interface RegistrySummary {
  generated_at: string;
  kpis: RegistryKpis;
  today_stream: TodayStreamItem[];
  signals: Record<'ending' | 'closed' | 'idle' | 'no_plan', RegistrySignal>;
}

export interface RegistryStudent {
  student_id: number;
  student_name: string;
  codes: string[];
  teacher_names: string[];
  balance: number;
  attended: number;
  planned: number;
  progress_pct: number | null;
  last_lesson_date: string | null;
  next_lesson_date: string | null;
  status: RegistryStatus;
}

// ===== Accounts & RBAC =====

export type Role = 'teacher' | 'manager' | 'admin' | 'superadmin';

export type AccountStatus = 'invited' | 'active' | 'expired' | 'disabled';

export interface Account {
  id: number;
  email: string;
  role: Role;
  teacher_id: number | null;
  teacher_name?: string | null;
  full_name?: string | null;
  // Вычисляемое сервером имя: full_name || teacher_name || email.
  name?: string;
  active: boolean;
  twofa_enabled: boolean;
  twofa_method: 'totp' | 'email' | null;
  last_login_at: string | null;
  // Вычисляемые сервером (список): есть ли активный invite и сводный статус.
  has_active_invite?: boolean;
  status?: AccountStatus;
}

export interface AuditEntry {
  id: number | string; // bigserial → pg отдаёт строкой
  occurred_at: string;
  account_id: number | null;
  account_email?: string | null;
  actor_email: string | null;
  event: string;
  ip: string | null;
  target_id: number | null;
  meta: unknown;
}

// ===== Dashboard =====

export interface DashboardDebt {
  student_id: number;
  student_name: string;
  balance: number; // в уроках, < 0 (общий пул ученика, без направления)
}

export interface DashboardData {
  month: string;            // 'YYYY-MM' (текущий МСК-месяц, для дефолтной подписи)
  from: string | null;      // эхо периода 'YYYY-MM-DD' (null = дефолтный месяц)
  to: string | null;        // эхо периода 'YYYY-MM-DD'
  revenue_month: number;    // собрано за период
  worked_off_month: number; // отработано за месяц (FIFO)
  carryover_month: number;  // revenue_month − worked_off_month (может быть < 0)
  deferred_total: number;   // снимок несписанных партий, ≥ 0
  debts: DashboardDebt[];   // топ-8 худших
  debts_total: number;      // всего пар с долгом
}

export interface MonthlyFinancePoint {
  month: number;      // 1..12
  revenue: number;    // собрано за месяц
  worked_off: number; // отработано за месяц (FIFO)
}

export interface MonthlyFinanceData {
  years: number[];                              // запрошенные года (sorted asc)
  available_years: number[];                    // годы с данными (для дропдауна)
  byYear: Record<string, MonthlyFinancePoint[]>; // ключ = год-строка → 12 точек (Янв..Дек)
}

// ===== Changelog (журнал изменений данных) =====
// Контракт: apps/changelog (repository.list_operations / get_operation / revert).

export interface ChangelogActor {
  account_id: number;
  email: string | null;
  name: string | null;   // имя преподавателя / ФИО / fallback email
  role: Role | null;
}

/** Сводка по одной сущности внутри операции (лента). */
export interface ChangelogEntitySummary {
  entity: string;   // ключ из apps/changelog/registry.py → CHANGELOG_ENTITY_LABELS
  inserts: number;
  updates: number;
  deletes: number;
}

/** Строка ленты: 1 строка = 1 операция (pghistory-контекст). */
export interface ChangelogOperation {
  id: string;                 // uuid контекста
  occurred_at: string;
  actor: ChangelogActor | null; // null = вне HTTP (management-команда)
  operation: string;          // ключ → CHANGELOG_OPERATION_LABELS
  summary: string;            // человекочитаемое описание (бэкенд)
  url: string | null;
  method: string | null;
  entities: ChangelogEntitySummary[];
  events_total: number;
  revertable: boolean;
  reverted: boolean;          // операция уже откатывалась
}

export type ChangelogEventLabel = 'insert' | 'update' | 'delete';

/** Одно очеловеченное изменение поля внутри события. */
export interface ChangelogFieldChange {
  label: string;          // русская подпись поля
  old: string | null;     // null у создания
  new: string | null;     // null у удаления
}

/** Полностью очеловеченное представление события (бэкенд). */
export interface ChangelogEventHuman {
  title: string;                       // «Ученик Иван Петров»
  text: string;                        // готовая фраза (= description)
  changes: ChangelogFieldChange[];
}

/** Одно row-событие внутри операции (детальная карточка). */
export interface ChangelogEvent {
  model: string;              // 'groups.Group'
  entity: string;
  obj_id: number | string | null;
  label: ChangelogEventLabel;
  data: Record<string, unknown>;
  /** поле → [было, стало]; null у insert/первого события строки. */
  diff: Record<string, [unknown, unknown]> | null;
  /** Готовая человекочитаемая фраза (бэкенд). Опционально — на случай старого кэша. */
  description?: string;
  /** Полностью очеловеченное представление (бэкенд). Опционально — на случай старого кэша. */
  human?: ChangelogEventHuman;
}

export interface ChangelogDetail {
  id: string;
  occurred_at: string;
  actor: ChangelogActor | null;
  operation: string;
  summary: string;
  url: string | null;
  method: string | null;
  revertable: boolean;
  reverted: boolean;
  events: ChangelogEvent[];
  /** Готовая русская причина недоступности отката; null = откат доступен. Опционально — старый кэш. */
  not_revertable_reason?: string | null;
}

export interface RevertResult {
  reverted_events: number;
  inserts_undone: number;
  deletes_undone: number;
  updates_undone: number;
}

/** Элемент details.conflicts в 409-ответе POST .../revert. */
export interface RevertConflictItem {
  model: string;   // 'groups.Group'
  entity: string;  // ключ → CHANGELOG_ENTITY_LABELS
  obj_id: number | string | null;
  reason: 'row_exists' | 'row_missing' | 'changed_later' | 'no_previous_state';
  fields?: string[];
}
