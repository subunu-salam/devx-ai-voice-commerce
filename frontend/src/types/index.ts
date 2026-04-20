// Menu data types

export interface Category {
  categoryId: string;
  name: string;
  sortOrder: number;
}

export interface MenuItem {
  itemId: string;
  categoryId: string;
  name: string;
  description: string;
  price: number; // cents
  imageUrl: string;
  category: string;
  featured: boolean;
  sortOrder: number;
}

export interface OrderItem {
  itemId: string;
  name: string;
  quantity: number;
  unitPrice: number; // cents
  specialInstructions?: string;
}

// Agent-controlled UI state — sent as a complete snapshot via update_ui tool
export interface AgentUIState {
  highlightedCategory: string | null;
  highlightedItem: string | null;
  orderItems: OrderItem[];
  orderTotal: number;
  orderConfirmed: boolean;
  orderNumber: string | null;
}

// The event the agent sends over WebSocket
export interface UIStateUpdateEvent {
  type: 'ui_state_update';
  state: AgentUIState;
}

// Legacy UI_Event types kept for backward compat (can be removed later)
export type UIEvent = UIStateUpdateEvent;

// Frontend -> Agent
export interface UIState {
  visibleCategory: string | null;
  selectedItem: string | null;
  orderItems: OrderItem[];
  orderTotal: number;
}

// Full application state
export interface AppState {
  menu: {
    categories: Category[];
    items: Record<string, MenuItem[]>;
    loading: boolean;
    error: string | null;
  };
  // Agent-controlled display state
  agentUI: AgentUIState;
  voice: {
    sessionActive: boolean;
    listening: boolean;
    micPermission: 'granted' | 'denied' | 'prompt';
  };
  auth: {
    authenticated: boolean;
    userId: string | null;
  };
}
