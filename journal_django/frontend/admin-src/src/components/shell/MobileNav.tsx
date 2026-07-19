import { NavLink } from 'react-router-dom';
import { SECTIONS, NAV_ICONS, ExtraLessonsBadge } from './Sidebar';
import { useAuth } from '../../hooks/useAuth';
import { canSeePayroll, canSeeAccounts, canSeeAudit, canSeeChangelog, canSeeSync, type Role } from '../../lib/permissions';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function MobileNav({ open, onClose }: Props) {
  const { me } = useAuth();
  const role = me?.role as Role | undefined;
  const visibleSections = SECTIONS.filter((s) => s.key !== 'payroll' || canSeePayroll(role));
  return (
    <>
      <div
        className={`mobile-nav-overlay${open ? ' open' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className={`mobile-nav${open ? ' open' : ''}`}
        role="dialog"
        aria-label="Меню разделов"
        aria-hidden={!open}
      >
        <div className="mobile-nav-handle" />
        <div className="mobile-nav-list">
          {visibleSections.map((s) => (
            <NavLink
              key={s.key}
              to={s.path}
              className={({ isActive }) => `mobile-nav-item${isActive ? ' active' : ''}`}
              onClick={onClose}
              tabIndex={open ? 0 : -1}
            >
              {NAV_ICONS[s.key]}
              <span>{s.label}</span>
              {s.key === 'extra-lessons' && <ExtraLessonsBadge />}
            </NavLink>
          ))}
          {canSeeAccounts(role) && (
            <NavLink
              to="/admin/accounts"
              className={({ isActive }) => `mobile-nav-item${isActive ? ' active' : ''}`}
              onClick={onClose}
              tabIndex={open ? 0 : -1}
            >
              {NAV_ICONS['accounts']}
              <span>Учётки</span>
            </NavLink>
          )}
          {canSeeAudit(role) && (
            <NavLink
              to="/admin/audit"
              className={({ isActive }) => `mobile-nav-item${isActive ? ' active' : ''}`}
              onClick={onClose}
              tabIndex={open ? 0 : -1}
            >
              {NAV_ICONS['audit']}
              <span>Журнал ИБ</span>
            </NavLink>
          )}
          {canSeeChangelog(role) && (
            <NavLink
              to="/admin/changelog"
              className={({ isActive }) => `mobile-nav-item${isActive ? ' active' : ''}`}
              onClick={onClose}
              tabIndex={open ? 0 : -1}
            >
              {NAV_ICONS['changelog']}
              <span>Журнал изменений</span>
            </NavLink>
          )}
          {canSeeSync(role) && (
            <NavLink
              to="/admin/sync"
              className={({ isActive }) => `mobile-nav-item${isActive ? ' active' : ''}`}
              onClick={onClose}
              tabIndex={open ? 0 : -1}
            >
              {NAV_ICONS['sync']}
              <span>Синхро</span>
            </NavLink>
          )}
        </div>
      </div>
    </>
  );
}
