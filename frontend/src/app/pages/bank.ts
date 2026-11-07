import { Component, ElementRef, OnDestroy, OnInit, computed, effect, inject, signal, untracked, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Dice } from '../core/dice';
import { Digits } from '../core/digits';
import { ActivatedRoute, Router } from '@angular/router';
import { GameStore } from '../core/game.store';
import { Api } from '../core/api';
import { BankAction, Flow, GameMode, PlayerView, StatusEffectDef } from '../core/models';
import { PALETTE } from '../core/palette';
import { Qr } from '../core/qr';
import { formatMoney, parseAmount } from '../core/util';

type Panel = 'collect' | 'invite' | 'sequence';

interface Seat {
  p: PlayerView;
  x: number;
  y: number;
}

/**
 * Bank dashboard for the host, built for a laptop, tablet or TV. Players sit around a table with the
 * bank in the middle; money visibly travels player -> bank -> player. Controls live in a side panel,
 * and the ledger and activity sit in a dock along the bottom.
 */
@Component({
  selector: 'ms-bank',
  imports: [FormsModule, Digits, Dice, Qr],
  template: `
    @if (store.snapshot(); as s) {
      <div class="bank2">
        <header class="bank-head">
          <div>
            <h1>MoneyShift Bank</h1>
            <span class="muted">Game <strong class="code-inline">{{ s.game.code }}</strong>
              · {{ store.playing().length }} player(s) · {{ s.game.mode.name }}</span>
          </div>
          <div class="bank-head-right">
            <button class="btn small" (click)="store.sound.toggle()" [attr.aria-pressed]="store.sound.enabled()">
              {{ store.sound.enabled() ? '🔊 Sound on' : '🔇 Sound off' }}
            </button>
            <span class="status" [class.on]="store.connection() === 'online'">
              <i></i>{{ store.connection() === 'online' ? 'Live' : 'Reconnecting…' }}
            </span>
            @if (s.me.plays) {
              <button class="btn small" (click)="toPlayer()">My player view</button>
            }
            @if (!store.ended()) {
              @if (confirmEnd()) {
                <button class="btn small danger" (click)="end()">Confirm end game</button>
                <button class="btn small" (click)="confirmEnd.set(false)">Cancel</button>
              } @else {
                <button class="btn small" (click)="confirmEnd.set(true)">End game…</button>
              }
            }
          </div>
        </header>

        @if (store.toast()) {
          <p class="toast" role="status">{{ store.toast() }}</p>
        }
        @if (store.ended()) {
          <p class="banner warn">
            The game has ended for everyone. Final balances are shown.
            <button class="btn small primary" (click)="close()">Close game</button>
          </p>
        }

        <div class="bank-body">
          <section class="stage">
            <div class="table" #table>
              <svg class="spokes" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                @for (seat of seats(); track seat.p.id) {
                  <line x1="50" y1="50" [attr.x2]="seat.x" [attr.y2]="seat.y" />
                }
              </svg>

              <div class="hub" #hub>
                <span class="big">🏦</span>
                <b>Bank</b>
                <span class="small">{{ bankNetLabel() }}</span>
              </div>

              @for (seat of seats(); track seat.p.id) {
                <button
                  class="seat"
                  [class.holder-ring]="s.game.dice?.holder_id === seat.p.id"
                  [attr.data-seat]="seat.p.id"
                  [class.sel]="selected() === seat.p.id"
                  [style.left.%]="seat.x"
                  [style.top.%]="seat.y"
                  [style.--c]="seat.p.colour"
                  (click)="selected.set(seat.p.id)"
                >
                  <span class="sname"><i class="presence" [class.on]="seat.p.connected"></i>{{ seat.p.name }}
                    @if (seat.p.role === 'host') {<span class="tag">host</span>}
                  </span>
                  @for (st of seat.p.statuses; track st.effect) {
                    @if (st.effect === 'dice') {
                      <span class="status-badge dice">🎲 Dice</span>
                    } @else {
                      <span class="status-badge">🔒 {{ st.label }} · {{ st.turns_left }}{{ st.decided ? ' (locked)' : '' }}</span>
                    }
                  }
                  <span class="sbal">{{ fmt(seat.p.balance ?? 0) }}</span>
                  <span class="small muted">{{ delta(seat.p.id) }}</span>
                </button>
              }

              @if (!seats().length) {
                <p class="empty muted">Waiting for players. Open “Invite players” on the right.</p>
              }
              <div class="fx" #fx></div>
            </div>
          </section>

          <aside class="bank-side">
            <section class="card">
              <h2>Game mode</h2>
              @if (modes().length > 1 && !store.ended()) {
                <div class="seg" role="radiogroup" aria-label="Game mode">
                  @for (m of modes(); track m.id) {
                    <button class="segbtn" role="radio" [attr.aria-checked]="s.game.mode.id === m.id" [class.sel]="s.game.mode.id === m.id" (click)="switchMode(m.id)">{{ m.name }}</button>
                  }
                </div>
              } @else {
                <p><b>{{ s.game.mode.name }}</b></p>
              }
              <p class="small muted">{{ s.game.mode.description }}</p>
              @if (s.game.mode.bank_actions.length && !store.ended()) {
                <p class="small muted">Quick actions for <b>{{ selected() ? nameOf(selected()) : 'a player (tap one on the table)' }}</b></p>
                <div class="qa">
                  @for (a of s.game.mode.bank_actions; track a.id) {
                    <button class="btn small" [class.primary]="a.kind === 'pay'" [disabled]="busy()" (click)="quickAction(a)">
                      {{ a.label }} {{ a.kind === 'pay' ? '+' : '−' }}{{ fmt(a.amount) }}
                    </button>
                  }
                </div>
              }
              @if (penaltyEffects().length && !store.ended()) {
                <h3 class="sub">Status effects</h3>
                @for (fx of penaltyEffects(); track fx.id) {
                  <p class="small muted">{{ fx.label }}: {{ fx.description }}</p>
                  <button class="btn small" [disabled]="!selected() || busy() || hasStatus(selected(), fx.id)" (click)="applyStatus(fx)">
                    🔒 Send {{ selected() ? nameOf(selected()) : 'the selected player' }} to {{ fx.label }}
                  </button>
                  @for (p of withStatus(fx.id); track p.id) {
                    <div class="line">
                      <span>🔒 <b>{{ p.name }}</b> · {{ turnsLeft(p, fx.id) }} turn(s) left{{ isDecided(p, fx.id) ? ' · fine no longer possible' : '' }}</span>
                      <span class="actions">
                        <button class="btn small" (click)="missTurn(p, fx)">{{ isDecided(p, fx.id) ? 'Missed turn' : 'Chooses to miss' }}</button>
                        <button class="btn small primary" [disabled]="isDecided(p, fx.id)" (click)="payFine(p, fx)">Pay {{ fmt(fx.fine) }}</button>
                        <button class="btn small" (click)="release(p, fx)" aria-label="Release without a fine">Release</button>
                      </span>
                    </div>
                  } @empty {
                    <p class="small muted">Nobody is in {{ fx.label }}.</p>
                  }
                }
              }
              @if (s.game.dice; as d) {
                <h3 class="sub">Dice</h3>
                <p class="small muted">
                  Goes round in player order and skips players in Jail. Override it here.
                </p>
                <p class="small"><b>{{ holderName() }}</b> has the dice
                  @if (d.last; as l) {· last roll {{ l.d1 }} + {{ l.d2 }} = {{ l.total }}{{ l.double ? ' (doubles)' : '' }}}
                </p>
                <ms-dice class="compact" [d1]="d.last?.d1 ?? null" [d2]="d.last?.d2 ?? null" [rollId]="d.last?.roll_id ?? 0" [showTotal]="true" />
                @if (!store.ended()) {
                  <div class="qa">
                    <button class="btn small primary" [disabled]="busy() || d.rolled || !d.holder_id" (click)="hostRoll()">Roll for {{ holderName() }}</button>
                    <button class="btn small" [disabled]="busy() || !d.holder_id" (click)="hostPass()">Pass to next</button>
                    <button class="btn small" [disabled]="busy() || !selected()" (click)="hostGive()">
                      Give {{ selected() ? nameOf(selected()) : 'player' }} dice
                    </button>
                  </div>
                }
              }
            </section>

            <section class="card acc">
              <button class="acc-head" (click)="toggle('sequence')" [attr.aria-expanded]="isOpen('sequence')">
                <span>Player sequence</span><i class="chev" [class.up]="isOpen('sequence')" aria-hidden="true"></i>
              </button>
              @if (isOpen('sequence')) {
                <p class="small muted">Drag a player up or down to change the order. Tap a colour dot to choose their colour.</p>
                <ol class="seqlist" #seqlist>
                  @for (p of orderedPlayers(); track p.id; let i = $index; let last = $last) {
                    <li class="seqrow" [class.dragging]="dragId() === p.id" [attr.data-pid]="p.id">
                      <div class="seqline">
                        <div class="grip" (pointerdown)="startDrag($event, p.id)" role="group" [attr.aria-label]="'Drag ' + p.name + ' to reorder'">
                          <span class="handle" aria-hidden="true">⠿</span>
                          <span class="num">{{ i + 1 }}</span>
                          <span class="sname">{{ p.name }}</span>
                        </div>
                        <button class="swatch" [style.background]="p.colour" (click)="toggleColour(p.id)" [attr.aria-expanded]="colourOpen() === p.id" [attr.aria-label]="'Choose colour for ' + p.name"></button>
                        <button class="btn small" [disabled]="i === 0" (click)="move(p.id, -1)" aria-label="Move up">▲</button>
                        <button class="btn small" [disabled]="last" (click)="move(p.id, 1)" aria-label="Move down">▼</button>
                      </div>
                      @if (colourOpen() === p.id) {
                        <div class="palette" role="listbox" [attr.aria-label]="'Colours for ' + p.name">
                          @for (c of palette; track c) {
                            <button class="pal" role="option" [attr.aria-selected]="c === p.colour.toLowerCase()" [class.sel]="c === p.colour.toLowerCase()" [class.taken]="isTaken(c, p.id)" [style.background]="c" [attr.aria-label]="c" (click)="pickColour(p, c)"></button>
                          }
                          <label class="pal custom" title="Any colour">+
                            <input type="color" [value]="p.colour" (change)="pickColour(p, $any($event.target).value)" />
                          </label>
                        </div>
                      }
                    </li>
                  } @empty {
                    <li class="muted small">No players yet.</li>
                  }
                </ol>
              }
            </section>

            <section class="card" [class.alert]="s.requests.length">
              <h2>Requests @if (s.requests.length) {<span class="badge">{{ s.requests.length }}</span>}</h2>
              @for (r of s.requests; track r.id) {
                <div class="req">
                  <div><b>{{ nameOf(r.player_id) }}</b> asks for <b>{{ fmt(r.amount) }}</b></div>
                  <div class="actions">
                    <button class="btn primary" (click)="resolve(r.id, true)">Approve</button>
                    <button class="btn" (click)="resolve(r.id, false)">Deny</button>
                  </div>
                </div>
              } @empty {
                <p class="muted small">No pending requests.</p>
              }
            </section>

            @if (!store.ended()) {
              <section class="card">
                <h2>Bank pay / collect</h2>
                <p class="small muted">
                  Player: <b>{{ selected() ? nameOf(selected()) : 'tap a player on the table' }}</b>
                </p>
                <input class="amt" [(ngModel)]="amount" msDigits placeholder="Amount" autocomplete="off" />
                <div class="chips">
                  @for (c of quick(); track c) {
                    <button class="chip" (click)="add(c)">+{{ c }}</button>
                  }
                  <button class="chip" (click)="amount = ''">Clear</button>
                </div>
                <div class="row">
                  <button class="btn primary grow" [disabled]="busy()" (click)="bank('pay')">Bank pays</button>
                  <button class="btn grow" [disabled]="busy()" (click)="bank('collect')">Bank collects</button>
                </div>
                @if (msg()) {
                  <p class="error" role="alert">{{ msg() }}</p>
                }
              </section>

              <section class="card acc">
                <button class="acc-head" (click)="toggle('collect')" [attr.aria-expanded]="isOpen('collect')">
                  <span>Collect by QR</span><i class="chev" [class.up]="isOpen('collect')" aria-hidden="true"></i>
                </button>
                @if (isOpen('collect')) {
                  <p class="muted small">Fines, taxes, purchases: players scan and pay the bank.</p>
                  <input [(ngModel)]="collectAmount" msDigits placeholder="Amount (optional)" autocomplete="off" />
                  <div class="qrbox"><ms-qr [value]="collectUrl()" [size]="200" /></div>
                }
              </section>

              <section class="card acc">
                <button class="acc-head" (click)="toggle('invite')" [attr.aria-expanded]="isOpen('invite')">
                  <span>Invite players</span><i class="chev" [class.up]="isOpen('invite')" aria-hidden="true"></i>
                </button>
                @if (isOpen('invite')) {
                  <div class="invite">
                    <ms-qr [value]="store.joinUrl()" />
                    <div>
                      <div class="code big">{{ s.game.code }}</div>
                      <p class="small url">{{ store.joinUrl() }}</p>
                    </div>
                  </div>
                }
              </section>
            }
          </aside>
        </div>

        <div class="bank-two">
          <div>
            <h2>Ledger</h2>
            <div class="scroll">
              @for (t of s.transactions; track t.id) {
                <div class="line" [class.struck]="t.reversed">
                  <span>#{{ t.id }} {{ nameOf(t.from_id) }} → {{ nameOf(t.to_id) }} <b>{{ fmt(t.amount) }}</b>
                    @if (t.kind === 'reversal') {<span class="tag">undo</span>}
                    @if (t.note && t.kind !== 'reversal') {<span class="small muted"> · {{ t.note }}</span>}
                  </span>
                  @if (canUndo(t)) {
                    <button class="btn small" (click)="undo(t.id)">Undo</button>
                  } @else if (t.reversed) {
                    <span class="small muted">undone</span>
                  }
                </div>
              } @empty {
                <p class="muted small">No transactions yet.</p>
              }
            </div>
          </div>
          <div>
            <h2>Activity</h2>
            <div class="scroll">
              @for (a of s.activity; track a.seq) {
                <p class="small act">{{ a.text }}</p>
              } @empty {
                <p class="muted small">Nothing yet.</p>
              }
            </div>
          </div>
        </div>
      </div>
    } @else if (store.notJoined()) {
      <main class="page">
        <section class="card">
          <h2>This device isn't the host of game {{ code }}</h2>
          <p class="muted small">The bank dashboard can only be opened on the device that created the game.</p>
          <button class="btn primary block" (click)="home()">Back</button>
        </section>
      </main>
    } @else {
      <main class="page"><p class="muted">Connecting to the host…</p></main>
    }
  `,
})
export class Bank implements OnInit, OnDestroy {
  protected readonly store = inject(GameStore);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(Api);
  protected readonly modes = signal<GameMode[]>([]);

