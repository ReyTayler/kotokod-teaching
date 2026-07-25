import type { Student, StudentStage } from '../lib/types';
import { fmtMonth } from '../lib/format';

// Тон — по виду стадии, а не по её color из БД: цвет стадии принадлежит
// колонкам доски, а в таблицах и героях цвет несёт семантику из токенов.
// frozen выделен отдельно: это не «плохо» и не «хорошо», а пауза, поэтому
// нейтральный серый тон (существующий .status-badge--muted).
function toneOf(stage: StudentStage): 'positive' | 'negative' | 'info' | 'muted' {
  if (stage.key === 'frozen') return 'muted';
  if (stage.kind === 'won') return 'positive';
  if (stage.kind === 'lost') return 'negative';
  return 'info';
}

type StageLike = Pick<Student, 'stage' | 'stage_is_open' | 'stage_frozen_until_month'>;

/**
 * «Статус» ученика = стадия его последней сделки продления (спека 2026-07-25).
 * Закрытая сделка (won/lost) — тот же бейдж, но приглушённый: ушедший ученик
 * остаётся визуально ушедшим, при этом не спорит по весу с активными.
 */
export function StageBadge({ row }: { row: StageLike }) {
  const { stage } = row;
  if (!stage) return <>—</>;

  const tone = toneOf(stage);
  // «Заморожен · до сентября 2026»: день в frozen_until_month всегда 1-е и
  // смысла не несёт, поэтому месяц без дня (fmtMonth).
  const label = row.stage_frozen_until_month
    ? `${stage.label} · до ${fmtMonth(row.stage_frozen_until_month)}`
    : stage.label;

  return (
    <span
      className={`status-badge status-badge--${tone}${row.stage_is_open ? '' : ' status-badge--dim'}`}
      title={row.stage_is_open ? undefined : 'Сделка закрыта'}
    >
      {label}
    </span>
  );
}
