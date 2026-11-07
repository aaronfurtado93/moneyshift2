import { Component, OnDestroy, OnInit, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Dice } from '../core/dice';
import { Digits } from '../core/digits';
import { ActivatedRoute, Router } from '@angular/router';
import { GameStore } from '../core/game.store';
import { BankAction, Callout, TxView } from '../core/models';
import { Qr } from '../core/qr';
import { Scanner } from '../core/scanner';
import { formatMoney, parseAmount, parsePayLink } from '../core/util';

@Component({
  selector: 'ms-game',
  imports: [FormsModule, Digits, Dice, Qr, Scanner],
  template: `
    @if (store.snapshot(); as s) {
      <main class="page">
        <header class="topbar">
          <span class="chip">Game <strong>{{ s.game.code }}</strong> · {{ s.game.mode.name }}</span>
          <button class="chip" (click)="store.sound.toggle()" [attr.aria-pressed]="store.sound.enabled()">
            {{ store.sound.enabled() ? '🔊 Sound on' : '🔇 Sound off' }}
          </button>
          <span class="status" [class.on]="store.connection() === 'online'">
            <i></i>{{ store.connection() === 'online' ? 'Live' : 'Reconnecting…' }}
          </span>
        </header>

        @if (store.queue().length) {
          <p class="banner warn">
            Offline: {{ store.queue().length }} action(s) saved and will send when you reconnect.
          </p>
        }
        @if (store.toast()) {
          <p class="toast" role="status">{{ store.toast() }}</p>
        }
        @if (store.ended()) {
          <section class="card">
            <h2>Game over</h2>
            <p class="muted small">Final balances</p>
            <ol class="standings">
              @for (p of ranking(); track p.id) {
                <li><span class="dot" [style.background]="p.colour"></span>{{ p.name }}<b>{{ bal(p.balance) }}</b></li>
              }
            </ol>
            <p class="muted small">The host ended this game for everyone.</p>
            <button class="btn primary block" (click)="leave()">Close game</button>
          </section>
        }

        <section class="card balance" [style.border-color]="s.me.colour">
          <span class="muted small">{{ s.me.name }}{{ store.isHost() ? ' · host & bank' : '' }}</span>
          <div class="amount">{{ fmt(store.myPlayer()?.balance ?? 0) }}</div>
        </section>

        @for (st of store.myPlayer()?.statuses ?? []; track st.effect) {
          @if (st.effect === 'jail') {
            <section class="card jail">
              <h2>🔒 You are in Jail</h2>
              @if (!st.decided) {
                <p class="small muted">
                  You get one chance to pay the fine. Or miss this turn, and then the next two as well.
                </p>
                <div class="row">
                  @if (effectFine('jail'); as fine) {
                    <button class="btn primary grow" [disabled]="busy()" (click)="payFine('jail')">Pay {{ fmt(fine) }} fine</button>
                  }
                  <button class="btn grow" [disabled]="busy() || !onMyTurn()" (click)="missJailTurn()">Miss this turn</button>
                </div>
                @if (!onMyTurn()) {
                  <p class="small muted">You can choose to miss when it is your turn.</p>
                }
              } @else {
                <p class="small muted">
                  You chose to miss your turn. {{ st.turns_left }} more turn(s) to miss, and the fine can no longer be paid.
                </p>
              }
            </section>
          }
        }

        @if (store.turn(); as t) {
          <!-- Open on your own turn, collapsed while someone else is up. -->
          <section class="card dice-card acc" [class.holder-ring]="store.iHoldTheTurn()">
            <button class="acc-head" (click)="turnOpen.set(!turnOpen())" [attr.aria-expanded]="turnOpen()">
              <span>
                {{ t.effect === 'dice' ? '🎲 Dice' : '🃏 Cards' }}
                <span class="small muted">
                  · {{ store.iHoldTheTurn() ? "your turn" : (store.turnHolder()?.name ?? 'someone') + "'s turn" }}
                </span>
              </span>
              <i class="chev" [class.up]="turnOpen()" aria-hidden="true"></i>
            </button>
            @if (turnOpen()) {
              <p class="small muted">
                @if (store.iHoldTheTurn()) {
                  <b>It's your turn</b>.
                  @if (t.effect === 'dice') {Roll doubles three times in a row and you go to Jail.} @else {Play your card, then tell us what you played.}
                } @else {
                  It's <b>{{ store.turnHolder()?.name ?? 'someone' }}</b>'s turn
                }
                @if (t.effect === 'card') {
                  <br />Direction of play: <b>{{ t.direction === 1 ? '↻ clockwise' : '↺ counter-clockwise' }}</b>
                }
              </p>
              @if (t.effect === 'dice') {
                <ms-dice [d1]="t.last?.d1 ?? null" [d2]="t.last?.d2 ?? null" [rollId]="t.last?.roll_id ?? 0" [showTotal]="true" />
                @if (t.last; as l) {
                  <p class="small">
                    {{ nameOf(l.roller_id) }} rolled
                    @if (l.double && !l.jailed) {<span> · doubles!</span>}
                    @if (l.jailed) {<span> · third double in a row: Jail!</span>}
                  </p>
                }
              }
              @if (store.iHoldTheTurn() && !store.ended()) {
                @if (myJail() && !myJail()!.decided) {
                  <p class="small muted">You are in Jail: pay the fine or miss your turn first.</p>
                } @else if (t.effect === 'dice') {
                  @if (t.streak > 0 && !t.rolled) {
                    <p class="small warn">
                      Doubles {{ t.streak }} in a row. {{ t.streak >= 2 ? 'One more and you go to Jail!' : 'Roll again, or end your turn.' }}
                    </p>
                  }
                  @if (!t.rolled) {
                    <button class="btn primary block" [disabled]="busy()" (click)="rollDice()">
                      {{ t.streak ? 'Roll again (doubles)' : 'Roll the dice' }}
                    </button>
                  }
                  @if (t.acted) {
                    <button class="btn block" [class.primary]="t.rolled" [disabled]="busy()" (click)="endTurn()">End turn</button>
                  }
                } @else {
                  <!-- Cards are in hand, so there is no roll: three ways to finish the turn. -->
                  <button class="btn primary block" [disabled]="busy()" (click)="endTurn()">End turn</button>
                  <button class="btn block" [disabled]="busy()" (click)="skipTurn()">⏭ Skip next player</button>
                  <button class="btn block" [disabled]="busy()" (click)="reverseTurn()">🔄 Reverse</button>
                }
              }
            }
          </section>

          @if (store.mode()?.callouts && !store.ended()) {
            @if (t.callout; as c) {
              <section class="card callout" aria-live="assertive">
                <h2>📣 Call out!</h2>
                <p>
                  <b>{{ nameOf(c.caller_id) }}</b> says <b>{{ nameOf(c.target_id) }}</b> ended their turn without
                  saying UNO.
                </p>
                <p class="small muted">Agreed: {{ c.agree.length }} of {{ c.voters.length }}. If everyone agrees they go to Jail.</p>
                @if (canVote(c)) {
                  <div class="row">
                    <button class="btn primary grow" [disabled]="busy()" (click)="vote(true)">Agree</button>
                    <button class="btn grow" [disabled]="busy()" (click)="vote(false)">Disagree</button>
                  </div>
                } @else if (c.target_id === store.me()?.id) {
                  <p class="small">The others are deciding…</p>
                } @else {
                  <p class="small muted">Waiting for the others to vote…</p>
                }
              </section>
            } @else if (t.last_ender !== null && t.last_ender !== store.me()?.id && store.me()?.plays) {
              <button class="btn danger block" [disabled]="busy()" (click)="callOut()">
                📣 Call Out! {{ nameOf(t.last_ender) }} didn't say UNO
              </button>
            }
          }
        }

        @if (!store.ended()) {

          <section class="card">
            <h2>Pay</h2>
            <div class="picker">
              @for (p of store.others(); track p.id) {
                <button class="pick" [class.sel]="target() === p.id" [style.border-left-color]="p.colour" (click)="target.set(p.id)">
                  <span class="pname"><i class="presence" [class.on]="p.connected"></i> {{ p.name }}</span>
                  <span class="small muted">{{ bal(p.balance) }}</span>
                </button>
              }
              <button class="pick" [class.sel]="target() === bankId" (click)="target.set(bankId)">
                <span class="pname">🏦 Bank</span>
                <span class="small muted">fines, taxes</span>
              </button>
            </div>
            @if (store.others().length === 0) {
              <p class="muted small">Waiting for other players to join. You can still pay the bank.</p>
            }
            <input class="amt" [(ngModel)]="payAmount" msDigits placeholder="Amount" autocomplete="off" />
            <div class="chips">
              @for (c of quick(); track c) {
                <button class="chip" (click)="add(c)">+{{ c }}</button>
              }
              <button class="chip" (click)="payAmount = ''">Clear</button>
            </div>
            <button class="btn primary block" [disabled]="busy() || !target()" (click)="pay()">
              Pay {{ targetName() }}
            </button>
            @if (payMsg()) {
              <p class="error" role="alert">{{ payMsg() }}</p>
            }
          </section>


          @if (!store.isHost()) {
            <section class="card">
              <h2>Ask the bank</h2>
              <p class="muted small">The host decides whether to approve.</p>
              <div class="row">
                <input class="grow" [(ngModel)]="askAmount" msDigits placeholder="Amount" autocomplete="off" />
                <button class="btn" [disabled]="busy()" (click)="ask()">Ask</button>
              </div>
              @for (r of s.requests; track r.id) {
                <p class="small muted">Waiting: {{ fmt(r.amount) }} requested</p>
              }
              @if (askMsg()) {
                <p class="error" role="alert">{{ askMsg() }}</p>
              }
            </section>
          }
        }

        @if (store.isHost()) {
          <section class="card host">
            <h2>Host &amp; bank</h2>

            @if (!store.ended()) {
              <button class="btn block" (click)="openBank()">Open the bank dashboard (larger screen view)</button>
              <h3>Invite players</h3>
              <div class="invite">
                <ms-qr [value]="store.joinUrl()" />
                <div>
                  <div class="code big">{{ s.game.code }}</div>
                  <p class="small muted">Scan the QR with the phone camera, or open:</p>
                  <p class="small url">{{ store.joinUrl() }}</p>
                </div>
              </div>
            }

            @if (s.requests.length) {
              <h3>Requests to the bank</h3>
              @for (r of s.requests; track r.id) {
                <div class="line">
                  <span>{{ nameOf(r.player_id) }} asks <b>{{ fmt(r.amount) }}</b></span>
                  <span class="actions">
                    <button class="btn small primary" (click)="resolve(r.id, true)">Approve</button>
                    <button class="btn small" (click)="resolve(r.id, false)">Deny</button>
                  </span>
                </div>
              }
            }

            @if (!store.ended()) {
              <h3>Bank pay / collect</h3>
              <div class="picker">
                @for (p of store.playing(); track p.id) {
                  <button class="pick" [class.sel]="bankPlayer === p.id" [style.border-left-color]="p.colour" (click)="bankPlayer = p.id">
                    <span class="pname">{{ p.name }}</span>
                    <span class="small muted">{{ bal(p.balance) }}</span>
                  </button>
                }
              </div>
              <div class="row">
                <input class="grow" [(ngModel)]="bankAmount" msDigits placeholder="Amount" autocomplete="off" />
                <button class="btn primary" [disabled]="busy()" (click)="bank('pay')">Bank pays</button>
                <button class="btn" [disabled]="busy()" (click)="bank('collect')">Bank collects</button>
              </div>
              @if (store.mode()?.bank_actions?.length) {
                <div class="qa">
                  @for (a of store.mode()!.bank_actions; track a.id) {
                    <button class="btn small" [class.primary]="a.kind === 'pay'" [disabled]="busy() || !bankPlayer" (click)="quickAction(a)">
                      {{ a.label }} {{ a.kind === 'pay' ? '+' : '−' }}{{ fmt(a.amount) }}
                    </button>
                  }
                </div>
              }
              @if (hostMsg()) {
                <p class="error" role="alert">{{ hostMsg() }}</p>
              }
            }

            <h3>Ledger</h3>
            @if (s.transactions.length === 0) {
              <p class="muted small">No transactions yet.</p>
            }
            @for (t of s.transactions; track t.id) {
              <div class="line" [class.struck]="t.reversed">
                <span>#{{ t.id }} {{ nameOf(t.from_id) }} → {{ nameOf(t.to_id) }} <b>{{ fmt(t.amount) }}</b>@if (t.note && t.kind !== 'reversal') {<span class="small muted"> · {{ t.note }}</span>}</span>
                @if (canUndo(t)) {
                  <button class="btn small" (click)="undo(t.id)">Undo</button>
                } @else if (t.reversed) {
                  <span class="small muted">undone</span>
                }
              </div>
            }

            <h3>Restart / end game</h3>
            @if (confirmRestart()) {
              <p class="small muted">Everyone goes back to {{ fmt(s.game.starting_balance) }} and the ledger is cleared.</p>
              <div class="row">
                <button class="btn danger grow" (click)="restart()">Yes, restart the game</button>
                <button class="btn" (click)="confirmRestart.set(false)">Cancel</button>
              </div>
            } @else if (confirmEnd()) {
              <div class="row">
                <button class="btn danger grow" (click)="end()">Yes, end the game</button>
                <button class="btn" (click)="confirmEnd.set(false)">Cancel</button>
              </div>
            } @else {
              <div class="row">
                <button class="btn grow" (click)="confirmEnd.set(false); confirmRestart.set(true)">Restart game…</button>
                @if (!store.ended()) {
                  <button class="btn grow" (click)="confirmRestart.set(false); confirmEnd.set(true)">End game…</button>
                }
              </div>
            }
          </section>
        }

        <!-- Only the host sees the player list and activity; players see just their own screen. -->
        @if (store.isHost()) {
          <section class="card">
            <h2>Players</h2>
            @for (p of store.playing(); track p.id) {
              <div class="line">
                <span><span class="dot" [style.background]="p.colour"></span>{{ p.name }}
                  @if (p.role === 'host') {<span class="tag">host</span>}
                </span>
                <b>{{ bal(p.balance) }}</b>
              </div>
            }
          </section>

          <section class="card">
            <h2>Activity</h2>
            @for (a of s.activity; track a.seq) {
              <p class="small act">{{ a.text }}</p>
            } @empty {
              <p class="muted small">Nothing yet.</p>
            }
          </section>
        }

        <!-- Scan and receive by QR: the last cards for players, collapsed until needed. -->
        @if (!store.ended()) {
          <section class="card acc">
            <button class="acc-head" (click)="togglePanel('scan')" [attr.aria-expanded]="isOpen('scan')">
              <span>Scan to pay</span><i class="chev" [class.up]="isOpen('scan')" aria-hidden="true"></i>
            </button>
            @if (isOpen('scan')) {
              <p class="muted small">Scan a player's or the bank's QR code to pay them.</p>
              <button class="btn primary block" (click)="scanning.set(true)">Scan QR code</button>
            }
            @if (scanMsg()) {
              <p class="error" role="alert">{{ scanMsg() }}</p>
            }
          </section>

          <section class="card acc">
            <button class="acc-head" (click)="togglePanel('receive')" [attr.aria-expanded]="isOpen('receive')">
              <span>Receive by QR</span><i class="chev" [class.up]="isOpen('receive')" aria-hidden="true"></i>
            </button>
            @if (isOpen('receive')) {
              <p class="muted small">Show this to a player. They scan it with their phone camera and confirm.</p>
              <input [(ngModel)]="receiveAmount" msDigits placeholder="Amount (optional)" autocomplete="off" />
              <div class="qrbox"><ms-qr [value]="receiveUrl()" [size]="220" /></div>
              <p class="small muted center">{{ receiveHint() }}</p>
            }
          </section>
        }

        @if (!store.ended()) {
          @if (confirmLeave()) {
            <section class="card">
              <p>
                @if (store.isHost()) {
                  <b>You are the host.</b> If you leave on this phone you can no longer run the bank for this game from it.
                } @else {
                  If you leave, you will have to join again as a new player (your balance stays with the old seat).
                }
              </p>
              <div class="row">
                <button class="btn danger grow" (click)="leave()">Leave game</button>
                <button class="btn" (click)="confirmLeave.set(false)">Stay</button>
              </div>
            </section>
          } @else {
            <button class="btn link" (click)="confirmLeave.set(true)">Leave this game on this phone</button>
          }
        }
      </main>
      @if (scanning()) {
        <ms-scanner (scanned)="onScanned($event)" (closed)="scanning.set(false)" />
      }
    } @else if (store.notJoined()) {
      <main class="page">
        <section class="card">
          <h2>You're not in game {{ code }} on this phone</h2>
          <p class="muted small">It may have been closed, or this phone left it.</p>
          <button class="btn primary block" (click)="joinThis()">Join game {{ code }}</button>
          <button class="btn block" (click)="home()">Back to start</button>
        </section>
      </main>
    } @else {
      <main class="page"><p class="muted">Connecting to the host…</p></main>
    }
  `,
})
export class Game implements OnInit, OnDestroy {
  protected readonly store = inject(GameStore);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected code = '';
  protected readonly quick = this.store.quickAmounts;
  /** Pseudo recipient id meaning "the bank". */
  protected readonly bankId = -1;
  protected readonly target = signal<number>(0);
  protected payAmount = '';
  protected askAmount = '';
  protected bankAmount = '';
  protected receiveAmount = '';
  protected bankPlayer = 0;
  protected readonly busy = signal(false);
  protected readonly payMsg = signal('');
  protected readonly askMsg = signal('');
  protected readonly hostMsg = signal('');
  protected readonly confirmEnd = signal(false);
  protected readonly confirmRestart = signal(false);
  protected readonly scanning = signal(false);
  protected readonly confirmLeave = signal(false);
  /** Accordion for the QR cards: one open at a time, both collapsed by default. */
  private readonly panel = signal<'scan' | 'receive' | null>(null);
  protected readonly scanMsg = signal('');
  private wakeLock?: { release(): Promise<void> };

