import { Component, computed, effect, input, signal } from '@angular/core';

const PIPS: Record<number, number[]> = {
  1: [4],
  2: [0, 8],
  3: [0, 4, 8],
  4: [0, 2, 6, 8],
  5: [0, 2, 4, 6, 8],
  6: [0, 2, 3, 5, 6, 8],
};

/** A pair of dice. When `rollId` changes the faces tumble for a moment and then settle on the result. */
@Component({
  selector: 'ms-dice',
  template: `
    <div class="dice-pair" [class.tumble]="rolling()" aria-live="polite">
      @for (face of faces(); track $index; let i = $index) {
        @if (i === 1 && showTotal() && hasRoll()) {
          <span class="dice-op" aria-hidden="true">+</span>
        }
        <div class="die" [attr.aria-label]="'Die showing ' + face">
          @for (on of cells(face); track $index) {
            <span class="pip" [class.on]="on"></span>
          }
        </div>
      }
      @if (showTotal() && hasRoll()) {
        <span class="dice-op" aria-hidden="true">=</span>
        <span class="dice-total" [attr.aria-label]="'Total ' + total()">{{ rolling() ? '…' : total() }}</span>
      }
    </div>
  `,
})
export class Dice {
  readonly d1 = input<number | null>(null);
  readonly d2 = input<number | null>(null);
  readonly rollId = input(0);
  /** Show "die + die = total" with the total in large type. */
  readonly showTotal = input(false);
  protected readonly hasRoll = computed(() => this.d1() !== null && this.d2() !== null);
  protected readonly total = computed(() => (this.d1() ?? 0) + (this.d2() ?? 0));

  protected readonly rolling = signal(false);
  protected readonly faces = signal<number[]>([1, 1]);
  private lastRoll = -1;
  private timer?: ReturnType<typeof setInterval>;

  constructor() {
    effect(() => {
      const id = this.rollId();
      const a = this.d1();
      const b = this.d2();
      if (a === null || b === null) {
        this.faces.set([1, 1]);
        this.lastRoll = id;
        return;
      }
      if (this.lastRoll === -1 || id === this.lastRoll) {
        this.faces.set([a, b]); // first view or unchanged: just show it
        this.lastRoll = id;
        return;
      }
      this.lastRoll = id;
      this.tumble(a, b);
    });
  }

  protected cells(face: number): boolean[] {
    const on = new Set(PIPS[face] ?? []);
    return Array.from({ length: 9 }, (_, i) => on.has(i));
  }

  private tumble(a: number, b: number): void {
    clearInterval(this.timer);
    this.rolling.set(true);
    let ticks = 0;
    this.timer = setInterval(() => {
      if (++ticks >= 9) {
        clearInterval(this.timer);
        this.faces.set([a, b]);
        this.rolling.set(false);
        return;
      }
      this.faces.set([1 + Math.floor(Math.random() * 6), 1 + Math.floor(Math.random() * 6)]);
    }, 70);
  }
}
