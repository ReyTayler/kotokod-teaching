export class ApiError extends Error {
  status: number;
  details?: unknown;
  /** Машиночитаемый код ошибки из тела ответа (`{code: '...'}`) — для UI-ветвлений
   *  (например, показать модалку по конкретному конфликту, а не generic-тост). */
  code?: string;
  constructor(status: number, message: string, details?: unknown, code?: string) {
    super(message);
    this.status = status;
    this.details = details;
    this.code = code;
  }
}

// custom_exception_handler на бэке всегда заворачивает ValidationError как
// {error: 'Validation failed', details: {...}} — реальное человеко-читаемое
// сообщение (см. например StudentStatusSerializer.validate, где ValueError
// заворачивается в ValidationError({'error': str(exc)})) лежит внутри
// `details` под одним из полевых ключей. Без этой распаковки пользователь
// увидит только общее «Validation failed».
export function extractErrorDetail(details: unknown): string | undefined {
  if (!details || typeof details !== 'object') return undefined;
  const d = details as Record<string, unknown>;
  for (const key of ['error', 'non_field_errors', 'status', 'frozen_from', 'frozen_until']) {
    const v = d[key];
    if (Array.isArray(v) && v.length > 0) return String(v[0]);
  }
  return undefined;
}

// Код конфликта бэкенда (apps.*.views): снятие членства ученика в группе
// заблокировано назначенными, но не проведёнными доп.уроками. Фронт показывает по
// нему блокирующую модалку, а не generic-тост.
export const MEMBERSHIP_HAS_SCHEDULED_MAKEUPS = 'membership_has_scheduled_makeups';

/** Если ошибка — именно блок «есть назначенные доп.уроки», вернуть её текст для
 *  модалки, иначе null (обрабатывать как обычную ошибку через useApiError). */
export function scheduledMakeupsBlockMessage(err: unknown): string | null {
  if (err instanceof ApiError && err.code === MEMBERSHIP_HAS_SCHEDULED_MAKEUPS) {
    return err.message || 'Нельзя снять ученика из группы: есть назначенные доп.уроки.';
  }
  return null;
}

// Методы, не требующие CSRF-токена (RFC 7231 safe methods).
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE']);

// Эндпоинт обновления access-токена. refresh-cookie шлётся браузером только сюда
// (AUTH_REFRESH_COOKIE_PATH). Сам refresh-запрос не реврайтим при 401 — иначе цикл.
const REFRESH_PATH = '/api/auth/refresh';

function getCookie(name: string): string | null {
  const match = document.cookie.match('(?:^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Возвращает csrftoken для заголовка X-CSRFToken. Если cookie ещё нет —
 * дёргает GET /api/auth/csrf (бэкенд выставит её через @ensure_csrf_cookie).
 * Self-healing: не требует отдельного bootstrap-вызова.
 *
 * In-flight промис мемоизируется: при первом рендере TanStack Query может
 * запустить несколько мутаций параллельно — все они ждут один /csrf-запрос,
 * а не плодят N одинаковых.
 */
let csrfInflight: Promise<void> | null = null;

async function ensureCsrfToken(): Promise<string | null> {
  let token = getCookie('csrftoken');
  if (!token) {
    if (!csrfInflight) {
      csrfInflight = fetch('/api/auth/csrf', { credentials: 'include' })
        .then(() => undefined)
        .finally(() => { csrfInflight = null; });
    }
    await csrfInflight;
    token = getCookie('csrftoken');
  }
  return token;
}

/**
 * Пытается обновить access-токен из refresh-cookie через POST /api/auth/refresh.
 * Возвращает true, если сервер выдал новый access (200), иначе false.
 *
 * CSRF не нужен: RefreshView объявлен с authentication_classes=[], поэтому DRF
 * не включает для него CSRF-проверку.
 *
 * In-flight промис мемоизируется так же, как в ensureCsrfToken: при истечении
 * access-токена TanStack Query упирается в пачку параллельных 401 — все они ждут
 * один refresh-запрос, а не плодят N штук.
 */
let refreshInflight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  if (!refreshInflight) {
    refreshInflight = fetch(REFRESH_PATH, { method: 'POST', credentials: 'include' })
      .then((res) => res.ok)
      .catch(() => false)
      .finally(() => { refreshInflight = null; });
  }
  return refreshInflight;
}

async function rawFetch(method: string, path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (!SAFE_METHODS.has(method.toUpperCase())) {
    const token = await ensureCsrfToken();
    if (token) headers['X-CSRFToken'] = token;
  }

  return fetch(path, {
    method,
    credentials: 'include',
    headers: Object.keys(headers).length ? headers : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res = await rawFetch(method, path, body);

  // Access-токен живёт 15 минут. При 401 один раз пробуем обновить его из
  // 7-дневной refresh-cookie и повторяем исходный запрос — пользователя не
  // выбрасывает на /login, пока жив refresh. На login отправляем только если
  // refresh тоже не удался (refresh-токен истёк / отозван).
  if (res.status === 401 && path !== REFRESH_PATH) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await rawFetch(method, path, body);
    }
  }

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const json = text ? JSON.parse(text) : null;
  if (!res.ok) {
    if (res.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('admin:auth-expired'));
    }
    throw new ApiError(res.status, json?.error || res.statusText, json?.details, json?.code);
  }
  return json as T;
}
