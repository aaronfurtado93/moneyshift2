/** Colours the host can give players (also what players are assigned by default). */
export const PALETTE = [
  '#e11d48',
  '#2563eb',
  '#16a34a',
  '#d97706',
  '#7c3aed',
  '#0891b2',
  '#db2777',
  '#65a30d',
  '#0d9488',
  '#ea580c',
  '#4f46e5',
  '#475569',
];

/** The next palette colour after `current`, skipping colours other players already have. */
export function nextColour(current: string, taken: string[]): string {
  const used = new Set(taken.map((c) => c.toLowerCase()));
  const start = PALETTE.indexOf(current.toLowerCase());
  for (let k = 1; k <= PALETTE.length; k++) {
    const colour = PALETTE[(start + k + PALETTE.length) % PALETTE.length];
    if (!used.has(colour)) return colour;
  }
  return PALETTE[(start + 1 + PALETTE.length) % PALETTE.length]; // all taken: just move on
}