  private readonly tableEl = viewChild<ElementRef<HTMLElement>>('table');
  private readonly fxEl = viewChild<ElementRef<HTMLElement>>('fx');
  private readonly hubEl = viewChild<ElementRef<HTMLElement>>('hub');
  private readonly seqList = viewChild<ElementRef<HTMLElement>>('seqlist');

  /** Player sequence (drag and drop). `order` follows the pointer while dragging, then is saved. */
  protected readonly order = signal<number[]>([]);
  private readonly dragging = signal<number | null>(null);
  protected readonly dragId = this.dragging.asReadonly();
  protected readonly orderedPlayers = computed(() => {
    const byId = new Map(this.store.playing().map((p) => [p.id, p]));
    return this.order().flatMap((id) => (byId.has(id) ? [byId.get(id)!] : []));
  });

  protected code = '';
  protected readonly quick = this.store.quickAmounts;
  protected readonly selected = signal(0);
  protected amount = '';
  protected collectAmount = '';
  protected readonly collectUrl = () => this.store.payUrl('bank', parseAmount(this.collectAmount));
  /** Accordion: one panel open at a time. undefined = not chosen yet (invite starts open in an empty game). */
  private readonly openPanel = signal<Panel | null | undefined>(undefined);
  protected readonly busy = signal(false);
  protected readonly msg = signal('');
  protected readonly confirmEnd = signal(false);

