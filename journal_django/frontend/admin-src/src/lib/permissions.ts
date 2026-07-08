export type Role = 'teacher' | 'manager' | 'admin' | 'superadmin';

const isSuper = (r?: Role | null) => r === 'superadmin';
const isAdminUp = (r?: Role | null) => r === 'admin' || r === 'superadmin';
const isStaff = (r?: Role | null) => r === 'manager' || r === 'admin' || r === 'superadmin';

// Разделы (видимость навигации / доступ к роуту)
export const canSeeAccounts = isSuper;
export const canSeeAudit = isSuper;
export const canSeePayroll = isSuper;
export const canSeeChangelog = isStaff;
export const canSeeRenewals = isStaff;

// Операции над сущностями (write-кнопки)
export const canWriteTeachers = isSuper;
export const canWriteDirections = isSuper;
export const canWriteSubscriptions = isSuper; // абонементы + скидки
export const canWriteLessons = isAdminUp;     // CRUD урока + посещаемость
export const canSeeLessonPayroll = isSuper;   // зарплата за урок
export const canRevertChangelog = isAdminUp;
export const canWriteRenewalStages = isSuper; // конфиг стадий воронки продлений (Фаза 6)
