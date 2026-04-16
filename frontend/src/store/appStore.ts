import { create } from 'zustand';
import type { AppState, AgentUIState, Category, MenuItem } from '../types';

interface AppActions {
  applyAgentUIState: (state: AgentUIState) => void;
  setMenuData: (categories: Category[], items: Record<string, MenuItem[]>) => void;
  setMenuLoading: (loading: boolean) => void;
  setMenuError: (error: string | null) => void;
  setVoiceSession: (active: boolean) => void;
  setListening: (listening: boolean) => void;
  setMicPermission: (permission: 'granted' | 'denied' | 'prompt') => void;
  endVoiceSession: () => void;
}

const initialAgentUI: AgentUIState = {
  highlightedCategory: null,
  highlightedItem: null,
  itemDetail: null,
  orderItems: [],
  orderTotal: 0,
  orderConfirmed: false,
  orderNumber: null,
};

const initialState: AppState = {
  menu: {
    categories: [],
    items: {},
    loading: false,
    error: null,
  },
  agentUI: initialAgentUI,
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

  // Replace the entire agent-controlled UI state
  applyAgentUIState: (agentUI: AgentUIState) =>
    set(() => ({ agentUI })),

  setMenuData: (categories, items) =>
    set((s) => ({ menu: { ...s.menu, categories, items } })),

  setMenuLoading: (loading) =>
    set((s) => ({ menu: { ...s.menu, loading } })),

  setMenuError: (error) =>
    set((s) => ({ menu: { ...s.menu, error } })),

  setVoiceSession: (active) =>
    set((s) => ({ voice: { ...s.voice, sessionActive: active } })),

  setListening: (listening) =>
    set((s) => ({ voice: { ...s.voice, listening } })),

  setMicPermission: (permission) =>
    set((s) => ({ voice: { ...s.voice, micPermission: permission } })),

  endVoiceSession: () =>
    set((s) => ({ voice: { ...s.voice, sessionActive: false, listening: false } })),
}));
