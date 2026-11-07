import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Digits } from '../core/digits';
import { ActivatedRoute, Router } from '@angular/router';
import { GameStore } from '../core/game.store';
import { formatMoney, parseAmount } from '../core/util';

/**
 * Opened by scanning a pay/collect QR code with the phone camera. The QR only pre-fills the form;
 * the payer always sees who they are paying and confirms, and the server validates everything.
 */
@Component({
  selector: 'ms-pay',
  imports: [FormsModule, Digits],
  template: `
    <main class="page">
      @if (store.snapshot(); as s) {
        <section class="card">
          @if (done()) {
            <h2>Paid ✓</h2>
            <p>{{ fmt(paidAmount()) }} sent to <b>{{ targetName() }}</b>.</p>
            <button class="btn primary block" (click)="back()">Back to the game</button>
          } @else if (!valid()) {
            <h2>This QR code isn't valid for this game</h2>
            <button class="btn block" (click)="back()">Back to the game</button>
          } @else if (isSelf()) {
            <h2>This is your own QR code</h2>
            <p class="muted">Show it to someone else so they can pay you.</p>
            <button class="btn block" (click)="back()">Back to the game</button>
          } @else {
            <h2>Pay {{ targetName() }}</h2>
            <p class="muted small">Your balance: {{ fmt(store.myPlayer()?.balance ?? 0) }}</p>
            @if (fixedAmount()) {
              <div class="amount">{{ fmt(fixedAmount()!) }}</div>
            } @else {
              <input class="amt" [(ngModel)]="amount" msDigits placeholder="Amount" autocomplete="off" />
            }
            <button class="btn primary block" [disabled]="busy()" (click)="confirm()">
              Confirm and pay
            </button>
            <button class="btn block" (click)="back()">Cancel</button>
          }
          @if (msg()) {
            <p class="error" role="alert">{{ msg() }}</p>
          }
        </section>
      } @else {
        <p class="muted">Loading…</p>
      }
    </main>
  `,
})
export class Pay implements OnInit {
  protected readonly store = inject(GameStore);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private code = '';
  private readonly to = signal<string>('');
  protected readonly fixedAmount = signal<number | null>(null);
  protected amount = '';
  protected readonly busy = signal(false);
  protected readonly msg = signal('');
  protected readonly done = signal(false);
  protected readonly paidAmount = signal(0);

  /** Player id, or null for the bank. undefined means the link is malformed. */
  private readonly toId = computed<number | null | undefined>(() => {
    const t = this.to();
    if (t === 'bank') return null;
    const n = Number(t);
    return Number.isInteger(n) && this.store.playing().some((p) => p.id === n) ? n : undefined;
  });
  protected readonly valid = computed(() => this.toId() !== undefined);
  protected readonly isSelf = computed(() => this.toId() !== null && this.toId() === this.store.me()?.id);
  protected readonly targetName = computed(() => {
    const id = this.toId();
    return id === null ? 'the bank' : (this.store.players().find((p) => p.id === id)?.name ?? '?');
  });

  async ngOnInit(): Promise<void> {
    this.code = (this.route.snapshot.paramMap.get('code') ?? '').toUpperCase();
    const q = this.route.snapshot.queryParamMap;
    this.to.set(q.get('to') ?? '');
    this.fixedAmount.set(parseAmount(q.get('amount') ?? ''));
    const ok = await this.store.open(this.code);
    if (!ok) {
      // Not joined on this phone yet: join first, then come straight back here.
      void this.router.navigate(['/join', this.code], { queryParams: { next: this.router.url } });
    }
  }

  protected fmt(n: number): string {
    return formatMoney(this.store.currency(), n);
  }

  protected async confirm(): Promise<void> {
    const amount = this.fixedAmount() ?? parseAmount(this.amount);
    if (amount === null) return void this.msg.set('Enter a whole amount greater than zero');
    const id = this.toId();
    if (id === undefined) return;
    this.msg.set('');
    this.busy.set(true);
    const err = await this.store.pay(id, amount);
    this.busy.set(false);
    if (err) this.msg.set(err);
    else {
      this.paidAmount.set(amount);
      this.done.set(true);
    }
  }

  protected back(): void {
    void this.router.navigate(['/game', this.code]);
  }
}
