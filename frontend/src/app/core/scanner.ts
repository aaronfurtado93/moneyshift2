import { Component, OnDestroy, OnInit, output, signal } from '@angular/core';
import jsQR from 'jsqr';

/**
 * In-app QR scanner.
 * - Live viewfinder when the browser allows camera access (HTTPS, or localhost).
 * - Otherwise (plain HTTP on the LAN) it falls back to taking a photo with the camera app and
 *   decoding that, which works on both Android and iOS without any special permission.
 */
@Component({
  selector: 'ms-scanner',
  template: `
    <div class="scanner" role="dialog" aria-label="Scan a QR code">
      <div class="scanner-box">
        <div class="scanner-head">
          <strong>Scan a QR code</strong>
          <button class="btn small" (click)="closed.emit()">Close</button>
        </div>

        @if (live()) {
          <video #video class="scanner-video" playsinline muted autoplay></video>
          <p class="small muted center">Point the camera at the QR code.</p>
        } @else {
          <p class="small muted">
            {{ liveReason() }} Take a photo of the QR code instead.
          </p>
        }

        <label class="btn primary block center-btn">
          {{ live() ? 'Use a photo instead' : 'Take a photo of the QR' }}
          <input type="file" accept="image/*" capture="environment" hidden (change)="onFile($event)" />
        </label>

        @if (error()) {
          <p class="error" role="alert">{{ error() }}</p>
        }
      </div>
    </div>
  `,
})
export class Scanner implements OnInit, OnDestroy {
  readonly scanned = output<string>();
  readonly closed = output<void>();

  protected readonly live = signal(false);
  protected readonly liveReason = signal('Starting the camera…');
  protected readonly error = signal('');

  private stream?: MediaStream;
  private timer?: ReturnType<typeof setInterval>;
  private done = false;

  async ngOnInit(): Promise<void> {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      this.liveReason.set('Live scanning needs HTTPS, which this connection does not have.');
      return;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } },
        audio: false,
      });
    } catch {
      this.liveReason.set('Camera access was not allowed.');
      return;
    }
    this.live.set(true);
    // The <video> exists after the next render.
    setTimeout(() => this.startLive(), 0);
  }

  ngOnDestroy(): void {
    this.stop();
  }

  private startLive(): void {
    const video = document.querySelector<HTMLVideoElement>('.scanner-video');
    if (!video || !this.stream) return;
    video.srcObject = this.stream;
    void video.play();
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    this.timer = setInterval(() => {
      if (!ctx || video.videoWidth === 0) return;
      const scale = Math.min(1, 640 / video.videoWidth);
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      this.emitIfFound(ctx.getImageData(0, 0, canvas.width, canvas.height));
    }, 200);
  }

  protected async onFile(event: Event): Promise<void> {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) return;
    this.error.set('');
    try {
      const bitmap = await createImageBitmap(file);
      // Try a few sizes: very large photos can defeat the decoder.
      for (const max of [1000, 1600, 600]) {
        const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(bitmap.width * scale);
        canvas.height = Math.round(bitmap.height * scale);
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        if (!ctx) break;
        ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        if (this.emitIfFound(ctx.getImageData(0, 0, canvas.width, canvas.height))) return;
      }
      this.error.set('Could not read a QR code from that photo. Try again, closer and in focus.');
    } catch {
      this.error.set('Could not open that photo.');
    }
  }

  private emitIfFound(image: ImageData): boolean {
    if (this.done) return true;
    const result = jsQR(image.data, image.width, image.height, { inversionAttempts: 'dontInvert' });
    if (!result?.data) return false;
    this.done = true;
    this.stop();
    this.scanned.emit(result.data);
    return true;
  }

  private stop(): void {
    clearInterval(this.timer);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = undefined;
  }
}
