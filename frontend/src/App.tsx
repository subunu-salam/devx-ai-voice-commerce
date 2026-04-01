import { useEffect, useRef, useCallback, useState } from 'react';
import { useAuthenticator } from '@aws-amplify/ui-react';
import { fetchAuthSession } from 'aws-amplify/auth';
import { MenuDisplay, OrderSummaryPanel, OrderConfirmation } from './components';
import { useAppStore } from './store';
import { createMenuService, groupItemsByCategory } from './services';
import {
  AgentCoreWebSocketClient,
  VoiceSessionManager,
  sendInitialState,
  sendItemSelection,
} from './voice';
import { getRuntimeConfig } from './config';
import type { MenuItem } from './types';

async function getJwtToken(): Promise<string> {
  const session = await fetchAuthSession();
  const token = session.tokens?.accessToken?.toString();
  if (!token) throw new Error('No JWT token available');
  return token;
}

async function getAwsCredentials() {
  const session = await fetchAuthSession();
  const creds = session.credentials;
  if (!creds) throw new Error('No AWS credentials available');
  return {
    accessKeyId: creds.accessKeyId,
    secretAccessKey: creds.secretAccessKey,
    sessionToken: creds.sessionToken,
  };
}

export default function App() {
  const { signOut } = useAuthenticator();
  const { setMenuData, setMenuLoading, setMenuError } = useAppStore();

  const sessionActive = useAppStore((s) => s.voice.sessionActive);
  const listening = useAppStore((s) => s.voice.listening);
  const micPermission = useAppStore((s) => s.voice.micPermission);
  const orderConfirmed = useAppStore((s) => s.order.confirmed);

  const voiceManagerRef = useRef<VoiceSessionManager | null>(null);
  const wsClientRef = useRef<AgentCoreWebSocketClient | null>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);

  // Load menu data on mount
  useEffect(() => {
    let cancelled = false;
    async function loadMenu() {
      setMenuLoading(true);
      setMenuError(null);
      try {
        const creds = await getAwsCredentials();
        const menuService = createMenuService(creds);
        const [categories, allItems] = await Promise.all([
          menuService.getCategories(),
          menuService.getAllMenuItems(),
        ]);
        if (cancelled) return;
        const grouped = groupItemsByCategory(allItems);
        setMenuData(categories, grouped);
      } catch (err) {
        if (cancelled) return;
        setMenuError((err as Error).message);
      } finally {
        if (!cancelled) setMenuLoading(false);
      }
    }
    void loadMenu();
    return () => { cancelled = true; };
  }, [setMenuData, setMenuLoading, setMenuError]);

  const handleStartVoice = useCallback(async () => {
    setVoiceError(null);
    try {
      const wsClient = new AgentCoreWebSocketClient();
      wsClientRef.current = wsClient;
      const manager = new VoiceSessionManager(wsClient);
      voiceManagerRef.current = manager;

      const token = await getJwtToken();
      await manager.startSession(getRuntimeConfig().agentEndpointUrl, token);
      sendInitialState(wsClient);
    } catch (err) {
      setVoiceError((err as Error).message);
    }
  }, []);

  const handleStopVoice = useCallback(() => {
    if (voiceManagerRef.current) {
      voiceManagerRef.current.endSession();
      voiceManagerRef.current = null;
      wsClientRef.current = null;
    }
  }, []);

  const handleItemClick = useCallback((item: MenuItem) => {
    if (wsClientRef.current && sessionActive) {
      sendItemSelection(wsClientRef.current, item.itemId);
    }
  }, [sessionActive]);

  if (orderConfirmed) {
    return (
      <div style={{ maxWidth: 600, margin: '0 auto', padding: 16 }}>
        <OrderConfirmation />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>Drive-Thru</h1>
        <button onClick={signOut} type="button">Sign Out</button>
      </div>

      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        {!sessionActive ? (
          <button onClick={handleStartVoice} type="button">
            Start Voice Order
          </button>
        ) : (
          <button onClick={handleStopVoice} type="button">
            Stop
          </button>
        )}
        {listening && (
          <span role="status" aria-label="Listening" style={{ color: 'green' }}>
            🎙️ Listening…
          </span>
        )}
        {micPermission === 'denied' && (
          <span role="alert" style={{ color: 'red' }}>
            Microphone access denied. Please allow microphone access to use voice ordering.
          </span>
        )}
        {voiceError && (
          <span role="alert" style={{ color: 'red' }}>
            {voiceError}
          </span>
        )}
      </div>

      <div style={{ display: 'flex', gap: 24 }}>
        <div style={{ flex: 2 }}>
          <MenuDisplay onItemClick={handleItemClick} />
        </div>
        <div style={{ flex: 1 }}>
          <OrderSummaryPanel />
        </div>
      </div>
    </div>
  );
}
