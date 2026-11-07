import { Component, effect, input, signal } from '@angular/core';
import QRCode from 'qrcode';

@Component({
  selector: 'ms-qr',
  template: `@if (src()) {<img [src]="src()" [alt]="'QR code for ' + value()" [attr.width]="size()" [attr.height]="size()" />}`,
  styles: `img { display: block; border-radius: 8px; background: #fff; padding: 6px; }`,
})
export class Qr {
  readonly value = input.required<string>();
  readonly size = input(176);
  protected readonly src = signal('');

  constructor() {
    effect(() => {
      const v = this.value();
      if (!v) return;
      QRCode.toDataURL(v, { margin: 1, width: this.size() * 2 }).then((url) => this.src.set(url));
    });
  }
}
