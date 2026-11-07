import { Injectable, signal } from '@angular/core';
import { playJailJingle, playSiren } from './synth';

export type SoundName = 'cash' | 'dice' | 'doubles';

const FILES: Record<SoundName, string> = {
  cash: '/sounds/cash-register.mp3',
  dice: '/sounds/dice-roll.mp3',
  doubles: '/sounds/doubles-dice-roll.mp3',
};

/**
 * Short sound effects (the cash register from the original MoneyShift). Browsers only allow audio
 * after the user has touched the page once, so the first tap unlocks playback; after that, events
 * arriving over the WebSocket (money received) can play on their own.
 */
@Injectable({ providedIn: 'root' })
export class Sound {
  private readonly key = 'ms.sound';
  private readonly clips = new Map<SoundName, HTMLAudioElement>();
  private unlocked = false;
  private audioContext?: AudioContext;

  readonly enabled = signal(this.load());

  constructor() {
    if (typeof document === 'undefined') return;
    const unlock = () => {
      if (this.unlocked) return;
      this.unlocked = true;
      void this.webAudio()?.resume(); // the synthesised sounds need the same first tap
      // A silent play/pause during a user gesture lets later programmatic plays through.
      const clip = this.clip('cash');
      if (!clip) return;
      clip.muted = true;
      Promise.resolve(clip.play())
        .then(() => {
          clip.pause();
          clip.currentTime = 0;
        })
        .catch(() => undefined)
        .finally(() => (clip.muted = false));
    };
    document.addEventListener('pointerdown', unlock, { once: true });
  }

  play(name: SoundName): void {
    if (!this.enabled()) return;
    const clip = this.clip(name);
    if (!clip) return;
    try {
      clip.currentTime = 0;
      Promise.resolve(clip.play()).catch(() => undefined); // blocked until the user has tapped once
    } catch {
      /* audio not available */
    }
  }

  /** Sad trombone then a cell-door clang, built in the browser (no audio files). */
  playJail(delayMs = 0): void {
    if (!this.enabled()) return;
    setTimeout(() => {
      const ctx = this.webAudio();
      if (!ctx) return;
      try {
        if (ctx.state === 'suspended') void ctx.resume();
        playJailJingle(ctx);
      } catch {
        /* audio not available */
      }
    }, delayMs);
  }

  /** Siren when someone is called out. `level` (0 to 1) is the host's siren volume setting. */
  playSiren(level = 1, force = false): void {
    if ((!this.enabled() && !force) || level <= 0) return;
    const ctx = this.webAudio();
    if (!ctx) return;
    try {
      if (ctx.state === 'suspended') void ctx.resume();
      playSiren(ctx, level);
    } catch {
      /* audio not available */
    }
  }

  toggle(): void {
    const next = !this.enabled();
    this.enabled.set(next);
    try {
      localStorage.setItem(this.key, next ? '1' : '0');
    } catch {
      /* storage unavailable */
    }
    if (next) this.play('cash');
  }

  private webAudio(): AudioContext | null {
    if (typeof AudioContext === 'undefined') return null;
    this.audioContext ??= new AudioContext();
    return this.audioContext;
  }

  private clip(name: SoundName): HTMLAudioElement | null {
    if (typeof Audio === 'undefined') return null;
    let clip = this.clips.get(name);
    if (!clip) {
      clip = new Audio(FILES[name]);
      clip.preload = 'auto';
      this.clips.set(name, clip);
    }
    return clip;
  }

  private load(): boolean {
    try {
      return localStorage.getItem(this.key) !== '0';
    } catch {
      return true;
    }
  }
}
