import type { StageKind } from '../../lib/renewals';

// Единый маппинг тона бейджа по kind стадии — используется в списке, канбане и drawer'е.
const STAGE_TONE: Record<StageKind, 'info' | 'muted' | 'positive' | 'negative'> = {
  progress: 'info',
  decision: 'muted',
  won: 'positive',
  lost: 'negative',
};

export function StageBadge({ label, kind }: { label: string; kind: StageKind }) {
  const tone = STAGE_TONE[kind] ?? 'muted';
  return <span className={`status-badge status-badge--${tone}`}>{label}</span>;
}
