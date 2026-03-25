import { useAppStore } from '../store';
import { formatPrice } from '../utils/formatPrice';

export function OrderConfirmation() {
  const confirmed = useAppStore((s) => s.order.confirmed);
  const orderNumber = useAppStore((s) => s.order.orderNumber);
  const items = useAppStore((s) => s.order.items);
  const total = useAppStore((s) => s.order.total);

  if (!confirmed) return null;

  return (
    <section aria-label="Order confirmation" className="order-confirmation" style={{ padding: '16px', textAlign: 'center' }}>
      <h2>Thank you for your order!</h2>
      <p style={{ fontSize: '1.2em', fontWeight: 'bold' }}>Order #{orderNumber}</p>
      <ul style={{ listStyle: 'none', padding: 0, margin: '16px 0', textAlign: 'left' }}>
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
            <span>{formatPrice(item.unitPrice * item.quantity)}</span>
          </li>
        ))}
      </ul>
      <div style={{ fontWeight: 'bold', fontSize: '1.2em' }}>
        Total: {formatPrice(total)}
      </div>
    </section>
  );
}