  protected readonly targetName = computed(
    () =>
      this.target() === this.bankId
        ? 'the bank'
        : (this.store.others().find((p) => p.id === this.target())?.name ?? 'someone'),
  );
  protected readonly receiveUrl = () => this.store.payUrl(this.store.me()?.id ?? 0, parseAmount(this.receiveAmount));
  protected readonly receiveHint = () => {
    const a = parseAmount(this.receiveAmount);
    return a ? `Asks for ${this.fmt(a)}` : 'Any amount: the payer chooses';
  };
  protected readonly ranking = computed(() => [...this.store.playing()].sort((a, b) => (b.balance ?? 0) - (a.balance ?? 0)));

  constructor() {
    // Keep a valid recipient selected as players join.
    effect(() => {
      const others = this.store.others();
      const t = this.target();
      if (t !== this.bankId && others.length && !others.some((p) => p.id === t)) this.target.set(others[0].id);
    });
    effect(() => this.turnOpen.set(this.store.iHoldTheTurn() || this.needsMyVote()));
    // A banker-only host has no player view: send them to the dashboard.
    effect(() => {
      if (this.store.bankOnly()) void this.router.navigate(['/bank', this.code], { replaceUrl: true });
    });
  }

  ngOnInit(): void {
    this.code = (this.route.snapshot.paramMap.get('code') ?? '').toUpperCase();
    void this.store.open(this.code);
    void this.keepAwake();
  }

