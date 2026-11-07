import { Sound } from './sound';

describe('Sound', () => {
  beforeEach(() => localStorage.clear());

  it('is on by default and remembers being switched off', () => {
    const s = new Sound();
    expect(s.enabled()).toBe(true);
    s.toggle();
    expect(s.enabled()).toBe(false);
    expect(new Sound().enabled()).toBe(false);
  });

  it('does not throw when playback is unavailable or blocked', () => {
    const s = new Sound();
    expect(() => s.play('cash')).not.toThrow();
  });
});
