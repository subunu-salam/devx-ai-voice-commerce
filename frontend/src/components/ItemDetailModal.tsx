import { useMemo, useState } from 'react';
import { useAppStore } from '../store';
import { formatPrice } from '../utils/formatPrice';
import type { MenuItem } from '../types';

export function ItemDetailModal() {
  const highlightedItem = useAppStore((s) => s.agentUI.highlightedItem);
  const menuItems = useAppStore((s) => s.menu.items);
  const [instructions, setInstructions] = useState('');

  // Look up the highlighted item from local menu data
  const item: MenuItem | null = useMemo(() => {
    if (!highlightedItem) return null;
    for (const items of Object.values(menuItems)) {
      const found = items.find((i) => i.itemId === highlightedItem);
      if (found) return found;
    }
    return null;
  }, [highlightedItem, menuItems]);

  if (!item) return null;

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        backgroundColor: 'rgba(0,0,0,0.5)',
      }}
      onClick={() => useAppStore.getState().applyAgentUIState({
        ...useAppStore.getState().agentUI,
        highlightedItem: null,
      })}
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
          src={item.imageUrl}
          alt={item.name}
          style={{ width: '100%', height: 200, objectFit: 'cover', borderRadius: 12 }}
          onError={(e) => {
            const img = e.target as HTMLImageElement;
            img.onerror = null;
            img.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="%23eee"/></svg>';
          }}
        />
        <h2 style={{ margin: '16px 0 4px' }}>{item.name}</h2>
        <p style={{ color: '#666', margin: '0 0 8px' }}>{item.description}</p>
        <p style={{ fontSize: '1.3em', fontWeight: 'bold', color: '#27ae60', margin: '0 0 16px' }}>
          {formatPrice(item.price)}
        </p>
        <label style={{ display: 'block', fontWeight: 600, marginBottom: 6 }}>Special instructions</label>
        <textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder="e.g. no pickles, extra sauce, well done..."
          rows={3}
          style={{ width: '100%', padding: 10, borderRadius: 8, border: '1px solid #ddd', fontSize: 14, resize: 'vertical', boxSizing: 'border-box' }}
        />
        <p style={{ color: '#888', fontSize: 12, margin: '8px 0 0' }}>
          You can also tell the voice agent your preferences
        </p>
      </div>
    </div>
  );
}
