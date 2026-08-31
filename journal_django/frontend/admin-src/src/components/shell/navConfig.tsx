import type { ReactElement } from 'react';
import {
  canSeePayroll, canSeeAccounts, canSeeAudit, canSeeChangelog,
  canSeeSync, canSeeArchive, type Role,
} from '../../lib/permissions';

export const NAV_ICONS: Record<string, ReactElement> = {
  dashboard: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1" y="1" width="6" height="6" rx="1"/>
      <rect x="9" y="1" width="6" height="6" rx="1"/>
      <rect x="1" y="9" width="6" height="6" rx="1"/>
      <rect x="9" y="9" width="6" height="6" rx="1"/>
    </svg>
  ),
  students: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
      <circle cx="9" cy="7" r="4"/>
      <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
      <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
    </svg>
  ),
  groups: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1"/>
      <rect x="14" y="3" width="7" height="7" rx="1"/>
      <rect x="3" y="14" width="7" height="7" rx="1"/>
      <rect x="14" y="14" width="7" height="7" rx="1"/>
    </svg>
  ),
  teachers: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 10v6M2 10l10-5 10 5-10 5z"/>
      <path d="M6 12v5c3 3 9 3 12 0v-5"/>
    </svg>
  ),
  directions: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
    </svg>
  ),
  lessons: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
    </svg>
  ),
  'extra-lessons': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
      <line x1="12" y1="8" x2="12" y2="14"/>
      <line x1="9" y1="11" x2="15" y2="11"/>
    </svg>
  ),
  calendar: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
      <line x1="16" y1="2" x2="16" y2="6"/>
      <line x1="8" y1="2" x2="8" y2="6"/>
      <line x1="3" y1="10" x2="21" y2="10"/>
    </svg>
  ),
  payroll: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 12V8H6a2 2 0 0 1-2-2c0-1.1.9-2 2-2h12v4"/>
      <path d="M4 6v12a2 2 0 0 0 2 2h14v-4"/>
      <path d="M18 12a2 2 0 0 0 0 4h4v-4z"/>
    </svg>
  ),
  subscriptions: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="14" rx="2"/>
      <line x1="3" y1="10" x2="21" y2="10"/>
      <line x1="7" y1="15" x2="11" y2="15"/>
    </svg>
  ),
  renewals: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M23 4v6h-6"/>
      <path d="M1 20v-6h6"/>
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10"/>
      <path d="M20.49 15a9 9 0 0 1-14.85 3.36L1 14"/>
    </svg>
  ),
  pay: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/>
      <path d="M12 6v12M9 9h4.5a2 2 0 0 1 0 4H9a2 2 0 0 0 0 4h6"/>
    </svg>
  ),
  archive: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="21 8 21 21 3 21 3 8"/>
      <rect x="1" y="3" width="22" height="5" rx="1"/>
      <line x1="10" y1="12" x2="14" y2="12"/>
    </svg>
  ),
  settings: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
    </svg>
  ),
  audit: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <line x1="16" y1="13" x2="8" y2="13"/>
      <line x1="16" y1="17" x2="8" y2="17"/>
      <polyline points="10 9 9 9 8 9"/>
    </svg>
  ),
  changelog: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12a9 9 0 1 0 3-6.7"/>
      <polyline points="3 4 3 9 8 9"/>
      <polyline points="12 7 12 12 16 14"/>
    </svg>
  ),
  accounts: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4"/>
      <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
      <line x1="19" y1="8" x2="22" y2="8"/>
      <line x1="19" y1="11" x2="22" y2="11"/>
    </svg>
  ),
  notifications: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>
      <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
    </svg>
  ),
  sync: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10"/>
      <polyline points="1 20 1 14 7 14"/>
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
    </svg>
  ),
  reports: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <line x1="8" y1="13" x2="12" y2="13"/>
      <line x1="8" y1="17" x2="16" y2="17"/>
      <path d="M15 11.5v-2M12 11.5v-4M9 11.5v-1"/>
    </svg>
  ),
  // «i» в круге — знак справки. Книга, стоявшая тут раньше, повторяла значок
  // «Отчёты», а в кабинете преподавателя — значок «Мои уроки».
  knowledge: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
         strokeLinecap="round" strokeLinejoin="round" width="16" height="16">
      <circle cx="12" cy="12" r="9.5"/>
      <line x1="12" y1="11" x2="12" y2="16.5"/>
      {/* Точка над «i»: путь нулевой длины с круглым концом — иначе она
          рисовалась бы отдельным <circle> с заливкой и жила бы по другим
          правилам масштабирования, чем остальные линии значка. */}
      <path d="M12 7.5h.01"/>
    </svg>
  ),
  // ── Иконки строк-групп. У вложенных пунктов иконок нет вовсе, поэтому
  //    сходство с иконками отдельных разделов (шапочка ↔ «Преподаватели»,
  //    книга ↔ «Уроки») в сайдбаре нигде не встречается глазу.
  'group-study': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 10 12 5 2 10l10 5 10-5Z"/>
      <path d="M6 12v5c3 2.5 9 2.5 12 0v-5"/>
      <path d="M22 10v5"/>
    </svg>
  ),
  'group-lessons': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 4h5.5A2.5 2.5 0 0 1 10 6.5V20a2 2 0 0 0-2-2H2z"/>
      <path d="M22 4h-5.5A2.5 2.5 0 0 0 14 6.5V20a2 2 0 0 1 2-2h6z"/>
    </svg>
  ),
  'group-finance': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2"/>
      <path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-3"/>
      <path d="M21 10h-4a2 2 0 0 0 0 4h4z"/>
    </svg>
  ),
  'group-system': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/>
      <path d="M1 14h6M9 8h6M17 16h6"/>
    </svg>
  ),
  // Один шеврон вправо; в развёрнутой группе поворачивается средствами CSS —
  // второй SVG «вниз» держать не нужно.
  chevron: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6"/>
    </svg>
  ),
};

