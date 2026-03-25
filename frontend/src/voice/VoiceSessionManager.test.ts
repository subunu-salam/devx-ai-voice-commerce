import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { VoiceSessionManager } from './VoiceSessionManager';
import type { WebSocketClient, WebSocketState } from './WebSocketClient';
import { useAppStore } from '../store/appStore';

// --- Mock WebSocketClient ---

function createMockWsClient(): WebSocketClient & {
  _binaryCallbacks: Array<(data: ArrayBuffer) => void>;
  _textCallbacks: Array<(data: string) => void>;
  _disconnectCallbacks: Array<(reason: string) => void>;
  _reconnectCallbacks: Array<() => void>;
  _connected: boolean;
} {
  const mock = {
    _binaryCallbacks: [] as Array<(data: ArrayBuffer) => void>,
    _textCallbacks: [] as Array<(data: string) => void>,
    _disconnectCallbacks: [] as Array<(reason: string) => void>,
    _reconnectCallbacks: [] as Array<() => void>,
    _connected: false,
    connect: vi.fn(async () => { mock._connected = true; }),
    disconnect: vi.fn(() => { mock._connected = false; }),
    sendAudio: vi.fn(),
    sendTextMessage: vi.fn(),
    onBinaryMessage: vi.fn((cb: (data: ArrayBuffer) => void) => {
      mock._binaryCallbacks.push(cb);
    }),
    onTextMessage: vi.fn((cb: (data: string) => void) => {
      mock._textCallbacks.push(cb);
    }),
    onDisconnect: vi.fn((cb: (reason: string) => void) => {
      mock._disconnectCallbacks.push(cb);
    }),
    onReconnect: vi.fn((cb: () => void) => {
      mock._reconnectCallbacks.push(cb);
    }),
    getState: vi.fn((): WebSocketState => (mock._connected ? 'connected' : 'disconnected')),
  };
  return mock;
}

// --- Mock MediaStream & getUserMedia ---

class MockMediaStreamTrack {
  enabled = true;
  stopped = false;
  stop() { this.stopped = true; }
}

class MockMediaStream {
  private tracks: MockMediaStreamTrack[];
  constructor(tracks: MockMediaStreamTrack[] = [new MockMediaStreamTrack()]) {
    this.tracks = tracks;
  }
  getTracks() { return this.tracks; }
}

// --- Mock AudioContext ---

const mockSourceConnect = vi.fn();
const mockProcessorConnect = vi.fn();
const mockProcessorDisconnect = vi.fn();
const mockClose = vi.fn(async () => {});

const mockCreateMediaStreamSource = vi.fn(() => ({
  connect: mockSourceConnect,
}));

const mockCreateScriptProcessor = vi.fn(() => ({
  connect: mockProcessorConnect,
  disconnect: mockProcessorDisconnect,
  onaudioprocess: null as ((event: unknown) => void) | null,
}));

const mockCreateBuffer = vi.fn(() => ({
  getChannelData: vi.fn(() => new Float32Array(0)),
}));

const mockCreateBufferSource = vi.fn(() => ({
  buffer: null,
  connect: vi.fn(),
  start: vi.fn(),
}));

class MockAudioContext {
  sampleRate = 16000;
  destination = {};
  createMediaStreamSource = mockCreateMediaStreamSource;
  createScriptProcessor = mockCreateScriptProcessor;
  createBuffer = mockCreateBuffer;
  createBufferSource = mockCreateBufferSource;
  close = mockClose;
}

// --- Setup / Teardown ---

const originalNavigator = globalThis.navigator;
const originalAudioContext = globalThis.AudioContext;

beforeEach(() => {
  useAppStore.setState({
    voice: { sessionActive: false, listening: false, micPermission: 'prompt' },
    order: { items: [], total: 0, confirmed: false, orderNumber: null },
  });
  vi.clearAllMocks();
  (globalThis as Record<string, unknown>).AudioContext = MockAudioContext;
});

afterEach(() => {
  (globalThis as Record<string, unknown>).AudioContext = originalAudioContext;
});

// --- Helper to mock getUserMedia ---

function mockGetUserMedia(result: 'granted' | 'denied') {
  const mediaDevices = {
    getUserMedia: result === 'granted'
      ? vi.fn(async () => new MockMediaStream())
      : vi.fn(async () => {
          throw new DOMException('Permission denied', 'NotAllowedError');
        }),
  };
  Object.defineProperty(globalThis, 'navigator', {
    value: { ...originalNavigator, mediaDevices },
    writable: true,
    configurable: true,
  });
  return mediaDevices;
}

function restoreNavigator() {
  Object.defineProperty(globalThis, 'navigator', {
    value: originalNavigator,
    writable: true,
    configurable: true,
  });
}

// --- Tests ---

