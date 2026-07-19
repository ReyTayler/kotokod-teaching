// journal_django/frontend/admin-src/src/lib/sync.ts
export type SyncAction =
  | 'teachers' | 'groups' | 'students' | 'lessons' | 'payments' | 'payroll'
  | 'rebuild-payroll' | 'rebuild-counters' | 'rebuild-planned-lessons'
  | 'rebuild-absence-resolutions' | 'run-all';

export interface SyncActionDef {
  action: SyncAction;
  label: string;
  group: 'run-all' | 'sheets' | 'rebuild';
}

export const SYNC_ACTIONS: SyncActionDef[] = [
  { action: 'run-all', label: 'Запустить всё (teachers→groups→students→lessons→payroll)', group: 'run-all' },
  { action: 'teachers', label: 'Преподаватели', group: 'sheets' },
  { action: 'groups', label: 'Группы', group: 'sheets' },
  { action: 'students', label: 'Ученики + абонементы', group: 'sheets' },
  { action: 'lessons', label: 'Занятия + посещаемость', group: 'sheets' },
  { action: 'payments', label: 'Оплаты (только новые)', group: 'sheets' },
  { action: 'payroll', label: 'Зарплата', group: 'sheets' },
  { action: 'rebuild-payroll', label: 'Зарплата по урокам (пересчёт)', group: 'rebuild' },
  { action: 'rebuild-counters', label: 'Счётчики уроков групп (пересчёт)', group: 'rebuild' },
  {
    action: 'rebuild-planned-lessons',
    label: '⚠️ Плановые уроки — ПОЛНЫЙ пересбор (перезаписывает переносы/отмены/смену препода)',
    group: 'rebuild',
  },
  {
    action: 'rebuild-absence-resolutions',
    label: 'Доп.уроки — создать пропуски в очередь (по пропущенным занятиям)',
    group: 'rebuild',
  },
];

export type SyncTaskState = 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE';

export interface SyncStatus {
  state: SyncTaskState;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface SyncRunResponse {
  task_id: string;
}
