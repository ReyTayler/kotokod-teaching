import { useEffect, useState } from 'react';
import { Dialog } from '../../components/ui/Dialog';
import { DateInput } from '../../components/form/DateInput';
import { NumberInput } from '../../components/form/NumberInput';
import { Checkbox } from '../../components/form/Checkbox';
import { SelectInput } from '../../components/form/SelectInput';
import { useToast } from '../../components/ui/Toast';
import { fmtRub, todayMSK } from '../../lib/format';
import type { PenaltyMode } from '../../lib/types';
import { DEFAULT_GROUP_RATES, previewGroupRates, useGroupRateMutations, type GroupRatePayload,
  type GroupRatePreview, type GroupRateVersion } from '../../hooks/useGroupMotivation';
import { norm, parseServerErrors, penaltyText, savedMessage, type ServerErrors } from './motivationFormat';

export const GROUP_MONEY_FIELDS = [
  ['small_full_rate', 'Малая группа: пришли все, ₽ за занятие', '500'],
  ['small_partial_rate', 'Малая группа: пришла часть, ₽ за занятие', '300'],
  ['per_student_rate', 'Большая группа, ₽ за присутствующего', '200'],
  ['half_lesson_rate', 'Урок 45 минут, ₽ за присутствующего', '250'],
  ['makeup_rate', 'Отработка, ₽ за присутствующего', '200'],
  ['burned_rate', 'Сгорание пропуска, ₽ за списание', '200'],
] as const;
type MoneyKey = typeof GROUP_MONEY_FIELDS[number][0];