export interface NavItem {
  key: string;
  label: string;
  path: string;
  /** Ролевой гейт: пункт виден, только если функция вернёт true. Без неё — всем staff. */
  can?: (role: Role | undefined) => boolean;
}

export interface NavGroup {
  /** Устойчивый ключ — по нему хранится состояние аккордеона. */
  key: string;
  title: string;
  /** Ключ в NAV_ICONS для иконки строки группы. */
  icon: string;
  items: NavItem[];
}

/**
 * Закреплено сверху, вне групп. «Дашборд» — точка входа, прятать его внутрь
 * аккордеона незачем; рядом с ним рендерится CTA «Внести оплату».
 */
export const NAV_PINNED: NavItem[] = [
  { key: 'dashboard', label: 'Дашборд', path: '/admin/dashboard' },
];

/**
 * Единый источник навигации admin SPA. Разделы спрятаны в смысловые группы:
 * группа раскрывается кликом, открыта всегда одна. Ролевые пункты несут `can`;
 * группа без единого видимого пункта не рисуется вовсе.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    key: 'study',
    title: 'Учебная часть',
    icon: 'group-study',
    items: [
      { key: 'students', label: 'Ученики', path: '/admin/students' },
      { key: 'groups', label: 'Группы', path: '/admin/groups' },
      { key: 'teachers', label: 'Преподаватели', path: '/admin/teachers' },
      { key: 'directions', label: 'Направления', path: '/admin/directions' },
      { key: 'renewals', label: 'Продления', path: '/admin/renewals' },
      { key: 'tasks', label: 'Задачи', path: '/admin/tasks' },
    ],
  },
  {
    key: 'lessons',
    title: 'Занятия',
    icon: 'group-lessons',
    items: [
      { key: 'lessons', label: 'Уроки', path: '/admin/lessons' },
      { key: 'extra-lessons', label: 'Доп.уроки', path: '/admin/extra-lessons' },
      { key: 'calendar', label: 'Календарь', path: '/admin/calendar' },
    ],
  },
  {
    key: 'finance',
    title: 'Финансы',
    icon: 'group-finance',
    items: [
      { key: 'subscriptions', label: 'Абонементы', path: '/admin/subscriptions' },
      { key: 'payroll', label: 'Зарплата', path: '/admin/payroll', can: canSeePayroll },
    ],
  },
  {
    key: 'system',
    title: 'Система',
    icon: 'group-system',
    items: [
      // Первыми в группе — пункты без ролевого условия, то есть те, которые
      // видят все. Между разделами, закрытыми для большинства ролей, они бы
      // терялись.
      { key: 'knowledge', label: 'Wiki', path: '/admin/knowledge' },
      { key: 'reports', label: 'Отчёты', path: '/admin/reports' },
      { key: 'settings', label: 'Настройки', path: '/admin/settings' },
      { key: 'archive', label: 'Архив', path: '/admin/archive', can: canSeeArchive },
      { key: 'accounts', label: 'Учётки', path: '/admin/accounts', can: canSeeAccounts },
      { key: 'audit', label: 'Журнал ИБ', path: '/admin/audit', can: canSeeAudit },
      { key: 'changelog', label: 'Журнал изменений', path: '/admin/changelog', can: canSeeChangelog },
      { key: 'notifications', label: 'Уведомления', path: '/admin/notifications', can: canSeeChangelog },
      { key: 'sync', label: 'Синхро', path: '/admin/sync', can: canSeeSync },
    ],
  },
];

/**
 * Ключ группы, которой принадлежит путь, либо null.
 *
 * Сравнение по началу пути с обязательным «/» на стыке: вложенные маршруты
 * (`/admin/students/42`) должны подсвечивать свою группу, но `/admin/lessons`
 * не должен ловить чужой `/admin/lessons-archive`, если такой однажды заведут.
 */
export function groupKeyOfPath(pathname: string): string | null {
  for (const group of NAV_GROUPS) {
    const hit = group.items.some(
      (it) => pathname === it.path || pathname.startsWith(`${it.path}/`),
    );
    if (hit) return group.key;
  }
  return null;
}
