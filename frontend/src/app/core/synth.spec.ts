import { playCellDoor, playJailJingle, playSadTrombone, playSiren } from './synth';

/** A stand-in for the browser's AudioContext that records what gets scheduled. */
function fakeContext() {
  const param = () => ({
    value: 0,
    setValueAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
    exponentialRampToValueAtTime: vi.fn(),
  });
  const node = () => ({ connect: vi.fn(), start: vi.fn(), stop: vi.fn(), frequency: param(), gain: param(), Q: param(), type: '' });
  const nodes: ReturnType<typeof node>[] = [];
  const make = () => {
    const n = node();
    nodes.push(n);
    return n;
  };
  const ctx = {
    currentTime: 10,
    sampleRate: 8000,
    destination: {},
    createOscillator: make,
    createGain: make,
    createBiquadFilter: make,
    createBufferSource: make,
    createBuffer: (_c: number, length: number) => ({ getChannelData: () => new Float32Array(length) }),
  };
  return { ctx: ctx as unknown as AudioContext, nodes };
}

describe('jail sounds', () => {
  it('plays a four-note sad trombone that ends after it starts', () => {
    const { ctx, nodes } = fakeContext();
    const end = playSadTrombone(ctx, 10);
    expect(end).toBeGreaterThan(12); // about 2.8 seconds of music
    expect(nodes.filter((n) => n.start.mock.calls.length > 0).length).toBeGreaterThanOrEqual(5); // 4 notes + vibrato
  });

  it('slams the cell door with ringing metal, noise and a thud', () => {
    const { ctx, nodes } = fakeContext();
    const end = playCellDoor(ctx, 5);
    expect(end).toBeGreaterThan(6);
    expect(nodes.filter((n) => n.start.mock.calls.length > 0).length).toBeGreaterThanOrEqual(7); // 5 partials + noise + thud
  });

  it('sounds a siren that swings between two pitches', () => {
    const { ctx, nodes } = fakeContext();
    const seconds = playSiren(ctx);
    expect(seconds).toBeGreaterThan(3);
    const osc = nodes.find((n) => n.start.mock.calls.length > 0)!;
    expect(osc.frequency.linearRampToValueAtTime.mock.calls.length).toBeGreaterThanOrEqual(8);
  });

  it('scales the siren loudness with the level and never exceeds the full-volume peak', () => {
    const peakOf = (level: number) => {
      const { ctx, nodes } = fakeContext();
      playSiren(ctx, level);
      const gains = nodes.flatMap((n) => n.gain.linearRampToValueAtTime.mock.calls.map((c) => c[0] as number));
      return Math.max(...gains);
    };
    expect(peakOf(1)).toBeCloseTo(0.28);
    expect(peakOf(0.4)).toBeCloseTo(0.112);
    expect(peakOf(0.4)).toBeLessThan(peakOf(1));
    expect(peakOf(5)).toBeCloseTo(0.28); // out-of-range levels are clamped
    expect(peakOf(0)).toBeLessThan(0.001);
  });

  it('puts the cell door after the trombone and reports a sensible length', () => {
    const { ctx } = fakeContext();
    const seconds = playJailJingle(ctx);
    expect(seconds).toBeGreaterThan(4);
    expect(seconds).toBeLessThan(8);
  });
});
