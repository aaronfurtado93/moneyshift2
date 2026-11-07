/** Random idempotency key. Uses getRandomValues, which works on plain-HTTP pages (randomUUID does not). */
export function newKey(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/** Link encoded in a pay/collect QR code. `to` is a player id or 'bank'. Scanning opens it in the browser. */
export function buildPayUrl(base: string, code: string, to: number | 'bank', amount?: number | null): string {
  const q = new URLSearchParams({ to: String(to) });
  if (amount && amount > 0) q.set('amount', String(amount));
  return `${base}/pay/${code}?${q.toString()}`;
}

/** Reads a scanned QR value. Only same-game pay links are accepted; the origin is ignored on purpose. */
export function parsePayLink(text: string, code: string): { to: string; amount?: string } | null {
  let url: URL;
  try {
    url = new URL(text.trim());
  } catch {
    return null;
  }
  const m = /^\/pay\/([A-Za-z0-9]{4})$/.exec(url.pathname);
  if (!m || m[1].toUpperCase() !== code.toUpperCase()) return null;
  const to = url.searchParams.get('to') ?? '';
  if (to !== 'bank' && !/^\d+$/.test(to)) return null;
  const amount = url.searchParams.get('amount');
  return amount && /^\d+$/.test(amount) ? { to, amount } : { to };
}

export function formatMoney(currency: string, amount: number): string {
  const sign = amount < 0 ? '-' : '';
  return `${sign}${currency}${Math.abs(amount).toLocaleString()}`;
}

/** Whole numbers only: digits, no decimals, signs, exponents or hex. Returns null when invalid or zero. */
export function parseAmount(value: string | number): number | null {
  const text = String(value).trim();
  if (!/^\d{1,10}$/.test(text)) return null;
  const n = Number(text);
  return n > 0 ? n : null;
}
