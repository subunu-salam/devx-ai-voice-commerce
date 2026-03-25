import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { WebSocketClient } from './WebSocketClient';
import { useAppStore } from '../store/appStore';
import { buildUIState, sendInitialState, sendCategoryChange, sendItemSelection } from './UIStateSender';

function createMockWsClient(): WebSocketClient {
  return {
    connect: vi.fn(),
    disconnect: vi.fn(),
    sendAudio: vi.fn(),
    sendTextMessage: vi.fn(),
    onBinaryMessage: vi.fn(),
    onTextMessage: vi.fn(),
    onDisconnect: vi.fn(),
    onReconnect: vi.fn(),
    getState: vi.fn().mockReturnValue('connected'),
  };
}

describe('UIStateSender', () => {
  let wsClient: WebSocketClient;

  beforeEach(() => {
    wsClient = createMockWsClient();
    // Reset store to initial state
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

  describe('buildUIState', () => {
    it('returns UIState with null values when store is in initial state', () => {
      const uiState = buildUIState();
      expect(uiState).toEqual({
        visibleCategory: null,
        selectedItem: null,
        orderItems: [],
        orderTotal: 0,
      });
    });

    it('reflects current store values', () => {
      useAppStore.setState({
        menu: {
          categories: [],
          items: {},
          highlightedCategory: 'burgers',
          highlightedItem: 'item-1',
          loading: false,
          error: null,
        },
        order: {
          items: [{ itemId: 'item-1', name: 'Cheeseburger', quantity: 2, unitPrice: 599 }],
          total: 1198,
          confirmed: false,
          orderNumber: null,
        },
      });

      const uiState = buildUIState();
      expect(uiState.visibleCategory).toBe('burgers');
      expect(uiState.selectedItem).toBe('item-1');
      expect(uiState.orderItems).toEqual([
        { itemId: 'item-1', name: 'Cheeseburger', quantity: 2, unitPrice: 599 },
      ]);
      expect(uiState.orderTotal).toBe(1198);
    });
  });

  describe('sendInitialState', () => {
    it('sends the current UIState as JSON over WebSocket', () => {
      sendInitialState(wsClient);

      expect(wsClient.sendTextMessage).toHaveBeenCalledTimes(1);
      const sent = JSON.parse((wsClient.sendTextMessage as ReturnType<typeof vi.fn>).mock.calls[0][0]);
      expect(sent).toEqual({
        visibleCategory: null,
        selectedItem: null,
        orderItems: [],
        orderTotal: 0,
      });
    });

    it('includes order items from the store', () => {
      useAppStore.setState({
        order: {
          items: [{ itemId: 'item-2', name: 'Fries', quantity: 1, unitPrice: 299 }],
          total: 299,
          confirmed: false,
          orderNumber: null,
        },
      });

      sendInitialState(wsClient);

      const sent = JSON.parse((wsClient.sendTextMessage as ReturnType<typeof vi.fn>).mock.calls[0][0]);
      expect(sent.orderItems).toEqual([
        { itemId: 'item-2', name: 'Fries', quantity: 1, unitPrice: 299 },
      ]);
      expect(sent.orderTotal).toBe(299);
    });
  });

  describe('sendCategoryChange', () => {
    it('sends UIState with the updated visibleCategory', () => {
      sendCategoryChange(wsClient, 'drinks');

      expect(wsClient.sendTextMessage).toHaveBeenCalledTimes(1);
      const sent = JSON.parse((wsClient.sendTextMessage as ReturnType<typeof vi.fn>).mock.calls[0][0]);
      expect(sent.visibleCategory).toBe('drinks');
    });

    it('preserves other state fields from the store', () => {
      useAppStore.setState({
        menu: {
          categories: [],
          items: {},
          highlightedCategory: 'burgers',
          highlightedItem: 'item-5',
          loading: false,
          error: null,
        },
        order: {
          items: [{ itemId: 'item-5', name: 'Shake', quantity: 1, unitPrice: 450 }],
          total: 450,
          confirmed: false,
          orderNumber: null,
        },
      });

      sendCategoryChange(wsClient, 'desserts');

      const sent = JSON.parse((wsClient.sendTextMessage as ReturnType<typeof vi.fn>).mock.calls[0][0]);
      expect(sent.visibleCategory).toBe('desserts');
      expect(sent.selectedItem).toBe('item-5');
      expect(sent.orderItems).toHaveLength(1);
      expect(sent.orderTotal).toBe(450);
    });
  });

  describe('sendItemSelection', () => {
    it('sends UIState with the updated selectedItem', () => {
      sendItemSelection(wsClient, 'item-42');

      expect(wsClient.sendTextMessage).toHaveBeenCalledTimes(1);
      const sent = JSON.parse((wsClient.sendTextMessage as ReturnType<typeof vi.fn>).mock.calls[0][0]);
      expect(sent.selectedItem).toBe('item-42');
    });

    it('preserves other state fields from the store', () => {
      useAppStore.setState({
        menu: {
          categories: [],
          items: {},
          highlightedCategory: 'sides',
          highlightedItem: null,
          loading: false,
          error: null,
        },
        order: {
          items: [{ itemId: 'item-3', name: 'Onion Rings', quantity: 3, unitPrice: 349 }],
          total: 1047,
          confirmed: false,
          orderNumber: null,
        },
      });

      sendItemSelection(wsClient, 'item-99');

      const sent = JSON.parse((wsClient.sendTextMessage as ReturnType<typeof vi.fn>).mock.calls[0][0]);
      expect(sent.visibleCategory).toBe('sides');
      expect(sent.selectedItem).toBe('item-99');
      expect(sent.orderItems).toHaveLength(1);
      expect(sent.orderTotal).toBe(1047);
    });
  });
});
