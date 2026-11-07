import { Directive, ElementRef, inject } from '@angular/core';

/**
 * Amount fields accept the digits 0-9 and nothing else: no letters, signs, decimal points,
 * spaces, commas or exponents, whether typed, pasted or entered through a phone keyboard.
 */
@Directive({
  selector: 'input[msDigits]',
  host: {
    inputmode: 'numeric',
    autocomplete: 'off',
    maxlength: '10',
    enterkeyhint: 'done',
    '(beforeinput)': 'onBeforeInput($event)',
    '(input)': 'onInput()',
  },
})
export class Digits {
  private readonly el = inject<ElementRef<HTMLInputElement>>(ElementRef);

  /** Block typed characters that are not digits before they appear. */
  protected onBeforeInput(e: InputEvent): void {
    if (e.data && /\D/.test(e.data)) e.preventDefault();
  }

  /** Clean up anything that still got in (paste, autofill, some Android keyboards). */
  protected onInput(): void {
    const input = this.el.nativeElement;
    const clean = input.value.replace(/\D/g, '').slice(0, 10);
    if (clean !== input.value) {
      input.value = clean;
      input.dispatchEvent(new Event('input', { bubbles: true })); // let ngModel see the cleaned value
    }
  }
}
