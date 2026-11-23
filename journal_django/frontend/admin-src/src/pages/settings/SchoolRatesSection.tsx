import { TableScrollArea } from '../../components/table/TableScrollArea';
import { HelpPopover } from '../../components/ui/HelpPopover';
import { useState } from 'react';
import { useRateVersions, useRateVersionMutations } from '../../hooks/useMotivation';
import { ConfirmModal } from '../../components/ui/ConfirmModal';
import { ActionMenu } from '../../components/ui/ActionMenu';
import { EmptyState } from '../../components/ui/EmptyState';
import { DirTag } from '../../components/ui/DirTag';
import { Pill } from '../../components/ui/Pill';
import { BlockLoading } from '../../components/ui/Skeleton';
import { useToast } from '../../components/ui/Toast';
import { useApiError } from '../../hooks/useApiError';
import { fmtDate, fmtDateTime, fmtRub, todayMSK } from '../../lib/format';
import type { RateVersion } from '../../lib/types';
import { RateVersionDialog } from './RateVersionDialog';
import { cancelText, penaltyText, savedMessage } from './motivationFormat';

type DialogState = { kind: 'create' } | { kind: 'edit'; version: RateVersion } | null;

/**
 * Ставки школы для индивидуального формата: текущая версия, кнопка «Изменить с
 * даты…», подсказка про уроки до первой версии и история версий.
 * У групповых занятий свой раздел и независимые версии.
 */
