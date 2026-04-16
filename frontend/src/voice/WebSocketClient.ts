/**
 * WebSocket client for AgentCore using OAuth via Sec-WebSocket-Protocol.
 * All communication is JSON — audio is base64-encoded inside typed events.
 */

export type WebSocketState = 'connecting' | 'connected' | 'disconnected';

export interface BidiEvent {
  type: string;
  [key: string]: unknown;
}

export interface AgentCoreWebSocketClient {
  connect(runtimeArn: string, region: string, jwtToken: string): Promise<void>;
  disconnect(): void;
  send(event: BidiEvent): void;
  onEvent(callback: (event: BidiEvent) => void): void;
  onDisconnect(callback: () => void): void;
  getState(): WebSocketState;
}

export function createWebSocketClient(): AgentCoreWebSocketClient {
  let ws: WebSocket | null = null;
  let state: WebSocketState = 'disconnected';
  const eventCallbacks: Array<(event: BidiEvent) => void> = [];
  const disconnectCallbacks: Array<() => void> = [];

  return {
    async connect(runtimeArn, region, jwtToken) {
      state = 'connecting';

      const encodedArn = encodeURIComponent(runtimeArn);
      const sessionId = crypto.randomUUID();
      const url = `wss://bedrock-agentcore.${region}.amazonaws.com/runtimes/${encodedArn}/ws?qualifier=DEFAULT&X-Amzn-Bedrock-AgentCore-Runtime-Session-Id=${sessionId}`;

      // OAuth via Sec-WebSocket-Protocol: base64url-encode the token
      const base64url = btoa(jwtToken)
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=/g, '');
      const protocols = [
        `base64UrlBearerAuthorization.${base64url}`,
        'base64UrlBearerAuthorization',
      ];

      console.log('[WS] Connecting to:', url.substring(0, 120) + '...');

      return new Promise<void>((resolve, reject) => {
        ws = new WebSocket(url, protocols);

        ws.onopen = () => {
          console.log('[WS] Connected');
          state = 'connected';
          resolve();
        };

        ws.onerror = (event) => {
          console.error('[WS] Error:', event);
          state = 'disconnected';
          reject(new Error('WebSocket connection failed'));
        };

        ws.onclose = (event) => {
          console.log('[WS] Closed:', event.code, event.reason, 'clean:', event.wasClean);
          state = 'disconnected';
          for (const cb of disconnectCallbacks) cb();
        };

        ws.onmessage = (msg) => {
          try {
            const event = JSON.parse(msg.data) as BidiEvent;
            for (const cb of eventCallbacks) cb(event);
          } catch { /* ignore non-JSON */ }
        };
      });
    },

    disconnect() {
      if (ws) {
        ws.close();
        ws = null;
      }
      state = 'disconnected';
    },

    send(event) {
      if (ws && state === 'connected') {
        ws.send(JSON.stringify(event));
      }
    },

    onEvent(callback) {
      eventCallbacks.push(callback);
    },

    onDisconnect(callback) {
      disconnectCallbacks.push(callback);
    },

    getState() {
      return state;
    },
  };
}
