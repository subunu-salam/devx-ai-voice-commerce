import { useState } from 'react';
import { useAppStore } from '../store';
import { formatPrice } from '../utils/formatPrice';

export function ItemDetailModal() {
  const itemDetail = useAppStore((s) => s.agentUI.itemDetail);
  const [instructions, setInstructions] = useState('');

  if (!itemDetail) return null;

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        backgroundColor: 'rgba(0,0,0,0.5)',
      }}
    >
      <div
        style={{
          background: '#fff', borderRadius: 16, padding: 24,
          maxWidth: 420, width: '90%', maxHeight: '80vh', overflow: 'auto',
          boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <img
          src={itemDetail.imageUrl}
          alt={itemDetail.name}
          style={{ width: '100%', height: 200, objectFit: 'cover', borderRadius: 12 }}
          onError={(e) => {
            const img = e.target as HTMLImageElement;
            img.onerror = null;
            img.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="%23eee"/></svg>';
          }}
        />
        <h2 style={{ margin: '16px 0 4px' }}>{itemDetail.name}</h2>
        <p style={{ color: '#666', margin: '0 0 8px' }}>{itemDetail.description}</p>
        <p style={{ fontSize: '1.3em', fontWeight: 'bold', color: '#27ae60', margin: '0 0 16px' }}>
          {formatPrice(itemDetail.price)}
        </p>
        <label style={{ display: 'block', fontWeight: 600, marginBottom: 6 }}>Special instructions</label>
        <textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder="e.g. no pickles, extra sauce, well done..."
          rows={3}
          style={{ width: '100%', padding: 10, borderRadius: 8, border: '1px solid #ddd', fontSize: 14, resize: 'vertical', boxSizing: 'border-box' }}
        />
        <p style={{ color: '#888', fontSize: 12, margin: '8px 0 16px' }}>
          You can also tell the voice agent your preferences
        </p>
      </div>
    </div>
  );
}
