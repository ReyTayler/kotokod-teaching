import { Outlet } from 'react-router-dom';
import { useEffect } from 'react';
import { useAuth } from '@shared/hooks/useAuth';
import type { Me } from '@shared/providers/AuthProvider';

/**
 * Роль, которой разрешён вход в teacher SPA — только 'teacher'.
 * Зеркалит серверный критерий (permission_classes=[IsTeacher] на всех вьюхах
 * teacher_spa). Реальная защита данных — на API; этот guard лишь не даёт
 * отрисовать кабинет чужой роли и уводит её в свой раздел.
 */
function canAccessTeacher(me: Me | null): boolean {
  return !!me && me.role === 'teacher';
}

/** Куда отправить аутентифицированного, но не имеющего доступа в кабинет. */
function redirectFor(me: Me | null): string {
  return me && (me.role === 'admin' || me.role === 'manager' || me.role === 'superadmin')
    ? '/admin' : '/login';
}

export function AuthGate() {
  const { authenticated, me } = useAuth();

  const ready = authenticated !== null && !(authenticated && me === null);
  const allowed = authenticated === true && canAccessTeacher(me);

  useEffect(() => {
    if (!ready) return;
    if (authenticated === false) {
      window.location.href = '/login';
      return;
    }
    if (!allowed) {
      window.location.href = redirectFor(me);
    }
  }, [ready, authenticated, allowed, me]);

  if (!ready) {
    return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text3)' }}>Загрузка…</div>;
  }
  if (!allowed) return null;

  return <Outlet />;
}
