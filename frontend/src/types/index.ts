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
  specialInstructions?: string; // e.g. "no pickles, extra sauce"
}

// Agent -> Frontend UI_Event protocol

export interface OrderUpdatePayload {
  items: OrderItem[];
  total: number;
}

export interface CategoryPayload {
  categoryId: string;
  categoryName: string;
}

export interface ItemPayload {
  itemId: string;
  itemName: string;
}

export interface OrderConfirmedPayload {
  orderNumber: string;
  items: OrderItem[];
  total: number;
  timestamp: string;
}

export interface ItemDetailPayload {
  itemId: string;
  categoryId: string;
  name: string;
  description: string;
  price: number;
  imageUrl: string;
  category: string;
}

export type UIEvent =
  | { type: 'order_update'; payload: OrderUpdatePayload }
  | { type: 'highlight_category'; payload: CategoryPayload }
  | { type: 'browse_category'; payload: CategoryPayload }
  | { type: 'highlight_item'; payload: ItemPayload }
  | { type: 'order_confirmed'; payload: OrderConfirmedPayload }
  | { type: 'show_item_detail'; payload: ItemDetailPayload };

// Frontend -> Agent UI_State protocol

export interface UIState {
  visibleCategory: string | null;
  selectedItem: string | null;
  orderItems: OrderItem[];
  orderTotal: number;
}

// Application state

export interface AppState {
  menu: {
    categories: Category[];
    items: Record<string, MenuItem[]>;
    highlightedCategory: string | null;
    highlightedItem: string | null;
    loading: boolean;
    error: string | null;
  };
  order: {
    items: OrderItem[];
    total: number;
    confirmed: boolean;
    orderNumber: string | null;
  };
  voice: {
    sessionActive: boolean;
    listening: boolean;
    micPermission: 'granted' | 'denied' | 'prompt';
  };
  auth: {
    authenticated: boolean;
    userId: string | null;
  };
  itemDetail: ItemDetailPayload | null;
}
