import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { AgentCoreWebSocketClient } from './WebSocketClient';
import type { WebSocketState } from './WebSocketClient';

// --- Mock WebSocket ---

type WSListener = (event: Record<string, unknown>) => void;

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  url: string;
  binaryType = '';
  readyState = 0; // CONNECTING

  onopen: WSListener | null = null;
  onclose: WSListener | null = null;
  onmessage: WSListener | null = null;
  onerror: WSListener | null = null;

  sent: Array<string | ArrayBuffer> = [];
  closed = false;
  closeCode?: number;
  closeReason?: string;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }

  close(code?: number, reason?: string) {
    this.closed = true;
    this.closeCode = code;
    this.closeReason = reason;
    this.readyState = 3; // CLOSED
  }

  // Test helpers
  simulateOpen() {
    this.readyState = 1; // OPEN
    this.onopen?.({});
  }

  simulateMessage(data: string | ArrayBuffer) {
    this.onmessage?.({ data });
  }

  simulateClose(code = 1006, reason = '') {
    this.readyState = 3;
    this.onclose?.({ code, reason, wasClean: code === 1000 });
  }

  simulateError() {
    this.onerror?.({});
  }
}

// Install mock
const originalWebSocket = globalThis.WebSocket;

beforeEach(() => {
  MockWebSocket.instances = [];
  (globalThis as Record<string, unknown>).WebSocket = MockWebSocket as unknown as typeof WebSocket;
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  (globalThis as Record<string, unknown>).WebSocket = originalWebSocket;
});

// --- Helpers ---

function latestMockWs(): MockWebSocket {
  return MockWebSocket.instances[MockWebSocket.instances.length - 1];
}

function connectClient(
  client: AgentCoreWebSocketClient,
  endpoint = 'wss://agent.example.com/ws',
  token = 'jwt-token-123',
): { promise: Promise<void>; ws: () => MockWebSocket } {
  const promise = client.connect(endpoint, token);
  return { promise, ws: latestMockWs };
}

// --- Tests ---

