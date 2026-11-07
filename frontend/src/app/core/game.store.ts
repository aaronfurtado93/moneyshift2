import { Injectable, computed, inject, signal } from '@angular/core';
import { Api, ApiError } from './api';
import { Flow, GameSettings, QueuedIntent, ServerInfo, Snapshot } from './models';
import { SessionStore } from './session';
import { Sound } from './sound';
import { buildPayUrl, newKey } from './util';

export type Connection = 'connecting' | 'online' | 'offline';

/**
 * Client-side view of one game. The server is the source of truth: every event from the
 * WebSocket (or a reconnect) just triggers a fresh snapshot. Player intents made while offline
 * are queued with their idempotency keys and replayed on reconnect.
 */
@Injectable({ providedIn: 'root' })
export class GameStore {
  private readonly api = inject(Api);
  private readonly sessions = inject(SessionStore);
  readonly sound = inject(Sound);

  readonly snapshot = signal<Snapshot | null>(null);
  readonly connection = signal<Connection>('offline');
  readonly queue = signal<QueuedIntent[]>([]);
  readonly toast = signal('');
  readonly info = signal<ServerInfo | null>(null);
  readonly notJoined = signal(false);
  /** Latest money movement (for the dashboard animation). */
  readonly flow = signal<Flow | null>(null);

  readonly me = computed(() => this.snapshot()?.me ?? null);
  readonly isHost = computed(() => this.me()?.role === 'host');
  readonly players = computed(() => this.snapshot()?.players ?? []);
  readonly myPlayer = computed(() => this.players().find((p) => p.id === this.me()?.id) ?? null);
  /** Everyone who actually plays (a banker-only host is excluded). */
  readonly playing = computed(() => this.players().filter((p) => p.plays));
  readonly others = computed(() => this.playing().filter((p) => p.id !== this.me()?.id));
  readonly bankOnly = computed(() => this.isHost() && this.me()?.plays === false);
  readonly currency = computed(() => this.snapshot()?.game.currency ?? '$');
  readonly mode = computed(() => this.snapshot()?.game.mode ?? null);
  readonly settings = computed(() => this.snapshot()?.game.settings ?? null);
  /** The turn going round the table: the Dice in Monopoly, the Card in UnoPoly. */
  readonly turn = computed(() => this.snapshot()?.game.turn ?? null);
  readonly turnHolder = computed(() => {
    const id = this.turn()?.holder_id;
    return this.players().find((p) => p.id === id) ?? null;
  });
  readonly iHoldTheTurn = computed(() => this.turn()?.holder_id === this.me()?.id);
  /** Quick-add amounts for the current game mode. */
  readonly quickAmounts = computed(() => this.mode()?.quick_amounts?.length ? this.mode()!.quick_amounts : [10, 50, 100, 500]);
  readonly ended = computed(() => this.snapshot()?.game.status === 'ended');
  /** Address other phones should use (never localhost). */
  readonly baseUrl = computed(() => {
    const local = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
    return local ? (this.info()?.base_url ?? location.origin) : location.origin;
  });
  readonly joinUrl = computed(() => {
    const code = this.snapshot()?.game.code;
    return code ? `${this.baseUrl()}/join/${code}` : '';
  });

  /** QR link that opens a confirm-and-pay screen for a player (or the bank). */
  payUrl(to: number | 'bank', amount?: number | null): string {
    const code = this.snapshot()?.game.code;
    return code ? buildPayUrl(this.baseUrl(), code, to, amount) : '';
  }

  private code = '';
  private token = '';
  private lastSeq = 0;
  private socket?: WebSocket;
  private retry = 0;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private toastTimer?: ReturnType<typeof setTimeout>;
  /** Set while this phone's own payment is in flight, so its balance drop does not chime twice. */
  private ownSpend = false;
  private calloutSeen = 0;
  private refreshing = false;
  private refreshAgain = false;
  private closed = true;

