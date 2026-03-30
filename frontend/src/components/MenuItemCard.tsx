import type { MenuItem } from '../types';
import { formatPrice } from '../utils/formatPrice';

interface MenuItemCardProps {
  item: MenuItem;
  highlighted?: boolean;
  onClick?: (item: MenuItem) => void;
}

export function MenuItemCard({ item, highlighted = false, onClick }: MenuItemCardProps) {
  return (
    <article
      className={`menu-item-card${highlighted ? ' menu-item-card--highlighted' : ''}`}
      onClick={() => onClick?.(item)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick?.(item);
        }
      }}
      style={{
        border: highlighted ? '2px solid #e67e22' : '1px solid #ddd',
        borderRadius: '8px',
        padding: '12px',
        cursor: 'pointer',
        backgroundColor: highlighted ? '#fef9e7' : '#fff',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        transition: 'border-color 0.2s, background-color 0.2s',
      }}
    >
      <img
        src={item.imageUrl}
        alt={item.name}
        width={200}
        height={200}
        style={{ width: 200, height: 200, objectFit: 'cover', borderRadius: '6px' }}
        onError={(e) => {
          const img = e.target as HTMLImageElement;
          img.onerror = null; // prevent infinite loop
          img.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="%23eee"/><text x="100" y="105" text-anchor="middle" font-family="sans-serif" font-size="14" fill="%23999">No image</text></svg>';
        }}
      />
      <h3 style={{ margin: '8px 0 4px' }}>{item.name}</h3>
      <p style={{ margin: '0 0 4px', color: '#666', textAlign: 'center', fontSize: '0.9em' }}>
        {item.description}
      </p>
      <span style={{ fontWeight: 'bold', color: '#27ae60' }}>{formatPrice(item.price)}</span>
    </article>
  );
}
