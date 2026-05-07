import { useState } from 'react';
import { useAppStore } from '../store';

export function DebugPanel() {
  const agentUI = useAppStore((s) => s.agentUI);
  const voice = useAppStore((s) => s.voice);
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div
      style={{
        position: 'fixed',
        top: 8,
        left: 8,
        bottom: 8,
        width: collapsed ? 40 : 320,
        zIndex: 9999,
        background: '#1e1e1e',
        color: '#d4d4d4',
        borderRadius: 8,
        boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
        fontFamily: 'monospace',
        fontSize: '11px',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        transition: 'width 0.2s',
      }}
    >
      <div
        style={{
          padding: '8px 12px',
          background: '#2d2d2d',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid #444',
          cursor: 'pointer',
        }}
        onClick={() => setCollapsed(!collapsed)}
      >
        {!collapsed && <span style={{ fontWeight: 'bold', color: '#569cd6' }}>🐛 Debug</span>}
        <span>{collapsed ? '▶' : '◀'}</span>
      </div>

      {!collapsed && (
        <div style={{ flex: 1, overflow: 'auto', padding: '8px 12px' }}>
          <Section title="Voice">
            <Row label="session" value={voice.sessionActive} />
            <Row label="listening" value={voice.listening} />
            <Row label="mic" value={voice.micPermission} />
          </Section>

          <Section title="Highlights">
            <Row label="category" value={agentUI.highlightedCategory} />
            <Row label="item" value={agentUI.highlightedItem} />
          </Section>

          <Section title="Order">
            <Row label="confirmed" value={agentUI.orderConfirmed} />
            <Row label="orderNumber" value={agentUI.orderNumber} />
            <Row label="total" value={agentUI.orderTotal} />
            <Row label="items" value={agentUI.orderItems.length} />
            {agentUI.orderItems.map((item) => (
              <div key={item.itemId} style={{ paddingLeft: 8, color: '#9cdcfe' }}>
                {item.name} ×{item.quantity}
              </div>
            ))}
          </Section>

          <Section title="Menu">
            <Row label="categories" value={agentUI.categories.length} />
            {agentUI.categories.map((cat) => (
              <div key={cat.categoryId} style={{ paddingLeft: 8, color: '#9cdcfe' }}>
                {cat.name} ({(agentUI.menuItems[cat.categoryId] || []).length} items)
              </div>
            ))}
          </Section>

          <Section title="Raw State">
            <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: '#ce9178' }}>
              {JSON.stringify({ agentUI, voice }, null, 2)}
            </pre>
          </Section>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ color: '#dcdcaa', fontWeight: 'bold', marginBottom: 4, borderBottom: '1px solid #333', paddingBottom: 2 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: unknown }) {
  const display = value === null ? 'null' : value === undefined ? 'undefined' : String(value);
  const color = value === true ? '#4ec9b0' : value === false ? '#f44747' : value === null ? '#666' : '#ce9178';
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '1px 0' }}>
      <span style={{ color: '#9cdcfe' }}>{label}</span>
      <span style={{ color }}>{display}</span>
    </div>
  );
}