export function GroupRateDialog({ base, editing, onClose }: {
  base: GroupRateVersion | null; editing: boolean; onClose: () => void;
}) {
  const { save } = useGroupRateMutations();
  const { toast } = useToast();
  const [body, setBody] = useState<GroupRatePayload>(() => ({ ...DEFAULT_GROUP_RATES, ...base,
    effective_from: editing && base ? base.effective_from : todayMSK(),
  }));
  const [errors, setErrors] = useState<ServerErrors>({ fields: {}, directions: {}, general: '' });
  const [preview, setPreview] = useState<GroupRatePreview | null>(null);
  const [previewError, setPreviewError] = useState('');
  const [previewFields, setPreviewFields] = useState<Record<string, string>>({});
  const [previewPending, setPreviewPending] = useState(true);
  // Текст поля границы хранится отдельно: в числовом body пустое поле стало бы 0,
  // и подпись «от 1 учеников» мелькала бы до ответа валидации сервера.
  const [limitText, setLimitText] = useState(() => String(body.small_group_limit || ''));
  const original = base ?? DEFAULT_GROUP_RATES;
  const change = <K extends keyof GroupRatePayload>(key: K, value: GroupRatePayload[K]) => {
    setBody((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => ({ ...prev, fields: { ...prev.fields, [key]: '' } }));
  };
  // Серверный предпросмотр использует тот же расчёт, что и начисления.
  useEffect(() => {
    let active = true;
    setPreviewPending(true);
    setPreview(null);
    setPreviewError('');
    setPreviewFields({});
    const timer = window.setTimeout(() => {
      // base содержит служебные поля версии, отправляем только контракт записи.
      previewGroupRates(payload(body)).then((data) => {
        if (active) { setPreview(data); setPreviewPending(false); }
      }).catch((err: unknown) => {
        if (active) {
          const parsed = parseServerErrors(err, Object.keys(payload(body)));
          setPreviewFields(parsed.fields);
          setPreviewError(parsed.general || 'Проверьте выделенные поля, чтобы увидеть расчёт.');
          setPreviewPending(false);
        }
      });
    }, 350);
    return () => { active = false; window.clearTimeout(timer); };
  }, [body]);
  const submit = () => {
    if (save.isPending || previewPending || !preview) return;
    save.mutate({ id: editing ? base?.id : undefined, body: payload(body) }, {
      onSuccess: (data) => { toast(savedMessage(data.recalculated), 'ok'); onClose(); },
      onError: (err) => setErrors(parseServerErrors(err, Object.keys(payload(body)))),
    });
  };
  const error = (key: keyof GroupRatePayload) => errors.fields[key] || previewFields[key];
  const money = (key: MoneyKey, label: string, unit: string) => {
    const aria = GROUP_MONEY_FIELDS.find(([field]) => field === key)![1];
    return <div className="motivation-rate-field" key={key}>
      <div><label htmlFor={`group-${key}`}>{label}</label><span>{unit}</span></div>
      <div><div className={`motivation-money${error(key) ? ' has-error' : ''}`}>
        <NumberInput id={`group-${key}`} min={0} step="0.01" required aria-label={aria}
          aria-invalid={!!error(key)} aria-describedby={error(key) ? `error-${key}` : undefined}
          value={body[key]} onChange={(e) => change(key, norm(e.target.value))} /><span>₽</span>
      </div>{error(key) && <p className="field-error" id={`error-${key}`} role="alert">{error(key)}</p>}</div>
    </div>;
  };
  const changes: { key: string; label: string; before: string; after: string }[] = GROUP_MONEY_FIELDS.filter(([key]) => Number(body[key]) !== Number(original[key]))
    .map(([key, label]) => ({ key, label: label.split(', ₽')[0], before: fmtRub(original[key]), after: fmtRub(body[key]) }));
  if (body.small_group_limit > 0 && body.small_group_limit !== original.small_group_limit) changes.unshift({
    key: 'small_group_limit', label: 'Малая группа', before: `до ${original.small_group_limit} чел.`, after: `до ${body.small_group_limit} чел.`,
  });
  if (penaltyText(body) !== penaltyText(original)) changes.push({
    key: 'penalty', label: 'Поздний отчёт', before: penaltyText(original), after: penaltyText(body),
  });

  return <Dialog open wide className="motivation-editor"
    title={editing ? 'Исправить групповые ставки' : 'Групповые ставки с даты'}
    onOpenChange={(open) => !open && !save.isPending && onClose()}
    footer={<div className="motivation-editor__footer">
      <span>Начисления до выбранной даты сохранят прежние условия</span>
      <div className="settings-actions">
        <button type="button" className="btn-cancel" disabled={save.isPending} onClick={onClose}>Отмена</button>
        <button type="submit" form="group-rate-form" className="btn-save" disabled={save.isPending || previewPending || !preview}>
          {save.isPending ? 'Сохраняем…' : 'Сохранить'}
        </button>
      </div>
    </div>}>
    <form id="group-rate-form" onSubmit={(event) => { event.preventDefault(); submit(); }} className="motivation-editor__layout">
      <fieldset className="motivation-editor__fields" disabled={save.isPending}>
        {errors.general && <div role="alert" className="motivation-form-error">{errors.general}</div>}
        <section className="motivation-form-section" aria-labelledby="group-period-heading">
          <h3 id="group-period-heading">Период действия</h3>
          <div className="motivation-period-field">
            <div className="motivation-field"><label htmlFor="group-effective">Действует с</label>
              <DateInput id="group-effective" aria-label="Действует с" min={todayMSK()} required value={body.effective_from}
                onChange={(e) => change('effective_from', e.target.value)} />
              {error('effective_from') && <p role="alert" className="field-error">{error('effective_from')}</p>}
            </div>
            <p>Для всех групповых занятий начиная с этой даты. Дата сдачи отчёта на выбор ставки не влияет.</p>
          </div>
        </section>
        <section className="motivation-form-section" aria-labelledby="group-payment-heading">
          <h3 id="group-payment-heading">Оплата занятий</h3>
          <div className="motivation-limit-field">
            <label htmlFor="group-limit">Малая группа — до</label>
            <NumberInput id="group-limit" aria-label="Граница малой группы" min={1} max={32767} step={1} required
              value={limitText} onChange={(e) => { setLimitText(e.target.value); change('small_group_limit', Number(e.target.value)); }} />
            <span>учеников включительно</span>
          </div>
          {error('small_group_limit') && <p className="field-error" role="alert">{error('small_group_limit')}</p>}
          {money('small_full_rate', 'Пришли все ученики малой группы', 'За занятие')}
          {money('small_partial_rate', 'Пришла часть малой группы', 'За занятие · есть хотя бы один присутствующий')}
          {money('per_student_rate', body.small_group_limit > 0 ? `Большая группа · от ${body.small_group_limit + 1} учеников` : 'Большая группа', 'За каждого присутствующего')}
          {money('half_lesson_rate', 'Занятие 45 минут', 'За присутствующего · любой размер группы')}
          <p className="motivation-inline-note">Никто не пришёл — 0 ₽. Ставка за 45 минут применяется вместо обычной ставки.</p>
        </section>
        <section className="motivation-form-section" aria-labelledby="group-other-heading">
          <h3 id="group-other-heading">Отработки и списания</h3>
          {money('makeup_rate', 'Отработка пропуска', 'За каждого присутствующего')}
          {money('burned_rate', 'Сгорание пропуска', 'За одно списание')}
        </section>
        <section className="motivation-form-section" aria-labelledby="group-penalty-heading">
          <h3 id="group-penalty-heading">Поздний отчёт</h3>
          <Checkbox label="Штрафовать за отчёт позже дня занятия" checked={body.penalty_enabled}
            onChange={(e) => change('penalty_enabled', e.target.checked)} />
          {body.penalty_enabled && <div className="motivation-penalty-fields">
            <div className="motivation-field"><label htmlFor="group-penalty">Сумма, ₽</label>
              <NumberInput id="group-penalty" aria-label="Сумма штрафа, ₽" min={0} step="0.01" required value={body.penalty_amount}
                onChange={(e) => change('penalty_amount', norm(e.target.value))} />
              {error('penalty_amount') && <p className="field-error" role="alert">{error('penalty_amount')}</p>}
            </div>
            <div className="motivation-field"><label>Начислять</label>
              <SelectInput aria-label="Как начислять штраф" value={body.penalty_mode} options={[
                { value: 'per_student', label: 'За присутствующего ученика' }, { value: 'per_lesson', label: 'За занятие' },
              ]} onChange={(e) => change('penalty_mode', e.target.value as PenaltyMode)} />
              {error('penalty_mode') && <p className="field-error" role="alert">{error('penalty_mode')}</p>}
            </div>
          </div>}
          <p className="motivation-inline-note">Только отчёты преподавателя. Административные записи и сгорания не штрафуются.</p>
        </section>
        <details className="motivation-help"><summary>Особенности расчёта</summary>
          <p>Неоплачиваемые пропуски исключаются из состава, бесплатные посещения учитываются.
            Доп.урок сверх курса считается по обычной схеме с составом 1. Групповые отмены не оплачиваются.</p>
        </details>
      </fieldset>
      <aside className="motivation-preview" aria-label="Проверка новых условий">
        <div className="motivation-preview__head"><h3>Проверка расчёта</h3><p>Примеры обычных занятий по новым ставкам</p></div>
        <div aria-live="polite" aria-busy={previewPending} className="motivation-preview__results">
          {previewPending ? <p className="motivation-meta">Обновляем расчёт…</p> : previewError ?
            <p className="field-error">{previewError}</p> : preview?.results.map((row, i) =>
              <div className="motivation-example" key={i}>
                <div><strong>{row.minutes} минут</strong><span>Пришли {row.present} из {row.total}</span></div>
                <strong>{fmtRub(row.payment)}</strong>
              </div>)}
        </div>
        <p className="motivation-preview__note">Отчёт вовремя, без штрафа. Ручные суммы сохраняются при пересчёте.</p>
        <div className="motivation-changes"><h3>Что изменится</h3>
          {changes.length ? <ul>{changes.map((item) => <li key={item.key}><span>{item.label}</span>
            <div><del>{item.before}</del><span aria-hidden="true"> → </span><strong>{item.after}</strong></div>
          </li>)}</ul> : <p>Суммы совпадают с {base ? 'выбранной версией' : 'базовыми правилами'}. Сохранение создаст условия с указанной даты.</p>}
        </div>
      </aside>
    </form>
  </Dialog>;
}

// Версия содержит служебные поля. API принимает только параметры расчёта и дату.
function payload(body: GroupRatePayload): GroupRatePayload {
  return Object.fromEntries(['effective_from', ...Object.keys(DEFAULT_GROUP_RATES)]
    .map((key) => [key, body[key as keyof GroupRatePayload]])) as unknown as GroupRatePayload;
}
