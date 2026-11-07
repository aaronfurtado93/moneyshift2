import { PALETTE, nextColour } from './palette';

describe('nextColour', () => {
  it('moves to the next palette colour', () => {
    expect(nextColour(PALETTE[0], [])).toBe(PALETTE[1]);
    expect(nextColour(PALETTE[PALETTE.length - 1], [])).toBe(PALETTE[0]);
  });

  it('skips colours other players already have', () => {
    expect(nextColour(PALETTE[0], [PALETTE[1], PALETTE[2].toUpperCase()])).toBe(PALETTE[3]);
  });

  it('still moves on when every colour is taken, and handles unknown colours', () => {
    expect(nextColour(PALETTE[0], PALETTE)).toBe(PALETTE[1]);
    expect(PALETTE).toContain(nextColour('#123456', []));
  });
});