  ngOnDestroy(): void {
    this.store.close();
    void this.wakeLock?.release();
  }

  protected fmt(n: number): string {
    return formatMoney(this.store.currency(), n);
  }

  /** Money for display; empty when the server keeps it private. */
  protected bal(n: number | null): string {
    return n === null ? '' : this.fmt(n);
  }

  protected nameOf(id: number | null): string {
    return id === null ? 'Bank' : (this.store.players().find((p) => p.id === id)?.name ?? '?');
  }

  protected canUndo(t: TxView): boolean {
    return !t.reversed && t.kind !== 'reversal' && !this.store.ended();
  }

  protected add(n: number): void {
    this.payAmount = String((parseAmount(this.payAmount) ?? 0) + n);
  }

  protected async pay(): Promise<void> {
    const amount = parseAmount(this.payAmount);
    if (!this.target()) return;
    if (amount === null) return void this.payMsg.set('Enter a whole amount greater than zero');
    this.payMsg.set('');
    this.busy.set(true);
    const err = await this.store.pay(this.target() === this.bankId ? null : this.target(), amount);
    this.busy.set(false);
    if (err) this.payMsg.set(err);
    else this.payAmount = '';
  }

  protected async ask(): Promise<void> {
    const amount = parseAmount(this.askAmount);
    if (amount === null) return void this.askMsg.set('Enter a whole amount greater than zero');
    this.askMsg.set('');
    this.busy.set(true);
    const err = await this.store.askBank(amount);
    this.busy.set(false);
    if (err) this.askMsg.set(err);
    else this.askAmount = '';
  }

