import { useState } from 'react';
import { Dialog } from '../ui/Dialog';
import { Field } from '../form/Field';
import { SelectInput } from '../form/SelectInput';
import { useMembershipMutations } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../ui/Toast';

interface Props {
  membershipId: number;
  currentGroupName: string;
  targetOptions: { value: number; label: string }[];
  onClose: () => void;
}

export function TransferMembershipModal({ membershipId, currentGroupName, targetOptions, onClose }: Props) {
  const muts = useMembershipMutations();
  const showError = useApiError();
  const { toast } = useToast();
  const [toGroupId, setToGroupId] = useState<number | ''>('');

  const handleConfirm = async () => {
    if (!toGroupId) return;
    try {
      await muts.transfer.mutateAsync({ id: membershipId, to_group_id: Number(toGroupId) });
      toast('Переведён', 'ok');
      onClose();
    } catch (err) { showError(err); }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={`Перевести из «${currentGroupName}»`}
      footer={(
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>Отмена</button>
          <button
            type="button"
            className="btn-primary"
            disabled={!toGroupId || muts.transfer.isPending}
            onClick={() => { void handleConfirm(); }}
          >Перевести</button>
        </>
      )}
    >
      <p className="transfer-modal__text">
        Ученик перейдёт в выбранную группу того же направления. Уроки, отработанные
        в «{currentGroupName}», останутся в истории — новая группа стартует с 0,
        но на карточке будет видно, откуда пришёл ученик.
      </p>
      <Field label="Новая группа" required>
        <SelectInput
          value={toGroupId === '' ? '' : String(toGroupId)}
          onChange={(e) => setToGroupId(e.target.value === '' ? '' : Number(e.target.value))}
          options={targetOptions}
          placeholder="Выберите группу…"
        />
      </Field>
    </Dialog>
  );
}
