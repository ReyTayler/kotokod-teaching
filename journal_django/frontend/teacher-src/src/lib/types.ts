/** Форма ответа /api/report (заморожена parity-тестами; см. teacher_spa/views.py). */

export type LessonStatus = 'done' | 'pending' | 'overdue' | 'notime';

export interface ReportStudent {
  name: string;
}

export interface ReportLesson {
  teacher: string;
  group: string;
  pm: string;
  vkChat: string;
  startDate: string;
  isGroup: boolean | null;
  students: ReportStudent[];
  groupDisplay: string;
  day: number | null;       // 1=Пн … 6=Сб, 0=Вс
  dayName: string | null;
  dayShort: string | null;
  time: string | null;      // 'HH:MM'
  sortKey?: number;
  status: LessonStatus;
  label: string;
}

export interface ReportResponse {
  lessons: ReportLesson[];
  noTime: ReportLesson[];
  weekStart: string;        // 'YYYY-MM-DD' (понедельник)
  cachedAt: string;
}

/** Формы ответов /api/getData, /api/getAllData, /api/submitLesson (заморожены). */

export interface TStudent {
  name: string;
  lessonsDone: number;
  remaining: number;
  // Дата рождения 'YYYY-MM-DD' | '' (поле age удалено; возраст teacher-фронт
  // при необходимости считает сам). Сейчас нигде не отображается.
  birthDate: string;
  sheetName: string;
  sheetRow: number;
  locked: boolean;
  lockedThrough: number | null;
  // «Неоплачиваемый пропуск» на следующий урок группы (пометка LessonSkip): ученика
  // отмечать нельзя, в зарплату не входит. Ставится менеджером (перевод/начал не с 1-го).
  skip?: boolean;
}

export interface GroupData {
  students: TStudent[];
  lessonsDone: number;
  pm: string;
  vkChat: string;
  startDate: string;
  isGroup: boolean;
}

/** Ключи — названия групп. */
export type GroupMap = Record<string, GroupData>;

/** POST /api/getData — группы ТОЛЬКО текущего преподавателя, без вложенности. */
export interface GetDataResponse {
  teacher: string;
  data: GroupMap;
}

/** POST /api/getAllData — вложено по преподавателю (для замен). */
export interface GetAllDataResponse {
  teacher: string;
  data: Record<string, GroupMap>;
}

/**
 * isSubstitution/originalTeacher/lessonType удалены: тип урока выводит сервер
 * из planned_lessons — замену из назначения «Сменить преподавателя» (admin),
 * перенос из moved_from_date плановой строки; присланные клиентом поля
 * отклоняются с 400.
 */
export interface SubmitPayload {
  group: string;
  date: string; // 'YYYY-MM-DD'
  recordUrl?: string;
  students: { name: string; present: boolean }[];
  /** Позиция курса (Occurrence.id) — какое именно занятие отмечается. Шлют оба
   *  входа, и календарь, и «Мои уроки»: без него сервер угадывает позицию по
   *  дате и на группах с двумя занятиями в день уходит на путь, где повторная
   *  отправка создаёт второй платный урок. Отсутствует только там, где позиции
   *  нет вовсе (группа без плана занятий). */
  plannedLessonId?: number;
}

export type SubmitResult =
  | { success: true; payment: number; penalty: number; lessonNumber: number }
  | { success: false; error: string };

/**
 * Форма элемента ответа GET /api/lessons (заморожена; см.
 * teacher_spa/serializers.py::MyLessonSerializer). ВНИМАНИЕ: lessonNumber/
 * payment/penalty приходят строками (Decimal, DateSafeJSONRenderer) — на
 * фронте приводить через Number(), с guard на null.
 */
export interface MyLesson {
  id: number;
  date: string; // 'YYYY-MM-DD'
  group: string;
  lessonNumber: string;
  lessonType: 'regular' | 'substitution' | 'reschedule';
  isSubstitution: boolean;
  originalTeacher: string | null;
  recordUrl: string | null;
  submittedAt: string; // ISO
  presentCount: number | null;
  totalCount: number | null;
  payment: string | null;
  penalty: string | null;
  direction: string | null;
  directionColor: string | null;
}

/** GET /api/lessons — StandardPagination envelope. */
export interface MyLessonsResponse {
  rows: MyLesson[];
  total: number;
  page: number;
  page_size: number;
}

/** Элемент карты GET /api/group-directions — направление конкретной группы. */
export interface GroupDirection {
  direction: string | null;
  color: string | null;
  isIndividual: boolean;
  /** Длительность урока в минутах (напр. 45/60/90) — первичный источник half-lesson (Ф4). */
  lessonDurationMinutes: number;
  /** Лимит уроков по курсу направления; null — лимита нет/неизвестен (Ф4). */
  totalLessons: number | null;
}

/** GET /api/group-directions — карта ВСЕХ активных групп преподавателя: имя → направление. */
export interface GroupDirectionsResponse {
  groups: Record<string, GroupDirection>;
}