  protected async bank(op: 'pay' | 'collect'): Promise<void> {
    const amount = parseAmount(this.bankAmount);
    if (!this.bankPlayer) return void this.hostMsg.set('Choose a player');
    if (amount === null) return void this.hostMsg.set('Enter a whole amount greater than zero');
    this.hostMsg.set('');
    this.busy.set(true);
    const err = await (op === 'pay'
      ? this.store.bankPay(this.bankPlayer, amount)
      : this.store.bankCollect(this.bankPlayer, amount));
    this.busy.set(false);
    if (err) this.hostMsg.set(err);
    else this.bankAmount = '';
  }

  /** The turn card is open on your turn (or when you must vote) and collapsed otherwise; you can still open it. */
  protected readonly turnOpen = signal(false);
  protected readonly needsMyVote = computed(() => {
    const c = this.store.turn()?.callout;
    return !!c && this.canVote(c);
  });
  protected readonly myJail = computed(() => this.store.myPlayer()?.statuses.find((s) => s.effect === 'jail') ?? null);
  /** True on this player's turn, or in modes without dice (where there are no turns to wait for). */
  protected readonly onMyTurn = computed(() => !this.store.turn() || this.store.iHoldTheTurn());

  protected async rollDice(): Promise<void> {
    this.busy.set(true);
    const err = await this.store.rollDice();
    this.busy.set(false);
    if (err) this.store.showToast(err);
  }