  /** Players around the table in join order (stable, so nobody jumps around when balances change). */
  protected readonly seats = computed<Seat[]>(() => {
    const players = this.store.playing();
    const n = Math.max(players.length, 1);
    return players.map((p, i) => {
      const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
      return { p, x: 50 + 37 * Math.cos(a), y: 50 + 35 * Math.sin(a) };
    });
  });

  protected readonly bankNetLabel = computed(() => {
    const snap = this.store.snapshot();
    if (!snap) return '';
    const players = this.store.playing();
    const total = players.reduce((sum, p) => sum + (p.balance ?? 0), 0);
    const net = total - players.length * snap.game.starting_balance;
    return net === 0 ? 'balanced' : `${net > 0 ? 'paid out' : 'collected'} ${this.fmt(Math.abs(net))}`;
  });

  constructor() {
    // Only the host may use the dashboard.
    effect(() => {
      const me = this.store.me();
      if (me && me.role !== 'host') void this.router.navigate(['/game', this.code], { replaceUrl: true });
    });
    // Keep the list in step with the server unless a drag is in progress.
    effect(() => {
      const ids = this.store.playing().map((p) => p.id);
      if (this.dragging() === null) untracked(() => this.order.set(ids));
    });
    // Animate every money movement as it happens.
    effect(() => {
      const flow = this.store.flow();
      if (flow) untracked(() => this.runFlow(flow));
    });
  }

