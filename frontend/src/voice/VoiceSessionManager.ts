import type { WebSocketClient } from './WebSocketClient';
import type { UIEvent } from '../types';
import { useAppStore } from '../store/appStore';

export class VoiceSessionManager {
  private wsClient: WebSocketClient;
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private scriptProcessor: ScriptProcessorNode | null = null;
  private playbackContext: AudioContext | null = null;
  private active = false;

  constructor(wsClient: WebSocketClient) {
    this.wsClient = wsClient;
  }

  async startSession(endpoint: string, jwtToken: string): Promise<void> {
    // 1. Request microphone access
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err: unknown) {
      const store = useAppStore.getState();
      store.setMicPermission('denied');
      if (err instanceof DOMException && err.name === 'NotAllowedError') {
        throw new Error('Microphone access is required for voice ordering. Please allow microphone access and try again.');
      }
      throw new Error('Failed to access microphone. Please check your device settings.');
    }

    // Mic granted
    const store = useAppStore.getState();
    store.setMicPermission('granted');

    // 2. Connect WebSocket
    await this.wsClient.connect(endpoint, jwtToken);

    // 3. Set up audio capture
    this.audioContext = new AudioContext({ sampleRate: 16000 });
    const source = this.audioContext.createMediaStreamSource(this.mediaStream);
    // Buffer size 4096, 1 input channel, 1 output channel
    this.scriptProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);

    this.scriptProcessor.onaudioprocess = (event: AudioProcessingEvent) => {
      if (!this.active) return;
      const inputData = event.inputBuffer.getChannelData(0);
      // Convert Float32 PCM to Int16 PCM
      const pcm16 = new ArrayBuffer(inputData.length * 2);
      const view = new DataView(pcm16);
      for (let i = 0; i < inputData.length; i++) {
        const s = Math.max(-1, Math.min(1, inputData[i]));
        view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      }
      this.wsClient.sendAudio(pcm16);
    };

    source.connect(this.scriptProcessor);
    this.scriptProcessor.connect(this.audioContext.destination);

    // 4. Set up audio playback from received binary frames
    // Use default sample rate — we specify the correct rate per buffer in playAudio()
    this.playbackContext = new AudioContext();
    this.nextPlayTime = 0;
    this.wsClient.onBinaryMessage((data: ArrayBuffer) => {
      this.playAudio(data);
    });

    // 5. Set up UI_Event handling from text frames
    this.wsClient.onTextMessage((data: string) => {
      try {
        const event = JSON.parse(data) as UIEvent;
        const currentStore = useAppStore.getState();
        currentStore.applyUIEvent(event);
      } catch {
        // Ignore malformed JSON per error handling spec
      }
    });

    // 6. Mark session as active
    this.active = true;
    store.setVoiceSession(true);
    store.setListening(true);
  }

  endSession(): void {
    // 1. Stop all media tracks
    if (this.mediaStream) {
      for (const track of this.mediaStream.getTracks()) {
        track.stop();
      }
      this.mediaStream = null;
    }

    // 2. Close AudioContext (capture)
    if (this.scriptProcessor) {
      this.scriptProcessor.disconnect();
      this.scriptProcessor = null;
    }
    if (this.audioContext) {
      this.audioContext.close().catch(() => {});
      this.audioContext = null;
    }

    // 3. Close playback AudioContext
    if (this.playbackContext) {
      this.playbackContext.close().catch(() => {});
      this.playbackContext = null;
    }

    // 4. Disconnect WebSocket
    this.wsClient.disconnect();

    // 5. Mark session as inactive (preserves order items via endVoiceSession)
    this.active = false;
    const store = useAppStore.getState();
    store.endVoiceSession();
  }

  isActive(): boolean {
    return this.active;
  }

  // Tracks when the next audio chunk should start playing
  private nextPlayTime = 0;

  private playAudio(data: ArrayBuffer): void {
    if (!this.playbackContext) return;
    // Interpret received binary as Int16 PCM at 16000 Hz from Nova Sonic
    const int16 = new Int16Array(data);
    if (int16.length === 0) return;

    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 0x8000;
    }

    const sampleRate = 16000;
    const buffer = this.playbackContext.createBuffer(1, float32.length, sampleRate);
    buffer.getChannelData(0).set(float32);

    const source = this.playbackContext.createBufferSource();
    source.buffer = buffer;
    source.connect(this.playbackContext.destination);

    // Schedule chunks sequentially so they don't overlap
    const now = this.playbackContext.currentTime;
    const startTime = Math.max(now, this.nextPlayTime);
    source.start(startTime);
    this.nextPlayTime = startTime + buffer.duration;
  }
}
