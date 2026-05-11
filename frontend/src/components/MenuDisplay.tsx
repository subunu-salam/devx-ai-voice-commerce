// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useAppStore } from '../store';
import { CategoryList } from './CategoryList';
import type { MenuItem } from '../types';

interface MenuDisplayProps {
  onItemClick?: (item: MenuItem) => void;
}

export function MenuDisplay({ onItemClick }: MenuDisplayProps) {
  const { categories, menuItems, highlightedCategory, highlightedItem } = useAppStore((s) => s.agentUI);

  if (categories.length === 0) {
    return null; // No menu data yet — agent hasn't sent it
  }

  // Separate "Build Your Own" from regular categories
  const regularCategories = categories.filter((c) => c.categoryId !== 'custom');

  return (
    <div className="menu-display">
      <CategoryList
        categories={regularCategories}
        items={menuItems}
        highlightedCategory={highlightedCategory}
        highlightedItem={highlightedItem}
        onItemClick={onItemClick}
      />
    </div>
  );
}