  protected canVote(c: Callout): boolean {
    const me = this.store.me()?.id;
    return me !== undefined && c.voters.includes(me) && !c.agree.includes(me) && !c.disagree.includes(me);
  }

  protected async skipTurn(): Promise<void> {
    this.busy.set(true);
    const err = await this.store.skipTurn();
    this.busy.set(false);
    if (err) this.store.showToast(err);
  }

  protected async reverseTurn(): Promise<void> {
    this.busy.set(true);
    const err = await this.store.reverseTurn();
    this.busy.set(false);
    if (err) this.store.showToast(err);
  }

  protected async callOut(): Promise<void> {
    this.busy.set(true);
    const err = await this.store.startCallout();
    this.busy.set(false);
    if (err) this.store.showToast(err);
  }

  protected async vote(agree: boolean): Promise<void> {
    this.busy.set(true);
    const err = await this.store.voteCallout(agree);
    this.busy.set(false);
    if (err) this.store.showToast(err);
  }

  protected async endTurn(): Promise<void> {
    this.busy.set(true);
    const err = await this.store.endTurn();
    this.busy.set(false);
    if (err) this.store.showToast(err);
  }

  protected async missJailTurn(): Promise<void> {
    const me = this.store.me();
    if (!me) return;
    this.busy.set(true);
    const err = await this.store.missTurn(me.id, 'jail');
    this.busy.set(false);
    if (err) this.store.showToast(err);
  }

