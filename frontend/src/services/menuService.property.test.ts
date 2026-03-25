import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { parseMenuItem, groupItemsByCategory } from './menuService';
import type { MenuItem } from '../types';

// --- Arbitraries ---

/** Arbitrary for a raw DynamoDB menu item with all expected fields. */
const arbDynamoDBItem = fc.record({
  PK: fc.string({ minLength: 1, maxLength: 20 }).map((s) => `CATEGORY#${s}`),
  SK: fc.string({ minLength: 1, maxLength: 20 }).map((s) => `ITEM#${s}`),
  name: fc.string({ minLength: 1, maxLength: 50 }),
  description: fc.string({ minLength: 0, maxLength: 100 }),
  price: fc.integer({ min: 0, max: 99999 }),
  imageUrl: fc.string({ minLength: 1, maxLength: 100 }),
  category: fc.string({ minLength: 1, maxLength: 30 }),
  featured: fc.boolean(),
  sortOrder: fc.integer({ min: 0, max: 999 }),
});

/** Arbitrary for a MenuItem (used in grouping tests). */
const arbMenuItem: fc.Arbitrary<MenuItem> = fc.record({
  itemId: fc.string({ minLength: 1, maxLength: 20 }),
  categoryId: fc.string({ minLength: 1, maxLength: 20 }),
  name: fc.string({ minLength: 1, maxLength: 50 }),
  description: fc.string({ minLength: 0, maxLength: 100 }),
  price: fc.integer({ min: 0, max: 99999 }),
  imageUrl: fc.string({ minLength: 1, maxLength: 100 }),
  category: fc.string({ minLength: 1, maxLength: 30 }),
  featured: fc.boolean(),
  sortOrder: fc.integer({ min: 0, max: 999 }),
});

// ============================================================
// Property 1: Menu data parsing produces complete MenuItems
// Validates: Requirements 1.1, 5.3
// ============================================================
describe('Property 1: Menu data parsing produces complete MenuItems', () => {
  it('parseMenuItem produces a MenuItem with all fields matching the source DynamoDB item', () => {
    /**
     * **Validates: Requirements 1.1, 5.3**
     * For any valid DynamoDB item containing name, description, price, category,
     * and imageUrl fields, parsing it through parseMenuItem should produce a
     * MenuItem object with all five fields present and matching the source values.
     */
    fc.assert(
      fc.property(arbDynamoDBItem, (dynamoItem) => {
        const result = parseMenuItem(dynamoItem);

        // Core fields must match source values
        expect(result.name).toBe(dynamoItem.name);
        expect(result.description).toBe(dynamoItem.description);
        expect(result.price).toBe(dynamoItem.price);
        expect(result.imageUrl).toBe(dynamoItem.imageUrl);
        expect(result.category).toBe(dynamoItem.category);

        // PK/SK derived fields
        expect(result.categoryId).toBe(dynamoItem.PK.replace('CATEGORY#', ''));
        expect(result.itemId).toBe(dynamoItem.SK.replace('ITEM#', ''));

        // Additional fields
        expect(result.featured).toBe(dynamoItem.featured);
        expect(result.sortOrder).toBe(dynamoItem.sortOrder);

        // All MenuItem fields must be present (not undefined)
        expect(result.name).toBeDefined();
        expect(result.description).toBeDefined();
        expect(result.price).toBeDefined();
        expect(result.imageUrl).toBeDefined();
        expect(result.category).toBeDefined();
        expect(result.itemId).toBeDefined();
        expect(result.categoryId).toBeDefined();
        expect(result.featured).toBeDefined();
        expect(result.sortOrder).toBeDefined();
      }),
      { numRuns: 100 },
    );
  });
});

// ============================================================
// Property 3: Category grouping correctness
// Validates: Requirements 1.3
// ============================================================
describe('Property 3: Category grouping correctness', () => {
  it('every item in each group has the matching categoryId, and total count equals original list length', () => {
    /**
     * **Validates: Requirements 1.3**
     * For any list of MenuItems with various category values, grouping them by
     * category should produce groups where every item in each group has the
     * matching category, and the total count of items across all groups equals
     * the original list length.
     */
    fc.assert(
      fc.property(fc.array(arbMenuItem, { minLength: 0, maxLength: 30 }), (items) => {
        const groups = groupItemsByCategory(items);

        // Every item in each group must have the matching categoryId
        for (const [categoryId, groupItems] of Object.entries(groups)) {
          for (const item of groupItems) {
            expect(item.categoryId).toBe(categoryId);
          }
        }

        // Total count across all groups equals original list length
        const totalGrouped = Object.values(groups).reduce(
          (sum, g) => sum + g.length,
          0,
        );
        expect(totalGrouped).toBe(items.length);
      }),
      { numRuns: 100 },
    );
  });
});
