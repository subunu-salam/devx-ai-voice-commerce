import { describe, it, expect, beforeEach } from 'vitest';
import fc from 'fast-check';
import { useAppStore } from './appStore';
import type {
  UIEvent,
  UIState,
  OrderItem,
  OrderUpdatePayload,
  CategoryPayload,
  ItemPayload,
  OrderConfirmedPayload,
} from '../types';

// --- Arbitraries ---

const arbOrderItem: fc.Arbitrary<OrderItem> = fc.record({
  itemId: fc.string({ minLength: 1, maxLength: 20 }),
  name: fc.string({ minLength: 1, maxLength: 30 }),
  quantity: fc.integer({ min: 1, max: 100 }),
  unitPrice: fc.integer({ min: 1, max: 99999 }),
});

const arbOrderUpdatePayload: fc.Arbitrary<OrderUpdatePayload> = fc.record({
  items: fc.array(arbOrderItem, { minLength: 0, maxLength: 10 }),
  total: fc.integer({ min: 0, max: 999999 }),
});

const arbCategoryPayload: fc.Arbitrary<CategoryPayload> = fc.record({
  categoryId: fc.string({ minLength: 1, maxLength: 20 }),
  categoryName: fc.string({ minLength: 1, maxLength: 30 }),
});

const arbItemPayload: fc.Arbitrary<ItemPayload> = fc.record({
  itemId: fc.string({ minLength: 1, maxLength: 20 }),
  itemName: fc.string({ minLength: 1, maxLength: 30 }),
});

const arbOrderConfirmedPayload: fc.Arbitrary<OrderConfirmedPayload> = fc.record({
  orderNumber: fc.string({ minLength: 1, maxLength: 20 }),
  items: fc.array(arbOrderItem, { minLength: 0, maxLength: 10 }),
  total: fc.integer({ min: 0, max: 999999 }),
  timestamp: fc.date().map((d) => d.toISOString()),
});

const arbUIEvent: fc.Arbitrary<UIEvent> = fc.oneof(
  arbOrderUpdatePayload.map((payload): UIEvent => ({ type: 'order_update', payload })),
  arbCategoryPayload.map((payload): UIEvent => ({ type: 'browse_category', payload })),
  arbItemPayload.map((payload): UIEvent => ({ type: 'highlight_item', payload })),
  arbCategoryPayload.map((payload): UIEvent => ({ type: 'highlight_category', payload })),
  arbOrderConfirmedPayload.map((payload): UIEvent => ({ type: 'order_confirmed', payload })),
);

const arbUIState: fc.Arbitrary<UIState> = fc.record({
  visibleCategory: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
  selectedItem: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
  orderItems: fc.array(arbOrderItem, { minLength: 0, maxLength: 10 }),
  orderTotal: fc.integer({ min: 0, max: 999999 }),
});

// --- Helpers ---

function resetStore() {
  useAppStore.setState({
    menu: {
      categories: [],
      items: {},
      highlightedCategory: null,
      highlightedItem: null,
      loading: false,
      error: null,
    },
    order: {
      items: [],
      total: 0,
      confirmed: false,
      orderNumber: null,
    },
    voice: {
      sessionActive: false,
      listening: false,
      micPermission: 'prompt',
    },
    auth: {
      authenticated: false,
      userId: null,
    },
  });
}

