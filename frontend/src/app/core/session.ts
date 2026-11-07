import { Injectable } from '@angular/core';
import { QueuedIntent } from './models';

export interface StoredSession {
  token: string;
  playerId: number;
  /** Set when this phone first saw the game end; the session is dropped some hours later. */
  endedAt?: number;
}

/** How long a finished game's result stays reachable on this phone. */
export const ENDED_TTL_MS = 12 * 60 * 60 * 1000;

/**
 * Remembers which game this phone is in, so stepping away from the browser and coming back lands
 * in the same game (as the same player) instead of at a blank start screen. Storage is per
 * browser and per address (origin).
 */
@Injectable({ providedIn: 'root' })
export class SessionStore {
  private readonly sessionsKey = 'ms.sessions';
  private readonly lastKey = 'ms.last';

  get(code: string): StoredSession | null {
    const key = code.toUpperCase();
    const s = this.readAll()[key];
    if (!s) return null;
    if (s.endedAt && Date.now() - s.endedAt > ENDED_TTL_MS) {
      this.clear(key);
      return null;
    }
    return s;
  }

  save(code: string, session: StoredSession): void {
    const all = this.readAll();
    all[code.toUpperCase()] = session;
    this.write(this.sessionsKey, JSON.stringify(all));
    this.write(this.lastKey, code.toUpperCase());
  }

  /** Called when the host ends the game: keep the result visible for a while, then forget it. */
  markEnded(code: string): void {
    const all = this.readAll();
    const s = all[code.toUpperCase()];
    if (!s || s.endedAt) return;
    s.endedAt = Date.now();
    this.write(this.sessionsKey, JSON.stringify(all));
  }

  clear(code: string): void {
    const key = code.toUpperCase();
    const all = this.readAll();
    delete all[key];
    this.write(this.sessionsKey, JSON.stringify(all));
    this.remove(`ms.queue.${key}`);
    if (this.readRaw(this.lastKey) === key) this.remove(this.lastKey);
  }

  /** The game this phone is currently in, if any. */
  current(): { code: string; ended: boolean } | null {
    const code = this.readRaw(this.lastKey);
    const s = code ? this.get(code) : null;
    return code && s ? { code, ended: !!s.endedAt } : null;
  }

  loadQueue(code: string): QueuedIntent[] {
    try {
      return JSON.parse(localStorage.getItem(`ms.queue.${code.toUpperCase()}`) ?? '[]');
    } catch {
      return [];
    }
  }

  saveQueue(code: string, queue: QueuedIntent[]): void {
    this.write(`ms.queue.${code.toUpperCase()}`, JSON.stringify(queue));
  }

  private readAll(): Record<string, StoredSession> {
    try {
      return JSON.parse(localStorage.getItem(this.sessionsKey) ?? '{}');
    } catch {
      return {};
    }
  }

  private readRaw(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  private write(key: string, value: string): void {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* private mode or storage disabled: the app still works, just without resume */
    }
  }

  private remove(key: string): void {
    try {
      localStorage.removeItem(key);
    } catch {
      /* storage unavailable */
    }
  }
}
