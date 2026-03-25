import { describe, it, expect } from 'vitest';
import { parseMenuItem, parseCategory, groupItemsByCategory } from './menuService';

describe('parseMenuItem', () => {
  it('parses a complete DynamoDB item into a MenuItem', () => {
    const item = {
      PK: 'CATEGORY#burgers',
      SK: 'ITEM#burger-01',
      name: 'Classic Burger',
      description: 'A juicy beef patty',
      price: 899,
      imageUrl: 'images/burger.jpg',
      category: 'Burgers',
      featured: true,
      sortOrder: 1,
    };

    const result = parseMenuItem(item);

    expect(result).toEqual({
      itemId: 'burger-01',
      categoryId: 'burgers',
      name: 'Classic Burger',
      description: 'A juicy beef patty',
      price: 899,
      imageUrl: 'images/burger.jpg',
      category: 'Burgers',
      featured: true,
      sortOrder: 1,
    });
  });

  it('strips CATEGORY# and ITEM# prefixes from PK and SK', () => {
    const item = {
      PK: 'CATEGORY#drinks',
      SK: 'ITEM#cola-01',
      name: 'Cola',
      description: 'Refreshing cola',
      price: 199,
      imageUrl: 'images/cola.jpg',
      category: 'Drinks',
      featured: false,
      sortOrder: 2,
    };

    expect(parseMenuItem(item).categoryId).toBe('drinks');
    expect(parseMenuItem(item).itemId).toBe('cola-01');
  });

  it('defaults missing fields gracefully', () => {
    const item = { PK: 'CATEGORY#sides', SK: 'ITEM#fries-01' };

    const result = parseMenuItem(item);

    expect(result.name).toBe('');
    expect(result.description).toBe('');
    expect(result.price).toBe(0);
    expect(result.imageUrl).toBe('');
    expect(result.category).toBe('');
    expect(result.featured).toBe(false);
    expect(result.sortOrder).toBe(0);
  });

  it('coerces price and sortOrder to numbers', () => {
    const item = {
      PK: 'CATEGORY#desserts',
      SK: 'ITEM#cake-01',
      name: 'Cake',
      price: '599',
      sortOrder: '3',
    };

    const result = parseMenuItem(item);
    expect(result.price).toBe(599);
    expect(result.sortOrder).toBe(3);
  });
});

describe('parseCategory', () => {
  it('parses a METADATA item into a Category', () => {
    const item = {
      PK: 'CATEGORY#burgers',
      SK: 'METADATA',
      name: 'Burgers',
      sortOrder: 1,
    };

    expect(parseCategory(item)).toEqual({
      categoryId: 'burgers',
      name: 'Burgers',
      sortOrder: 1,
    });
  });

  it('defaults missing fields gracefully', () => {
    const item = { PK: 'CATEGORY#sides' };

    const result = parseCategory(item);
    expect(result.categoryId).toBe('sides');
    expect(result.name).toBe('');
    expect(result.sortOrder).toBe(0);
  });
});

describe('groupItemsByCategory', () => {
  it('groups items by their categoryId', () => {
    const items = [
      { itemId: '1', categoryId: 'burgers', name: 'Burger', description: '', price: 899, imageUrl: '', category: 'Burgers', featured: false, sortOrder: 0 },
      { itemId: '2', categoryId: 'drinks', name: 'Cola', description: '', price: 199, imageUrl: '', category: 'Drinks', featured: false, sortOrder: 0 },
      { itemId: '3', categoryId: 'burgers', name: 'Cheeseburger', description: '', price: 999, imageUrl: '', category: 'Burgers', featured: false, sortOrder: 1 },
    ];

    const groups = groupItemsByCategory(items);

    expect(Object.keys(groups)).toHaveLength(2);
    expect(groups['burgers']).toHaveLength(2);
    expect(groups['drinks']).toHaveLength(1);
  });

  it('returns empty object for empty input', () => {
    expect(groupItemsByCategory([])).toEqual({});
  });

  it('preserves total item count across groups', () => {
    const items = [
      { itemId: '1', categoryId: 'a', name: '', description: '', price: 0, imageUrl: '', category: '', featured: false, sortOrder: 0 },
      { itemId: '2', categoryId: 'b', name: '', description: '', price: 0, imageUrl: '', category: '', featured: false, sortOrder: 0 },
      { itemId: '3', categoryId: 'a', name: '', description: '', price: 0, imageUrl: '', category: '', featured: false, sortOrder: 0 },
      { itemId: '4', categoryId: 'c', name: '', description: '', price: 0, imageUrl: '', category: '', featured: false, sortOrder: 0 },
    ];

    const groups = groupItemsByCategory(items);
    const totalItems = Object.values(groups).reduce((sum, g) => sum + g.length, 0);
    expect(totalItems).toBe(items.length);
  });
});