// ============================================================
// Property 8: UI_Event processing updates state store correctly
// Validates: Requirements 4.1, 4.5, 8.4, 8.5
// ============================================================
describe('Property 8: UI_Event processing updates state store correctly', () => {
  beforeEach(resetStore);

  it('order_update sets order items and total, leaves menu/voice/auth unchanged', () => {
    fc.assert(
      fc.property(arbOrderUpdatePayload, (payload) => {
        resetStore();
        const before = useAppStore.getState();
        const menuBefore = { ...before.menu };
        const voiceBefore = { ...before.voice };
        const authBefore = { ...before.auth };

        useAppStore.getState().applyUIEvent({ type: 'order_update', payload });

        const after = useAppStore.getState();
        expect(after.order.items).toEqual(payload.items);
        expect(after.order.total).toBe(payload.total);
        // Unrelated fields unchanged
        expect(after.menu).toEqual(menuBefore);
        expect(after.voice).toEqual(voiceBefore);
        expect(after.auth).toEqual(authBefore);
      }),
      { numRuns: 100 },
    );
  });

  it('browse_category sets highlightedCategory, leaves order/voice/auth unchanged', () => {
    fc.assert(
      fc.property(arbCategoryPayload, (payload) => {
        resetStore();
        const before = useAppStore.getState();
        const orderBefore = { ...before.order };
        const voiceBefore = { ...before.voice };
        const authBefore = { ...before.auth };

        useAppStore.getState().applyUIEvent({ type: 'browse_category', payload });

        const after = useAppStore.getState();
        expect(after.menu.highlightedCategory).toBe(payload.categoryId);
        expect(after.order).toEqual(orderBefore);
        expect(after.voice).toEqual(voiceBefore);
        expect(after.auth).toEqual(authBefore);
      }),
      { numRuns: 100 },
    );
  });

  it('highlight_item sets highlightedItem, leaves order/voice/auth unchanged', () => {
    fc.assert(
      fc.property(arbItemPayload, (payload) => {
        resetStore();
        const before = useAppStore.getState();
        const orderBefore = { ...before.order };
        const voiceBefore = { ...before.voice };
        const authBefore = { ...before.auth };

        useAppStore.getState().applyUIEvent({ type: 'highlight_item', payload });

        const after = useAppStore.getState();
        expect(after.menu.highlightedItem).toBe(payload.itemId);
        expect(after.order).toEqual(orderBefore);
        expect(after.voice).toEqual(voiceBefore);
        expect(after.auth).toEqual(authBefore);
      }),
      { numRuns: 100 },
    );
  });

  it('highlight_category sets highlightedCategory, leaves order/voice/auth unchanged', () => {
    fc.assert(
      fc.property(arbCategoryPayload, (payload) => {
        resetStore();
        const before = useAppStore.getState();
        const orderBefore = { ...before.order };
        const voiceBefore = { ...before.voice };
        const authBefore = { ...before.auth };

        useAppStore.getState().applyUIEvent({ type: 'highlight_category', payload });

        const after = useAppStore.getState();
        expect(after.menu.highlightedCategory).toBe(payload.categoryId);
        expect(after.order).toEqual(orderBefore);
        expect(after.voice).toEqual(voiceBefore);
        expect(after.auth).toEqual(authBefore);
      }),
      { numRuns: 100 },
    );
  });

  it('order_confirmed sets confirmed/orderNumber/items/total, leaves menu/voice/auth unchanged', () => {
    fc.assert(
      fc.property(arbOrderConfirmedPayload, (payload) => {
        resetStore();
        const before = useAppStore.getState();
        const menuBefore = { ...before.menu };
        const voiceBefore = { ...before.voice };
        const authBefore = { ...before.auth };

        useAppStore.getState().applyUIEvent({ type: 'order_confirmed', payload });

        const after = useAppStore.getState();
        expect(after.order.confirmed).toBe(true);
        expect(after.order.orderNumber).toBe(payload.orderNumber);
        expect(after.order.items).toEqual(payload.items);
        expect(after.order.total).toBe(payload.total);
        expect(after.menu).toEqual(menuBefore);
        expect(after.voice).toEqual(voiceBefore);
        expect(after.auth).toEqual(authBefore);
      }),
      { numRuns: 100 },
    );
  });

  it('any UI_Event updates only the targeted state fields', () => {
    /**
     * Validates: Requirements 4.1, 4.5, 8.4, 8.5
     * For any valid UI_Event, applying it should update exactly the corresponding
     * state fields and leave unrelated fields unchanged.
     */
    fc.assert(
      fc.property(arbUIEvent, (event) => {
        resetStore();
        const before = useAppStore.getState();

        useAppStore.getState().applyUIEvent(event);

        const after = useAppStore.getState();

        switch (event.type) {
          case 'order_update':
            expect(after.order.items).toEqual(event.payload.items);
            expect(after.order.total).toBe(event.payload.total);
            expect(after.menu).toEqual(before.menu);
            expect(after.voice).toEqual(before.voice);
            break;
          case 'browse_category':
          case 'highlight_category':
            expect(after.menu.highlightedCategory).toBe(event.payload.categoryId);
            expect(after.order).toEqual(before.order);
            expect(after.voice).toEqual(before.voice);
            break;
          case 'highlight_item':
            expect(after.menu.highlightedItem).toBe(event.payload.itemId);
            expect(after.order).toEqual(before.order);
            expect(after.voice).toEqual(before.voice);
            break;
          case 'order_confirmed':
            expect(after.order.confirmed).toBe(true);
            expect(after.order.orderNumber).toBe(event.payload.orderNumber);
            expect(after.order.items).toEqual(event.payload.items);
            expect(after.order.total).toBe(event.payload.total);
            expect(after.menu).toEqual(before.menu);
            expect(after.voice).toEqual(before.voice);
            break;
        }
      }),
      { numRuns: 100 },
    );
  });
});

