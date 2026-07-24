import type { ReactElement } from 'react';
import { NavLink } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { ThemeToggle } from './ThemeToggle';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import { usePendingExtraLessonsCount } from '../../hooks/useExtraLessons';
import { canSeePayroll, canSeeAccounts, canSeeAudit, canSeeChangelog, canSeeSync, canSeeArchive, type Role } from '../../lib/permissions';

/** Красный бейдж с числом необработанных пропусков на кнопке «Доп.уроки». */
export function ExtraLessonsBadge() {
  const { data } = usePendingExtraLessonsCount();
  const count = data?.count ?? 0;
  if (count <= 0) return null;
  return (
    <span className="nav-badge" title={`Необработанных пропусков: ${count}`}>
      {count > 99 ? '99+' : count}
    </span>
  );
}

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
};

export interface NavItem {
  key: string;
  label: string;
  path: string;
  /** Ролевой гейт: пункт виден, только если функция вернёт true. Без неё — всем staff. */
  can?: (role: Role | undefined) => boolean;
}

export interface NavGroup {
  /** Заголовок группы (null — группа без заголовка: «Дашборд» сверху). */
  title: string | null;
  items: NavItem[];
}

/**
 * Единый источник навигации admin SPA — разделы сгруппированы по смыслу с
 * заголовками (Sidebar рисует заголовки, MobileNav — плоским списком). Ролевые
 * пункты несут `can`; группа без видимых пунктов не рисуется вовсе.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    title: null,
    items: [{ key: 'dashboard', label: 'Дашборд', path: '/admin/dashboard' }],
  },
  {
    title: 'Учебная часть',
    items: [
      { key: 'students', label: 'Ученики', path: '/admin/students' },
      { key: 'groups', label: 'Группы', path: '/admin/groups' },
      { key: 'teachers', label: 'Преподаватели', path: '/admin/teachers' },
      { key: 'directions', label: 'Направления', path: '/admin/directions' },
    ],
  },
  {
    title: 'Занятия',
    items: [
      { key: 'lessons', label: 'Уроки', path: '/admin/lessons' },
      { key: 'extra-lessons', label: 'Доп.уроки', path: '/admin/extra-lessons' },
      { key: 'calendar', label: 'Календарь', path: '/admin/calendar' },
    ],
  },
  {
    title: 'Финансы',
    items: [
      { key: 'subscriptions', label: 'Абонементы', path: '/admin/subscriptions' },
      { key: 'renewals', label: 'Продления', path: '/admin/renewals' },
      { key: 'reports', label: 'Отчёты', path: '/admin/reports' },
      { key: 'payroll', label: 'Зарплата', path: '/admin/payroll', can: canSeePayroll },
    ],
  },
  {
    title: 'Система',
    items: [
      { key: 'settings', label: 'Настройки', path: '/admin/settings' },
      { key: 'archive', label: 'Архив', path: '/admin/archive', can: canSeeArchive },
      { key: 'accounts', label: 'Учётки', path: '/admin/accounts', can: canSeeAccounts },
      { key: 'audit', label: 'Журнал ИБ', path: '/admin/audit', can: canSeeAudit },
      { key: 'changelog', label: 'Журнал изменений', path: '/admin/changelog', can: canSeeChangelog },
      { key: 'sync', label: 'Синхро', path: '/admin/sync', can: canSeeSync },
    ],
  },
];

/** Плоский список всех пунктов (для MobileNav). */
export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);

function Avatar({ name }: { name: string }) {
  const parts = name.trim().split(' ');
  const initials = parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  const hue = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  return (
    <div
      className="avatar"
      style={{
        width: 32,
        height: 32,
        fontSize: 14,
        background: `hsl(${hue},55%,92%)`,
        border: `2px solid hsl(${hue},50%,80%)`,
        color: `hsl(${hue},55%,35%)`,
      }}
    >
      {initials.toUpperCase()}
    </div>
  );
}

function PayButton() {
  const { open } = usePaymentModal();
  return (
    <button
      type="button"
      className="nav-btn nav-btn--cta"
      onClick={() => open()}
    >
      {NAV_ICONS['pay']} Внести оплату
    </button>
  );
}

