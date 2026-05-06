// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useAppStore } from '../store';
import { formatPrice } from '../utils/formatPrice';

export function OrderSummaryPanel() {
  const items = useAppStore((s) => s.agentUI.orderItems);
  const total = useAppStore((s) => s.agentUI.orderTotal);

  return (
    <section aria-label="Order summary" className="order-summary-panel" style={{ padding: '16px' }}>
      <h2>Your Order</h2>
      {items.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '24px 0', color: '#aaa' }}>
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none" style={{ marginBottom: 12, opacity: 0.5 }}>
            <rect x="12" y="20" width="40" height="36" rx="4" stroke="#ccc" strokeWidth="2" />
            <path d="M12 28h40" stroke="#ccc" strokeWidth="2" />
            <path d="M24 20V14a8 8 0 0 1 16 0v6" stroke="#ccc" strokeWidth="2" strokeLinecap="round" />
            <circle cx="26" cy="38" r="2" fill="#ccc" />
            <circle cx="38" cy="38" r="2" fill="#ccc" />
            <path d="M26 46c2 2 10 2 12 0" stroke="#ccc" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <p style={{ fontSize: '0.95em', margin: '0 0 4px', color: '#999' }}>Your bag is empty</p>
          <p style={{ fontSize: '0.8em', color: '#bbb' }}>Use your voice to start ordering</p>
        </div>
      ) : (
        <>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {items.map((item) => (
              <li key={item.itemId} className="order-item-enter" style={{ padding: '8px 0', borderBottom: '1px solid #eee' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>{item.name} × {item.quantity}</span>
                  <span style={{ fontWeight: 'bold' }}>{formatPrice(item.unitPrice * item.quantity)}</span>
                </div>
                {item.specialInstructions && (
                  <div style={{ color: '#888', fontSize: '0.85em', fontStyle: 'italic', marginTop: 2 }}>
                    📝 {item.specialInstructions}
                  </div>
                )}
              </li>
            ))}
          </ul>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '12px', fontWeight: 'bold', fontSize: '1.1em' }}>
            <span>Total</span>
            <span>{formatPrice(total)}</span>
          </div>
        </>
      )}
    </section>
  );
}
