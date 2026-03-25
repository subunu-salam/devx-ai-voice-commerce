import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { OrderSummaryPanel } from './OrderSummaryPanel';
import { useAppStore } from '../store';

describe('OrderSummaryPanel', () => {
  beforeEach(() => {
    useAppStore.setState({
      order: { items: [], total: 0, confirmed: false, orderNumber: null },
    });
  });

  it('renders "Your Order" heading', () => {
    render(<OrderSummaryPanel />);
    expect(screen.getByText('Your Order')).toBeInTheDocument();
  });

  it('shows "No items yet" when order is empty', () => {
    render(<OrderSummaryPanel />);
    expect(screen.getByText('No items yet')).toBeInTheDocument();
  });

  it('renders item names, quantities, individual prices, and line totals', () => {
    useAppStore.setState({
      order: {
        items: [
          { itemId: 'b1', name: 'Classic Burger', quantity: 2, unitPrice: 899 },
          { itemId: 'd1', name: 'Cola', quantity: 1, unitPrice: 199 },
        ],
        total: 1997,
        confirmed: false,
        orderNumber: null,
      },
    });

    render(<OrderSummaryPanel />);

    expect(screen.getByText(/Classic Burger/)).toBeInTheDocument();
    expect(screen.getByText(/× 2/)).toBeInTheDocument();
    expect(screen.getByText(/\$8\.99\s+ea/)).toBeInTheDocument();
    expect(screen.getByText('$17.98')).toBeInTheDocument();

    expect(screen.getByText(/Cola/)).toBeInTheDocument();
    expect(screen.getByText(/× 1/)).toBeInTheDocument();
    expect(screen.getByText(/\$1\.99\s+ea/)).toBeInTheDocument();

    expect(screen.getByText('$19.97')).toBeInTheDocument();
  });

  it('does not show "No items yet" when items exist', () => {
    useAppStore.setState({
      order: {
        items: [{ itemId: 'b1', name: 'Burger', quantity: 1, unitPrice: 500 }],
        total: 500,
        confirmed: false,
        orderNumber: null,
      },
    });

    render(<OrderSummaryPanel />);
    expect(screen.queryByText('No items yet')).not.toBeInTheDocument();
  });

  it('reactively updates when store changes', () => {
    const { rerender } = render(<OrderSummaryPanel />);
    expect(screen.getByText('No items yet')).toBeInTheDocument();

    useAppStore.setState({
      order: {
        items: [{ itemId: 'f1', name: 'Fries', quantity: 3, unitPrice: 299 }],
        total: 897,
        confirmed: false,
        orderNumber: null,
      },
    });

    rerender(<OrderSummaryPanel />);
    expect(screen.queryByText('No items yet')).not.toBeInTheDocument();
    expect(screen.getByText(/Fries/)).toBeInTheDocument();
    expect(screen.getAllByText('$8.97')).toHaveLength(2); // line total + order total
  });

  it('has an accessible section label', () => {
    render(<OrderSummaryPanel />);
    expect(screen.getByRole('region', { name: 'Order summary' })).toBeInTheDocument();
  });
});