  async open(code: string): Promise<boolean> {
    this.close();
    this.code = code.toUpperCase();
    const session = this.sessions.get(this.code);
    if (!session) {
      this.notJoined.set(true);
      return false;
    }
    this.notJoined.set(false);
    this.token = session.token;
    this.closed = false;
    this.snapshot.set(null);
    this.lastSeq = 0;
    this.calloutSeen = 0;
    this.queue.set(this.sessions.loadQueue(this.code));
    this.connection.set('connecting');
    this.api.info().then((i) => this.info.set(i)).catch(() => undefined);
    await this.refresh();
    if (!this.closed) this.connect();
    return !this.notJoined();
  }

  close(): void {
    this.closed = true;
    clearTimeout(this.reconnectTimer);
    this.socket?.close();
    this.socket = undefined;
    this.connection.set('offline');
  }

  leave(): void {
    this.sessions.clear(this.code);
    this.close();
    this.snapshot.set(null);
  }

  // ---------- player intents (queued when offline) ----------
  pay(toId: number | null, amount: number, note?: string): Promise<string | null> {
    return this.send({ key: newKey(), kind: 'pay', to_id: toId, amount, note });
  }

  askBank(amount: number, note?: string): Promise<string | null> {
    return this.send({ key: newKey(), kind: 'ask', amount, note });
  }

  /** Re-send the same intent with the same key (what a flaky connection would do). */
  private async perform(i: QueuedIntent): Promise<void> {
    if (i.kind === 'pay') {
      await this.api.pay(this.code, this.token, { to_id: i.to_id ?? null, amount: i.amount, key: i.key, note: i.note });
    } else {
      await this.api.askBank(this.code, this.token, { amount: i.amount, key: i.key, note: i.note });
    }
  }

  private async send(i: QueuedIntent): Promise<string | null> {
    if (i.kind === 'pay') {
      this.ownSpend = true;
      setTimeout(() => (this.ownSpend = false), 5000);
    }
    try {
      await this.perform(i);
    } catch (e) {
      this.ownSpend = false;
      if (e instanceof ApiError && e.network) {
        this.setQueue([...this.queue(), i]);
        return 'No connection: saved and will be sent when you are back online';
      }
      return this.errorText(e);
    }
    if (i.kind === 'pay') this.sound.play('cash');
    await this.refresh();
    return null;
  }

  private async flushQueue(): Promise<void> {
    const pending = [...this.queue()];
    for (const i of pending) {
      try {
        await this.perform(i);
      } catch (e) {
        if (e instanceof ApiError && e.network) return; // still offline; keep the rest
        this.showToast(`A queued action was rejected: ${this.errorText(e)}`);
      }
      this.setQueue(this.queue().filter((q) => q.key !== i.key));
    }
  }

  private setQueue(q: QueuedIntent[]): void {
    this.queue.set(q);
    this.sessions.saveQueue(this.code, q);
  }

  // ---------- host / bank actions ----------
  bankPay(playerId: number, amount: number, note?: string) {
    return this.run(
      () => this.api.bank(this.code, this.token, 'pay', { player_id: playerId, amount, note }),
      playerId !== this.me()?.id,
    );
  }

  bankCollect(playerId: number, amount: number, note?: string) {
    return this.run(
      () => this.api.bank(this.code, this.token, 'collect', { player_id: playerId, amount, note }),
      playerId !== this.me()?.id,
    );
  }

  resolveRequest(id: number, approve: boolean) {
    return this.run(() => this.api.resolve(this.code, this.token, id, approve));
  }

  undo(txId: number) {
    return this.run(() => this.api.reverse(this.code, this.token, txId));
  }

  rollDice() {
    return this.run(() => this.api.turn(this.code, this.token, 'roll'));
  }

  endTurn() {
    return this.run(() => this.api.turn(this.code, this.token, 'end'));
  }

  skipTurn() {
    return this.run(() => this.api.turn(this.code, this.token, 'skip'));
  }

  reverseTurn() {
    return this.run(() => this.api.turn(this.code, this.token, 'reverse'));
  }

  passTurn() {
    return this.run(() => this.api.turn(this.code, this.token, 'pass'));
  }

  giveTurn(playerId: number) {
    return this.run(() => this.api.assignTurn(this.code, this.token, playerId));
  }