  ngOnInit(): void {
    this.code = (this.route.snapshot.paramMap.get('code') ?? '').toUpperCase();
    void this.store.open(this.code);
    this.api.modes().then((r) => this.modes.set(r.modes)).catch(() => undefined);
  }

  ngOnDestroy(): void {
    this.store.close();
  }

  protected isOpen(panel: Panel): boolean {
    const chosen = this.openPanel();
    return chosen === undefined ? panel === 'invite' && this.store.playing().length === 0 : chosen === panel;
  }

  protected toggle(panel: Panel): void {
    this.openPanel.set(this.isOpen(panel) ? null : panel);
  }

  protected fmt(n: number): string {
    return formatMoney(this.store.currency(), n);
  }

  protected nameOf(id: number | null): string {
    return id === null ? 'Bank' : (this.store.players().find((p) => p.id === id)?.name ?? '?');
  }

  protected delta(id: number): string {
    const start = this.store.snapshot()?.game.starting_balance ?? 0;
    const bal = this.store.players().find((p) => p.id === id)?.balance ?? 0;
    const d = bal - start;
    return d === 0 ? 'even with start' : `${d > 0 ? '+' : '-'}${this.fmt(Math.abs(d))} vs start`;
  }

  protected canUndo(t: { reversed: boolean; kind: string }): boolean {
    return !t.reversed && t.kind !== 'reversal' && !this.store.ended();
  }

