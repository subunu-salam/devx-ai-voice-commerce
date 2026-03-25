import { useEffect, useRef, useCallback, useState } from 'react';
import { useAuth } from './auth';
import { SignInForm } from './auth';
import { MenuDisplay, OrderSummaryPanel, OrderConfirmation } from './components';
import { useAppStore } from './store';
import { createMenuService, groupItemsByCategory } from './services';
import {
  AgentCoreWebSocketClient,
  VoiceSessionManager,
  sendInitialState,
  sendItemSelection,
} from './voice';
import type { MenuItem } from './types';

const AGENT_ENDPOINT = import.meta.env.VITE_AGENT_ENDPOINT ?? '';

function AuthenticatedApp() {
  const { getJwtToken, getAwsCredentials } = useAuth();
  const {
    setMenuData,
    setMenuLoading,
    setMenuError,
  } = useAppStore();

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
  }, [getAwsCredentials, setMenuData, setMenuLoading, setMenuError]);

  const handleStartVoice = useCallback(async () => {
    setVoiceError(null);
    try {
      const wsClient = new AgentCoreWebSocketClient();
      wsClientRef.current = wsClient;
      const manager = new VoiceSessionManager(wsClient);
      voiceManagerRef.current = manager;

      const token = await getJwtToken();
      await manager.startSession(AGENT_ENDPOINT, token);

      // Send initial UI_State after connection
      sendInitialState(wsClient);
    } catch (err) {
      setVoiceError((err as Error).message);
    }
  }, [getJwtToken]);

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
      {/* Voice controls */}
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

      {/* Two-column layout: menu left, order right */}
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

export default function App() {
  const { authenticated, loading } = useAuth();

  if (loading) {
    return <div role="status">Loading…</div>;
  }

  if (!authenticated) {
    return (
      <div style={{ maxWidth: 400, margin: '80px auto', padding: 16 }}>
        <SignInForm />
      </div>
    );
  }

  return <AuthenticatedApp />;
}
