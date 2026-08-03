import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Paginated } from '../lib/types';

// ─── Типы раздела «Уведомления» ───────────────────────────────────────────────
// Форма строк — из apps/notifications/serializers.py и views.NotificationScheduleView.

export interface NotificationRow {
  id: number;
  kind: string;
  channel: string;
  chat_id: number;
  /** null для сообщений в общий чат — у них нет персонального адресата. */
  teacher_name: string | null;
  text: string;
  status: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
  source_kind: string | null;
  source_id: number | null;
}

export interface NotificationScheduleJob {
  key: string;
  title: string;
  schedule: string;
  /** null у служебной задачи «Отправка очереди» — она не имеет своего типа сообщений. */
  kind: string | null;
  last_run_at: string | null;
}

export interface NotificationSchedule {
  jobs: NotificationScheduleJob[];
  counts: Record<string, number>;
}

export interface NotificationsQuery {
  page: number;
  pageSize?: number;
  kind?: string;
  channel?: string;
  status?: string;
}

/**
 * Лента доставки. Фильтры — плоские query-параметры (бэкенд читает
 * `kind`/`channel`/`status` напрямую из query_params, без обёртки `filter[...]`,
 * которую использует журнал изменений).
 */
export function useNotifications({ page, pageSize = 50, kind, channel, status }: NotificationsQuery) {
  const params = new URLSearchParams();
  params.set('page', String(page));
  params.set('page_size', String(pageSize));
  if (kind) params.set('kind', kind);
  if (channel) params.set('channel', channel);
  if (status) params.set('status', status);
  const query = params.toString();

  return useQuery({
    queryKey: ['notifications', query],
    queryFn: () => api<Paginated<NotificationRow>>('GET', `/api/admin/notifications?${query}`),
    // Без keepPreviousData таблица мигает пустотой на каждой смене страницы/фильтра.
    placeholderData: keepPreviousData,
  });
}

export function useNotificationSchedule() {
  return useQuery({
    queryKey: ['notifications', 'schedule'],
    queryFn: () => api<NotificationSchedule>('GET', '/api/admin/notifications/schedule'),
  });
}

// ─── Telegram-аккаунты и привязка к преподавателю ─────────────────────────────

export type TelegramAccount = {
  chat_id: number;
  username: string | null;
  full_name: string;
  /** ФИО преподавателя, если аккаунт уже привязан; иначе null. */
  bound_to: string | null;
};

export function useTelegramAccounts() {
  return useQuery({
    queryKey: ['telegram-users'],
    queryFn: () => api<{ rows: TelegramAccount[]; total: number }>('GET', '/api/admin/telegram-users'),
  });
}

/**
 * Привязка/отвязка Telegram-аккаунта преподавателю.
 *
 * Инвалидируем и `teachers` (поле `telegram` в карточке и списке), и
 * `telegram-users` (пометка «уже привязан» у аккаунтов): после привязки оба
 * ответа устарели.
 */
export function useTeacherTelegramMutations(teacherId: number) {
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['teachers'] });
    void qc.invalidateQueries({ queryKey: ['telegram-users'] });
  };
  return {
    link: useMutation({
      mutationFn: (chatId: number) =>
        api<unknown>('POST', `/api/admin/teachers/${teacherId}/telegram`, { chat_id: chatId }),
      onSuccess: invalidate,
    }),
    unlink: useMutation({
      mutationFn: () => api<void>('DELETE', `/api/admin/teachers/${teacherId}/telegram`),
      onSuccess: invalidate,
    }),
  };
}