export function SchoolRatesSection() {
  const q = useRateVersions();
  const { remove } = useRateVersionMutations();
  const { toast } = useToast();
  const apiError = useApiError();
  const [dialog, setDialog] = useState<DialogState>(null);
  const [deleting, setDeleting] = useState<RateVersion | null>(null);

  if (q.isLoading) return <BlockLoading rows={4} />;
  // Упавший запрос не должен выглядеть как «ставки не заданы»: это про деньги.
  if (q.isError || !q.data) {
    return (
      <EmptyState
        hint="Это сбой загрузки, а не отсутствие ставок. Обновите страницу или попробуйте позже."
        action={<button type="button" className="btn-secondary" onClick={() => q.refetch()}>Повторить</button>}
      >
        Не удалось загрузить ставки школы
      </EmptyState>
    );
  }

  const { results, engine_lessons, directions } = q.data;
  const current = results.find((v) => v.is_current) ?? null;
  // Текущей нет, но версии есть — значит все они в будущем; ближайшая — с минимальной датой.
  const nextVersion = current ? null
    : results.reduce<RateVersion | null>(
      (m, v) => (!m || v.effective_from < m.effective_from ? v : m), null);
  // Ставки действуют только с сегодняшнего дня: прошлые начисления не меняются
  // (решение владельца), поэтому и для первой версии дата по умолчанию — сегодня.
  const defaultDate = todayMSK();

  const dirRate = (v: RateVersion, id: number) => v.directions.find((d) => d.direction_id === id);

  const confirmDelete = () => {
    if (!deleting) return;
    remove.mutate(deleting.id, {
      onSuccess: (res) => { toast(savedMessage(res.recalculated), 'ok'); setDeleting(null); },
      onError: (e) => { apiError(e); setDeleting(null); },
    });
  };

  return (
    <section className="settings-section" aria-labelledby="school-rates-title">
      <div className="settings-section__head">
        <h2 id="school-rates-title" className="settings-section__title">Индивидуальные занятия <HelpPopover>
        Ставки индивидуальных занятий. Групповые ставки настраиваются в отдельном разделе ниже.
      </HelpPopover></h2>
        <button type="button" className="btn-primary" onClick={() => setDialog({ kind: 'create' })}>
          {current ? 'Изменить с даты…' : 'Задать ставки'}
        </button>
      </div>


      {engine_lessons.lessons > 0 && (
        <div className="settings-info" role="status">
          {results.length
            ? `Индивидуальные уроки до ${fmtDate(results[results.length - 1].effective_from)} `
            : 'Пока ставки не заданы, индивидуальные уроки '}
          считаются по правилам движка — прошлое не пересчитывается
          {' '}({engine_lessons.lessons} ур.
          {engine_lessons.latest && `, последний — ${fmtDate(engine_lessons.latest)}`}).
        </div>
      )}

      {!current ? (
        <EmptyState hint="Пока ставок нет, индивидуальные занятия считаются по правилам движка.">
          {nextVersion
            ? `Текущих ставок нет, ближайшая версия действует с ${fmtDate(nextVersion.effective_from)}`
            : 'Ставки ещё не заданы'}
        </EmptyState>
      ) : (
        <div className="table-panel">
          <TableScrollArea >
            <table className="data-table settings-table">
              <thead>
                <tr><th>Направление</th><th>Индивидуальный урок</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>По умолчанию</td>
                  <td>{fmtRub(current.individual_rate)}</td>
                </tr>
                {directions.map((d) => {
                  const own = dirRate(current, d.id)?.individual_rate;
                  return (
                    <tr key={d.id}>
                      <td><DirTag name={d.name} /></td>
                      {own != null
                        ? <td>{fmtRub(own)}</td>
                        : <td className="settings-muted">как по умолчанию ({fmtRub(current.individual_rate)})</td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableScrollArea>
          <div className="settings-summary">
            <div>Отработка пропуска (индив): {fmtRub(current.makeup_rate)}</div>
            <div>Сгорание пропуска (индив): {fmtRub(current.burned_rate)}</div>
            <div>Отмена урока (индив, по причине с компенсацией): {cancelText(current)}</div>
            <div>Штраф за отчёт не в день урока (индив): {penaltyText(current)}</div>
            <div className="settings-muted">Действует с {fmtDate(current.effective_from)}</div>
          </div>
        </div>
      )}

      {results.length > 0 && (
        <details className="motivation-history">
          <summary>История и будущие изменения · {results.length} верс.</summary>
          <div className="table-panel">
            <TableScrollArea >
              <table className="data-table settings-table">
                <thead>
                  <tr>
                    <th>С даты</th><th>Индив</th><th>Отработка</th><th>Сгорание</th>
                    <th>Отмена</th><th>Штраф</th><th>Кто изменил</th><th>Когда</th><th aria-label="Действия" />
                  </tr>
                </thead>
                <tbody>
                  {results.map((v) => (
                    <tr key={v.id}>
                      <td>
                        {fmtDate(v.effective_from)} {v.is_current && <Pill>Действует</Pill>}
                      </td>
                      <td>{fmtRub(v.individual_rate)}</td>
                      <td>{fmtRub(v.makeup_rate)}</td>
                      <td>{fmtRub(v.burned_rate)}</td>
                      <td>{cancelText(v)}</td>
                      <td>{penaltyText(v)}</td>
                      <td>{v.created_by_name || '—'}</td>
                      <td>{fmtDateTime(v.created_at)}</td>
                      <td>
                        {v.editable ? (
                          <ActionMenu
                            label="Действия с версией"
                            items={[
                              { label: 'Исправить', onSelect: () => setDialog({ kind: 'edit', version: v }) },
                              { label: 'Удалить', danger: true, onSelect: () => setDeleting(v) },
                            ]}
                          />
                        ) : (
                          // Начавшуюся версию править нельзя: объясняем, а не прячем молча.
                          <HelpPopover label="Почему нельзя исправить версию">Версия уже действует — задайте новую с сегодняшнего дня.</HelpPopover>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScrollArea>
          </div>
        </details>
      )}

      {dialog && (
        <RateVersionDialog
          directions={directions}
          base={dialog.kind === 'edit' ? dialog.version : current}
          editing={dialog.kind === 'edit' ? dialog.version : null}
          defaultDate={defaultDate}
          onClose={() => setDialog(null)}
        />
      )}
      {deleting && (
        <ConfirmModal
          title="Удалить версию ставок?"
          message={`Версия «с ${fmtDate(deleting.effective_from)}» будет удалена: начисления этого периода пересчитаются по предыдущей версии, а без неё — по правилам движка.`}
          confirmLabel="Удалить"
          danger
          isPending={remove.isPending}
          onConfirm={confirmDelete}
          onClose={() => setDeleting(null)}
        />
      )}
    </section>
  );
}
