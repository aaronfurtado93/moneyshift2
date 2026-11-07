"""Game rules and ledger. Pure domain logic: depends on SQLAlchemy models, not on FastAPI.

Rules in one place:
- The server is the source of truth; clients send intents.
- The bank is the host's authority and has no balance limit.
- Players pay each other instantly but cannot overspend.
- Players can only *request* money from the bank; the host approves or denies.
- Every state-changing call may carry an idempotency key so retries never double-apply.
- Undo is a compensating ledger entry, never a delete.
"""

import json
import random
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import BankRequest, Event, Game, Player, PlayerStatus, Transaction
from app.domain.modes import DEFAULT_MODE, EFFECTS, StatusEffect, get_mode

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MAX_AMOUNT = 1_000_000_000
COLOUR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_COLOURS = ["#e11d48", "#2563eb", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777"]


class DomainError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


@dataclass
class Outcome:
    """Result of a mutation: what to return to the caller and which events to broadcast."""

    data: dict
    events: list[dict] = field(default_factory=list)
    duplicate: bool = False


_rng = random.SystemRandom()


def roll_die() -> int:
    """One six-sided die, rolled on the server so nobody can fake a roll."""
    return _rng.randint(1, 6)


def _money(game: Game, amount: int) -> str:
    return f"{game.currency}{amount:,}"


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not 1 <= len(name) <= 24:
        raise DomainError("Name must be 1 to 24 characters")
    return name


def _clean_amount(amount: int) -> int:
    if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= MAX_AMOUNT:
        raise DomainError("Amount must be a whole number greater than zero")
    return amount


def _clean_note(note: str | None) -> str:
    return " ".join((note or "").split())[:60]


class GameService:
    def __init__(self, db: Session):
        self.db = db

    # ---------- lookup / auth ----------
    def get_game(self, code: str) -> Game:
        game = self.db.scalar(select(Game).where(Game.code == code.upper()))
        if not game:
            raise DomainError("Game not found", 404, "not_found")
        return game

    def authenticate(self, code: str, token: str | None) -> tuple[Game, Player]:
        game = self.get_game(code)
        if not token:
            raise DomainError("Missing player token", 401, "unauthorized")
        player = self.db.scalar(select(Player).where(Player.game_id == game.id, Player.token == token))
        if not player:
            raise DomainError("Unknown player token", 401, "unauthorized")
        return game, player

    def _player(self, game: Game, player_id: int) -> Player:
        player = self.db.get(Player, player_id)
        if not player or player.game_id != game.id:
            raise DomainError("Unknown player", 404, "not_found")
        return player

    @staticmethod
    def _require_plays(player: Player, what: str = "play") -> None:
        if not player.plays:
            raise DomainError(f"{player.name} is only the bank and cannot {what}", 400, "not_a_player")

    @staticmethod
    def _require_host(player: Player) -> None:
        if player.role != "host":
            raise DomainError("Only the host (the bank) can do that", 403, "forbidden")

    @staticmethod
    def _require_active(game: Game) -> None:
        if game.status != "active":
            raise DomainError("This game has ended", 409, "game_ended")

    # ---------- events ----------
    def _event(
        self,
        game: Game,
        type_: str,
        text: str,
        involves: list[int | None] | None = None,
        data: dict | None = None,
    ) -> dict:
        """Record an event. involves=None makes it public; otherwise only those players (and the host).

        `data` is sent with the live event only (never stored): the bank dashboard uses it to animate
        money moving between players.
        """
        last = self.db.scalar(select(func.max(Event.seq)).where(Event.game_id == game.id)) or 0
        ids = None if involves is None else ",".join(str(i) for i in involves if i is not None)
        ev = Event(game_id=game.id, seq=last + 1, type=type_, text=text, involves=ids)
        self.db.add(ev)
        self.db.flush()
        out = self._event_dict(ev)
        if data:
            out["data"] = data
        return out

    @staticmethod
    def _flow(tx: Transaction) -> dict:
        return {"from_id": tx.from_id, "to_id": tx.to_id, "amount": tx.amount, "kind": tx.kind}

    @staticmethod
    def _event_dict(ev: Event) -> dict:
        return {
            "seq": ev.seq,
            "type": ev.type,
            "text": ev.text,
            "at": ev.created_at.isoformat() if ev.created_at else None,
            # Internal routing info; stripped before anything is sent to a client.
            "involves": None if ev.involves is None else [int(i) for i in ev.involves.split(",") if i],
        }

    @staticmethod
    def can_see(ev: dict, viewer_id: int, is_host: bool) -> bool:
        """Public events go to everyone; private ones only to the people involved and the host."""
        return is_host or ev["involves"] is None or viewer_id in ev["involves"]

    def events_since(self, game: Game, since: int, viewer_id: int, is_host: bool) -> list[dict]:
        rows = self.db.scalars(
            select(Event).where(Event.game_id == game.id, Event.seq > since).order_by(Event.seq)
        ).all()
        return [d for d in map(self._event_dict, rows) if self.can_see(d, viewer_id, is_host)]

    def last_seq(self, game: Game) -> int:
        return self.db.scalar(select(func.max(Event.seq)).where(Event.game_id == game.id)) or 0

    # ---------- game lifecycle ----------
    def create_game(
        self,
        host_name: str,
        starting_balance: int | None = None,
        currency: str | None = None,
        colour: str | None = None,
        host_plays: bool = True,
        mode: str | None = None,
    ) -> tuple[Game, Player, list[dict]]:
        host_name = _clean_name(host_name)
        game_mode = get_mode(mode)
        if game_mode is None:
            raise DomainError(f"Unknown game mode: {mode}", 400, "unknown_mode")
        # Anything the host leaves blank comes from the mode.
        if starting_balance is None:
            starting_balance = game_mode.starting_balance
        if isinstance(starting_balance, bool) or not 0 <= starting_balance <= MAX_AMOUNT:
            raise DomainError("Starting balance must be between 0 and 1,000,000,000")
        currency = ((currency or game_mode.currency).strip()[:8]) or game_mode.currency
        code = self._new_code()
        game = Game(code=code, mode=game_mode.id, starting_balance=starting_balance, currency=currency)
        self.db.add(game)
        self.db.flush()
        host = Player(
            game_id=game.id,
            name=host_name,
            colour=self._colour(colour, 0),
            role="host",
            token=secrets.token_urlsafe(24),
            balance=starting_balance if host_plays else 0,
            plays=host_plays,
            position=1,
        )
        self.db.add(host)
        self.db.flush()
        who = host.name if host_plays else f"{host.name} (bank)"
        ev = self._event(game, "player_joined", f"{who} created the game")
        return game, host, [ev, *self.ensure_dice(game)]

    def join(self, code: str, name: str, colour: str | None) -> tuple[Game, Player, list[dict]]:
        game = self.get_game(code)
        self._require_active(game)
        name = _clean_name(name)
        existing = self.db.scalars(select(Player).where(Player.game_id == game.id)).all()
        if len(existing) >= 12:
            raise DomainError("This game is full", 409, "full")
        if any(p.name.lower() == name.lower() for p in existing):
            raise DomainError("That name is already taken in this game", 409, "name_taken")
        player = Player(
            game_id=game.id,
            name=name,
            colour=self._colour(colour, len(existing)),
            role="player",
            token=secrets.token_urlsafe(24),
            balance=game.starting_balance,
            position=self._next_position(game),
        )
        self.db.add(player)
        self.db.flush()
        ev = self._event(game, "player_joined", f"{player.name} joined")
        return game, player, [ev, *self.ensure_dice(game)]

    def end_game(self, game: Game, me: Player) -> Outcome:
        self._require_host(me)
        self._require_active(game)
        game.status = "ended"
        ev = self._event(game, "game_ended", "The host ended the game")
        return Outcome({"status": game.status}, [ev])

    def _next_position(self, game: Game) -> int:
        return (self.db.scalar(select(func.max(Player.position)).where(Player.game_id == game.id)) or 0) + 1

    def reorder_players(self, game: Game, me: Player, order: list[int]) -> Outcome:
        """Host sets the seating / turn order. `order` may list just some players: they take, in the
        new order, the places those same players held before; everyone else stays where they are."""
        self._require_host(me)
        self._require_active(game)
        if len(set(order)) != len(order):
            raise DomainError("A player appears twice in the new order")
        players = self.db.scalars(
            select(Player).where(Player.game_id == game.id).order_by(Player.position, Player.id)
        ).all()
        by_id = {p.id: p for p in players}
        if any(i not in by_id for i in order):
            raise DomainError("Unknown player in the new order", 404, "not_found")
        slots = iter(order)
        sequence = [by_id[next(slots)] if p.id in order else p for p in players]
        for n, p in enumerate(sequence, start=1):
            p.position = n
        ev = self._event(game, "players_changed", "The host changed the player order")
        return Outcome({"order": [p.id for p in sequence]}, [ev])

    def set_colour(self, game: Game, me: Player, player_id: int, colour: str) -> Outcome:
        self._require_host(me)
        self._require_active(game)
        if not COLOUR_RE.match(colour or ""):
            raise DomainError("Colour must look like #1a2b3c")
        player = self._player(game, player_id)
        player.colour = colour.lower()
        ev = self._event(game, "players_changed", f"The host changed {player.name}'s colour")
        return Outcome({"player_id": player.id, "colour": player.colour}, [ev])

    # ---------- status effects (for example Jail) ----------
    def _effect(self, effect_id: str) -> StatusEffect:
        effect = EFFECTS.get(effect_id)
        if effect is None:
            raise DomainError(f"Unknown status effect: {effect_id}", 400, "unknown_effect")
        return effect

    def _penalty(self, effect_id: str) -> StatusEffect:
        effect = self._effect(effect_id)
        if effect.kind != "penalty":
            raise DomainError(f"{effect.label} is handled with its own controls", 400, "not_a_penalty")
        return effect

    def _status(self, game: Game, player: Player, effect_id: str) -> PlayerStatus | None:
        return self.db.scalar(
            select(PlayerStatus).where(PlayerStatus.player_id == player.id, PlayerStatus.effect == effect_id)
        )

    def _require_status(self, game: Game, player: Player, effect_id: str) -> PlayerStatus:
        status = self._status(game, player, effect_id)
        if status is None:
            raise DomainError(f"{player.name} is not in {self._effect(effect_id).label}", 404, "not_found")
        return status

    def apply_status(self, game: Game, me: Player, player_id: int, effect_id: str) -> Outcome:
        self._require_host(me)
        self._require_active(game)
        effect = self._penalty(effect_id)
        mode = get_mode(game.mode) or get_mode(DEFAULT_MODE)
        if effect.id not in mode.status_effects:
            raise DomainError(f"{effect.label} is not part of the {mode.name} mode", 400, "not_in_mode")
        player = self._player(game, player_id)
        self._require_plays(player, f"go to {effect.label}")
        if self._status(game, player, effect.id):
            raise DomainError(f"{player.name} is already in {effect.label}", 409, "conflict")
        self.db.add(
            PlayerStatus(game_id=game.id, player_id=player.id, effect=effect.id, turns_left=effect.turns)
        )
        self.db.flush()
        ev = self._event(
            game, "status_changed", f"{player.name} went to {effect.label} ({effect.turns} turns)"
        )
        return Outcome({"player_id": player.id, "effect": effect.id, "turns_left": effect.turns}, [ev])

    def miss_turn(self, game: Game, me: Player, player_id: int, effect_id: str) -> Outcome:
        """Jail, first time: the player chooses to miss this turn (their one chance to pay the fine is
        gone) and will miss the next two as well. After that the host can still record one by hand."""
        self._require_active(game)
        effect = self._penalty(effect_id)
        player = self._player(game, player_id)
        if me.id != player.id and me.role != "host":
            raise DomainError("Only the player or the host can do that", 403, "forbidden")
        status = self._require_status(game, player, effect.id)
        holder = self._holder(game) if self._has_dice(game) else None
        on_turn = holder is not None and holder.id == player.id
        if not status.decided:
            if me.role != "host" and self._has_dice(game) and not on_turn:
                raise DomainError("You choose on your own turn", 409, "not_your_turn")
            events = self._jail_miss(game, player, status, effect)
            if on_turn:  # their turn is over
                events += self._advance_dice(game, player)
            return Outcome(self._status_view(status, player, effect), events)
        self._require_host(me)  # already decided: only the host can adjust by hand
        events = self._jail_miss(game, player, status, effect, manual=True)
        return Outcome(self._status_view(status, player, effect), events)

    def _status_view(self, status: PlayerStatus, player: Player, effect: StatusEffect) -> dict:
        left = 0 if status in self.db.deleted else status.turns_left
        return {"player_id": player.id, "effect": effect.id, "turns_left": max(left, 0)}

    def _jail_miss(
        self, game: Game, player: Player, status: PlayerStatus, effect: StatusEffect, manual: bool = False
    ) -> list[dict]:
        """One missed turn. The first one locks in the choice (no more fine); the last one releases."""
        chose = not status.decided
        status.decided = True
        status.turns_left -= 1
        left = status.turns_left
        if left <= 0:
            self.db.delete(status)
            text = f"{player.name} is out of {effect.label}"
        elif chose:
            text = f"{player.name} chose to miss the turn in {effect.label} ({left} more to miss)"
        else:
            text = f"{player.name} misses a turn in {effect.label} ({left} left)"
        self.db.flush()
        return [self._event(game, "status_changed", text)]

    def pay_status_fine(self, game: Game, me: Player, player_id: int, effect_id: str) -> Outcome:
        """Pay the fine to the bank and clear the status. The player or the host can do it."""
        self._require_active(game)
        effect = self._penalty(effect_id)
        if me.id != player_id and me.role != "host":
            raise DomainError("Only the player or the host can pay this fine", 403, "forbidden")
        player = self._player(game, player_id)
        status = self._require_status(game, player, effect.id)
        if status.decided:
            raise DomainError(
                "You only get one chance to pay the fine, and you chose to miss the turn", 409, "chance_used"
            )
        if player.balance < effect.fine:
            need, have = _money(game, effect.fine), _money(game, player.balance)
            raise DomainError(f"{player.name} needs {need} for the fine but has {have}", 409, "insufficient")
        tx = self._apply(game, player, None, effect.fine, "bank_collect", f"{effect.label} fine", me, None)
        self.db.delete(status)
        self.db.flush()
        pay_ev = self._event(
            game,
            "transaction",
            f"{player.name} paid the bank {_money(game, effect.fine)} ({effect.label} fine)",
            [player.id],
            self._flow(tx),
        )
        out_ev = self._event(game, "status_changed", f"{player.name} paid their way out of {effect.label}")
        return Outcome(self.tx_dict(tx), [pay_ev, out_ev])

    def clear_status(self, game: Game, me: Player, player_id: int, effect_id: str) -> Outcome:
        """Host releases a player without a fine (for example after a correction)."""
        self._require_host(me)
        self._require_active(game)
        effect = self._penalty(effect_id)
        player = self._player(game, player_id)
        status = self._require_status(game, player, effect.id)
        self.db.delete(status)
        self.db.flush()
        ev = self._event(game, "status_changed", f"{player.name} was released from {effect.label}")
        return Outcome({"player_id": player.id, "effect": effect.id, "turns_left": 0}, [ev])

    # ---------- dice: a status effect that goes round the table in player order ----------
    def _mode_of(self, game: Game):
        return get_mode(game.mode) or get_mode(DEFAULT_MODE)

    def _has_dice(self, game: Game) -> bool:
        return "dice" in self._mode_of(game).status_effects

    def _sequence(self, game: Game) -> list[Player]:
        """Players who take turns, in the host's player sequence."""
        return list(
            self.db.scalars(
                select(Player)
                .where(Player.game_id == game.id, Player.plays.is_(True))
                .order_by(Player.position, Player.id)
            )
        )

    def _holder(self, game: Game) -> Player | None:
        status = self.db.scalar(
            select(PlayerStatus).where(PlayerStatus.game_id == game.id, PlayerStatus.effect == "dice")
        )
        return self.db.get(Player, status.player_id) if status else None

    def _dice_state(self, game: Game) -> dict:
        # rolled: a non-double was rolled, so the turn must end. acted: rolled at least once this turn.
        base = {"rolled": False, "acted": False, "streak": 0, "last": None}
        return {**base, **(json.loads(game.dice) if game.dice else {})}

    def _save_dice(self, game: Game, state: dict) -> None:
        game.dice = json.dumps(state)

    def _give_dice(self, game: Game, player: Player) -> dict:
        for old in self.db.scalars(
            select(PlayerStatus).where(PlayerStatus.game_id == game.id, PlayerStatus.effect == "dice")
        ):
            self.db.delete(old)
        self.db.flush()
        self.db.add(PlayerStatus(game_id=game.id, player_id=player.id, effect="dice", turns_left=0))
        state = self._dice_state(game)
        state.update(rolled=False, acted=False, streak=0)
        self._save_dice(game, state)
        self.db.flush()
        return self._event(game, "dice_passed", f"{player.name} has the dice")

    def ensure_dice(self, game: Game) -> list[dict]:
        """In modes with dice, someone always holds them: the first player in the sequence to start."""
        if not self._has_dice(game) or self._holder(game):
            return []
        sequence = self._sequence(game)
        return [self._give_dice(game, sequence[0])] if sequence else []

    def _advance_dice(self, game: Game, current: Player) -> list[dict]:
        """Pass the dice to the next player in the sequence. Players in Jail are skipped and lose a turn."""
        sequence = self._sequence(game)
        if not sequence:
            return []
        start = next((i for i, p in enumerate(sequence) if p.id == current.id), -1)
        events: list[dict] = []
        chosen = None
        for step in range(1, len(sequence) + 1):
            candidate = sequence[(start + step) % len(sequence)]
            jail = self._status(game, candidate, "jail")
            if jail is None or not jail.decided:
                # Free, or in Jail for the first time: their turn (to roll, or to decide about the fine).
                chosen = candidate
                break
            events += self._jail_miss(game, candidate, jail, EFFECTS["jail"])  # a missed turn, no choice left
        if chosen is None:  # everyone is in Jail: just hand it on
            chosen = sequence[(start + 1) % len(sequence)]
        events.append(self._give_dice(game, chosen))
        return events

    def _dice_actor(self, game: Game, me: Player) -> Player:
        self._require_active(game)
        if not self._has_dice(game):
            raise DomainError("This game mode has no dice", 400, "not_in_mode")
        holder = self._holder(game)
        if holder is None:
            raise DomainError("Nobody has the dice yet", 409, "conflict")
        if me.id != holder.id and me.role != "host":
            raise DomainError(f"It is {holder.name}'s turn to roll", 403, "forbidden")
        return holder

    def _forfeit_jail_turn(self, game: Game, holder: Player) -> list[dict]:
        """If the host takes the dice away from a jailed player, that counts as their missed turn."""
        jail = self._status(game, holder, "jail")
        return self._jail_miss(game, holder, jail, EFFECTS["jail"]) if jail else []

    def roll_dice(self, game: Game, me: Player) -> Outcome:
        holder = self._dice_actor(game, me)
        if self._status(game, holder, "jail"):
            raise DomainError(
                f"{holder.name} is in Jail: pay the fine or choose to miss the turn", 409, "in_jail"
            )
        state = self._dice_state(game)
        if state["rolled"]:
            raise DomainError("Already rolled this turn: end the turn", 409, "conflict")
        d1, d2 = roll_die(), roll_die()
        double = d1 == d2
        streak = state["streak"] + 1 if double else 0
        last = {
            "roll_id": ((state["last"] or {}).get("roll_id") or 0) + 1,
            "roller_id": holder.id,
            "d1": d1,
            "d2": d2,
            "total": d1 + d2,
            "double": double,
            "streak": streak,
            "jailed": False,
        }
        text = f"{holder.name} rolled {d1} + {d2} = {d1 + d2}"
        events: list[dict] = []
        jail_ok = "jail" in self._mode_of(game).status_effects
        if double and streak >= 3 and jail_ok:
            last["jailed"] = True
            self.db.add(
                PlayerStatus(
                    game_id=game.id, player_id=holder.id, effect="jail", turns_left=EFFECTS["jail"].turns
                )
            )
            self.db.flush()
            events.append(self._event(game, "dice_rolled", f"{text}: third double in a row, go to Jail!"))
            state.update(rolled=False, acted=True, streak=0, last=last)
            self._save_dice(game, state)
            events += self._advance_dice(game, holder)
        else:
            events.append(
                self._event(game, "dice_rolled", text + (" (doubles: roll again)" if double else ""))
            )
            state.update(rolled=not double, acted=True, streak=streak, last=last)
            self._save_dice(game, state)
        return Outcome(last, events)

    def end_turn(self, game: Game, me: Player) -> Outcome:
        holder = self._dice_actor(game, me)
        if not self._dice_state(game)["acted"] and me.role != "host":
            raise DomainError("Roll the dice first", 409, "conflict")
        events = self._forfeit_jail_turn(game, holder) + self._advance_dice(game, holder)
        new_holder = self._holder(game)
        return Outcome({"holder_id": new_holder.id if new_holder else None}, events)

    def pass_dice(self, game: Game, me: Player) -> Outcome:
        """Host override: hand the dice to the next player in the sequence."""
        self._require_host(me)
        holder = self._dice_actor(game, me)
        events = self._forfeit_jail_turn(game, holder) + self._advance_dice(game, holder)
        new_holder = self._holder(game)
        return Outcome({"holder_id": new_holder.id if new_holder else None}, events)

    def assign_dice(self, game: Game, me: Player, player_id: int) -> Outcome:
        """Host override: give the dice to any player, out of sequence."""
        self._require_host(me)
        self._require_active(game)
        if not self._has_dice(game):
            raise DomainError("This game mode has no dice", 400, "not_in_mode")
        player = self._player(game, player_id)
        self._require_plays(player, "hold the dice")
        return Outcome({"holder_id": player.id}, [self._give_dice(game, player)])

    def set_mode(self, game: Game, me: Player, mode_id: str) -> Outcome:
        """Switch the game mode. Only quick amounts and bank shortcuts change; balances do not."""
        self._require_host(me)
        self._require_active(game)
        mode = get_mode(mode_id)
        if mode is None:
            raise DomainError(f"Unknown game mode: {mode_id}", 400, "unknown_mode")
        game.mode = mode.id
        events = [self._event(game, "mode_changed", f"The host switched the game mode to {mode.name}")]
        if "dice" in mode.status_effects:
            events += self.ensure_dice(game)
        else:  # no dice in this mode: forget who held them
            for old in self.db.scalars(
                select(PlayerStatus).where(PlayerStatus.game_id == game.id, PlayerStatus.effect == "dice")
            ):
                self.db.delete(old)
            game.dice = None
            self.db.flush()
        return Outcome({"mode": mode.public()}, events)

    def _new_code(self) -> str:
        for _ in range(50):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
            if not self.db.scalar(select(Game.id).where(Game.code == code)):
                return code
        raise DomainError("Could not allocate a game code", 500, "server_error")

    @staticmethod
    def _colour(colour: str | None, index: int) -> str:
        if colour and COLOUR_RE.match(colour):
            return colour.lower()
        return DEFAULT_COLOURS[index % len(DEFAULT_COLOURS)]

    # ---------- money ----------
    def _find_tx(self, game: Game, key: str | None) -> Transaction | None:
        if not key:
            return None
        return self.db.scalar(
            select(Transaction).where(Transaction.game_id == game.id, Transaction.idem_key == key)
        )

    def _apply(
        self,
        game: Game,
        sender: Player | None,
        receiver: Player | None,
        amount: int,
        kind: str,
        note: str,
        created_by: Player,
        key: str | None,
        reverses_id: int | None = None,
    ) -> Transaction:
        if sender:
            sender.balance -= amount
        if receiver:
            receiver.balance += amount
        tx = Transaction(
            game_id=game.id,
            from_id=sender.id if sender else None,
            to_id=receiver.id if receiver else None,
            amount=amount,
            kind=kind,
            note=note,
            created_by=created_by.id,
            idem_key=key,
            reverses_id=reverses_id,
        )
        self.db.add(tx)
        self.db.flush()
        return tx

    def pay(
        self,
        game: Game,
        me: Player,
        to_id: int | None,
        amount: int,
        key: str | None,
        note: str | None = None,
    ) -> Outcome:
        self._require_active(game)
        dup = self._find_tx(game, key)
        if dup:
            return Outcome(self.tx_dict(dup), duplicate=True)
        amount = _clean_amount(amount)
        self._require_plays(me, "pay")
        receiver = self._player(game, to_id) if to_id is not None else None
        if receiver:
            self._require_plays(receiver, "be paid")
            if receiver.id == me.id:
                raise DomainError("You cannot pay yourself")
        if me.balance < amount:
            raise DomainError(f"Not enough money: you have {_money(game, me.balance)}", 409, "insufficient")
        kind = "payment" if receiver else "bank_collect"
        tx = self._apply(game, me, receiver, amount, kind, _clean_note(note), me, key)
        target = receiver.name if receiver else "the bank"
        ev = self._event(
            game,
            "transaction",
            f"{me.name} paid {target} {_money(game, amount)}",
            [me.id, receiver.id if receiver else None],
            self._flow(tx),
        )
        return Outcome(self.tx_dict(tx), [ev])

    def bank_pay(
        self, game: Game, me: Player, to_id: int, amount: int, key: str | None, note: str | None
    ) -> Outcome:
        self._require_host(me)
        self._require_active(game)
        dup = self._find_tx(game, key)
        if dup:
            return Outcome(self.tx_dict(dup), duplicate=True)
        amount = _clean_amount(amount)
        receiver = self._player(game, to_id)
        self._require_plays(receiver, "receive money")
        tx = self._apply(game, None, receiver, amount, "bank_pay", _clean_note(note), me, key)
        ev = self._event(
            game,
            "transaction",
            f"Bank paid {receiver.name} {_money(game, amount)}",
            [receiver.id],
            self._flow(tx),
        )
        return Outcome(self.tx_dict(tx), [ev])

    def bank_collect(
        self, game: Game, me: Player, from_id: int, amount: int, key: str | None, note: str | None
    ) -> Outcome:
        self._require_host(me)
        self._require_active(game)
        dup = self._find_tx(game, key)
        if dup:
            return Outcome(self.tx_dict(dup), duplicate=True)
        amount = _clean_amount(amount)
        sender = self._player(game, from_id)
        self._require_plays(sender, "pay the bank")
        if sender.balance < amount:
            raise DomainError(f"{sender.name} only has {_money(game, sender.balance)}", 409, "insufficient")
        tx = self._apply(game, sender, None, amount, "bank_collect", _clean_note(note), me, key)
        ev = self._event(
            game,
            "transaction",
            f"{sender.name} paid the bank {_money(game, amount)}",
            [sender.id],
            self._flow(tx),
        )
        return Outcome(self.tx_dict(tx), [ev])

    def reverse(self, game: Game, me: Player, tx_id: int) -> Outcome:
        self._require_host(me)
        self._require_active(game)
        tx = self.db.get(Transaction, tx_id)
        if not tx or tx.game_id != game.id:
            raise DomainError("Transaction not found", 404, "not_found")
        if tx.kind == "reversal":
            raise DomainError("A reversal cannot be undone; make a new payment instead")
        if tx.reversed:
            raise DomainError("Already undone", 409, "conflict")
        sender = self.db.get(Player, tx.to_id) if tx.to_id else None
        receiver = self.db.get(Player, tx.from_id) if tx.from_id else None
        tx.reversed = True
        comp = self._apply(game, sender, receiver, tx.amount, "reversal", f"Undo #{tx.id}", me, None, tx.id)
        ev = self._event(
            game,
            "reversal",
            f"Host undid transaction #{tx.id} ({_money(game, tx.amount)})",
            [tx.from_id, tx.to_id],
            self._flow(comp),
        )
        return Outcome(self.tx_dict(comp), [ev])

    # ---------- bank requests ----------
    def ask_bank(self, game: Game, me: Player, amount: int, key: str | None, note: str | None) -> Outcome:
        self._require_active(game)
        if key:
            dup = self.db.scalar(
                select(BankRequest).where(BankRequest.game_id == game.id, BankRequest.idem_key == key)
            )
            if dup:
                return Outcome(self.req_dict(dup), duplicate=True)
        self._require_plays(me, "ask the bank")
        amount = _clean_amount(amount)
        req = BankRequest(
            game_id=game.id, player_id=me.id, amount=amount, note=_clean_note(note), idem_key=key
        )
        self.db.add(req)
        self.db.flush()
        ev = self._event(
            game, "request_created", f"{me.name} asked the bank for {_money(game, amount)}", [me.id]
        )
        return Outcome(self.req_dict(req), [ev])

    def resolve_request(self, game: Game, me: Player, request_id: int, approve: bool) -> Outcome:
        self._require_host(me)
        self._require_active(game)
        req = self.db.get(BankRequest, request_id)
        if not req or req.game_id != game.id:
            raise DomainError("Request not found", 404, "not_found")
        if req.status != "pending":
            raise DomainError("Request already handled", 409, "conflict")
        player = self._player(game, req.player_id)
        req.status = "approved" if approve else "denied"
        req.resolved_at = datetime.now(UTC)
        events = []
        if approve:
            paid = self._apply(
                game, None, player, req.amount, "bank_pay", req.note or "Bank request", me, None
            )
            events.append(
                self._event(
                    game,
                    "transaction",
                    f"Bank paid {player.name} {_money(game, req.amount)}",
                    [player.id],
                    self._flow(paid),
                )
            )
        events.append(
            self._event(
                game,
                "request_resolved",
                f"Bank {req.status} {player.name}'s request for {_money(game, req.amount)}",
                [player.id],
            )
        )
        return Outcome(self.req_dict(req), events)

    # ---------- serialisation ----------
    @staticmethod
    def tx_dict(tx: Transaction) -> dict:
        return {
            "id": tx.id,
            "from_id": tx.from_id,
            "to_id": tx.to_id,
            "amount": tx.amount,
            "kind": tx.kind,
            "note": tx.note,
            "reversed": tx.reversed,
            "reverses_id": tx.reverses_id,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
        }

    @staticmethod
    def req_dict(req: BankRequest) -> dict:
        return {
            "id": req.id,
            "player_id": req.player_id,
            "amount": req.amount,
            "note": req.note,
            "status": req.status,
        }

    def _dice_view(self, game: Game) -> dict | None:
        if not self._has_dice(game):
            return None
        holder = self._holder(game)
        state = self._dice_state(game)
        return {
            "holder_id": holder.id if holder else None,
            "rolled": state["rolled"],
            "acted": state["acted"],
            "streak": state["streak"],
            "last": state["last"],
        }

    def snapshot(self, game: Game, me: Player, connected: set[int]) -> dict:
        is_host = me.role == "host"
        # Players only see their own money and their own transactions, until the game has ended.
        reveal_balances = is_host or game.status == "ended"
        players = self.db.scalars(
            select(Player).where(Player.game_id == game.id).order_by(Player.position, Player.id)
        ).all()
        tx_q = select(Transaction).where(Transaction.game_id == game.id)
        if not is_host:
            tx_q = tx_q.where((Transaction.from_id == me.id) | (Transaction.to_id == me.id))
        txs = self.db.scalars(tx_q.order_by(Transaction.id.desc()).limit(60)).all()
        statuses: dict[int, list[dict]] = {}
        for st in self.db.scalars(select(PlayerStatus).where(PlayerStatus.game_id == game.id)).all():
            label = EFFECTS[st.effect].label if st.effect in EFFECTS else st.effect
            statuses.setdefault(st.player_id, []).append(
                {"effect": st.effect, "label": label, "turns_left": st.turns_left, "decided": st.decided}
            )
        reqs_q = select(BankRequest).where(BankRequest.game_id == game.id, BankRequest.status == "pending")
        if me.role != "host":
            reqs_q = reqs_q.where(BankRequest.player_id == me.id)
        reqs = self.db.scalars(reqs_q.order_by(BankRequest.id)).all()
        raw_events = self.db.scalars(
            select(Event).where(Event.game_id == game.id).order_by(Event.seq.desc()).limit(150)
        ).all()
        activity = [d for d in map(self._event_dict, raw_events) if self.can_see(d, me.id, is_host)][:40]
        return {
            "game": {
                "code": game.code,
                "status": game.status,
                "starting_balance": game.starting_balance,
                "currency": game.currency,
                "mode": (get_mode(game.mode) or get_mode(DEFAULT_MODE)).public(),
                "dice": self._dice_view(game),
            },
            "me": {"id": me.id, "name": me.name, "role": me.role, "colour": me.colour, "plays": me.plays},
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "colour": p.colour,
                    "role": p.role,
                    "plays": p.plays,
                    "statuses": statuses.get(p.id, []),
                    "balance": p.balance if (reveal_balances or p.id == me.id) else None,
                    "connected": p.id in connected,
                }
                for p in players
            ],
            "transactions": [self.tx_dict(t) for t in txs],
            "requests": [self.req_dict(r) for r in reqs],
            "activity": [{k: v for k, v in d.items() if k != "involves"} for d in activity],
            "seq": self.last_seq(game),
        }
