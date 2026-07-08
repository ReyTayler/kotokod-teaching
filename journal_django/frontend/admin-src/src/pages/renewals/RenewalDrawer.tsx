// Заглушка Фазы 5.3 — drawer с деталями сделки (useRenewalDeal/useRenewalActivity,
// комментарии, PaymentModalProvider для привязки оплаты) строится в следующей фазе.
export function RenewalDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  return (
    <div className="renewals-drawer-placeholder" role="dialog" aria-modal="true">
      <div className="renewals-drawer-placeholder__body">
        <p>Карточка сделки #{id} скоро появится</p>
        <button type="button" className="btn-secondary" onClick={onClose}>Закрыть</button>
      </div>
    </div>
  );
}
