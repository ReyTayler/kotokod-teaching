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

export interface RenewalCard {
  id: number;
  student_name: string;
  direction_name: string;
  direction_color: string | null;
  cycle_no: number;
  expected_amount: string | null;
  next_touch_at: string | null;
  assignee_name: string | null;
  days_in_stage: number;
}

export interface RenewalColumn {
  stage_id: number;
  key: string;
  label: string;
  kind: StageKind;
  color: string | null;
  count: number;
  sum_potential: number;
  cards: RenewalCard[];
}

export interface RenewalBoard {
  columns: RenewalColumn[];
}

export interface RenewalListRow {
  id: number;
  student_name: string;
  direction_name: string;
  direction_color: string | null;
  cycle_no: number;
  stage_label: string;
  stage_kind: StageKind;
  next_touch_at: string | null;
  assignee_name: string | null;
  days_in_stage: number;
}

export interface RenewalDealDetail {
  id: number;
  student_id: number;
  direction_id: number;
  cycle_no: number;
  stage_id: number;
  stage_key: string;
  stage_label: string;
  stage_kind: StageKind;
  stage_color: string | null;
  assignee_id: number | null;
  assignee_name: string | null;
  expected_amount: string | null;
  next_touch_at: string | null;
  reason_code: string | null;
  stage_entered_at: string;
  outcome_at: string | null;
  created_at: string;
  student_name: string;
  direction_name: string;
  direction_color: string | null;
  days_in_stage: number;
  lesson_in_cycle: number;
  balance: number;
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
}
