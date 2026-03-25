import { describe, it, expect, vi, beforeEach } from 'vitest';
import fc from 'fast-check';
import { AgentCoreWebSocketClient } from './WebSocketClient';
import type { WebSocketClient } from './WebSocketClient';
import { useAppStore } from '../store/appStore';
import { sendCategoryChange, sendItemSelection } from './UIStateSender';

// --- Mock WebSocket for Property 16 ---

type WSListener = (event: Record<string, unknown>) => void;

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  url: string;
  binaryType = '';
  readyState = 0;

  onopen: WSListener | null = null;
  onclose: WSListener | null = null;
  onmessage: WSListener | null = null;
  onerror: WSListener | null = null;

  sent: Array<string | ArrayBuffer> = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }

  close() {
    this.readyState = 3;
  }

  simulateOpen() {
    this.readyState = 1;
    this.onopen?.({});
  }

  simulateMessage(data: string | ArrayBuffer) {
    this.onmessage?.({ data });
  }
}

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

function createMockWsClient(): WebSocketClient & { sentMessages: string[] } {
  const sentMessages: string[] = [];
  return {
    connect: vi.fn(),
    disconnect: vi.fn(),
    sendAudio: vi.fn(),
    sendTextMessage: vi.fn((msg: string) => {
      sentMessages.push(msg);
    }),
    onBinaryMessage: vi.fn(),
    onTextMessage: vi.fn(),
    onDisconnect: vi.fn(),
    onReconnect: vi.fn(),
    getState: vi.fn().mockReturnValue('connected'),
    sentMessages,
  };
}

