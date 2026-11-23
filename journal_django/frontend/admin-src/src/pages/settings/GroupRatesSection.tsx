import { useState } from 'react';
import { DEFAULT_GROUP_RATES, useGroupRates, useGroupRateMutations,
  type GroupRatePayload, type GroupRateVersion } from '../../hooks/useGroupMotivation';
import { ConfirmModal } from '../../components/ui/ConfirmModal';
import { BlockLoading } from '../../components/ui/Skeleton';
import { EmptyState } from '../../components/ui/EmptyState';
import { HelpPopover } from '../../components/ui/HelpPopover';
import { useToast } from '../../components/ui/Toast';
import { useApiError } from '../../hooks/useApiError';
import { fmtDate, fmtDateTime, fmtRub, todayMSK } from '../../lib/format';
import { penaltyText, savedMessage } from './motivationFormat';
import { GroupRateDialog } from './GroupRateDialog';

function Rules({ rates }: { rates: Omit<GroupRatePayload, 'effective_from'> }) {
  const rows = [
    ['Малая группа · пришли все', `Состав до ${rates.small_group_limit} чел. включительно`, rates.small_full_rate, 'за занятие'],
    ['Малая группа · пришла часть', 'Есть хотя бы один присутствующий', rates.small_partial_rate, 'за занятие'],
    ['Большая группа', `Состав от ${rates.small_group_limit + 1} чел.`, rates.per_student_rate, 'за присутствующего'],
    ['Занятие 45 минут', 'Любой размер группы · вместо обычной ставки', rates.half_lesson_rate, 'за присутствующего'],
  ];
  return <div className="motivation-rules" role="list" aria-label="Правила оплаты занятий">
    {rows.map(([name, condition, amount, unit]) => <div className="motivation-rule" role="listitem" key={name}>
      <div><strong>{name}</strong><span>{condition}</span></div>
      <div className="motivation-rule__amount"><strong>{fmtRub(amount)}</strong><span>{unit}</span></div>
    </div>)}
  </div>;
}

