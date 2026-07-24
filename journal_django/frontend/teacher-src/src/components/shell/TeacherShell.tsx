import { Outlet, NavLink } from 'react-router-dom';
import type { ReactElement } from 'react';
import { useAuth } from '@shared/hooks/useAuth';
import { useTheme } from '@shared/providers/ThemeProvider';

const NAV_ICONS: Record<string, ReactElement> = {
  calendar: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  ),
  groups: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  ),
  lessons: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
  ),
  report: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  ),
};

const SECTIONS = [
  { key: 'calendar', label: 'Календарь', path: '/calendar' },
  { key: 'groups', label: 'Мои группы', path: '/groups' },
  { key: 'lessons', label: 'Мои уроки', path: '/lessons' },
  { key: 'report', label: 'Отчёт по уроку', path: '/report' },
];

function Avatar({ name }: { name: string }) {
  const parts = name.trim().split(' ');
  const initials = parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  const hue = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  return (
    <div
      style={{
        width: 32, height: 32, flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        borderRadius: '50%', fontSize: 13, fontWeight: 700,
        background: `hsl(${hue},55%,92%)`,
        border: `2px solid hsl(${hue},50%,80%)`,
        color: `hsl(${hue},55%,35%)`,
      }}
    >
      {initials.toUpperCase()}
    </div>
  );
}

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <button type="button" className="t-icon-btn" onClick={toggle} aria-label="Переключить тему" title="Тема">
      {theme === 'dark' ? (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="5" />
          <line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
          <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
          <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
          <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      )}
    </button>
  );
}

export function TeacherShell() {
  const { me, logout } = useAuth();
  return (
    <div className="t-shell">
      <header className="t-topbar">
        <NavLink to="/calendar" className="t-brand">
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
          <span className="t-brand-sub">Кабинет<br />преподавателя</span>
        </NavLink>

        <nav className="t-tabs">
          {SECTIONS.map((s) => (
            <NavLink
              key={s.key}
              to={s.path}
              className={({ isActive }) => `t-tab${isActive ? ' active' : ''}`}
            >
              {NAV_ICONS[s.key]} {s.label}
            </NavLink>
          ))}
        </nav>

        <div className="t-topbar-right">
          <div className="t-user">
            <Avatar name={me?.name || 'Преподаватель'} />
            <div className="t-user-meta">
              <div className="t-user-name">{me?.name || 'Преподаватель'}</div>
              <div className="t-user-role">Преподаватель</div>
            </div>
          </div>
          <ThemeToggle />
          <button
            type="button"
            className="t-icon-btn"
            onClick={() => { void logout(); }}
            aria-label="Выйти"
            title="Выйти"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
          </button>
        </div>
      </header>

      <main className="t-main">
        <Outlet />
      </main>
    </div>
  );
}
