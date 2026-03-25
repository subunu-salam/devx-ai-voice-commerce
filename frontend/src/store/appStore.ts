import { create } from 'zustand';
import type { AppState, Category, MenuItem, UIEvent } from '../types';

interface AppActions {
  applyUIEvent: (event: UIEvent) => void;
  setMenuData: (categories: Category[], items: Record<string, MenuItem[]>) => void;
  setMenuLoading: (loading: boolean) => void;
  setMenuError: (error: string | null) => void;
  setVoiceSession: (active: boolean) => void;
  setListening: (listening: boolean) => void;
  setMicPermission: (permission: 'granted' | 'denied' | 'prompt') => void;
  endVoiceSession: () => void;
  resetOrder: () => void;
}

const initialState: AppState = {
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
};

export const useAppStore = create<AppState & AppActions>()((set) => ({
  ...initialState,

  applyUIEvent: (event: UIEvent) => {
    switch (event.type) {
      case 'order_update':
        set((state) => ({
          order: {
            ...state.order,
            items: event.payload.items,
            total: event.payload.total,
          },
        }));
        break;

      case 'browse_category':
        set((state) => ({
          menu: {
            ...state.menu,
            highlightedCategory: event.payload.categoryId,
          },
        }));
        break;

      case 'highlight_item':
        set((state) => ({
          menu: {
            ...state.menu,
            highlightedItem: event.payload.itemId,
          },
        }));
        break;

      case 'highlight_category':
        set((state) => ({
          menu: {
            ...state.menu,
            highlightedCategory: event.payload.categoryId,
          },
        }));
        break;

      case 'order_confirmed':
        set((state) => ({
          order: {
            ...state.order,
            confirmed: true,
            orderNumber: event.payload.orderNumber,
            items: event.payload.items,
            total: event.payload.total,
          },
        }));
        break;
    }
  },

  setMenuData: (categories, items) =>
    set((state) => ({
      menu: { ...state.menu, categories, items },
    })),

  setMenuLoading: (loading) =>
    set((state) => ({
      menu: { ...state.menu, loading },
    })),

  setMenuError: (error) =>
    set((state) => ({
      menu: { ...state.menu, error },
    })),

  setVoiceSession: (active) =>
    set((state) => ({
      voice: { ...state.voice, sessionActive: active },
    })),

  setListening: (listening) =>
    set((state) => ({
      voice: { ...state.voice, listening },
    })),

  setMicPermission: (permission) =>
    set((state) => ({
      voice: { ...state.voice, micPermission: permission },
    })),

  endVoiceSession: () =>
    set((state) => ({
      voice: { ...state.voice, sessionActive: false, listening: false },
    })),

  resetOrder: () =>
    set(() => ({
      order: {
        items: [],
        total: 0,
        confirmed: false,
        orderNumber: null,
      },
    })),
}));