  // ---------- Uno call-outs ----------
  startCallout() {
    return this.run(() => this.api.callout(this.code, this.token, 'start'));
  }

  voteCallout(agree: boolean) {
    return this.run(() => this.api.voteCallout(this.code, this.token, agree));
  }

  cancelCallout() {
    return this.run(() => this.api.callout(this.code, this.token, 'cancel'));
  }

  updateSettings(settings: Partial<GameSettings>) {
    return this.run(() => this.api.updateSettings(this.code, this.token, settings));
  }

  /** Ask every player's device to sound the siren once, at the saved volume. */
  testSirenOnPlayers() {
    return this.run(() => this.api.testSiren(this.code, this.token));
  }

  /** Play the siren on this device at the given loudness (0 to 1), even if this device is muted. */
  previewSiren(level: number): void {
    this.sound.playSiren(level, true);
  }

  restartGame() {
    return this.run(() => this.api.restart(this.code, this.token));
  }

  applyStatus(playerId: number, effect: string) {
    return this.run(() => this.api.applyStatus(this.code, this.token, playerId, effect));
  }

  missTurn(playerId: number, effect: string) {
    return this.run(() => this.api.statusAction(this.code, this.token, playerId, effect, 'turn'));
  }

  payStatusFine(playerId: number, effect: string) {
    return this.run(() => this.api.statusAction(this.code, this.token, playerId, effect, 'pay'));
  }

  clearStatus(playerId: number, effect: string) {
    return this.run(() => this.api.statusAction(this.code, this.token, playerId, effect, 'clear'));
  }

  reorderPlayers(order: number[]) {
    return this.run(() => this.api.reorderPlayers(this.code, this.token, order));
  }

  setPlayerColour(playerId: number, colour: string) {
    return this.run(() => this.api.setColour(this.code, this.token, playerId, colour));
  }

  changeMode(mode: string) {
    return this.run(() => this.api.setMode(this.code, this.token, mode));
  }

  endGame() {
    return this.run(() => this.api.end(this.code, this.token));
  }

  private async run(fn: () => Promise<unknown>, chime = false): Promise<string | null> {
    try {
      await fn();
    } catch (e) {
      return this.errorText(e);
    }
    // A banker-only dashboard chimes from the transaction event instead (avoids doubling up).
    if (chime && !this.bankOnly()) this.sound.play('cash');
    await this.refresh();
    return null;
  }

