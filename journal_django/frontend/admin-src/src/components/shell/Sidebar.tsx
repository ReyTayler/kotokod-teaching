import { useEffect, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { ThemeToggle } from './ThemeToggle';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import { canWritePayments, type Role } from '../../lib/permissions';
import { NAV_ICONS, NAV_PINNED, NAV_GROUPS, groupKeyOfPath } from './navConfig';
import { NavGroup } from './NavGroup';
import { BrandMark } from './BrandMark';

function Avatar({ name }: { name: string }) {
  const parts = name.trim().split(' ');
  const initials = parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  const hue = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  return (
    <div
      className="avatar"
      style={{
        width: 36,
        height: 36,
        fontSize: 15,
        background: `hsl(${hue},55%,92%)`,
        border: `2px solid hsl(${hue},50%,80%)`,
        color: `hsl(${hue},55%,35%)`,
      }}
    >
      {initials.toUpperCase()}
    </div>
  );
}

function PayButton({ rail }: { rail?: boolean }) {
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
      title={rail ? 'Внести оплату' : undefined}
      aria-label={rail ? 'Внести оплату' : undefined}
    >
      {NAV_ICONS['pay']}
      <span className="nav-btn__label">Внести оплату</span>
    </button>
  );
}

interface Props {
  /** Рельса: колонка сужена до иконок, подписи прячутся, разделы группы
   *  открываются вылетающей панелью (см. NavGroup). */
  rail?: boolean;
  /** Кнопка в шапке панели. На широком экране переключает рельсу, в выезжающей
   *  панели закрывает её. Без обработчика кнопка не рисуется. */
  onToggle?: () => void;
  /** Подпись кнопки для скринридера — смысл у неё в разных местах разный. */
  toggleLabel?: string;
}

export function Sidebar({ rail, onToggle, toggleLabel = 'Скрыть боковую панель' }: Props = {}) {
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
    <aside className={`sidebar${rail ? ' sidebar--rail' : ''}`}>
      <div className="sidebar-logo">
        {/* В рельсе знак обрезан до «кота»: словесная часть логотипа в 64px
            превратилась бы в нечитаемую полоску. */}
        <div className="sidebar-logo__brand">
          <BrandMark compact={rail} className="logo-mark" />
          <div className="logo-sub">Admin Panel</div>
        </div>
        {onToggle && (
          <button
            type="button"
            className="sidebar-toggle-btn"
            onClick={onToggle}
            aria-label={toggleLabel}
            title={toggleLabel}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points={rail ? '9 18 15 12 9 6' : '15 18 9 12 15 6'} />
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
              title={rail ? it.label : undefined}
              aria-label={rail ? it.label : undefined}
            >
              {NAV_ICONS[it.key]}
              <span className="nav-btn__label">{it.label}</span>
            </NavLink>
          ))}
          <PayButton rail={rail} />
        </div>
        {NAV_GROUPS.map((group) => {
          const items = group.items.filter((it) => !it.can || it.can(role));
          if (items.length === 0) return null;
          return (
            <NavGroup
              key={group.key}
              group={group}
              items={items}
              rail={rail}
              open={openKey === group.key}
              hasActive={activeKey === group.key}
              onToggle={() => setOpenKey((k) => (k === group.key ? null : group.key))}
            />
          );
        })}
      </nav>
      <div className="sidebar-footer">
        <div className="user-row" title={rail ? `${me?.name || 'Admin'} · ${me?.role || ''}` : undefined}>
          <Avatar name={me?.name || 'Admin'} />
          <div className="user-row__text">
            <div className="user-name">{me?.name || 'Admin'}</div>
            <div className="user-role">{me?.role || 'Администратор'}</div>
          </div>
        </div>
        <ThemeToggle rail={rail} />
        <button
          type="button"
          className="logout-btn"
          onClick={() => { void logout(); }}
          title={rail ? 'Выйти' : undefined}
          aria-label={rail ? 'Выйти' : undefined}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
            <polyline points="16 17 21 12 16 7"/>
            <line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
          <span className="nav-btn__label">Выйти</span>
        </button>
      </div>
    </aside>
  );
}
