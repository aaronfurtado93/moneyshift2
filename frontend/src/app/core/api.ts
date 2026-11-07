import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';
import { Created, GameMode, ServerInfo, Snapshot } from './models';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
  }

  /** True when the request never reached the host (offline, Wi-Fi dropped, server asleep). */
  get network(): boolean {
    return this.status === 0;
  }
}

@Injectable({ providedIn: 'root' })
export class Api {
  private readonly http = inject(HttpClient);

  info() {
    return this.call(this.http.get<ServerInfo>('/api/info'));
  }

  modes() {
    return this.call(this.http.get<{ default: string; modes: GameMode[] }>('/api/modes'));
  }

  turn(code: string, token: string, action: 'roll' | 'end' | 'skip' | 'reverse' | 'pass') {
    return this.call(this.http.post(`/api/games/${code}/turn/${action}`, {}, this.auth(token)));
  }

  assignTurn(code: string, token: string, playerId: number) {
    return this.call(this.http.post(`/api/games/${code}/turn/assign`, { player_id: playerId }, this.auth(token)));
  }

  callout(code: string, token: string, action: 'start' | 'cancel') {
    const path = action === 'start' ? 'callout' : 'callout/cancel';
    return this.call(this.http.post(`/api/games/${code}/turn/${path}`, {}, this.auth(token)));
  }

  voteCallout(code: string, token: string, agree: boolean) {
    return this.call(this.http.post(`/api/games/${code}/turn/callout/vote`, { agree }, this.auth(token)));
  }

  testSiren(code: string, token: string) {
    return this.call(this.http.post(`/api/games/${code}/settings/test-siren`, {}, this.auth(token)));
  }

  updateSettings(code: string, token: string, settings: { siren_volume?: number }) {
    return this.call(this.http.post(`/api/games/${code}/settings`, settings, this.auth(token)));
  }

  restart(code: string, token: string) {
    return this.call(this.http.post(`/api/games/${code}/restart`, {}, this.auth(token)));
  }

  applyStatus(code: string, token: string, playerId: number, effect: string) {
    return this.call(
      this.http.post(`/api/games/${code}/players/${playerId}/status`, { effect }, this.auth(token)),
    );
  }

  statusAction(
    code: string,
    token: string,
    playerId: number,
    effect: string,
    action: 'turn' | 'pay' | 'clear',
  ) {
    return this.call(
      this.http.post(`/api/games/${code}/players/${playerId}/status/${effect}/${action}`, {}, this.auth(token)),
    );
  }

  reorderPlayers(code: string, token: string, order: number[]) {
    return this.call(this.http.post(`/api/games/${code}/players/order`, { order }, this.auth(token)));
  }

  setColour(code: string, token: string, playerId: number, colour: string) {
    return this.call(
      this.http.post(`/api/games/${code}/players/${playerId}/colour`, { colour }, this.auth(token)),
    );
  }

  setMode(code: string, token: string, mode: string) {
    return this.call(this.http.post(`/api/games/${code}/mode`, { mode }, this.auth(token)));
  }

  createGame(body: {
    host_name: string;
    mode: string;
    starting_balance: number;
    currency: string;
    host_plays: boolean;
  }) {
    return this.call(this.http.post<Created>('/api/games', body));
  }

  join(code: string, name: string) {
    return this.call(this.http.post<Created>(`/api/games/${code}/join`, { name }));
  }

  snapshot(code: string, token: string) {
    return this.call(this.http.get<Snapshot>(`/api/games/${code}`, this.auth(token)));
  }

  pay(code: string, token: string, body: { to_id: number | null; amount: number; key: string; note?: string }) {
    return this.call(this.http.post(`/api/games/${code}/transactions`, body, this.auth(token)));
  }

  askBank(code: string, token: string, body: { amount: number; key: string; note?: string }) {
    return this.call(this.http.post(`/api/games/${code}/requests`, body, this.auth(token)));
  }

  resolve(code: string, token: string, requestId: number, approve: boolean) {
    return this.call(
      this.http.post(`/api/games/${code}/requests/${requestId}/resolve`, { approve }, this.auth(token)),
    );
  }

  bank(
    code: string,
    token: string,
    op: 'pay' | 'collect',
    body: { player_id: number; amount: number; note?: string },
  ) {
    return this.call(this.http.post(`/api/games/${code}/bank/${op}`, body, this.auth(token)));
  }

  reverse(code: string, token: string, txId: number) {
    return this.call(this.http.post(`/api/games/${code}/transactions/${txId}/reverse`, {}, this.auth(token)));
  }

  end(code: string, token: string) {
    return this.call(this.http.post(`/api/games/${code}/end`, {}, this.auth(token)));
  }

  private auth(token: string) {
    return { headers: { 'X-Player-Token': token } };
  }

  private async call<T>(obs: Observable<T>): Promise<T> {
    try {
      return await firstValueFrom(obs);
    } catch (e) {
      if (e instanceof HttpErrorResponse) {
        const detail = e.error && typeof e.error === 'object' ? e.error.detail : undefined;
        const message =
          e.status === 0
            ? 'Cannot reach the host'
            : typeof detail === 'string'
              ? detail
              : Array.isArray(detail)
                ? 'Please check what you entered'
                : `Request failed (${e.status})`;
        throw new ApiError(message, e.status, e.error?.code ?? 'error');
      }
      throw e;
    }
  }
}