describe('AgentCoreWebSocketClient', () => {
  let client: AgentCoreWebSocketClient;

  beforeEach(() => {
    client = new AgentCoreWebSocketClient();
  });

  describe('initial state', () => {
    it('starts in disconnected state', () => {
      expect(client.getState()).toBe<WebSocketState>('disconnected');
    });
  });

  describe('connect', () => {
    it('creates WebSocket with JWT token in URL query param', () => {
      client.connect('wss://agent.example.com/ws', 'my-jwt');
      const ws = latestMockWs();
      expect(ws.url).toBe('wss://agent.example.com/ws?token=my-jwt');
    });

    it('appends token with & when endpoint already has query params', () => {
      client.connect('wss://agent.example.com/ws?session=abc', 'my-jwt');
      const ws = latestMockWs();
      expect(ws.url).toBe('wss://agent.example.com/ws?session=abc&token=my-jwt');
    });

    it('sets binaryType to arraybuffer', () => {
      client.connect('wss://agent.example.com/ws', 'jwt');
      expect(latestMockWs().binaryType).toBe('arraybuffer');
    });

    it('transitions to connecting state', () => {
      client.connect('wss://agent.example.com/ws', 'jwt');
      expect(client.getState()).toBe<WebSocketState>('connecting');
    });

    it('resolves promise and transitions to connected on open', async () => {
      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;
      expect(client.getState()).toBe<WebSocketState>('connected');
    });

    it('rejects promise on initial connection failure', async () => {
      const { promise } = connectClient(client);
      latestMockWs().simulateClose(1006, 'Connection refused');
      await expect(promise).rejects.toThrow('Connection refused');
      expect(client.getState()).toBe<WebSocketState>('disconnected');
    });
  });

  describe('disconnect', () => {
    it('closes the WebSocket with code 1000', async () => {
      const { promise } = connectClient(client);
      const ws = latestMockWs();
      ws.simulateOpen();
      await promise;

      client.disconnect();
      expect(ws.closed).toBe(true);
      expect(ws.closeCode).toBe(1000);
      expect(client.getState()).toBe<WebSocketState>('disconnected');
    });

    it('prevents reconnection after intentional disconnect', async () => {
      const { promise } = connectClient(client);
      const ws = latestMockWs();
      ws.simulateOpen();
      await promise;

      client.disconnect();
      // Simulate close event after disconnect
      ws.simulateClose(1006, 'gone');

      // Advance timers — no reconnect should happen
      vi.advanceTimersByTime(10000);
      expect(MockWebSocket.instances).toHaveLength(1);
      expect(client.getState()).toBe<WebSocketState>('disconnected');
    });
  });

  describe('sending messages', () => {
    it('sendAudio sends ArrayBuffer when connected', async () => {
      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;

      const buf = new ArrayBuffer(16);
      client.sendAudio(buf);
      expect(latestMockWs().sent).toContain(buf);
    });

    it('sendTextMessage sends string when connected', async () => {
      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;

      client.sendTextMessage('{"type":"ui_state"}');
      expect(latestMockWs().sent).toContain('{"type":"ui_state"}');
    });

    it('sendAudio does nothing when not connected', () => {
      client.sendAudio(new ArrayBuffer(8));
      // No WebSocket created, no error thrown
      expect(MockWebSocket.instances).toHaveLength(0);
    });

    it('sendTextMessage does nothing when not connected', () => {
      client.sendTextMessage('hello');
      expect(MockWebSocket.instances).toHaveLength(0);
    });
  });

  describe('message demultiplexing', () => {
    it('routes binary frames to onBinaryMessage callbacks', async () => {
      const received: ArrayBuffer[] = [];
      client.onBinaryMessage((data) => received.push(data));

      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;

      const buf = new ArrayBuffer(32);
      latestMockWs().simulateMessage(buf);
      expect(received).toHaveLength(1);
      expect(received[0]).toBe(buf);
    });

    it('routes text frames to onTextMessage callbacks', async () => {
      const received: string[] = [];
      client.onTextMessage((data) => received.push(data));

      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;

      latestMockWs().simulateMessage('{"type":"order_update"}');
      expect(received).toHaveLength(1);
      expect(received[0]).toBe('{"type":"order_update"}');
    });

    it('supports multiple callbacks for the same message type', async () => {
      const r1: string[] = [];
      const r2: string[] = [];
      client.onTextMessage((d) => r1.push(d));
      client.onTextMessage((d) => r2.push(d));

      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;

      latestMockWs().simulateMessage('test');
      expect(r1).toHaveLength(1);
      expect(r2).toHaveLength(1);
    });
  });

  describe('auto-reconnect', () => {
    it('attempts reconnect on unexpected disconnect', async () => {
      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;

      // Simulate unexpected close
      latestMockWs().simulateClose(1006, 'Network error');
      expect(client.getState()).toBe<WebSocketState>('reconnecting');

      // After 1s delay, a new WebSocket should be created
      vi.advanceTimersByTime(1000);
      expect(MockWebSocket.instances).toHaveLength(2);
    });

    it('uses exponential backoff: 1s, 2s, 4s', async () => {
      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;

      // First disconnect
      latestMockWs().simulateClose(1006, 'err');
      expect(MockWebSocket.instances).toHaveLength(1);

      // Retry 1 at 1s
      vi.advanceTimersByTime(1000);
      expect(MockWebSocket.instances).toHaveLength(2);
      latestMockWs().simulateClose(1006, 'err');

      // Retry 2 at 2s
      vi.advanceTimersByTime(2000);
      expect(MockWebSocket.instances).toHaveLength(3);
      latestMockWs().simulateClose(1006, 'err');

      // Retry 3 at 4s
      vi.advanceTimersByTime(4000);
      expect(MockWebSocket.instances).toHaveLength(4);
    });

    it('stops reconnecting after 3 retries', async () => {
      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;

      // Exhaust all retries
      latestMockWs().simulateClose(1006, 'err');
      vi.advanceTimersByTime(1000);
      latestMockWs().simulateClose(1006, 'err');
      vi.advanceTimersByTime(2000);
      latestMockWs().simulateClose(1006, 'err');
      vi.advanceTimersByTime(4000);
      latestMockWs().simulateClose(1006, 'err');

      // No more retries
      vi.advanceTimersByTime(10000);
      expect(MockWebSocket.instances).toHaveLength(4); // 1 original + 3 retries
      expect(client.getState()).toBe<WebSocketState>('disconnected');
    });

    it('fires onReconnect callback on successful reconnect', async () => {
      const reconnected = vi.fn();
      client.onReconnect(reconnected);

      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;
      expect(reconnected).not.toHaveBeenCalled();

      // Disconnect and reconnect
      latestMockWs().simulateClose(1006, 'err');
      vi.advanceTimersByTime(1000);
      latestMockWs().simulateOpen();

      expect(reconnected).toHaveBeenCalledTimes(1);
      expect(client.getState()).toBe<WebSocketState>('connected');
    });

    it('resets retry count after successful reconnect', async () => {
      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;

      // First disconnect + reconnect
      latestMockWs().simulateClose(1006, 'err');
      vi.advanceTimersByTime(1000);
      latestMockWs().simulateOpen();

      // Second disconnect — should start retries from 0 again
      latestMockWs().simulateClose(1006, 'err');
      vi.advanceTimersByTime(1000);
      latestMockWs().simulateOpen();

      expect(client.getState()).toBe<WebSocketState>('connected');
    });

    it('fires onDisconnect callback on unexpected close', async () => {
      const disconnected = vi.fn();
      client.onDisconnect(disconnected);

      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;

      latestMockWs().simulateClose(1006, 'Network error');
      expect(disconnected).toHaveBeenCalledWith('Network error');
    });

    it('fires onDisconnect with default reason when none provided', async () => {
      const disconnected = vi.fn();
      client.onDisconnect(disconnected);

      const { promise } = connectClient(client);
      latestMockWs().simulateOpen();
      await promise;

      latestMockWs().simulateClose(1006, '');
      expect(disconnected).toHaveBeenCalledWith('Connection closed');
    });
  });
});
