// journal_django/frontend/admin-src/src/pages/notifications/NotificationToggleBar.tsx
import { useState } from 'react';
import { Checkbox } from '../../components/form/Checkbox';
import { Dialog } from '../../components/ui/Dialog';
import { useApiError } from '../../hooks/useApiError';
import { fmtDateTime } from '../../lib/format';
import { useNotificationToggle, useSetNotificationToggle } from '../../hooks/useNotifications';

/**
 * Общешкольный выключатель рассылки. Рисуется над вкладками раздела и виден
 * на обеих — это состояние не «Журнала» и не «Расписания», а всей отправки
 * целиком (каникулы, инцидент, разъехавшиеся данные).
 *
 * Семантика выключения — полная тишина: пока выключено, сообщения не
 * создаются вовсе (ни точечные, ни дайджесты), уже стоящие в очереди не
 * отправляются, а при включении обратно ничего не досылается задним числом —
 * о событиях за время паузы преподаватели просто не узнают. Поэтому включение
 * происходит сразу, а выключение требует подтверждения: случайный клик
 * заставит замолчать сотню людей.
 */
export function NotificationToggleBar() {
  const { data } = useNotificationToggle();
  const setToggle = useSetNotificationToggle();
  const showError = useApiError();
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Пока состояние не загрузилось — не показываем ни чекбокс, ни плашку:
  // мигание «выключено → включено» на каждом заходе в раздел хуже, чем пауза.
  if (!data) return null;

  const apply = (value: boolean) => {
    setToggle.mutate(value, { onError: (err) => showError(err) });
  };

  return (
    <div className="notif-toggle">
      <div className="notif-toggle__row">
        <Checkbox
          label={data.is_enabled ? 'Рассылка включена' : 'Рассылка выключена'}
          checked={data.is_enabled}
          disabled={setToggle.isPending}
          onChange={(e) => {
            if (e.target.checked) {
              apply(true);
            } else {
              // Выключение — с подтверждением; сам чекбокс не переключаем,
              // пока не подтвердят (иначе он мигнёт и вернётся обратно).
              setConfirmOpen(true);
            }
          }}
        />
        {data.updated_by && (
          <span className="notif-toggle__meta">
            изменил(а) {data.updated_by} · {fmtDateTime(data.updated_at)}
          </span>
        )}
      </div>

      {!data.is_enabled && (
        <div className="notif-toggle__banner" role="alert">
          Рассылка выключена: уведомления преподавателям не создаются и не отправляются —
          ни точечные, ни дайджесты расписания и незаполненных отчётов. О событиях за время
          паузы преподаватели не узнают: при включении обратно накопившееся задним числом
          разослано не будет.
        </div>
      )}

      {confirmOpen && (
        <Dialog
          open
          onOpenChange={(o) => { if (!o) setConfirmOpen(false); }}
          title="Выключить рассылку?"
          footer={
            <>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setConfirmOpen(false)}
                disabled={setToggle.isPending}
              >
                Отмена
              </button>
              <button
                type="button"
                className="btn-danger"
                disabled={setToggle.isPending}
                onClick={() => {
                  apply(false);
                  setConfirmOpen(false);
                }}
              >
                {setToggle.isPending ? 'Выключаем…' : 'Выключить'}
              </button>
            </>
          }
        >
          <p>
            Уведомления преподавателям перестанут создаваться — ни точечные сообщения об
            изменениях, ни дайджесты расписания и незаполненных отчётов. Сообщения, которые
            должны были уйти за время паузы, разосланы не будут — ни сейчас, ни задним числом
            после включения обратно.
          </p>
        </Dialog>
      )}
    </div>
  );
}