  protected add(n: number): void {
    this.amount = String((parseAmount(this.amount) ?? 0) + n);
  }

  protected async bank(op: 'pay' | 'collect'): Promise<void> {
    const amount = parseAmount(this.amount);
    if (!this.selected()) return void this.msg.set('Tap a player on the table first');
    if (amount === null) return void this.msg.set('Enter a whole amount greater than zero');
    this.msg.set('');
    this.busy.set(true);
    const err = await (op === 'pay'
      ? this.store.bankPay(this.selected(), amount)
      : this.store.bankCollect(this.selected(), amount));
    this.busy.set(false);
    if (err) this.msg.set(err);
    else this.amount = '';
  }

  // ---------- player sequence ----------
  /** Pointer events work for mouse and touch; the listeners live on the document while dragging. */
  protected startDrag(event: PointerEvent, id: number): void {
    event.preventDefault();
    this.dragging.set(id);
    document.addEventListener('pointermove', this.onDragMove);
    document.addEventListener('pointerup', this.onDragEnd);
    document.addEventListener('pointercancel', this.onDragEnd);
  }

  private readonly onDragMove = (e: PointerEvent): void => {
    const id = this.dragging();
    const list = this.seqList()?.nativeElement;
    if (id === null || !list) return;
    const rows = [...list.querySelectorAll<HTMLElement>('[data-pid]')];
    let target = rows.length - 1;
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i].getBoundingClientRect();
      if (e.clientY < r.top + r.height / 2) {
        target = i;
        break;
      }
    }
    const current = this.order().indexOf(id);
    if (target === current) return;
    const next = [...this.order()];
    next.splice(current, 1);
    next.splice(target, 0, id);
    this.order.set(next);
  };

  private readonly onDragEnd = (): void => {
    document.removeEventListener('pointermove', this.onDragMove);
    document.removeEventListener('pointerup', this.onDragEnd);
    document.removeEventListener('pointercancel', this.onDragEnd);
    this.dragging.set(null);
    void this.saveOrder();
  };

  protected move(id: number, delta: -1 | 1): void {
    const next = [...this.order()];
    const i = next.indexOf(id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    this.order.set(next);
    void this.saveOrder();
  }

  private async saveOrder(): Promise<void> {
    const wanted = this.order();
    if (wanted.join() === this.store.playing().map((p) => p.id).join()) return; // nothing changed
    const err = await this.store.reorderPlayers(wanted);
    if (err) {
      this.store.showToast(err);
      this.order.set(this.store.playing().map((p) => p.id)); // put the list back
    }
  }

  // ---------- player colours ----------
  protected readonly palette = PALETTE;
  protected readonly colourOpen = signal<number | null>(null);

  protected toggleColour(id: number): void {
    this.colourOpen.set(this.colourOpen() === id ? null : id);
  }

  /** True when another player already uses this colour (still allowed, just flagged). */
  protected isTaken(colour: string, playerId: number): boolean {
    return this.store.players().some((x) => x.id !== playerId && x.colour.toLowerCase() === colour);
  }

  protected async pickColour(p: PlayerView, colour: string): Promise<void> {
    this.colourOpen.set(null);
    if (colour.toLowerCase() === p.colour.toLowerCase()) return;
    const err = await this.store.setPlayerColour(p.id, colour.toLowerCase());
    if (err) this.store.showToast(err);
  }

  // ---------- status effects ----------
  protected readonly penaltyEffects = computed(
    () => this.store.mode()?.status_effects.filter((e) => e.kind === 'penalty') ?? [],
  );

  protected holderName(): string {
    return this.store.diceHolder()?.name ?? 'nobody';
  }

  protected isDecided(p: PlayerView, effect: string): boolean {
    return p.statuses.find((s) => s.effect === effect)?.decided ?? false;
  }

  // ---------- dice overrides ----------
  protected async hostRoll(): Promise<void> {
    this.busy.set(true);
    const err = await this.store.rollDice();
    this.busy.set(false);
    if (err) this.store.showToast(err);
  }

  protected async hostPass(): Promise<void> {
    this.busy.set(true);
    const err = await this.store.passDice();
    this.busy.set(false);
    if (err) this.store.showToast(err);
  }

  protected async hostGive(): Promise<void> {
    if (!this.selected()) return;
    this.busy.set(true);
    const err = await this.store.giveDice(this.selected());
    this.busy.set(false);
    if (err) this.store.showToast(err);
  }

  protected withStatus(effect: string): PlayerView[] {
    return this.store.playing().filter((p) => p.statuses.some((s) => s.effect === effect));
  }

  protected hasStatus(playerId: number, effect: string): boolean {
    return this.store.players().find((p) => p.id === playerId)?.statuses.some((s) => s.effect === effect) ?? false;
  }

  protected turnsLeft(p: PlayerView, effect: string): number {
    return p.statuses.find((s) => s.effect === effect)?.turns_left ?? 0;
  }

  protected async applyStatus(fx: StatusEffectDef): Promise<void> {
    if (!this.selected()) return;
    this.busy.set(true);
    const err = await this.store.applyStatus(this.selected(), fx.id);
    this.busy.set(false);
    if (err) this.store.showToast(err);
  }

  protected async missTurn(p: PlayerView, fx: StatusEffectDef): Promise<void> {
    const err = await this.store.missTurn(p.id, fx.id);
    if (err) this.store.showToast(err);
  }

  protected async payFine(p: PlayerView, fx: StatusEffectDef): Promise<void> {
    const err = await this.store.payStatusFine(p.id, fx.id);
    if (err) this.store.showToast(err);
  }

  protected async release(p: PlayerView, fx: StatusEffectDef): Promise<void> {
    const err = await this.store.clearStatus(p.id, fx.id);
    if (err) this.store.showToast(err);
  }

  protected async switchMode(id: string): Promise<void> {
    if (this.store.mode()?.id === id) return;
    const err = await this.store.changeMode(id);
    if (err) this.store.showToast(err);
  }

  /** One-tap bank action from the game mode (for example Monopoly's Pass GO). */
  protected async quickAction(a: BankAction): Promise<void> {
    if (!this.selected()) return void this.msg.set('Tap a player on the table first');
    this.msg.set('');
    this.busy.set(true);
    const err = await (a.kind === 'pay'
      ? this.store.bankPay(this.selected(), a.amount, a.label)
      : this.store.bankCollect(this.selected(), a.amount, a.label));
    this.busy.set(false);
    if (err) this.msg.set(err);
  }

  protected async resolve(id: number, approve: boolean): Promise<void> {
    const err = await this.store.resolveRequest(id, approve);
    if (err) this.store.showToast(err);
  }

  protected async undo(id: number): Promise<void> {
    const err = await this.store.undo(id);
    if (err) this.store.showToast(err);
  }

  protected async end(): Promise<void> {
    this.confirmEnd.set(false);
    const err = await this.store.endGame();
    if (err) this.store.showToast(err);
  }

  protected close(): void {
    this.store.leave();
    void this.router.navigate(['/']);
  }

  protected toPlayer(): void {
    void this.router.navigate(['/game', this.code]);
  }

  protected home(): void {
    void this.router.navigate(['/']);
  }

  // ---------- money animation ----------
  /** Coins fly from the payer to the bank, pause there, then on to the receiver. */
  private runFlow(f: Flow): void {
    const table = this.tableEl()?.nativeElement;
    const fx = this.fxEl()?.nativeElement;
    if (!table || !fx) return;
    const box = table.getBoundingClientRect();
    const point = (id: number | null) => {
      const seat = id === null ? undefined : this.seats().find((s) => s.p.id === id);
      return seat ? { x: (seat.x / 100) * box.width, y: (seat.y / 100) * box.height } : { x: box.width / 2, y: box.height / 2 };
    };
    const from = point(f.from_id);
    const mid = { x: box.width / 2, y: box.height / 2 };
    const to = point(f.to_id);
    const symbol = this.store.currency().charAt(0) || '$';
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const duration = 1600;

    this.flash(f.from_id, 0, '#ef4444');
    this.flash(f.to_id, duration * 0.85, '#22c55e');
    this.label(fx, from, `-${this.fmt(f.amount)}`, '#ef4444', 0);
    this.label(fx, to, `+${this.fmt(f.amount)}`, '#22c55e', duration * 0.8);
    this.hubEl()?.nativeElement.animate(
      [
        { transform: 'translate(-50%, -50%) scale(1)' },
        { transform: 'translate(-50%, -50%) scale(1.14)', filter: 'brightness(1.3)' },
        { transform: 'translate(-50%, -50%) scale(1)' },
      ],
      { duration: 450, delay: duration * 0.42 },
    );
    if (reduce) return;

    const coins = Math.min(9, Math.max(3, Math.ceil(Math.log10(f.amount + 1) * 2)));
    const at = (p: { x: number; y: number }, scale: number) => `translate(${p.x}px, ${p.y}px) translate(-50%, -50%) scale(${scale})`;
    for (let i = 0; i < coins; i++) {
      const coin = document.createElement('div');
      coin.className = 'coin';
      coin.textContent = symbol;
      fx.appendChild(coin);
      const jitter = { x: (Math.random() - 0.5) * 24, y: (Math.random() - 0.5) * 24 };
      const arrive = { x: mid.x + jitter.x, y: mid.y + jitter.y };
      const anim = coin.animate(
        [
          { transform: at(from, 0.5), opacity: 0, offset: 0 },
          { transform: at(from, 0.9), opacity: 1, offset: 0.1 },
          { transform: at(arrive, 1.15), opacity: 1, offset: 0.48 },
          { transform: at(arrive, 1.15), opacity: 1, offset: 0.56 },
          { transform: at(to, 0.9), opacity: 1, offset: 0.92 },
          { transform: at(to, 0.5), opacity: 0, offset: 1 },
        ],
        { duration, delay: i * 110, easing: 'cubic-bezier(0.4, 0, 0.2, 1)', fill: 'both' },
      );
      anim.onfinish = () => coin.remove();
    }
  }

  private label(fx: HTMLElement, p: { x: number; y: number }, text: string, colour: string, delay: number): void {
    const el = document.createElement('div');
    el.className = 'fx-label';
    el.textContent = text;
    el.style.color = colour;
    fx.appendChild(el);
    const base = `translate(${p.x}px, ${p.y}px) translate(-50%, -50%)`;
    const anim = el.animate(
      [
        { transform: base, opacity: 0 },
        { transform: `${base} translateY(-18px)`, opacity: 1, offset: 0.25 },
        { transform: `${base} translateY(-44px)`, opacity: 0 },
      ],
      { duration: 1200, delay, easing: 'ease-out', fill: 'both' },
    );
    anim.onfinish = () => el.remove();
  }

  private flash(id: number | null, delay: number, colour: string): void {
    if (id === null) return;
    const seat = this.tableEl()?.nativeElement.querySelector<HTMLElement>(`[data-seat="${id}"]`);
    seat?.animate(
      [
        { boxShadow: `0 0 0 0 ${colour}00`, transform: 'translate(-50%, -50%) scale(1)' },
        { boxShadow: `0 0 28px 8px ${colour}aa`, transform: 'translate(-50%, -50%) scale(1.07)', offset: 0.4 },
        { boxShadow: `0 0 0 0 ${colour}00`, transform: 'translate(-50%, -50%) scale(1)' },
      ],
      { duration: 800, delay },
    );
  }
}