  // ---------- sync ----------
  async refresh(): Promise<void> {
    if (this.refreshing) {
      this.refreshAgain = true;
      return;
    }
    this.refreshing = true;
    try {
      do {
        this.refreshAgain = false;
        const snap = await this.api.snapshot(this.code, this.token);
        this.playOnBalanceChange(snap);
        this.playOnRoll(snap);
        this.playOnJail(snap);
        this.playOnCallout(snap);
        this.snapshot.set(snap);
        if (snap.game.status === 'ended') this.sessions.markEnded(this.code);
        this.lastSeq = Math.max(this.lastSeq, snap.seq);
      } while (this.refreshAgain);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 404)) {
        this.sessions.clear(this.code);
        this.notJoined.set(true);
        this.close();
      }
    } finally {
      this.refreshing = false;
    }
  }

  /**
   * Cash register whenever this player's own balance changes (money received, or the bank collecting),
   * but not on the first load, and not a second time for a payment this phone just made itself.
   */
  private playOnBalanceChange(next: Snapshot): void {
    const prev = this.snapshot();
    if (!prev || prev.game.code !== next.game.code) return;
    const before = prev.players.find((p) => p.id === prev.me.id)?.balance;
    const after = next.players.find((p) => p.id === next.me.id)?.balance;
    if (typeof before !== 'number' || typeof after !== 'number' || after === before) return;
    if (after < before && this.ownSpend) {
      this.ownSpend = false; // already chimed when the payment succeeded
      return;
    }
    this.sound.play('cash');
  }

  /** Dice sound for everyone whenever a new roll shows up (doubles have their own sound). */
  private playOnRoll(next: Snapshot): void {
    const prev = this.snapshot();
    const before = prev?.game.code === next.game.code ? (prev.game.turn?.last?.roll_id ?? 0) : null;
    const last = next.game.turn?.last;
    if (before === null || !last || last.roll_id <= before) return;
    this.sound.play(last.double ? 'doubles' : 'dice');
  }

  /** Sad trombone and a cell door, but only on the device of the player who has just been sent to Jail. */
  private playOnJail(next: Snapshot): void {
    const prev = this.snapshot();
    if (!prev || prev.game.code !== next.game.code) return;
    const jailed = (s: Snapshot) => new Set(s.players.filter((p) => p.statuses.some((x) => x.effect === 'jail')).map((p) => p.id));
    const before = jailed(prev);
    const me = next.me.id;
    if (before.has(me) || !jailed(next).has(me)) return; // somebody else, or I was already in Jail
    // After a third double the dice sound is playing: let it finish first.
    const last = next.game.turn?.last;
    const justRolled = !!last && last.roll_id > (prev.game.turn?.last?.roll_id ?? 0);
    this.sound.playJail(justRolled ? 1600 : 0);
  }

  /** Siren on every device when a new call-out starts (not when you join a call-out already open). */
  private playOnCallout(next: Snapshot): void {
    const prev = this.snapshot();
    const callout = next.game.turn?.callout;
    if (!callout || callout.id <= this.calloutSeen) return;
    this.calloutSeen = callout.id;
    // The host's siren volume applies on every device.
    if (prev && prev.game.code === next.game.code) this.sound.playSiren((next.game.settings?.siren_volume ?? 40) / 100);
  }

  private connect(): void {
    if (this.closed) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}/api/games/${this.code}/ws?token=${encodeURIComponent(this.token)}&since=${this.lastSeq}`;
    const ws = new WebSocket(url);
    this.socket = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.connection.set('online');
      void this.flushQueue().then(() => this.refresh());
    };
    ws.onmessage = (m) => {
      let msg: {
        kind: string;
        seq?: number;
        type?: string;
        text?: string;
        data?: Omit<Flow, 'key'>;
      };
      try {
        msg = JSON.parse(m.data);
      } catch {
        return;
      }
      if (msg.kind === 'event' && msg.seq) {
        this.lastSeq = Math.max(this.lastSeq, msg.seq);
        if (msg.type === 'transaction' && this.bankOnly()) this.sound.play('cash');
        if (msg.data && ['transaction', 'reversal'].includes(msg.type ?? '')) {
          this.flow.set({ ...msg.data, key: msg.seq });
        }
        if (msg.type === 'siren_test') this.sound.playSiren((this.snapshot()?.game.settings?.siren_volume ?? 40) / 100);
        this.maybeToast(msg.text ?? '', msg.type ?? '');
      }
      if (msg.kind === 'event' || msg.kind === 'presence') void this.refresh();
    };
    ws.onclose = () => {
      if (this.socket === ws) this.socket = undefined;
      if (this.closed) return;
      this.connection.set('offline');
      const delay = Math.min(8000, 1000 * 2 ** this.retry++);
      this.reconnectTimer = setTimeout(() => this.connect(), delay);
    };
    ws.onerror = () => ws.close();
  }

  private maybeToast(text: string, type: string): void {
    if (type === 'game_ended') return this.showToast('The host ended the game.');
    if (type === 'game_restarted') return this.showToast('The host restarted the game.');
    if (type === 'callout_started' || type === 'callout_result') return this.showToast(text);
    const me = this.me();
    if (!me || !['transaction', 'request_resolved', 'reversal'].includes(type)) return;
    if (text.includes(me.name) && !text.startsWith(me.name) || type === 'reversal') {
      this.showToast(text);
      try {
        navigator.vibrate?.(80);
      } catch {
        /* not supported */
      }
    }
  }

  showToast(text: string): void {
    this.toast.set(text);
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => this.toast.set(''), 4000);
  }

  private errorText(e: unknown): string {
    return e instanceof Error ? e.message : 'Something went wrong';
  }
}
