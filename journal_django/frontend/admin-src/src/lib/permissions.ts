export type Role = 'teacher' | 'manager' | 'admin' | 'superadmin';

const isSuper = (r?: Role | null) => r === 'superadmin';
const isAdminUp = (r?: Role | null) => r === 'admin' || r === 'superadmin';

// Разделы (видимость навигации / доступ к роуту)
export const canSeeAccounts = isSuper;
export const canSeeAudit = isSuper;
export const canSeePayroll = isSuper;
export const canSeeChangelog = isAdminUp; // журнал изменений — только admin/superadmin (не manager)
export const canSeeSync = isSuper;
export const canSeeArchive = isSuper;

// Архивация / разархивация сущностей (кнопки на detail-страницах, чекбокс active
// в формах). Только суперадмин — включая группы, где обычная правка доступна
// админам/менеджерам, а (раз)архивация — нет.
export const canArchiveEntities = isSuper;

// Операции над сущностями (write-кнопки)
export const canWriteTeachers = isSuper;
export const canWriteDirections = isSuper;
export const canWriteSubscriptions = isSuper; // абонементы + скидки
export const canWriteLessons = isAdminUp;     // CRUD урока + посещаемость
export const canSeeLessonPayroll = isSuper;   // зарплата за урок
export const canRevertChangelog = isAdminUp;
export const canWriteRenewalStages = isSuper; // конфиг стадий воронки продлений (Фаза 6)
export const canDeleteStudentComments = isAdminUp; // удаление комментария к ученику
export const canWriteStudentManager = isAdminUp; // назначение ответственного менеджера ученику
