import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Digits } from '../core/digits';
import { ActivatedRoute, Router } from '@angular/router';
import { Api } from '../core/api';
import { GameMode } from '../core/models';
import { SessionStore } from '../core/session';

@Component({
  selector: 'ms-home',
  imports: [FormsModule, Digits],
  template: `
    <main class="page">
      <h1 class="brand">MoneyShift</h1>
      <p class="muted">Money for your board game, on everyone's phone.</p>

      @if (conflict(); as c) {
        <section class="card">
          <h2>You're already in game {{ c }}</h2>
          <p class="muted small">Joining {{ joinCode() }} means leaving it on this phone.</p>
          <button class="btn primary block" (click)="resumeGame(c)">Back to my game</button>
          <button class="btn block" (click)="leaveAndContinue(c)">Leave it and join {{ joinCode() }}</button>
        </section>
      }

      @if (!joinCode() && !conflict()) {
        <section class="card">
          <h2>Start a game</h2>
          <p class="muted small">You become the host and the bank.</p>
          @if (modes().length) {
            <div class="modes" role="radiogroup" aria-label="Game mode">
              @for (m of modes(); track m.id) {
                <button class="mode" role="radio" [attr.aria-checked]="mode() === m.id" [class.sel]="mode() === m.id" (click)="pickMode(m)">
                  <b>{{ m.name }}</b>
                  <span class="small muted">{{ m.description }}</span>
                </button>
              }
            </div>
          }
          <label>Your name <input [(ngModel)]="hostName" maxlength="24" autocomplete="off" /></label>
          <label class="check">
            <input type="checkbox" [(ngModel)]="bankOnly" />
            I'm only the bank (not playing). Use a big screen for the bank dashboard.
          </label>
          <div class="row">
            <label class="grow">Starting money
              <input [(ngModel)]="startAmount" msDigits />
            </label>
            <label class="narrow">Symbol <input [(ngModel)]="currency" maxlength="3" /></label>
          </div>
          <button class="btn primary block" [disabled]="busy()" (click)="create()">Create game</button>
        </section>
      }

      @if (!conflict()) {
      <section class="card">
        <h2>Join a game</h2>
        <label>Game code
          <input [(ngModel)]="code" maxlength="4" autocapitalize="characters" autocomplete="off" class="code" />
        </label>
        <label>Your name <input [(ngModel)]="playerName" maxlength="24" autocomplete="off" /></label>
        <button class="btn block" [class.primary]="!!joinCode()" [disabled]="busy()" (click)="join()">Join</button>
      </section>
      }

      @if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      }
    </main>
  `,
})
export class Home implements OnInit {
  private readonly api = inject(Api);
  private readonly sessions = inject(SessionStore);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected hostName = '';
  protected bankOnly = false;
  protected readonly modes = signal<GameMode[]>([]);
  protected readonly mode = signal('monopoly');
  protected startAmount = '1500';
  protected currency = '$';
  protected code = '';
  protected playerName = '';
  protected readonly joinCode = signal('');
  protected readonly conflict = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal('');

  ngOnInit(): void {
    const fromLink = this.route.snapshot.paramMap.get('code')?.toUpperCase() ?? '';
    this.joinCode.set(fromLink);
    this.code = fromLink;
    void this.loadModes();
    const current = this.sessions.current();
    if (fromLink && this.sessions.get(fromLink)) return this.go(fromLink);
    if (current && !fromLink) return this.go(current.code, true); // coming back: resume where you were
    if (current && fromLink && current.code !== fromLink) {
      if (current.ended) this.sessions.clear(current.code); // that game is over; nothing to protect
      else this.conflict.set(current.code); // do not silently switch games
    }
  }

  private async loadModes(): Promise<void> {
    try {
      const { default: def, modes } = await this.api.modes();
      this.modes.set(modes);
      const chosen = modes.find((m) => m.id === def) ?? modes[0];
      if (chosen) this.pickMode(chosen);
    } catch {
      /* offline or older server: the form still works with its defaults */
    }
  }

  /** Choosing a mode fills in its starting money and symbol; both stay editable for house rules. */
  protected pickMode(m: GameMode): void {
    this.mode.set(m.id);
    this.startAmount = String(m.starting_balance);
    this.currency = m.currency;
  }

  protected resumeGame(code: string): void {
    void this.router.navigate(['/game', code], { replaceUrl: true });
  }

  protected leaveAndContinue(code: string): void {
    this.sessions.clear(code);
    this.conflict.set(null);
  }

  protected go(code: string, replace = false): void {
    // After joining from a scanned pay link, continue to that payment (same-site paths only).
    const next = this.route.snapshot.queryParamMap.get('next');
    if (next && next.startsWith('/') && !next.startsWith('//')) void this.router.navigateByUrl(next);
    else void this.router.navigate(['/game', code], { replaceUrl: replace });
  }

  protected async create(): Promise<void> {
    if (!this.hostName.trim() && !this.bankOnly) return this.fail('Enter your name');
    if (!/^\d{1,10}$/.test(this.startAmount.trim())) return this.fail('Starting money must be a whole number');
    const amount = Number(this.startAmount.trim());
    await this.attempt(async () => {
      const g = await this.api.createGame({
        host_name: this.hostName.trim() || 'Bank',
        mode: this.mode(),
        starting_balance: amount,
        currency: this.currency.trim() || '$',
        host_plays: !this.bankOnly,
      });
      this.sessions.save(g.code, { token: g.token, playerId: g.player_id });
      if (this.bankOnly) void this.router.navigate(['/bank', g.code]);
      else this.go(g.code);
    });
  }

  protected async join(): Promise<void> {
    const code = this.code.trim().toUpperCase();
    if (code.length !== 4) return this.fail('Enter the 4-character game code');
    if (!this.playerName.trim()) return this.fail('Enter your name');
    await this.attempt(async () => {
      const g = await this.api.join(code, this.playerName);
      this.sessions.save(g.code, { token: g.token, playerId: g.player_id });
      this.go(g.code);
    });
  }

  private fail(msg: string): void {
    this.error.set(msg);
  }

  private async attempt(fn: () => Promise<void>): Promise<void> {
    this.error.set('');
    this.busy.set(true);
    try {
      await fn();
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : 'Something went wrong');
    } finally {
      this.busy.set(false);
    }
  }
}
