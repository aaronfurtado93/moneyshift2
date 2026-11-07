export interface Created {
  code: string;
  token: string;
  player_id: number;
}

export interface PlayerView {
  id: number;
  name: string;
  colour: string;
  role: 'host' | 'player';
  plays: boolean;
  statuses: PlayerStatus[];
  /** null when the server hides it: players only see their own money until the game ends. */
  balance: number | null;
  connected: boolean;
}

export interface TxView {
  id: number;
  from_id: number | null;
  to_id: number | null;
  amount: number;
  kind: 'payment' | 'bank_pay' | 'bank_collect' | 'reversal';
  note: string;
  reversed: boolean;
  reverses_id: number | null;
  created_at: string | null;
}

export interface RequestView {
  id: number;
  player_id: number;
  amount: number;
  note: string;
  status: 'pending' | 'approved' | 'denied';
}

export interface ActivityView {
  seq: number;
  type: string;
  text: string;
  at: string | null;
}

export interface BankAction {
  id: string;
  label: string;
  kind: 'pay' | 'collect';
  amount: number;
}

export interface StatusEffectDef {
  id: string;
  label: string;
  description: string;
  turns: number;
  fine: number;
  /** penalty: Jail-style (turns and a fine). turn: one holder passed round the table (Dice). */
  kind: 'penalty' | 'turn';
}

export interface PlayerStatus {
  effect: string;
  label: string;
  turns_left: number;
  /** Jail: the one chance to pay the fine has been used. */
  decided: boolean;
}

export interface DiceRoll {
  roll_id: number;
  roller_id: number;
  d1: number;
  d2: number;
  total: number;
  double: boolean;
  streak: number;
  jailed: boolean;
}

export interface DiceState {
  holder_id: number | null;
  /** True once the holder has rolled without doubles: they can now end the turn. */
  rolled: boolean;
  /** True once the holder has rolled at least once this turn, so they can end it. */
  acted: boolean;
  streak: number;
  last: DiceRoll | null;
}

export interface GameMode {
  id: string;
  name: string;
  description: string;
  starting_balance: number;
  currency: string;
  quick_amounts: number[];
  bank_actions: BankAction[];
  status_effects: StatusEffectDef[];
}

export interface Snapshot {
  game: {
    code: string;
    status: 'active' | 'ended';
    starting_balance: number;
    currency: string;
    mode: GameMode;
    /** null in modes without dice. */
    dice: DiceState | null;
  };
  me: { id: number; name: string; role: 'host' | 'player'; colour: string; plays: boolean };
  players: PlayerView[];
  transactions: TxView[];
  requests: RequestView[];
  activity: ActivityView[];
  seq: number;
}

/** Money moving, sent with live events so the bank dashboard can animate it. null = the bank. */
export interface Flow {
  key: number;
  from_id: number | null;
  to_id: number | null;
  amount: number;
  kind: string;
}

export interface ServerInfo {
  lan_ip: string;
  port: number;
  base_url: string;
}

export interface QueuedIntent {
  key: string;
  kind: 'pay' | 'ask';
  to_id?: number | null;
  amount: number;
  note?: string;
}