  protected effectFine(effect: string): number {
    return this.store.mode()?.status_effects.find((e) => e.id === effect)?.fine ?? 0;
  }

  protected async payFine(effect: string): Promise<void> {
    const me = this.store.me();
    if (!me) return;
    this.busy.set(true);
    const err = await this.store.payStatusFine(me.id, effect);
    this.busy.set(false);
    if (err) this.store.showToast(err);
  }

  protected async quickAction(a: BankAction): Promise<void> {
    if (!this.bankPlayer) return void this.hostMsg.set('Choose a player');
    this.hostMsg.set('');
    this.busy.set(true);
    const err = await (a.kind === 'pay'
      ? this.store.bankPay(this.bankPlayer, a.amount, a.label)
      : this.store.bankCollect(this.bankPlayer, a.amount, a.label));
    this.busy.set(false);
    if (err) this.hostMsg.set(err);
  }

  protected async resolve(id: number, approve: boolean): Promise<void> {
    const err = await this.store.resolveRequest(id, approve);
    if (err) this.store.showToast(err);
  }

  protected async undo(id: number): Promise<void> {
    const err = await this.store.undo(id);
    if (err) this.store.showToast(err);
  }

  protected async restart(): Promise<void> {
    this.confirmRestart.set(false);
    const err = await this.store.restartGame();
    if (err) this.store.showToast(err);
  }

