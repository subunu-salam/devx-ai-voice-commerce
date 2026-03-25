import { describe, it, expect, beforeEach } from 'vitest';
import { useAppStore } from './appStore';
import type { UIEvent } from '../types';

describe('appStore', () => {
  beforeEach(() => {
    // Reset store to initial state before each test
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
  });

  describe('applyUIEvent', () => {
    it('handles order_update event', () => {
      const event: UIEvent = {
        type: 'order_update',
        payload: {
          items: [{ itemId: 'burger-1', name: 'Cheeseburger', quantity: 2, unitPrice: 599 }],
          total: 1198,
        },
      };

      useAppStore.getState().applyUIEvent(event);

      const { order } = useAppStore.getState();
      expect(order.items).toEqual(event.payload.items);
      expect(order.total).toBe(1198);
      expect(order.confirmed).toBe(false);
    });

    it('handles browse_category event', () => {
      const event: UIEvent = {
        type: 'browse_category',
        payload: { categoryId: 'cat-burgers', categoryName: 'Burgers' },
      };

      useAppStore.getState().applyUIEvent(event);

      const { menu } = useAppStore.getState();
      expect(menu.highlightedCategory).toBe('cat-burgers');
    });

    it('handles highlight_item event', () => {
      const event: UIEvent = {
        type: 'highlight_item',
        payload: { itemId: 'item-cheese', itemName: 'Cheeseburger' },
      };

      useAppStore.getState().applyUIEvent(event);

      const { menu } = useAppStore.getState();
      expect(menu.highlightedItem).toBe('item-cheese');
    });

    it('handles highlight_category event', () => {
      const event: UIEvent = {
        type: 'highlight_category',
        payload: { categoryId: 'cat-drinks', categoryName: 'Drinks' },
      };

      useAppStore.getState().applyUIEvent(event);

      const { menu } = useAppStore.getState();
      expect(menu.highlightedCategory).toBe('cat-drinks');
    });

    it('handles order_confirmed event', () => {
      const event: UIEvent = {
        type: 'order_confirmed',
        payload: {
          orderNumber: 'ORD-12345',
          items: [{ itemId: 'burger-1', name: 'Cheeseburger', quantity: 1, unitPrice: 599 }],
          total: 599,
          timestamp: '2025-01-01T12:00:00Z',
        },
      };

      useAppStore.getState().applyUIEvent(event);

      const { order } = useAppStore.getState();
      expect(order.confirmed).toBe(true);
      expect(order.orderNumber).toBe('ORD-12345');
      expect(order.items).toEqual(event.payload.items);
      expect(order.total).toBe(599);
    });

    it('order_update does not affect menu state', () => {
      useAppStore.setState({
        menu: {
          ...useAppStore.getState().menu,
          highlightedCategory: 'cat-burgers',
          highlightedItem: 'item-1',
        },
      });

      const event: UIEvent = {
        type: 'order_update',
        payload: {
          items: [{ itemId: 'burger-1', name: 'Burger', quantity: 1, unitPrice: 500 }],
          total: 500,
        },
      };

      useAppStore.getState().applyUIEvent(event);

      const { menu } = useAppStore.getState();
      expect(menu.highlightedCategory).toBe('cat-burgers');
      expect(menu.highlightedItem).toBe('item-1');
    });

    it('highlight_item does not affect order state', () => {
      useAppStore.setState({
        order: {
          items: [{ itemId: 'b1', name: 'Burger', quantity: 1, unitPrice: 500 }],
          total: 500,
          confirmed: false,
          orderNumber: null,
        },
      });

      const event: UIEvent = {
        type: 'highlight_item',
        payload: { itemId: 'item-fries', itemName: 'Fries' },
      };

      useAppStore.getState().applyUIEvent(event);

      const { order } = useAppStore.getState();
      expect(order.items).toHaveLength(1);
      expect(order.total).toBe(500);
    });
  });

  describe('setMenuData', () => {
    it('sets categories and items', () => {
      const categories = [{ categoryId: 'c1', name: 'Burgers', sortOrder: 1 }];
      const items = {
        c1: [
          {
            itemId: 'i1',
            categoryId: 'c1',
            name: 'Burger',
            description: 'A burger',
            price: 599,
            imageUrl: '/img/burger.png',
            category: 'Burgers',
            featured: false,
            sortOrder: 1,
          },
        ],
      };

      useAppStore.getState().setMenuData(categories, items);

      const { menu } = useAppStore.getState();
      expect(menu.categories).toEqual(categories);
      expect(menu.items).toEqual(items);
    });
  });

  describe('setMenuLoading', () => {
    it('sets loading to true', () => {
      useAppStore.getState().setMenuLoading(true);
      expect(useAppStore.getState().menu.loading).toBe(true);
    });

    it('sets loading to false', () => {
      useAppStore.getState().setMenuLoading(true);
      useAppStore.getState().setMenuLoading(false);
      expect(useAppStore.getState().menu.loading).toBe(false);
    });
  });

  describe('setMenuError', () => {
    it('sets error message', () => {
      useAppStore.getState().setMenuError('Failed to load menu');
      expect(useAppStore.getState().menu.error).toBe('Failed to load menu');
    });

    it('clears error with null', () => {
      useAppStore.getState().setMenuError('Some error');
      useAppStore.getState().setMenuError(null);
      expect(useAppStore.getState().menu.error).toBeNull();
    });
  });

  describe('setVoiceSession', () => {
    it('sets session active', () => {
      useAppStore.getState().setVoiceSession(true);
      expect(useAppStore.getState().voice.sessionActive).toBe(true);
    });

    it('sets session inactive', () => {
      useAppStore.getState().setVoiceSession(true);
      useAppStore.getState().setVoiceSession(false);
      expect(useAppStore.getState().voice.sessionActive).toBe(false);
    });
  });

  describe('setListening', () => {
    it('sets listening state', () => {
      useAppStore.getState().setListening(true);
      expect(useAppStore.getState().voice.listening).toBe(true);
    });
  });

  describe('setMicPermission', () => {
    it('sets mic permission to granted', () => {
      useAppStore.getState().setMicPermission('granted');
      expect(useAppStore.getState().voice.micPermission).toBe('granted');
    });

    it('sets mic permission to denied', () => {
      useAppStore.getState().setMicPermission('denied');
      expect(useAppStore.getState().voice.micPermission).toBe('denied');
    });
  });

  describe('endVoiceSession', () => {
    it('sets sessionActive and listening to false', () => {
      useAppStore.setState({
        voice: { sessionActive: true, listening: true, micPermission: 'granted' },
      });

      useAppStore.getState().endVoiceSession();

      const { voice } = useAppStore.getState();
      expect(voice.sessionActive).toBe(false);
      expect(voice.listening).toBe(false);
    });

    it('preserves order items (Req 9.4)', () => {
      useAppStore.setState({
        voice: { sessionActive: true, listening: true, micPermission: 'granted' },
        order: {
          items: [{ itemId: 'b1', name: 'Burger', quantity: 2, unitPrice: 599 }],
          total: 1198,
          confirmed: false,
          orderNumber: null,
        },
      });

      useAppStore.getState().endVoiceSession();

      const { order } = useAppStore.getState();
      expect(order.items).toHaveLength(1);
      expect(order.items[0].itemId).toBe('b1');
      expect(order.total).toBe(1198);
    });

    it('preserves mic permission', () => {
      useAppStore.setState({
        voice: { sessionActive: true, listening: true, micPermission: 'granted' },
      });

      useAppStore.getState().endVoiceSession();

      expect(useAppStore.getState().voice.micPermission).toBe('granted');
    });
  });

  describe('resetOrder', () => {
    it('clears order state', () => {
      useAppStore.setState({
        order: {
          items: [{ itemId: 'b1', name: 'Burger', quantity: 1, unitPrice: 599 }],
          total: 599,
          confirmed: true,
          orderNumber: 'ORD-123',
        },
      });

      useAppStore.getState().resetOrder();

      const { order } = useAppStore.getState();
      expect(order.items).toEqual([]);
      expect(order.total).toBe(0);
      expect(order.confirmed).toBe(false);
      expect(order.orderNumber).toBeNull();
    });

    it('does not affect voice or menu state', () => {
      useAppStore.setState({
        voice: { sessionActive: true, listening: true, micPermission: 'granted' },
        menu: {
          ...useAppStore.getState().menu,
          highlightedCategory: 'cat-1',
        },
      });

      useAppStore.getState().resetOrder();

      expect(useAppStore.getState().voice.sessionActive).toBe(true);
      expect(useAppStore.getState().menu.highlightedCategory).toBe('cat-1');
    });
  });
});
