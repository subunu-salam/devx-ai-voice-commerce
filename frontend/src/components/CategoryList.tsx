// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useRef, useEffect } from 'react';
import type { Category, MenuItem } from '../types';
import { MenuItemCard } from './MenuItemCard';

interface CategoryListProps {
  categories: Category[];
  items: Record<string, MenuItem[]>;
  highlightedCategory: string | null;
  highlightedItem: string | null;
  onItemClick?: (item: MenuItem) => void;
}

export function CategoryList({
  categories,
  items,
  highlightedCategory,
  highlightedItem,
  onItemClick,
}: CategoryListProps) {
  const categoryRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    if (highlightedCategory && categoryRefs.current[highlightedCategory]) {
      categoryRefs.current[highlightedCategory]?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      });
    }
  }, [highlightedCategory]);

  const sorted = [...categories].sort((a, b) => a.sortOrder - b.sortOrder);

  return (
    <div className="category-list">
      {sorted.map((cat) => {
        const catItems = items[cat.categoryId] ?? [];
        const isHighlighted = highlightedCategory === cat.categoryId;

        return (
          <section
            key={cat.categoryId}
            ref={(el) => { categoryRefs.current[cat.categoryId] = el; }}
            style={{
              marginBottom: '24px',
              padding: '12px',
              borderRadius: '8px',
              backgroundColor: isHighlighted ? '#eaf2f8' : 'transparent',
              transition: 'background-color 0.2s',
            }}
          >
            <h2 style={{ borderBottom: '2px solid #ccc', paddingBottom: '6px' }}>
              {cat.name}
            </h2>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
                gap: '16px',
                marginTop: '12px',
              }}
            >
              {catItems.map((item) => (
                <MenuItemCard
                  key={item.itemId}
                  item={item}
                  highlighted={highlightedItem === item.itemId}
                  onClick={onItemClick}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
