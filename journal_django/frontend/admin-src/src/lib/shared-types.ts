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
  sheet_name: string;
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

// ===== Students =====
export type EnrollmentStatus = 'enrolled' | 'not_enrolled' | 'frozen' | 'declined';

export interface Student {
  id: ID;
  full_name: string;
  birth_date: string | null;
  phone: string | null;
  school_grade: number | null;
  platform_id: string | null;
  parent_name: string | null;
  first_purchase_date: string | null;
  age: number | null;
  pm: string | null;
  enrollment_status: EnrollmentStatus;
  frozen_until_month: number | null; // 1..12
  consent_given: boolean;
  consent_at: string | null;
  consent_by: string | null;
  consent_note: string | null;
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

// ===== Payroll =====
export interface PayrollEntry {
  id: ID;
  lesson_id: ID;
  teacher_id: ID;
  total_students: number;
  present_count: number;
  payment: string | number;  // numeric(10,2)
  penalty: string | number;
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
  paid_at: string;               // 'YYYY-MM-DD'
  note: string | null;
  created_at: string;
  created_by: string | null;
  // joined-only:
  student_name?: string;
  direction_name?: string;
}

// ===== Balance =====

export interface DirectionBalance {
  direction_id: ID;
  direction_name: string;
  direction_color: string | null;
  purchased_lessons: number;  // SUM(subscriptions_count * 4)
  attended_lessons: number;   // half=0.5
  balance: number;            // purchased − attended (может быть < 0)
  total_paid_amount: number | string;
}

export interface StudentBalance {
  per_direction: DirectionBalance[];
  total_balance: number;
  total_paid_amount: number | string;
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

// ===== Accounts & RBAC =====

export type Role = 'teacher' | 'manager' | 'admin';

export type AccountStatus = 'invited' | 'active' | 'expired' | 'disabled';

export interface Account {
  id: number;
  email: string;
  role: Role;
  teacher_id: number | null;
  teacher_name?: string | null;
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
  direction_id: number;
  direction_name: string;
  direction_color: string | null;
  balance: number; // в уроках, < 0
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
