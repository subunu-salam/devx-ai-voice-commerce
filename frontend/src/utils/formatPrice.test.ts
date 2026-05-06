// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, it, expect } from 'vitest';
import { formatPrice } from './formatPrice';

describe('formatPrice', () => {
  it('formats zero cents as $0.00', () => {
    expect(formatPrice(0)).toBe('$0.00');
  });

  it('formats 100 cents as $1.00', () => {
    expect(formatPrice(100)).toBe('$1.00');
  });

  it('formats 999 cents as $9.99', () => {
    expect(formatPrice(999)).toBe('$9.99');
  });

  it('formats 1 cent as $0.01', () => {
    expect(formatPrice(1)).toBe('$0.01');
  });

  it('formats 1050 cents as $10.50', () => {
    expect(formatPrice(1050)).toBe('$10.50');
  });

  it('formats large values correctly', () => {
    expect(formatPrice(99999)).toBe('$999.99');
  });
});
