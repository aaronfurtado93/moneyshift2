import { ENDED_TTL_MS, SessionStore } from './session';

describe('SessionStore', () => {
  let store: SessionStore;

  beforeEach(() => {
    localStorage.clear();
    store = new SessionStore();
  });

  it('remembers the current game and player', () => {
    expect(store.current()).toBeNull();
    store.save('ab12', { token: 't', playerId: 3 });
    expect(store.get('AB12')).toEqual({ token: 't', playerId: 3 });
    expect(store.current()).toEqual({ code: 'AB12', ended: false });
  });

  it('keeps an ended game visible, then forgets it after the TTL', () => {
    store.save('AB12', { token: 't', playerId: 3 });
    store.markEnded('AB12');
    expect(store.current()).toEqual({ code: 'AB12', ended: true });
    vi.useFakeTimers();
    vi.setSystemTime(Date.now() + ENDED_TTL_MS + 1000);
    expect(store.get('AB12')).toBeNull();
    expect(store.current()).toBeNull();
    vi.useRealTimers();
  });

  it('clearing a game also drops its queued actions and the current pointer', () => {
    store.save('AB12', { token: 't', playerId: 3 });
    store.saveQueue('AB12', [{ key: 'k', kind: 'ask', amount: 5 }]);
    store.clear('AB12');
    expect(store.get('AB12')).toBeNull();
    expect(store.loadQueue('AB12')).toEqual([]);
    expect(store.current()).toBeNull();
  });

  it('does not mix games: current points to the most recently joined', () => {
    store.save('AAAA', { token: '1', playerId: 1 });
    store.save('BBBB', { token: '2', playerId: 2 });
    expect(store.current()?.code).toBe('BBBB');
    store.clear('BBBB');
    expect(store.get('AAAA')).not.toBeNull();
  });
});
