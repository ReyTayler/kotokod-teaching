import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../../lib/api';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../../components/ui/Toast';
import { Checkbox } from '../../components/form/Checkbox';
import { TextInput } from '../../components/form/TextInput';
import { DateInput } from '../../components/form/DateInput';

interface Props {
  studentId: number;
  initial: {
    consent_given: boolean;
    consent_at: string | null;
    consent_by: string | null;
    consent_note: string | null;
  };
}

export function ConsentBlock({ studentId, initial }: Props) {
  const qc = useQueryClient();
  const showError = useApiError();
  const { toast } = useToast();

  const [given, setGiven] = useState(initial.consent_given);
  const [at, setAt] = useState(initial.consent_at ?? '');
  const [by, setBy] = useState(initial.consent_by ?? '');
  const [note, setNote] = useState(initial.consent_note ?? '');
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await api('PATCH', `/api/admin/students/${studentId}`, {
        consent_given: given,
        consent_at: at || null,
        consent_by: by || null,
        consent_note: note || null,
      });
      qc.invalidateQueries({ queryKey: ['students'] });
      toast('Согласие сохранено', 'ok');
    } catch (err) {
      showError(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="balance-block consent-block">
      <div className="balance-block__head">
        <h3>Согласие на обработку ПДн</h3>
      </div>

      <div className="consent-block__fields">
        <div className="consent-block__row">
          <Checkbox
            checked={given}
            onChange={(e) => setGiven(e.target.checked)}
            label="Согласие получено (152-ФЗ)"
          />
        </div>

        <div className="consent-block__row">
          <label className="consent-block__label" htmlFor={`consent-at-${studentId}`}>
            Дата согласия
          </label>
          <DateInput
            id={`consent-at-${studentId}`}
            value={at}
            onChange={(e) => setAt(e.target.value)}
            placeholder="дд.мм.гггг"
          />
        </div>

        <div className="consent-block__row">
          <label className="consent-block__label" htmlFor={`consent-by-${studentId}`}>
            Кто дал (родитель / представитель)
          </label>
          <TextInput
            id={`consent-by-${studentId}`}
            value={by}
            onChange={(e) => setBy(e.target.value)}
            placeholder="ФИО родителя или представителя"
            className="consent-block__input"
          />
        </div>

        <div className="consent-block__row">
          <label className="consent-block__label" htmlFor={`consent-note-${studentId}`}>
            Основание / примечание
          </label>
          <TextInput
            id={`consent-note-${studentId}`}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Номер бланка, форма согласия и т. д."
            className="consent-block__input"
          />
        </div>
      </div>

      <div className="consent-block__footer">
        <button
          type="button"
          className="btn-save"
          onClick={() => { void save(); }}
          disabled={saving}
        >
          {saving ? 'Сохранение…' : 'Сохранить'}
        </button>
      </div>
    </section>
  );
}
