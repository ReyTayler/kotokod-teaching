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
  age: string;
  sheetName: string;
  sheetRow: number;
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
