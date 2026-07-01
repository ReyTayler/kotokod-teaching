// Уже авторизован? Страница /login ему не нужна — сразу уводим в его раздел.
//   role === 'teacher' → /teacher, иначе (manager|admin) → /admin
//   (зеркалит серверный apps/auth_app/services.py: redirect_for). 401 → показываем форму.
// Вынесено из inline <script> ради CSP `script-src 'self'` (без 'unsafe-inline').
(function () {
  fetch('/api/auth/me', { credentials: 'include', headers: { Accept: 'application/json' } })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (me) {
      if (me && me.role) {
        window.location.replace(me.role === 'teacher' ? '/teacher' : '/admin');
      }
    })
    .catch(function () { /* сеть/ошибка — оставляем форму входа */ });
})();
