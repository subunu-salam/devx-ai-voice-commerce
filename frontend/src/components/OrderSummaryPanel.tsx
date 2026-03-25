import { useAppStore } from '../store';
import { formatPrice } from '../utils/formatPrice';

export function OrderSummaryPanel() {
  const items = useAppStore((s) => s.order.items);
  const total = useAppStore((s) => s.order.total);

  return (
    <section aria-label="Order summary" className="order-summary-panel" style={{ padding: '16px' }}>
      <h2>Your Order</h2>
      {items.length === 0 ? (
        <p>No items yet</p>
      ) : (
        <>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {items.map((item) => (
              <li
                key={item.itemId}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '8px 0',
                  borderBottom: '1px solid #eee',
                }}
              >
                <span>
                  {item.name} × {item.quantity}
                </span>
                <span style={{ display: 'flex', gap: '12px' }}>
                  <span>{formatPrice(item.unitPrice)} ea</span>
                  <span style={{ fontWeight: 'bold' }}>
                    {formatPrice(item.unitPrice * item.quantity)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginTop: '12px',
              fontWeight: 'bold',
              fontSize: '1.1em',
            }}
          >
            <span>Total</span>
            <span>{formatPrice(total)}</span>
          </div>
        </>
      )}
    </section>
  );
}
