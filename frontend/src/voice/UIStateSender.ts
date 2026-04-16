import type { AgentCoreWebSocketClient } from './WebSocketClient';
import type { UIState } from '../types';
import { useAppStore } from '../store/appStore';

export function buildUIState(): UIState {
  const state = useAppStore.getState();
  return {
    visibleCategory: state.agentUI.highlightedCategory,
    selectedItem: state.agentUI.highlightedItem,
    orderItems: state.agentUI.orderItems,
    orderTotal: state.agentUI.orderTotal,
  };
}

export function sendInitialState(client: AgentCoreWebSocketClient): void {
  client.send({ type: 'ui_state', ...buildUIState() });
}

export function sendCategoryChange(client: AgentCoreWebSocketClient, categoryId: string): void {
  const state = buildUIState();
  state.visibleCategory = categoryId;
  client.send({ type: 'ui_state', ...state });
}

export function sendItemSelection(client: AgentCoreWebSocketClient, itemId: string): void {
  const state = buildUIState();
  state.selectedItem = itemId;
  client.send({ type: 'ui_state', ...state });
}
