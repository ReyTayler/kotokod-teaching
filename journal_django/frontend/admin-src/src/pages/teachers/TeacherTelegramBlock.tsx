import { useState } from 'react';
import { Combobox } from '../../components/form/Combobox';
import { Field } from '../../components/form/Field';
import { useToast } from '../../components/ui/Toast';
import { useApiError } from '../../hooks/useApiError';
import { useAuth } from '../../hooks/useAuth';
import { useTeacherTelegramMutations, useTelegramAccounts } from '../../hooks/useNotifications';
import { canWriteTeacherTelegram, type Role } from '../../lib/permissions';
import type { Teacher } from '../../lib/types';

/** Подпись аккаунта в списке: «Имя (@ник)», занятые — с пометкой владельца. */
function optionLabel(fullName: string, username: string | null, boundTo: string | null): string {
  const base = username ? `${fullName} (@${username})` : fullName;
  return boundTo ? `${base} — уже привязан: ${boundTo}` : base;
}

/** Текущее состояние привязки словами — то, ради чего человек сюда смотрит. */
function TelegramStatus({ telegram }: { telegram: Teacher['telegram'] }) {
  if (!telegram) {
    return <div className="teacher-telegram__status">не привязан</div>;
  }
  if (!telegram.is_active) {
    return (
      <div className="teacher-telegram__status teacher-telegram__status--error">
        заблокировал бота{telegram.blocked_reason ? `: ${telegram.blocked_reason}` : ''}
      </div>
    );
  }
  return (
    <div className="teacher-telegram__status">
      привязан{telegram.username ? `, @${telegram.username}` : `, ${telegram.full_name}`}
    </div>
  );
}

/**
 * Поле «Telegram» карточки преподавателя.
 *
 * Выбор из списка аккаунтов, а не ввод ника: Bot API умеет писать только по
 * числовому chat_id, которого человек не видит, а набор руками даёт опечатки.
 * Список — те, кто уже написал боту /start (иначе привязывать нечего).
 *
 * Менеджеру блок показывается только на чтение: право на POST/DELETE у бэка
 * admin-only (ReadStaffWriteAdmin), кнопка с гарантированным 403 бесполезна.
 */
export function TeacherTelegramBlock({ teacher }: { teacher: Teacher }) {
  const { me } = useAuth();
  const canWrite = canWriteTeacherTelegram(me?.role as Role);
  const { data, isLoading } = useTelegramAccounts();
  const muts = useTeacherTelegramMutations(teacher.id);
  const { toast } = useToast();
  const showError = useApiError();

  const current = teacher.telegram?.chat_id != null ? String(teacher.telegram.chat_id) : '';
  const [selected, setSelected] = useState(current);

  const options = (data?.rows ?? []).map((a) => ({
    value: String(a.chat_id),
    // Свою же привязку не помечаем «уже привязан»: это не конфликт.
    label: optionLabel(a.full_name, a.username, a.bound_to === teacher.name ? null : a.bound_to),
  }));

  const dirty = selected !== current;
  const busy = muts.link.isPending || muts.unlink.isPending;

  const handleSave = async () => {
    try {
      await muts.link.mutateAsync(Number(selected));
      toast('Telegram привязан', 'ok');
    } catch (err) { showError(err, 'Не удалось привязать Telegram'); }
  };

  const handleUnlink = async () => {
    try {
      await muts.unlink.mutateAsync();
      setSelected('');
      toast('Telegram отвязан', 'ok');
    } catch (err) { showError(err, 'Не удалось отвязать Telegram'); }
  };

  if (!canWrite) {
    return (
      <div className="teacher-telegram">
        <div className="teacher-telegram__label-ro">Telegram</div>
        <TelegramStatus telegram={teacher.telegram} />
      </div>
    );
  }

  return (
    <div className="teacher-telegram">
      <Field label="Telegram">
        <div className="teacher-telegram__controls">
          <div className="teacher-telegram__combobox">
            <Combobox
              value={selected}
              onChange={setSelected}
              options={options}
              placeholder={isLoading ? 'Загрузка…' : 'Выберите аккаунт'}
            />
          </div>
          <button
            type="button"
            className="btn-save"
            onClick={() => { void handleSave(); }}
            disabled={busy || !selected || !dirty}
          >
            Сохранить
          </button>
          {teacher.telegram && (
            <button
              type="button"
              className="btn-cancel"
              onClick={() => { void handleUnlink(); }}
              disabled={busy}
            >
              Отвязать
            </button>
          )}
        </div>
      </Field>
      <TelegramStatus telegram={teacher.telegram} />
      {!isLoading && options.length === 0 && (
        <div className="teacher-telegram__status">
          Боту ещё никто не писал: аккаунт появится в списке после команды /start.
        </div>
      )}
    </div>
  );
}
