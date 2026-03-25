/**
 * Format a price in cents to a dollar string like "$X.XX".
 */
export function formatPrice(cents: number): string {
  const dollars = (cents / 100).toFixed(2);
  return `$${dollars}`;
}
