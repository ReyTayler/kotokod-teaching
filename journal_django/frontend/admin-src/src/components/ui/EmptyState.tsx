import { type ReactNode } from 'react';

export function EmptyState({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
  return (
    <div className="memberships__empty" style={{ padding: 40 }}>
      {icon}
      {children}
    </div>
  );
}
