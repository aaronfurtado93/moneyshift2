import { buildPayUrl, formatMoney, newKey, parseAmount, parsePayLink } from './util';

describe('util', () => {
  it('generates distinct idempotency keys', () => {
    const keys = new Set(Array.from({ length: 200 }, () => newKey()));
    expect(keys.size).toBe(200);
  });

  it('formats money with currency and grouping', () => {
    expect(formatMoney('$', 1500)).toBe('$1,500');
    expect(formatMoney('£', -20)).toBe('-£20');
  });

  it('builds pay links for players and the bank', () => {
    expect(buildPayUrl('http://h:8000', 'AB12', 7, 250)).toBe('http://h:8000/pay/AB12?to=7&amount=250');
    expect(buildPayUrl('http://h:8000', 'AB12', 'bank')).toBe('http://h:8000/pay/AB12?to=bank');
    expect(buildPayUrl('http://h:8000', 'AB12', 7, 0)).toBe('http://h:8000/pay/AB12?to=7');
  });

  it('parses only pay links for the current game', () => {
    expect(parsePayLink('http://x:8000/pay/AB12?to=7&amount=250', 'ab12')).toEqual({ to: '7', amount: '250' });
    expect(parsePayLink('https://other/pay/AB12?to=bank', 'AB12')).toEqual({ to: 'bank' });
    expect(parsePayLink('http://x/pay/ZZZZ?to=7', 'AB12')).toBeNull(); // other game
    expect(parsePayLink('http://x/pay/AB12?to=evil', 'AB12')).toBeNull();
    expect(parsePayLink('http://x/join/AB12', 'AB12')).toBeNull();
    expect(parsePayLink('not a url', 'AB12')).toBeNull();
  });

  it('accepts only positive whole amounts', () => {
    expect(parseAmount('250')).toBe(250);
    expect(parseAmount('0')).toBeNull();
    expect(parseAmount('-3')).toBeNull();
    expect(parseAmount('2.5')).toBeNull();
    expect(parseAmount('abc')).toBeNull();
    expect(parseAmount('')).toBeNull();
    expect(parseAmount('1e3')).toBeNull();
    expect(parseAmount('0x10')).toBeNull();
    expect(parseAmount('12.0')).toBeNull();
    expect(parseAmount('1,000')).toBeNull();
    expect(parseAmount('+5')).toBeNull();
    expect(parseAmount(' 75 ')).toBe(75);
    expect(parseAmount(2.5)).toBeNull();
  });
});
