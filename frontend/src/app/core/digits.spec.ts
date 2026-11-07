import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { Digits } from './digits';

@Component({
  imports: [FormsModule, Digits],
  template: '<input msDigits [(ngModel)]="value" />',
})
class Host {
  value = '';
}

describe('Digits', () => {
  async function setup() {
    await TestBed.configureTestingModule({ imports: [Host] }).compileComponents();
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    const input = fixture.nativeElement.querySelector('input') as HTMLInputElement;
    return { fixture, input };
  }

  it('strips everything except 0-9 from pasted or entered text', async () => {
    const { fixture, input } = await setup();
    for (const [raw, expected] of [
      ['12abc34', '1234'],
      ['1,000.50', '100050'],
      ['-5', '5'],
      ['+7e3', '73'],
      ['  42 ', '42'],
      ['٣٤', ''], // non-ASCII digits are not accepted either
    ]) {
      input.value = raw;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await fixture.whenStable();
      expect(input.value).toBe(expected);
      expect(fixture.componentInstance.value).toBe(expected);
    }
  });

  it('blocks non-digit keystrokes and allows digits', async () => {
    const { input } = await setup();
    const typed = (data: string) => {
      const e = new InputEvent('beforeinput', { data, cancelable: true, bubbles: true });
      input.dispatchEvent(e);
      return e.defaultPrevented;
    };
    expect(typed('e')).toBe(true);
    expect(typed('.')).toBe(true);
    expect(typed('-')).toBe(true);
    expect(typed('5')).toBe(false);
  });

  it('asks the phone for a numeric keypad and limits the length', async () => {
    const { input } = await setup();
    expect(input.getAttribute('inputmode')).toBe('numeric');
    expect(input.getAttribute('maxlength')).toBe('10');
  });
});
