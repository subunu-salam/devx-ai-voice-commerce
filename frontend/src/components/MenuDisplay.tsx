import { useAppStore } from '../store';
import { CategoryList } from './CategoryList';
import type { MenuItem } from '../types';

interface MenuDisplayProps {
  onItemClick?: (item: MenuItem) => void;
}

export function MenuDisplay({ onItemClick }: MenuDisplayProps) {
  const { categories, items, highlightedCategory, highlightedItem, loading, error } =
    useAppStore((s) => s.menu);

  if (loading) {
    return (
      <div className="menu-loading" role="status" aria-label="Loading menu">
        <p>Loading menu…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="menu-error" role="alert">
        <p>Menu unavailable. Please try again.</p>
      </div>
    );
  }

  return (
    <div className="menu-display">
      <CategoryList
        categories={categories}
        items={items}
        highlightedCategory={highlightedCategory}
        highlightedItem={highlightedItem}
        onItemClick={onItemClick}
      />
    </div>
  );
}
