import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { OrderConfirmation } from './OrderConfirmation';
import { useAppStore } from '../store';

describe('OrderConfirmation', () => {
  beforeEach(() => {
    useAppStore.setState({
      order: { items: [], total: 0, confirmed: false, orderNumber: null },
    });
  });

  it('renders nothing when order is not confirmed', () => {
    const { container } = render(<OrderConfirmation />);
    expect(container.innerHTML).toBe('');
  });

  it('renders confirmation with order number and thank you message', () => {
    useAppStore.setState({
      order: {
        items: [{ itemId: 'b1', name: 'Classic Burger', quantity: 1, unitPrice: 899 }],
        total: 899,
        confirmed: true,
        orderNumber: 'ORD-12345',
      },
    });

    render(<OrderConfirmation />);

    expect(screen.getByText('Thank you for your order!')).toBeInTheDocument();
    expect(screen.getByText('Order #ORD-12345')).toBeInTheDocument();
  });

  it('displays all items with quantities and prices', () => {
    useAppStore.setState({
      order: {
        items: [
          { itemId: 'b1', name: 'Classic Burger', quantity: 2, unitPrice: 899 },
          { itemId: 'd1', name: 'Cola', quantity: 1, unitPrice: 199 },
        ],
        total: 1997,
        confirmed: true,
        orderNumber: 'ORD-99',
      },
    });

    render(<OrderConfirmation />);

    expect(screen.getByText(/Classic Burger × 2/)).toBeInTheDocument();
    expect(screen.getByText('$17.98')).toBeInTheDocument();
    expect(screen.getByText(/Cola × 1/)).toBeInTheDocument();
    expect(screen.getByText('$1.99')).toBeInTheDocument();
    expect(screen.getByText(/\$19\.97/)).toBeInTheDocument();
  });

  it('shows confirmation after order_confirmed event is applied', () => {
    const { container, unmount } = render(<OrderConfirmation />);
    expect(screen.queryByText('Thank you for your order!')).not.toBeInTheDocument();

    useAppStore.getState().applyUIEvent({
      type: 'order_confirmed',
      payload: {
        orderNumber: 'ORD-ABC',
        items: [{ itemId: 'x1', name: 'Shake', quantity: 1, unitPrice: 499 }],
        total: 499,
        timestamp: '2025-01-01T00:00:00Z',
      },
    });

    unmount();
    const { container: c2 } = render(<OrderConfirmation />);
    expect(c2.querySelector('.order-confirmation')).toBeInTheDocument();
    expect(screen.getByText('Order #ORD-ABC')).toBeInTheDocument();
  });

  it('has an accessible section label when confirmed', () => {
    useAppStore.setState({
      order: {
        items: [{ itemId: 'b1', name: 'Burger', quantity: 1, unitPrice: 500 }],
        total: 500,
        confirmed: true,
        orderNumber: 'ORD-1',
      },
    });

    render(<OrderConfirmation />);
    expect(screen.getByRole('region', { name: 'Order confirmation' })).toBeInTheDocument();
  });
});