export function GroupRatesSection() {
  const query = useGroupRates();
  const { remove } = useGroupRateMutations();
  const { toast } = useToast();
  const apiError = useApiError();
  const [dialog, setDialog] = useState<{ base: GroupRateVersion | null; editing: boolean } | null>(null);
  const [deleting, setDeleting] = useState<GroupRateVersion | null>(null);
  if (query.isLoading) return <BlockLoading rows={4} />;
  if (query.isError || !query.data) return <EmptyState action={
    <button type="button" className="btn-secondary" onClick={() => query.refetch()}>Повторить</button>
  }>Не удалось загрузить групповые ставки</EmptyState>;
  const versions = query.data.results;
  const current = versions.find((v) => v.is_current) ?? null;
  const rates = current ?? DEFAULT_GROUP_RATES;
  const future = versions.filter((v) => v.effective_from > todayMSK());
  const next = future.length ? future[future.length - 1] : null;
  return <section className="motivation-section" aria-labelledby="group-rates-title">
    <div className="motivation-section__head">
      <div><h2 id="group-rates-title">Групповые занятия</h2>
        <p>Общие условия для всех преподавателей групповых занятий</p></div>
      <button type="button" className="btn-primary" onClick={() => setDialog({ base: current, editing: false })}>
        {current ? 'Изменить с даты…' : 'Настроить ставки'}
      </button>
    </div>
    {next && <div className="motivation-notice" role="status">
      Следующее изменение — с {fmtDate(next.effective_from)}
      <button type="button" className="motivation-text-button" onClick={() => setDialog({ base: next, editing: true })}>Открыть версию</button>
    </div>}
    <div className="motivation-panel">
      <div className="motivation-panel__head">
        <h3>Действующие условия</h3>
        <span className={`motivation-status${current ? ' motivation-status--active' : ''}`}>
          {current ? `Действует с ${fmtDate(current.effective_from)}` : 'Базовые правила'}
        </span>
      </div>
      {!current && <p className="motivation-panel__note">Пока версия ставок не задана, занятия оплачиваются по базовым правилам ниже.</p>}
      <Rules rates={rates} />
      <div className="motivation-panel__foot">Никто не пришёл — 0 ₽. <HelpPopover label="Как определяется размер группы">
        Состав берётся из посещаемости конкретного занятия. Неоплачиваемые пропуски исключаются,
        бесплатное присутствие учитывается. Ставка за 45 минут имеет приоритет перед размером группы.
      </HelpPopover></div>
    </div>
    <div className="motivation-secondary">
      <div className="motivation-panel">
        <div className="motivation-panel__head"><h3>Отработки и списания</h3></div>
        <dl className="motivation-definition">
          <div><dt>Отработка пропуска</dt><dd>{fmtRub(rates.makeup_rate)}<span>за присутствующего</span></dd></div>
          <div><dt>Сгорание пропуска</dt><dd>{fmtRub(rates.burned_rate)}<span>за списание</span></dd></div>
        </dl>
        <div className="motivation-panel__foot">Доп.урок сверх курса — по обычной схеме с составом 1.</div>
      </div>
      <div className="motivation-panel">
        <div className="motivation-panel__head"><h3>Поздний отчёт</h3>
          <span className="motivation-status">{rates.penalty_enabled ? 'Штраф включён' : 'Без штрафа'}</span></div>
        <div className="motivation-penalty-summary">
          <strong>{rates.penalty_enabled ? fmtRub(rates.penalty_amount) : '0 ₽'}</strong>
          <span>{rates.penalty_enabled ? (rates.penalty_mode === 'per_student' ? 'за присутствующего ученика' : 'за занятие') : 'За позднюю сдачу отчёта'}</span>
          <p>Только отчёт преподавателя позже дня занятия. Записи администратора и сгорания не штрафуются.</p>
        </div>
      </div>
    </div>
    <details className="motivation-history">
      <summary><span>История и будущие изменения</span><span>{versions.length} верс.</span></summary>
      <div className="motivation-history__body">
        {!versions.length && <p>Версий пока нет. Первая сохранённая настройка появится здесь.</p>}
        {versions.map((v) => <details className="motivation-history__entry" key={v.id}>
          <summary><span>С {fmtDate(v.effective_from)}</span><span className="motivation-status">
            {v.is_current ? 'Действует' : v.effective_from > todayMSK() ? 'Запланирована' : 'Архив'}</span></summary>
          <div className="motivation-history__content">
            <Rules rates={v} />
            <p>Отработка: {fmtRub(v.makeup_rate)} за присутствующего · Сгорание: {fmtRub(v.burned_rate)} за списание</p>
            <p>Штраф: {penaltyText(v)}</p>
            <p className="motivation-meta">{v.created_by_name || 'Автор не указан'} · {fmtDateTime(v.created_at)}</p>
            <div className="motivation-history__actions">
              <button type="button" className="btn-secondary" onClick={() => setDialog({ base: v, editing: false })}>Создать на основе этой версии</button>
              {v.editable ? <>
                <button type="button" className="btn-secondary" onClick={() => setDialog({ base: v, editing: true })}>Исправить версию</button>
                <button type="button" className="motivation-text-button motivation-text-button--danger" onClick={() => setDeleting(v)}>Удалить версию</button>
              </> : <span className="motivation-meta">Прошлую версию можно только просмотреть</span>}
            </div>
          </div>
        </details>)}
      </div>
    </details>
    <p className="motivation-meta">Новые условия действуют с выбранной даты. Групповые отмены не оплачиваются.</p>
    {dialog && <GroupRateDialog {...dialog} onClose={() => setDialog(null)} />}
    {deleting && <ConfirmModal title="Удалить групповую версию?"
      message={`Версия с ${fmtDate(deleting.effective_from)} будет удалена. Её период пересчитается по предыдущей версии, а без неё — по прежним правилам.`}
      confirmLabel="Удалить" danger isPending={remove.isPending} onClose={() => !remove.isPending && setDeleting(null)}
      onConfirm={() => remove.mutate(deleting.id, {
        onSuccess: (res) => { toast(savedMessage(res.recalculated), 'ok'); setDeleting(null); },
        onError: (err) => apiError(err),
      })} />}
  </section>;
}