  protected async end(): Promise<void> {
    this.confirmEnd.set(false);
    const err = await this.store.endGame();
    if (err) this.store.showToast(err);
  }

  protected onScanned(text: string): void {
    this.scanning.set(false);
    const link = parsePayLink(text, this.code);
    if (!link) return void this.scanMsg.set('That is not a pay code for this game.');
    this.scanMsg.set('');
    void this.router.navigate(['/pay', this.code], { queryParams: link });
  }

  protected isOpen(p: 'scan' | 'receive'): boolean {
    return this.panel() === p;
  }

  protected togglePanel(p: 'scan' | 'receive'): void {
    this.panel.set(this.panel() === p ? null : p);
  }

  protected openBank(): void {
    void this.router.navigate(['/bank', this.code]);
  }

  protected leave(): void {
    this.store.leave();
    void this.router.navigate(['/']);
  }

  protected home(): void {
    void this.router.navigate(['/']);
  }

  protected joinThis(): void {
    void this.router.navigate(['/join', this.code]);
  }

  /** Keep the screen on during play where the browser allows it (needs HTTPS; silently skipped on HTTP). */
  private async keepAwake(): Promise<void> {
    try {
      const nav = navigator as unknown as { wakeLock?: { request(t: 'screen'): Promise<{ release(): Promise<void> }> } };
      this.wakeLock = await nav.wakeLock?.request('screen');
    } catch {
      /* unsupported or denied */
    }
  }
}
