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
// Оплаты: менеджер их видит, но не вносит и не удаляет — деньги заводит
// админ/суперадмин (решение 2026-07-28). Бэк: ReadStaffWriteAdmin на
// /api/admin/payments. Возврат средств менеджеру закрыт отдельно (IsAdminOrSuperAdmin).
export const canWritePayments = isAdminUp;
// Откат проведённого доп.урока и откат сгорания: обе операции возвращают урок на
// баланс ученика и снимают зарплату преподавателю — значит это деньги, и правит их
// админ/суперадмин (решение 2026-07-30). Менеджер кнопку видит, но она неактивна.
// Бэк: ReadStaffWriteAdmin на DELETE /api/admin/extra-lessons/:id.
export const canRollbackExtraLesson = isAdminUp;
export const canSeeLessonPayroll = isSuper;   // зарплата за урок
export const canRevertChangelog = isAdminUp;
export const canWriteRenewalStages = isSuper; // конфиг стадий воронки продлений (Фаза 6)
export const canDeleteStudentComments = isAdminUp; // удаление комментария к ученику
// Вкладка «Уроки» на странице группы (сетка занятий + редактор урока). Менеджеру
// не нужна — уроки он всё равно не правит (canWriteLessons), а вкладка только
// шумит (решение 2026-07-28). Набор группы («Ученики») менеджеру доступен.
export const canSeeGroupLessonsTab = isAdminUp;
export const canWriteStudentManager = isAdminUp; // назначение ответственного менеджера ученику
// Привязка Telegram-аккаунта преподавателю. Менеджер поле видит (чтобы понимать,
// дойдут ли до преподавателя напоминания), но не меняет. Бэк:
// ReadStaffWriteAdmin на POST/DELETE /api/admin/teachers/:id/telegram.
export const canWriteTeacherTelegram = isAdminUp;
