export type WebSocketState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';

export interface WebSocketClient {
  connect(endpoint: string, jwtToken: string): Promise<void>;
  disconnect(): void;
  sendAudio(data: ArrayBuffer): void;
  sendTextMessage(message: string): void;
  onBinaryMessage(callback: (data: ArrayBuffer) => void): void;
  onTextMessage(callback: (data: string) => void): void;
  onDisconnect(callback: (reason: string) => void): void;
  onReconnect(callback: () => void): void;
  getState(): WebSocketState;
}

const MAX_RETRIES = 3;
const BASE_DELAY_MS = 1000;

export class AgentCoreWebSocketClient implements WebSocketClient {
  private ws: WebSocket | null = null;
  private state: WebSocketState = 'disconnected';
  private retryCount = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;

  private endpoint = '';
  private jwtToken = '';

  private binaryCallbacks: Array<(data: ArrayBuffer) => void> = [];
  private textCallbacks: Array<(data: string) => void> = [];
  private disconnectCallbacks: Array<(reason: string) => void> = [];
  private reconnectCallbacks: Array<() => void> = [];

  connect(endpoint: string, jwtToken: string): Promise<void> {
    this.endpoint = endpoint;
    this.jwtToken = jwtToken;
    this.intentionalClose = false;
    this.retryCount = 0;
    return this.createConnection();
  }

  disconnect(): void {
    this.intentionalClose = true;
    this.clearRetryTimer();
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    this.state = 'disconnected';
  }

  sendAudio(data: ArrayBuffer): void {
    if (this.ws && this.state === 'connected') {
      this.ws.send(data);
    }
  }

  sendTextMessage(message: string): void {
    if (this.ws && this.state === 'connected') {
      this.ws.send(message);
    }
  }

  onBinaryMessage(callback: (data: ArrayBuffer) => void): void {
    this.binaryCallbacks.push(callback);
  }

  onTextMessage(callback: (data: string) => void): void {
    this.textCallbacks.push(callback);
  }

  onDisconnect(callback: (reason: string) => void): void {
    this.disconnectCallbacks.push(callback);
  }

  onReconnect(callback: () => void): void {
    this.reconnectCallbacks.push(callback);
  }

  getState(): WebSocketState {
    return this.state;
  }

  private createConnection(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      this.state = this.retryCount > 0 ? 'reconnecting' : 'connecting';

      const url = this.endpoint;

      // Browser WebSocket API can't set custom headers, so AgentCore accepts
      // the OAuth bearer token via Sec-WebSocket-Protocol header:
      // base64url-encode the token, prefix with "base64UrlBearerAuthorization.",
      // and include the sentinel subprotocol "base64UrlBearerAuthorization".
      const base64url = btoa(this.jwtToken)
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=/g, '');
      const protocols = [
        `base64UrlBearerAuthorization.${base64url}`,
        'base64UrlBearerAuthorization',
      ];

      try {
        this.ws = new WebSocket(url, protocols);
        this.ws.binaryType = 'arraybuffer';
      } catch (err) {
        this.state = 'disconnected';
        reject(err);
        return;
      }

      this.ws.onopen = () => {
        const wasReconnect = this.retryCount > 0;
        this.state = 'connected';
        this.retryCount = 0;
        if (wasReconnect) {
          for (const cb of this.reconnectCallbacks) cb();
        }
        resolve();
      };

      this.ws.onmessage = (event: MessageEvent) => {
        if (event.data instanceof ArrayBuffer) {
          for (const cb of this.binaryCallbacks) cb(event.data);
        } else if (typeof event.data === 'string') {
          for (const cb of this.textCallbacks) cb(event.data);
        }
      };

      this.ws.onerror = () => {
        // Error is followed by close, so handling happens in onclose
      };

      this.ws.onclose = (event: CloseEvent) => {
        this.ws = null;

        if (this.intentionalClose) {
          this.state = 'disconnected';
          return;
        }

        const reason = event.reason || 'Connection closed';

        if (this.state === 'connecting' && this.retryCount === 0) {
          // Initial connection failed
          this.state = 'disconnected';
          reject(new Error(reason));
          return;
        }

        for (const cb of this.disconnectCallbacks) cb(reason);
        this.scheduleReconnect();
      };
    });
  }

  private scheduleReconnect(): void {
    if (this.intentionalClose || this.retryCount >= MAX_RETRIES) {
      this.state = 'disconnected';
      return;
    }

    this.state = 'reconnecting';
    const delay = BASE_DELAY_MS * Math.pow(2, this.retryCount);
    this.retryCount++;

    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.createConnection().catch(() => {
        // Reconnect failure handled in onclose
      });
    }, delay);
  }

  private clearRetryTimer(): void {
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
  }
}