export function Sidebar({ onClose }: { onClose?: () => void } = {}) {
  const { me, logout } = useAuth();
  const role = me?.role as Role | undefined;
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div>
          <svg className="logo-mark" viewBox="0 0 207 40" fill="none" role="img" aria-label="КОТОКОД">
            <path clipRule="evenodd" fillRule="evenodd" fill="currentColor" d="M169.067 32.8482H173.403V30.2503H184.328V32.8482H188.664V26.2668H186.929V17.2608H171.755V23.2359C171.751 24.2787 171.565 25.0656 170.801 26.2668H169.067V32.8482ZM182.594 21.2442V26.2668H175.31C175.842 25.1354 175.977 24.4685 176.004 23.2359V21.2442H182.594Z" />
            <path fill="currentColor" d="M63.9746 30.2503V17.2608H68.3101V21.7638H71.6051L75.5937 17.2608H80.8831L75.2469 23.7555L80.8831 30.2503H75.5937L71.6051 25.7472H68.3101V30.2503H63.9746Z" />
            <path fill="currentColor" d="M134.557 30.2503V17.2608H138.892V21.7638H142.187L146.176 17.2608H151.465L145.829 23.7555L151.465 30.2503H146.176L142.187 25.7472H138.892V30.2503H134.557Z" />
            <path clipRule="evenodd" fillRule="evenodd" fill="currentColor" d="M80.4489 23.8391C80.4492 23.8067 80.4495 23.7788 80.4495 23.7555C80.4495 23.7323 80.4492 23.7043 80.4489 23.672C80.4373 22.62 80.3743 16.9144 89.2072 16.9144C98.0402 16.9144 97.9772 22.62 97.9656 23.672C97.9653 23.7043 97.9649 23.7323 97.9649 23.7555C97.9649 23.7788 97.9653 23.8067 97.9656 23.8391C97.9772 24.8911 98.0402 30.5966 89.2072 30.5966C80.3743 30.5966 80.4373 24.8911 80.4489 23.8391ZM84.785 23.7555C84.785 25.0545 85.4787 26.44 89.2072 26.44C92.9357 26.44 93.6294 25.0545 93.6294 23.7555C93.6294 22.4566 92.9357 20.8978 89.2072 20.8978C85.4787 20.8978 84.785 22.4566 84.785 23.7555Z" />
            <path clipRule="evenodd" fillRule="evenodd" fill="currentColor" d="M115.135 23.8391C115.135 23.8067 115.135 23.7788 115.135 23.7555C115.135 23.7323 115.135 23.7043 115.135 23.672C115.123 22.62 115.06 16.9144 123.893 16.9144C132.726 16.9144 132.663 22.62 132.651 23.672C132.651 23.7043 132.651 23.7323 132.651 23.7555C132.651 23.7788 132.651 23.8067 132.651 23.8391C132.663 24.8911 132.726 30.5966 123.893 30.5966C115.06 30.5966 115.123 24.8911 115.135 23.8391ZM119.471 23.7555C119.471 25.0545 120.164 26.44 123.893 26.44C127.621 26.44 128.315 25.0545 128.315 23.7555C128.315 22.4566 127.621 20.8978 123.893 20.8978C120.164 20.8978 119.471 22.4566 119.471 23.7555Z" />
            <path clipRule="evenodd" fillRule="evenodd" fill="currentColor" d="M151.033 23.8391C151.033 23.8067 151.033 23.7788 151.033 23.7555C151.033 23.7323 151.033 23.7043 151.033 23.672C151.021 22.62 150.958 16.9144 159.791 16.9144C168.624 16.9144 168.561 22.62 168.549 23.672C168.549 23.7043 168.549 23.7323 168.549 23.7555C168.549 23.7788 168.549 23.8067 168.549 23.8391C168.561 24.8911 168.624 30.5966 159.791 30.5966C150.958 30.5966 151.021 24.8911 151.033 23.8391ZM155.369 23.7555C155.369 25.0545 156.062 26.44 159.791 26.44C163.519 26.44 164.213 25.0545 164.213 23.7555C164.213 22.4566 163.519 20.8978 159.791 20.8978C156.062 20.8978 155.369 22.4566 155.369 23.7555Z" />
            <path fill="currentColor" d="M98.6586 21.3308V17.2608H114.44V21.3308H108.804V30.2503H104.468V21.3308H98.6586Z" />
            <path fill="#50dcfe" d="M17.9712 0.980652L26.1208 9.15181H49.7547L57.9043 0.980652V37.7509C57.9043 39.556 56.4448 41.0193 54.6444 41.0193H21.231C19.4307 41.0193 17.9712 39.556 17.9712 37.7509V0.980652Z" />
            <path fill="#50dcfe" d="M203.129 25.392L194.775 21.2042V17.4251L207 22.7363V28.0476L194.775 33.3588V29.5797L203.129 25.392Z" />
            <path fill="#50dcfe" d="M3.87106 25.392L12.2244 21.2042V17.4251L0 22.7363V28.0476L12.2244 33.3588V29.5797L3.87106 25.392Z" />
          </svg>
          <div className="logo-sub">Admin Panel</div>
        </div>
        {onClose && (
          <button
            type="button"
            className="sidebar-close-btn"
            onClick={onClose}
            aria-label="Скрыть боковую панель"
            title="Скрыть"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6"/>
            </svg>
          </button>
        )}
      </div>
      <nav className="sidebar-nav">
        {NAV_GROUPS.map((group, gi) => {
          const items = group.items.filter((it) => !it.can || it.can(role));
          if (items.length === 0) return null;
          return (
            <div key={group.title ?? '__top'} className="nav-group">
              {group.title && <div className="nav-group__title">{group.title}</div>}
              {items.map((it) => (
                <NavLink
                  key={it.key}
                  to={it.path}
                  className={({ isActive }) => `nav-btn${isActive ? ' active' : ''}`}
                >
                  {NAV_ICONS[it.key]} {it.label}
                  {it.key === 'extra-lessons' && <ExtraLessonsBadge />}
                </NavLink>
              ))}
              {/* CTA «Внести оплату» — сразу под Дашбордом (первая группа). */}
              {gi === 0 && <PayButton />}
            </div>
          );
        })}
      </nav>
      <div className="sidebar-footer">
        <div className="user-row">
          <Avatar name={me?.name || 'Admin'} />
          <div>
            <div className="user-name">{me?.name || 'Admin'}</div>
            <div className="user-role">{me?.role || 'Администратор'}</div>
          </div>
        </div>
        <ThemeToggle />
        <button
          type="button"
          className="logout-btn"
          onClick={() => { void logout(); }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
            <polyline points="16 17 21 12 16 7"/>
            <line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
          Выйти
        </button>
      </div>
    </aside>
  );
}