// ============================================================
// Property 16: WebSocket message demultiplexing
// Validates: Requirements 11.2
// ============================================================
describe('Property 16: WebSocket message demultiplexing', () => {
  const originalWebSocket = globalThis.WebSocket;

  beforeEach(() => {
    MockWebSocket.instances = [];
    (globalThis as Record<string, unknown>).WebSocket = MockWebSocket as unknown as typeof WebSocket;
  });

  afterEach(() => {
    (globalThis as Record<string, unknown>).WebSocket = originalWebSocket;
  });

  it('binary frames are routed to onBinaryMessage callbacks', async () => {
    /**
     * Validates: Requirements 11.2
     * For any incoming binary WebSocket message (ArrayBuffer), it should be
     * routed to the audio handler (onBinaryMessage callbacks).
     */
    await fc.assert(
      fc.asyncProperty(
        fc.uint8Array({ minLength: 1, maxLength: 512 }),
        async (bytes) => {
          MockWebSocket.instances = [];
          const client = new AgentCoreWebSocketClient();
          const binaryReceived: ArrayBuffer[] = [];
          const textReceived: string[] = [];

          client.onBinaryMessage((data) => binaryReceived.push(data));
          client.onTextMessage((data) => textReceived.push(data));

          const connectPromise = client.connect('wss://test.example.com/ws', 'jwt');
          const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
          ws.simulateOpen();
          await connectPromise;

          const buffer = bytes.buffer.slice(
            bytes.byteOffset,
            bytes.byteOffset + bytes.byteLength,
          );
          ws.simulateMessage(buffer);

          expect(binaryReceived).toHaveLength(1);
          expect(textReceived).toHaveLength(0);
        },
      ),
      { numRuns: 100 },
    );
  });

  it('text frames are routed to onTextMessage callbacks', async () => {
    /**
     * Validates: Requirements 11.2
     * For any incoming text WebSocket message (JSON string), it should be
     * parsed and routed to the UI_Event handler (onTextMessage callbacks).
     */
    await fc.assert(
      fc.asyncProperty(
        fc.record({
          type: fc.constantFrom(
            'order_update',
            'browse_category',
            'highlight_item',
            'highlight_category',
            'order_confirmed',
          ),
          payload: fc.record({
            id: fc.string({ minLength: 1, maxLength: 20 }),
          }),
        }),
        async (eventObj) => {
          MockWebSocket.instances = [];
          const client = new AgentCoreWebSocketClient();
          const binaryReceived: ArrayBuffer[] = [];
          const textReceived: string[] = [];

          client.onBinaryMessage((data) => binaryReceived.push(data));
          client.onTextMessage((data) => textReceived.push(data));

          const connectPromise = client.connect('wss://test.example.com/ws', 'jwt');
          const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
          ws.simulateOpen();
          await connectPromise;

          const jsonStr = JSON.stringify(eventObj);
          ws.simulateMessage(jsonStr);

          expect(textReceived).toHaveLength(1);
          expect(binaryReceived).toHaveLength(0);
          // The text callback receives the raw string
          const parsed = JSON.parse(textReceived[0]);
          expect(parsed).toEqual(eventObj);
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ============================================================
// Property 4: Active voice session shows listening indicator
// Validates: Requirements 2.5
// ============================================================
describe('Property 4: Active voice session shows listening indicator', () => {
  beforeEach(resetStore);

  it('when sessionActive is set to true, store reflects listening state', () => {
    /**
     * Validates: Requirements 2.5
     * For any app state where voice.sessionActive is true, the store should
     * have listening=true after startSession flow (setVoiceSession + setListening).
     */
    fc.assert(
      fc.property(
        fc.record({
          highlightedCategory: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
          highlightedItem: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
          orderTotal: fc.integer({ min: 0, max: 999999 }),
        }),
        (randomState) => {
          resetStore();

          // Set some random menu/order state first
          useAppStore.setState({
            menu: {
              ...useAppStore.getState().menu,
              highlightedCategory: randomState.highlightedCategory,
              highlightedItem: randomState.highlightedItem,
            },
            order: {
              ...useAppStore.getState().order,
              total: randomState.orderTotal,
            },
          });

          // Simulate the startSession flow: setVoiceSession(true) + setListening(true)
          const store = useAppStore.getState();
          store.setVoiceSession(true);
          store.setListening(true);

          const after = useAppStore.getState();
          // When sessionActive is true, listening must also be true
          expect(after.voice.sessionActive).toBe(true);
          expect(after.voice.listening).toBe(true);
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ============================================================
// Property 18: User interaction sends UI_State with current context
// Validates: Requirements 11.11, 11.12
// ============================================================
describe('Property 18: User interaction sends UI_State with current context', () => {
  beforeEach(resetStore);

  it('sendCategoryChange sends UI_State with the updated visibleCategory', () => {
    /**
     * Validates: Requirements 11.11
     * For any category ID, calling sendCategoryChange should send a UI_State
     * message over the WebSocket containing the updated visibleCategory value.
     */
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 50 }),
        (categoryId) => {
          resetStore();
          const wsClient = createMockWsClient();

          sendCategoryChange(wsClient, categoryId);

          expect(wsClient.sentMessages).toHaveLength(1);
          const sent = JSON.parse(wsClient.sentMessages[0]);
          expect(sent.visibleCategory).toBe(categoryId);
          // Should also contain the other UIState fields
          expect(sent).toHaveProperty('selectedItem');
          expect(sent).toHaveProperty('orderItems');
          expect(sent).toHaveProperty('orderTotal');
        },
      ),
      { numRuns: 100 },
    );
  });

  it('sendItemSelection sends UI_State with the updated selectedItem', () => {
    /**
     * Validates: Requirements 11.12
     * For any item ID, calling sendItemSelection should send a UI_State
     * message over the WebSocket containing the updated selectedItem value.
     */
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 50 }),
        (itemId) => {
          resetStore();
          const wsClient = createMockWsClient();

          sendItemSelection(wsClient, itemId);

          expect(wsClient.sentMessages).toHaveLength(1);
          const sent = JSON.parse(wsClient.sentMessages[0]);
          expect(sent.selectedItem).toBe(itemId);
          // Should also contain the other UIState fields
          expect(sent).toHaveProperty('visibleCategory');
          expect(sent).toHaveProperty('orderItems');
          expect(sent).toHaveProperty('orderTotal');
        },
      ),
      { numRuns: 100 },
    );
  });

  it('sendCategoryChange preserves existing order context in UI_State', () => {
    /**
     * Validates: Requirements 11.11
     * For any category change with existing order items, the sent UI_State
     * should contain both the new category and the current order context.
     */
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 50 }),
        fc.array(
          fc.record({
            itemId: fc.string({ minLength: 1, maxLength: 20 }),
            name: fc.string({ minLength: 1, maxLength: 30 }),
            quantity: fc.integer({ min: 1, max: 100 }),
            unitPrice: fc.integer({ min: 1, max: 99999 }),
          }),
          { minLength: 1, maxLength: 5 },
        ),
        fc.integer({ min: 1, max: 999999 }),
        (categoryId, orderItems, orderTotal) => {
          resetStore();
          useAppStore.setState({
            order: {
              items: orderItems,
              total: orderTotal,
              confirmed: false,
              orderNumber: null,
            },
          });

          const wsClient = createMockWsClient();
          sendCategoryChange(wsClient, categoryId);

          const sent = JSON.parse(wsClient.sentMessages[0]);
          expect(sent.visibleCategory).toBe(categoryId);
          expect(sent.orderItems).toEqual(orderItems);
          expect(sent.orderTotal).toBe(orderTotal);
        },
      ),
      { numRuns: 100 },
    );
  });

  it('sendItemSelection preserves existing order context in UI_State', () => {
    /**
     * Validates: Requirements 11.12
     * For any item selection with existing order items, the sent UI_State
     * should contain both the new selected item and the current order context.
     */
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 50 }),
        fc.array(
          fc.record({
            itemId: fc.string({ minLength: 1, maxLength: 20 }),
            name: fc.string({ minLength: 1, maxLength: 30 }),
            quantity: fc.integer({ min: 1, max: 100 }),
            unitPrice: fc.integer({ min: 1, max: 99999 }),
          }),
          { minLength: 1, maxLength: 5 },
        ),
        fc.integer({ min: 1, max: 999999 }),
        (itemId, orderItems, orderTotal) => {
          resetStore();
          useAppStore.setState({
            order: {
              items: orderItems,
              total: orderTotal,
              confirmed: false,
              orderNumber: null,
            },
          });

          const wsClient = createMockWsClient();
          sendItemSelection(wsClient, itemId);

          const sent = JSON.parse(wsClient.sentMessages[0]);
          expect(sent.selectedItem).toBe(itemId);
          expect(sent.orderItems).toEqual(orderItems);
          expect(sent.orderTotal).toBe(orderTotal);
        },
      ),
      { numRuns: 100 },
    );
  });
});
