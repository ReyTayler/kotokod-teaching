// journal_django/frontend/admin-src/src/lib/reports.ts
// Типы раздела «Отчёты». Отчёты НЕ хранятся: генерация в Celery, скачивание
// сразу по готовности по task_id (celery result backend).

export type ReportTaskState = 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE';

export interface ReportRunResponse {
  task_id: string;
}

export interface ReportTaskStatus {
  state: ReportTaskState;
  filename: string | null;
  row_count: number | null;
  error: string | null;
}

export const RENEWALS_MONTH = 'renewals_month';
export const ACCOUNTING_MONTH = 'accounting_month';

// Месяцы для селекта.
export const MONTHS_RU = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];

/** Описание типа отчёта для UI: заголовок, подпись и сборка params(year, month→1..12). */
export interface ReportTypeDef {
  reportType: string;
  title: string;
  desc: string;
  buildParams: (year: number, month: number) => Record<string, unknown>;
}

export const REPORT_TYPES: ReportTypeDef[] = [
  {
    reportType: RENEWALS_MONTH,
    title: 'Отчёт по продлениям',
    desc: 'Промежуточные результаты по статусам сделок (активных и закрытых), затронутых в выбранном месяце.',
    buildParams: (year, month) => ({ year, month }),
  },
  {
    reportType: ACCOUNTING_MONTH,
    title: 'Бухгалтерский отчёт',
    desc: 'По каждому ученику за месяц: посещённые уроки, оплаты, остаток оплаченных уроков и остаток аванса.',
    buildParams: (year, month) => ({ month: `${year}-${String(month).padStart(2, '0')}` }),
  },
];