// ============================================================
// Property 15: Protocol message serialization round-trip
// Validates: Requirements 11.1, 11.9
// ============================================================
describe('Property 15: Protocol message serialization round-trip', () => {
  it('UIEvent survives JSON round-trip', () => {
    /**
     * Validates: Requirements 11.1, 11.9
     * For any valid UIEvent, serializing to JSON and deserializing back
     * should produce an object equal to the original.
     */
    fc.assert(
      fc.property(arbUIEvent, (event) => {
        const roundTripped = JSON.parse(JSON.stringify(event));
        expect(roundTripped).toEqual(event);
      }),
      { numRuns: 100 },
    );
  });

  it('UIState survives JSON round-trip', () => {
    /**
     * Validates: Requirements 11.1, 11.9
     * For any valid UIState, serializing to JSON and deserializing back
     * should produce an object equal to the original.
     */
    fc.assert(
      fc.property(arbUIState, (state) => {
        const roundTripped = JSON.parse(JSON.stringify(state));
        expect(roundTripped).toEqual(state);
      }),
      { numRuns: 100 },
    );
  });
});

// ============================================================
// Property 14: Session end preserves order items
// Validates: Requirements 9.4
// ============================================================
describe('Property 14: Session end preserves order items', () => {
  beforeEach(resetStore);

  it('endVoiceSession sets sessionActive to false while preserving order', () => {
    /**
     * Validates: Requirements 9.4
     * For any app state with an active voice session and items in the order,
     * ending the session should set voice.sessionActive to false while keeping
     * order.items and order.total unchanged.
     */
    fc.assert(
      fc.property(
        fc.array(arbOrderItem, { minLength: 1, maxLength: 10 }),
        fc.integer({ min: 0, max: 999999 }),
        (items, total) => {
          resetStore();

          // Set up state with active voice session and order items
          useAppStore.setState({
            voice: { sessionActive: true, listening: true, micPermission: 'granted' },
            order: {
              items,
              total,
              confirmed: false,
              orderNumber: null,
            },
          });

          const orderBefore = { ...useAppStore.getState().order };

          useAppStore.getState().endVoiceSession();

          const after = useAppStore.getState();
          // Voice session should be ended
          expect(after.voice.sessionActive).toBe(false);
          expect(after.voice.listening).toBe(false);
          // Order should be preserved exactly
          expect(after.order.items).toEqual(orderBefore.items);
          expect(after.order.total).toBe(orderBefore.total);
          expect(after.order.confirmed).toBe(orderBefore.confirmed);
          expect(after.order.orderNumber).toBe(orderBefore.orderNumber);
        },
      ),
      { numRuns: 100 },
    );
  });
});