describe('VoiceSessionManager', () => {
  let wsClient: ReturnType<typeof createMockWsClient>;
  let manager: VoiceSessionManager;

  beforeEach(() => {
    wsClient = createMockWsClient();
    manager = new VoiceSessionManager(wsClient);
  });

  afterEach(() => {
    restoreNavigator();
  });

  describe('initial state', () => {
    it('starts inactive', () => {
      expect(manager.isActive()).toBe(false);
    });
  });

  describe('startSession', () => {
    it('requests microphone access and connects WebSocket', async () => {
      const mediaDevices = mockGetUserMedia('granted');
      await manager.startSession('wss://agent.example.com/ws', 'jwt-123');
      expect(mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: true });
      expect(wsClient.connect).toHaveBeenCalledWith('wss://agent.example.com/ws', 'jwt-123');
      expect(manager.isActive()).toBe(true);
    });

    it('sets mic permission to granted on success', async () => {
      mockGetUserMedia('granted');
      await manager.startSession('wss://agent.example.com/ws', 'jwt-123');
      expect(useAppStore.getState().voice.micPermission).toBe('granted');
    });

    it('sets voice session active and listening in store', async () => {
      mockGetUserMedia('granted');
      await manager.startSession('wss://agent.example.com/ws', 'jwt-123');
      const state = useAppStore.getState();
      expect(state.voice.sessionActive).toBe(true);
      expect(state.voice.listening).toBe(true);
    });

    it('sets up audio capture with AudioContext and ScriptProcessor', async () => {
      mockGetUserMedia('granted');
      await manager.startSession('wss://agent.example.com/ws', 'jwt-123');
      expect(mockCreateMediaStreamSource).toHaveBeenCalled();
      expect(mockCreateScriptProcessor).toHaveBeenCalledWith(4096, 1, 1);
      expect(mockSourceConnect).toHaveBeenCalled();
      expect(mockProcessorConnect).toHaveBeenCalled();
    });

    it('registers binary and text message handlers on WebSocket', async () => {
      mockGetUserMedia('granted');
      await manager.startSession('wss://agent.example.com/ws', 'jwt-123');
      expect(wsClient.onBinaryMessage).toHaveBeenCalled();
      expect(wsClient.onTextMessage).toHaveBeenCalled();
    });

    it('throws descriptive error when mic permission is denied', async () => {
      mockGetUserMedia('denied');
      await expect(
        manager.startSession('wss://agent.example.com/ws', 'jwt-123'),
      ).rejects.toThrow('Microphone access is required for voice ordering');
      expect(manager.isActive()).toBe(false);
    });

    it('sets mic permission to denied in store when denied', async () => {
      mockGetUserMedia('denied');
      await expect(
        manager.startSession('wss://agent.example.com/ws', 'jwt-123'),
      ).rejects.toThrow();
      expect(useAppStore.getState().voice.micPermission).toBe('denied');
    });

    it('does not connect WebSocket when mic is denied', async () => {
      mockGetUserMedia('denied');
      await expect(
        manager.startSession('wss://agent.example.com/ws', 'jwt-123'),
      ).rejects.toThrow();
      expect(wsClient.connect).not.toHaveBeenCalled();
    });
  });

  describe('text message handling (UI_Events)', () => {
    it('dispatches valid UI_Events to the store', async () => {
      mockGetUserMedia('granted');
      await manager.startSession('wss://agent.example.com/ws', 'jwt-123');

      const orderUpdateEvent = JSON.stringify({
        type: 'order_update',
        payload: {
          items: [{ itemId: 'burger-1', name: 'Cheeseburger', quantity: 2, unitPrice: 599 }],
          total: 1198,
        },
      });
      for (const cb of wsClient._textCallbacks) { cb(orderUpdateEvent); }

      const state = useAppStore.getState();
      expect(state.order.items).toHaveLength(1);
      expect(state.order.items[0].name).toBe('Cheeseburger');
      expect(state.order.total).toBe(1198);
    });

    it('ignores malformed JSON text messages', async () => {
      mockGetUserMedia('granted');
      await manager.startSession('wss://agent.example.com/ws', 'jwt-123');
      for (const cb of wsClient._textCallbacks) { cb('not valid json {{{'); }
      expect(useAppStore.getState().order.items).toHaveLength(0);
    });
  });

  describe('endSession', () => {
    it('marks session as inactive', async () => {
      mockGetUserMedia('granted');
      await manager.startSession('wss://agent.example.com/ws', 'jwt-123');
      manager.endSession();
      expect(manager.isActive()).toBe(false);
    });

    it('disconnects WebSocket', async () => {
      mockGetUserMedia('granted');
      await manager.startSession('wss://agent.example.com/ws', 'jwt-123');
      manager.endSession();
      expect(wsClient.disconnect).toHaveBeenCalled();
    });

    it('closes AudioContext', async () => {
      mockGetUserMedia('granted');
      await manager.startSession('wss://agent.example.com/ws', 'jwt-123');
      manager.endSession();
      expect(mockClose).toHaveBeenCalled();
    });

    it('sets voice session inactive in store via endVoiceSession', async () => {
      mockGetUserMedia('granted');
      await manager.startSession('wss://agent.example.com/ws', 'jwt-123');
      manager.endSession();
      const state = useAppStore.getState();
      expect(state.voice.sessionActive).toBe(false);
      expect(state.voice.listening).toBe(false);
    });

    it('preserves order items after session ends', async () => {
      mockGetUserMedia('granted');
      await manager.startSession('wss://agent.example.com/ws', 'jwt-123');

      const orderUpdateEvent = JSON.stringify({
        type: 'order_update',
        payload: {
          items: [{ itemId: 'fries-1', name: 'Large Fries', quantity: 1, unitPrice: 349 }],
          total: 349,
        },
      });
      for (const cb of wsClient._textCallbacks) { cb(orderUpdateEvent); }

      manager.endSession();

      const state = useAppStore.getState();
      expect(state.order.items).toHaveLength(1);
      expect(state.order.items[0].name).toBe('Large Fries');
      expect(state.order.total).toBe(349);
    });

    it('can be called safely when no session is active', () => {
      manager.endSession();
      expect(manager.isActive()).toBe(false);
    });
  });
});
