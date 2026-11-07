/**
 * Sounds built from scratch with the Web Audio API, so there are no audio files and no licensing
 * questions. The jail jingle is a sad trombone ("wah wah wah waaah") followed by a cell-door clang.
 */

/** Four descending trombone notes: Bb3, A3, Ab3, G3. Returns the time the phrase ends. */
export function playSadTrombone(ctx: AudioContext, start: number): number {
  const notes = [
    { f: 233.08, d: 0.4 },
    { f: 220.0, d: 0.4 },
    { f: 207.65, d: 0.4 },
    { f: 196.0, d: 1.4 }, // the long, drooping last note
  ];
  let t = start;
  notes.forEach((note, i) => {
    const last = i === notes.length - 1;
    const osc = ctx.createOscillator();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(note.f * 1.04, t); // brass notes start slightly sharp
    osc.frequency.linearRampToValueAtTime(note.f, t + 0.06);
    if (last) {
      osc.frequency.setValueAtTime(note.f, t + 0.35);
      osc.frequency.linearRampToValueAtTime(note.f * 0.88, t + note.d); // sag
      const vibrato = ctx.createOscillator();
      const depth = ctx.createGain();
      vibrato.frequency.value = 5.5;
      depth.gain.value = 4;
      vibrato.connect(depth);
      depth.connect(osc.frequency);
      vibrato.start(t + 0.3);
      vibrato.stop(t + note.d + 0.05);
    }
    // The "wah": the filter opens and then closes again on every note.
    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.Q.value = 2;
    filter.frequency.setValueAtTime(350, t);
    filter.frequency.linearRampToValueAtTime(1500, t + note.d * 0.35);
    filter.frequency.linearRampToValueAtTime(450, t + note.d);
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.linearRampToValueAtTime(0.32, t + 0.05);
    gain.gain.setValueAtTime(0.32, t + note.d - 0.1);
    gain.gain.linearRampToValueAtTime(0.0001, t + note.d);
    osc.connect(filter);
    filter.connect(gain);
    gain.connect(ctx.destination);
    osc.start(t);
    osc.stop(t + note.d + 0.05);
    t += note.d + 0.03;
  });
  return t;
}

/** A heavy metal door slamming shut: a low thud, a burst of noise and ringing metallic partials. */
export function playCellDoor(ctx: AudioContext, start: number): number {
  const master = ctx.createGain();
  master.gain.value = 0.55;
  master.connect(ctx.destination);

  // Ringing metal: inharmonic partials, the higher ones dying away faster.
  const base = 380;
  const partials: [number, number][] = [
    [1, 0.5],
    [2.76, 0.4],
    [5.4, 0.3],
    [8.93, 0.2],
    [11.34, 0.14],
  ];
  partials.forEach(([ratio, level], i) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = base * ratio;
    gain.gain.setValueAtTime(level, start);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 1.7 / (1 + i * 0.45));
    osc.connect(gain);
    gain.connect(master);
    osc.start(start);
    osc.stop(start + 1.8);
  });

  // The impact: a short burst of noise.
  const length = Math.floor(ctx.sampleRate * 0.18);
  const buffer = ctx.createBuffer(1, length, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let n = 0; n < length; n++) data[n] = (Math.random() * 2 - 1) * (1 - n / length) ** 2;
  const noise = ctx.createBufferSource();
  noise.buffer = buffer;
  const band = ctx.createBiquadFilter();
  band.type = 'bandpass';
  band.frequency.value = 2400;
  band.Q.value = 0.8;
  const noiseGain = ctx.createGain();
  noiseGain.gain.value = 0.9;
  noise.connect(band);
  band.connect(noiseGain);
  noiseGain.connect(master);
  noise.start(start);

  // The thud of the door hitting the frame.
  const thud = ctx.createOscillator();
  const thudGain = ctx.createGain();
  thud.type = 'sine';
  thud.frequency.setValueAtTime(120, start);
  thud.frequency.exponentialRampToValueAtTime(50, start + 0.3);
  thudGain.gain.setValueAtTime(0.9, start);
  thudGain.gain.exponentialRampToValueAtTime(0.0001, start + 0.35);
  thud.connect(thudGain);
  thudGain.connect(master);
  thud.start(start);
  thud.stop(start + 0.4);

  return start + 1.8;
}

/** Sad trombone, then the cell door. Returns how long it lasts, in seconds. */
export function playJailJingle(ctx: AudioContext): number {
  const start = ctx.currentTime + 0.05;
  const trombone = playSadTrombone(ctx, start);
  const end = playCellDoor(ctx, trombone + 0.15);
  return end - start;
}

/**
 * A police-style siren ("wee-woo") for a call-out. `level` scales the loudness from 0 (silent) to 1;
 * 1 is the old full-volume siren, which was too loud. Returns how long it lasts, in seconds.
 */
export function playSiren(ctx: AudioContext, level = 1): number {
  const start = ctx.currentTime + 0.05;
  const high = 980;
  const low = 640;
  const segment = 0.45;
  const swings = 8;
  const osc = ctx.createOscillator();
  osc.type = 'sawtooth';
  osc.frequency.setValueAtTime(low, start);
  for (let i = 0; i < swings; i++) {
    osc.frequency.linearRampToValueAtTime(i % 2 === 0 ? high : low, start + (i + 1) * segment * 0.92);
  }
  const filter = ctx.createBiquadFilter();
  filter.type = 'lowpass';
  filter.frequency.value = 1800; // a softer edge than before
  const duration = swings * segment;
  const peak = 0.28 * Math.min(Math.max(level, 0), 1);
  const gain = ctx.createGain();
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.linearRampToValueAtTime(Math.max(peak, 0.0001), start + 0.08);
  gain.gain.setValueAtTime(Math.max(peak, 0.0001), start + duration - 0.3);
  gain.gain.linearRampToValueAtTime(0.0001, start + duration);
  osc.connect(filter);
  filter.connect(gain);
  gain.connect(ctx.destination);
  osc.start(start);
  osc.stop(start + duration + 0.05);
  return duration;
}