/**
 * Форма ответа GET /api/calendar (заморожена; см. teacher_spa/views.py).
 * В отличие от /api/report, occurrence привязан к РЕАЛЬНОЙ дате занятия
 * (occ.date), а не к дню недели+номеру недели — окно произвольное (≤92 дней),
 * поэтому месяц можно запросить ОДНИМ запросом. direction/color приходят
 * прямо в occurrence — отдельного useGroupDirections для календаря не нужно.
 */
export type OccStatus = 'pending' | 'overdue' | 'done' | 'cancelled' | 'moved';

export interface OccStudent {
  name: string;
}

export interface Occurrence {
  /**
   * PlannedLesson.id — позиция курса этого занятия. Ею LessonForm называет
   * серверу, КАКОЙ урок отмечается (submitLesson.plannedLessonId): сервер берёт
   * из позиции номер урока и закрепляет за ней факт, поэтому повторная отправка
   * упирается в занятую позицию (409) вместо создания второго урока.
   * null у карточек доп.урока — они отмечаются своим путём (extraLessonId).
   */
  id: number | null;
  group: string;
  groupDisplay: string;
  teacher: string;
  teacherOverride: string | null;
  direction: string | null;
  color: string | null; // hex #RRGGBB или null
  isGroup: boolean;
  /** Длительность занятия в минутах (groups.lesson_duration_minutes) — высота ячейки в сетке. */
  durationMinutes: number;
  /** Ссылка на чат группы (groups.vk_chat) — пункт «Перейти в чат» контекстного меню. */
  vkChat: string | null;
  date: string;         // 'YYYY-MM-DD' — реальная дата занятия
  time: string | null;  // 'HH:MM'
  day: number;           // 0=Вс…6=Сб (как раньше report.day)
  seq: number | null;
  lessonNumber: number | null;
  isHalf: boolean;
  isExtra: boolean;
  /**
   * Присутствует только для карточек ExtraLessonAssignment (доп.урок за
   * пропуск конкретного основного урока, apps.extra_lessons) — отличать от
   * isExtra (групповое доп.занятие вне курса, apps.scheduling.PlannedLesson).
   * CalendarView красит такие карточки фиксированным красным (не по
   * направлению); OccurrenceMenu подставляет «Провести доп.урок».
   */
  extraLessonId?: number | null;
  status: OccStatus;
  label: string;         // готовая подпись (напр. «Перенесён на 10.06»)
  movedFrom: string | null; // 'YYYY-MM-DD'
  movedTo: string | null;   // 'YYYY-MM-DD'
  students: OccStudent[];
}

export interface UnscheduledGroup {
  group: string;
  reason: 'no_start_date' | 'no_slots';
}

export interface CalendarResponse {
  occurrences: Occurrence[];
  unscheduled: UnscheduledGroup[];
  window: { from: string; to: string };
}

/**
 * GET /api/my-payroll?month=YYYY-MM — своя зарплата за месяц с расшифровкой
 * (apps/payroll/views.py::MyPayrollView). Деньги приходят строками с масштабом
 * ('800.00') — как во всём teacher-контракте; на фронте форматировать через
 * lib/money.ts, а не Number() + toFixed по месту.
 */
export type PayrollRuleCode =
  | 'per_student'
  | 'small_group_full'
  | 'small_group_partial'
  | 'half_lesson'
  | 'extra_flat'
  | 'extra_individual'
  | 'none'
  | 'adjusted';

export interface PayrollRule {
  code: PayrollRuleCode;
  /** Короткая формула для строки урока: '4 × 200 ₽'. */
  text: string;
  /** Правило словами: 'группа от 3 человек — 200 ₽ за каждого пришедшего'. */
  note: string;
}

export type PayrollLessonKind =
  | 'regular' | 'substitution' | 'reschedule' | 'extra' | 'burned';

export interface PayrollEntry {
  lessonId: number;
  date: string;             // 'YYYY-MM-DD'
  group: string;
  direction: string | null;
  directionColor: string | null;
  lessonNumber: string;
  kind: PayrollLessonKind;
  durationMinutes: number;
  totalStudents: number;
  presentCount: number;
  payment: string;          // начислено
  penalty: string;          // удержано
  net: string;              // к выплате за этот урок
  rule: PayrollRule;
  /** Почему удержали; null — штрафа нет. */
  penaltyNote: string | null;
  /** Почему headcount меньше группы (бесплатные/непл. пропуски); null — все учтены. */
  excludedNote: string | null;
  /** Сумму правил администратор — формулой она не объясняется. */
  adjusted: boolean;
}

export interface MyPayrollResponse {
  month: string;            // 'YYYY-MM'
  monthLabel: string;       // 'Июль 2026'
  totals: {
    lessons: number;
    presences: number;
    payment: string;
    penalty: string;
    net: string;
  };
  rows: PayrollEntry[];
}
