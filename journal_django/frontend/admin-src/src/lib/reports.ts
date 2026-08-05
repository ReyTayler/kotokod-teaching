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
export const ATTENDANCE_MONTH = 'attendance_month';
export const REVENUE_FORECAST = 'revenue_forecast';
export const RETENTION = 'retention';

// Месяцы для селекта.
export const MONTHS_RU = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];

/** Дополнительный флажок в карточке отчёта (кроме месяца/года). */
export interface ReportToggleDef {
  key: string;
  label: string;
  hint?: string;
}

/**
 * Описание типа отчёта для UI: заголовок, подпись, опциональные флажки и сборка
 * params(year, month→1..12, значения флажков).
 */
export interface ReportTypeDef {
  reportType: string;
  title: string;
  desc: string;
  toggles?: ReportToggleDef[];
  /** Подпись к селектору месяца, если «за месяц» неточно (у прогноза это старт раскладки). */
  monthLabel?: string;
  /**
   * Отчёт строится по всей истории — селекторы месяца и года не показываются.
   * Не «период по умолчанию», а осознанное отсутствие периода: у отчёта по
   * переходимости интерес в тренде, и урезать историю окном значило бы
   * спрятать месяцы, когда уходы ещё не отмечали.
   */
  noPeriod?: boolean;
  buildParams: (
    year: number,
    month: number,
    toggles: Record<string, boolean>,
  ) => Record<string, unknown>;
}

const ym = (year: number, month: number) => `${year}-${String(month).padStart(2, '0')}`;

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
    buildParams: (year, month) => ({ month: ym(year, month) }),
  },
  {
    reportType: ATTENDANCE_MONTH,
    title: 'Отчёт по посещаемости',
    desc: 'По каждому ученику базы и каждой его группе: даты уроков за месяц и статус «Был» / «Не был» / «Отработал» / «Сгорел».',
    buildParams: (year, month) => ({ month: ym(year, month) }),
  },
  {
    reportType: REVENUE_FORECAST,
    title: 'Прогноз отработки денег',
    desc: 'Неотработанные деньги каждого ученика, разложенные на месяцы вперёд по одному абонементу (4 урока) в месяц. Лист на каждое направление.',
    monthLabel: 'Раскладка с месяца',
    toggles: [
      {
        key: 'full_history',
        label: 'Вся история',
        hint: 'Добавить прошлые месяцы фактом отработки — видно и уже признанную выручку, и прогноз.',
      },
    ],
    buildParams: (year, month, toggles) => ({
      month: ym(year, month),
      full_history: Boolean(toggles.full_history),
    }),
  },
  {
    reportType: RETENTION,
    title: 'Отчёт по переходимости',
    desc: 'На каком цикле школа теряет детей: воронка по циклам с графиками, разрезы по '
      + 'преподавателям и направлениям, рабочий список зависших сделок и детализация. '
      + 'Цикл = 4 урока. Вся история, без выбора периода.',
    noPeriod: true,
    buildParams: () => ({}),
  },
];
