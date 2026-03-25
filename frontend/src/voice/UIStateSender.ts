import type { WebSocketClient } from './WebSocketClient';
import type { UIState } from '../types';
import { useAppStore } from '../store/appStore';

/**
 * Builds the current UIState from the Zustand store.
 */
export function buildUIState(): UIState {
  const state = useAppStore.getState();
  return {
    visibleCategory: state.menu.highlightedCategory,
    selectedItem: state.menu.highlightedItem,
    orderItems: state.order.items,
    orderTotal: state.order.total,
  };
}

/**
 * Sends the full current UIState over WebSocket (used on initial connect).
 */
export function sendInitialState(wsClient: WebSocketClient): void {
  const uiState = buildUIState();
  wsClient.sendTextMessage(JSON.stringify(uiState));
}

/**
 * Sends a UIState with the updated visibleCategory.
 */
export function sendCategoryChange(wsClient: WebSocketClient, categoryId: string): void {
  const uiState = buildUIState();
  uiState.visibleCategory = categoryId;
  wsClient.sendTextMessage(JSON.stringify(uiState));
}

/**
 * Sends a UIState with the updated selectedItem.
 */
export function sendItemSelection(wsClient: WebSocketClient, itemId: string): void {
  const uiState = buildUIState();
  uiState.selectedItem = itemId;
  wsClient.sendTextMessage(JSON.stringify(uiState));
}
