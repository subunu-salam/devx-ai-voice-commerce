import { useAppStore } from '../store';
import { formatPrice } from '../utils/formatPrice';
import type { BurgerBuilderState } from '../types';

const TOPPING_ICONS: Record<string, string> = {
  'beef patty': '🥩',
  'chicken patty': '🍗',
  'american cheese': '🧀',
  'cheddar cheese': '🧀',
  'pepper jack cheese': '🧀',
  'swiss cheese': '🧀',
  'bacon': '🥓',
  'avocado': '🥑',
  'fried egg': '🍳',
  'lettuce': '🥬',
  'tomato': '🍅',
  'onion': '🧅',
  'pickles': '🥒',
  'jalapeños': '🌶️',
  'mushrooms': '🍄',
  'ketchup': '🔴',
  'mustard': '🟡',
  'mayo': '⚪',
  'bbq sauce': '🟤',
  'chipotle mayo': '🟠',
  'special sauce': '✨',
};

const TOPPING_PRICES: Record<string, number> = {
  'american cheese': 100,
  'cheddar cheese': 100,
  'pepper jack cheese': 100,
  'swiss cheese': 100,
  'bacon': 150,
  'avocado': 150,
  'fried egg': 150,
};

export function BurgerBuilder() {
  const builder = useAppStore((s) => s.agentUI.burgerBuilder);
  const highlightedItem = useAppStore((s) => s.agentUI.highlightedItem);

  // Show when burger builder state is active OR when custom-burger is highlighted
  const isOpen = (builder && builder.active) || highlightedItem === 'custom-burger';

  if (!isOpen) return null;

  // Use builder state if available, otherwise show empty starter state
  const state = builder && builder.active ? builder : {
    active: true,
    patty: null,
    toppings: [],
    sauces: [],
    price: 899,
  };

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        backgroundColor: 'rgba(0,0,0,0.5)',
      }}
      onClick={() => useAppStore.getState().applyAgentUIState({
        ...useAppStore.getState().agentUI,
        burgerBuilder: null,
        highlightedItem: null,
      })}
    >
      <div
        style={{
          background: '#fff', borderRadius: 16, padding: 24,
          maxWidth: 480, width: '90%', maxHeight: '85vh', overflow: 'auto',
          boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ margin: '0 0 4px', textAlign: 'center' }}>🍔 Build Your Burger</h2>
        <p style={{ color: '#666', textAlign: 'center', margin: '0 0 16px', fontSize: '0.9em' }}>
          Tell the agent what you want!
        </p>

        {/* Burger Stack Visualization */}
        <BurgerStack builder={state} />

        {/* Selected ingredients list */}
        <div style={{ marginTop: 16 }}>
          {state.patty && (
            <IngredientSection title="Patty" items={[state.patty]} />
          )}
          {state.toppings.length > 0 && (
            <IngredientSection title="Toppings" items={state.toppings} />
          )}
          {state.sauces.length > 0 && (
            <IngredientSection title="Sauces" items={state.sauces} />
          )}
          {!state.patty && state.toppings.length === 0 && state.sauces.length === 0 && (
            <p style={{ textAlign: 'center', color: '#aaa', fontStyle: 'italic', padding: '12px 0' }}>
              Start by telling me what patty you'd like...
            </p>
          )}
        </div>

        {/* Running total */}
        <div style={{
          marginTop: 16, padding: '12px 16px',
          background: '#f8f9fa', borderRadius: 8,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span style={{ fontWeight: 'bold' }}>Running Total</span>
          <span style={{ fontSize: '1.3em', fontWeight: 'bold', color: '#27ae60' }}>
            {formatPrice(state.price)}
          </span>
        </div>
      </div>
    </div>
  );
}

function BurgerStack({ builder }: { builder: BurgerBuilderState }) {
  const layers: { label: string; color: string; height: number }[] = [];

  // Top bun
  layers.push({ label: '🍞', color: '#f4a460', height: 28 });

  // Sauces on top
  for (const sauce of builder.sauces) {
    layers.push({ label: TOPPING_ICONS[sauce] || '💧', color: '#ffe4b5', height: 12 });
  }

  // Toppings
  for (const topping of [...builder.toppings].reverse()) {
    const color = getLayerColor(topping);
    layers.push({ label: `${TOPPING_ICONS[topping] || '•'} ${topping}`, color, height: 20 });
  }

  // Patty
  if (builder.patty) {
    layers.push({ label: `${TOPPING_ICONS[builder.patty] || '🥩'} ${builder.patty}`, color: '#8B4513', height: 24 });
  }

  // Bottom bun
  layers.push({ label: '🍞', color: '#f4a460', height: 28 });

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      gap: 2, padding: '16px 0',
    }}>
      {layers.map((layer, i) => (
        <div
          key={i}
          className="burger-layer-enter"
          style={{
            width: `${Math.min(85, 60 + layers.length * 2)}%`,
            height: layer.height,
            background: layer.color,
            borderRadius: layer.height / 2,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '0.75em', color: '#fff', fontWeight: 'bold',
            textShadow: '0 1px 2px rgba(0,0,0,0.3)',
            transition: 'all 0.3s ease',
          }}
        >
          {layer.label}
        </div>
      ))}
    </div>
  );
}

function IngredientSection({ title, items }: { title: string; items: string[] }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: '0.8em', color: '#888', fontWeight: 'bold', textTransform: 'uppercase', marginBottom: 4 }}>
        {title}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {items.map((item, i) => {
          const price = TOPPING_PRICES[item];
          return (
            <span
              key={i}
              style={{
                padding: '4px 10px', borderRadius: 12,
                background: '#f0f0f0', fontSize: '0.85em',
                display: 'flex', alignItems: 'center', gap: 4,
              }}
            >
              {TOPPING_ICONS[item] || '•'} {item}
              {price ? <span style={{ color: '#e67e22', fontSize: '0.8em' }}>+{formatPrice(price)}</span> : null}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function getLayerColor(topping: string): string {
  if (topping.includes('cheese')) return '#ffd700';
  if (topping === 'bacon') return '#8B0000';
  if (topping === 'avocado') return '#2e8b57';
  if (topping === 'fried egg') return '#fff8dc';
  if (topping === 'lettuce') return '#228b22';
  if (topping === 'tomato') return '#dc143c';
  if (topping === 'onion') return '#dda0dd';
  if (topping === 'pickles') return '#6b8e23';
  if (topping === 'jalapeños') return '#228b22';
  if (topping === 'mushrooms') return '#d2b48c';
  return '#ddd';
}
