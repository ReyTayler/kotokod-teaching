// Типы для раздела «Продления» (CRM-воронка продлений учеников).
// Бэкенд: /api/admin/renewals* (Django+DRF, см. журнал изменений плана
// docs/superpowers/plans/2026-07-08-renewals-crm-pipeline.md).

export type StageKind = 'progress' | 'decision' | 'won' | 'lost';

export interface RenewalStage {
  id: number;
  key: string;
  label: string;
  color: string | null;
  kind: StageKind;
  is_auto: boolean;
  sort_order: number;
}

/** Активное направление ученика — справочная информация на карточке. */
export interface RenewalDirection {
  name: string;
  color: string | null;
}

export interface RenewalCard {
  id: number;
  student_id: number;
  student_name: string;
  /** Активные направления ученика (сделка — per ученик, подписочная модель). */
  directions: RenewalDirection[];
  cycle_no: number;
  next_touch_at: string | null;
  /** Дата отработки 4-го урока цикла (созревание продления). */
  due_at: string | null;
  assignee_name: string | null;
  days_in_stage: number;
  /** Баланс ученика < 0 — красный бейдж «Долг». */
  debt: boolean;
  /** Отработаны ли все 4 урока текущего цикла — пока false, «Продлён» недоступен. */
  cycle_completed: boolean;
}

export interface RenewalColumn {
  stage_id: number;
  key: string;
  label: string;
  kind: StageKind;
  color: string | null;
  count: number;
  cards: RenewalCard[];
}

export interface RenewalBoard {
  columns: RenewalColumn[];
}

export interface RenewalListRow {
  id: number;
  student_name: string;
  directions: RenewalDirection[];
  cycle_no: number;
  stage_label: string;
  stage_kind: StageKind;
  stage_color: string | null;
  next_touch_at: string | null;
  due_at: string | null;
  assignee_name: string | null;
  days_in_stage: number;
}

export interface RenewalDealDetail {
  id: number;
  student_id: number;
  cycle_no: number;
  stage_id: number;
  stage_key: string;
  stage_label: string;
  stage_kind: StageKind;
  stage_color: string | null;
  assignee_id: number | null;
  assignee_name: string | null;
  next_touch_at: string | null;
  reason_code: string | null;
  /** Дата отработки 4-го урока цикла (созревание продления). */
  due_at: string | null;
  stage_entered_at: string;
  outcome_at: string | null;
  created_at: string;
  student_name: string;
  directions: RenewalDirection[];
  days_in_stage: number;
  lesson_in_cycle: number;
  /** true — все 4 урока цикла отработаны, пора продлевать. */
  cycle_completed: boolean;
  balance: number;
  /** Баланс ученика < 0 — красный бейдж «Долг». */
  debt: boolean;
}

export interface RenewalActivityItem {
  id: number;
  kind: 'stage_change' | 'comment' | 'payment_linked' | 'system';
  body: string | null;
  created_at: string;
  from_label: string | null;
  to_label: string | null;
  author_name: string | null;
  payment_id: number | null;
}

export interface RenewalFilters {
  assignee_id?: string;
  direction_id?: string;
  stage_id?: string;
  overdue?: string;
  /** Поиск по имени ученика внутри колонки канбана (per-column, server-side ILIKE). */
  student?: string;
  /** 'true' — списочный вид включает закрытые (won/lost) сделки. */
  include_closed?: string;
}

/** Кандидат в ответственные по сделке (менеджер/админ). */
export interface RenewalAssignee {
  id: number;
  full_name: string;
}

export type RenewalLostReason = 'price' | 'schedule' | 'lost_interest' | 'relocation' | 'other';

/** Строка сводки «Ученики без сделок» (активный membership, открытой сделки нет). */
export interface RenewalUnassignedRow {
  student_id: number;
  student_name: string;
  directions: RenewalDirection[];
  /** Суммарно посещено уроков за всю историю. */
  attended: number;
  /** Расчётный номер цикла будущей сделки. */
  cycle_no: number;
  debt: boolean;
}
