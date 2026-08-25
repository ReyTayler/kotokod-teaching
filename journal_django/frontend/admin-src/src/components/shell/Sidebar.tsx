import { useEffect, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { ThemeToggle } from './ThemeToggle';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import { canWritePayments, type Role } from '../../lib/permissions';
import { NAV_ICONS, NAV_PINNED, NAV_GROUPS, groupKeyOfPath } from './navConfig';
import { NavGroup } from './NavGroup';

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
  const { me } = useAuth();
  // Оплаты вносит только админ/суперадмин — менеджеру кнопку не показываем
  // (бэк отдаст 403 в любом случае, это UX-слой).
  if (!canWritePayments(me?.role as Role)) return null;
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
  const { pathname } = useLocation();

  // Состояние аккордеона выводится из маршрута, а не хранится между сессиями:
  // открыта группа текущего раздела. Клик по строке группы открывает её и
  // закрывает предыдущую.
  const activeKey = groupKeyOfPath(pathname);
  const [openKey, setOpenKey] = useState<string | null>(activeKey);
  useEffect(() => {
    const key = groupKeyOfPath(pathname);
    // Переход в раздел другой группы (по ссылке со страницы, не из сайдбара)
    // раскрывает нужную группу. Если пользователь сам свернул группу текущего
    // раздела — она останется свёрнутой до следующей смены пути.
    if (key) setOpenKey(key);
  }, [pathname]);

  const pinned = NAV_PINNED.filter((it) => !it.can || it.can(role));

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
        <div className="nav-pinned">
          {pinned.map((it) => (
            <NavLink
              key={it.key}
              to={it.path}
              className={({ isActive }) => `nav-btn${isActive ? ' active' : ''}`}
            >
              {NAV_ICONS[it.key]} {it.label}
            </NavLink>
          ))}
          <PayButton />
        </div>
        {NAV_GROUPS.map((group) => {
          const items = group.items.filter((it) => !it.can || it.can(role));
          if (items.length === 0) return null;
          return (
            <NavGroup
              key={group.key}
              group={group}
              items={items}
              open={openKey === group.key}
              hasActive={activeKey === group.key}
              onToggle={() => setOpenKey((k) => (k === group.key ? null : group.key))}
            />
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
