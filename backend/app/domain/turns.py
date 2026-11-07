"""Turn order: the status effect that goes round the table (Dice or Card), plus Uno call-outs.

`TurnMixin` is mixed into `GameService` and relies on its helpers (`db`, `_event`, `_player`,
`_require_*`, `_status`, `_jail_miss`). Which effect is in play comes from the game's mode:
Monopoly uses Dice, UnoPoly uses Card.
"""

import json
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Game, Player, PlayerStatus
from app.domain.common import DomainError, Outcome
from app.domain.modes import DEFAULT_MODE, EFFECTS, GameMode, get_mode

_rng = random.SystemRandom()


def roll_die() -> int:
    """One six-sided die, rolled on the server so nobody can fake a roll."""
    return _rng.randint(1, 6)


class TurnMixin:
    db: Session

    # ---------- helpers ----------
    def _mode_of(self, game: Game) -> GameMode:
        return get_mode(game.mode) or get_mode(DEFAULT_MODE)  # type: ignore[return-value]

    def _turn_effect(self, game: Game) -> str | None:
        return self._mode_of(game).turn_effect

    def _has_turn(self, game: Game) -> bool:
        return self._turn_effect(game) is not None

    def _sequence(self, game: Game) -> list[Player]:
        """Players who take turns, in the host's player sequence."""
        return list(
            self.db.scalars(
                select(Player)
                .where(Player.game_id == game.id, Player.plays.is_(True))
                .order_by(Player.position, Player.id)
            )
        )

    def _turn_statuses(self, game: Game) -> list[PlayerStatus]:
        return list(
            self.db.scalars(
                select(PlayerStatus).where(
                    PlayerStatus.game_id == game.id, PlayerStatus.effect.in_(("dice", "card"))
                )
            )
        )

    def _holder(self, game: Game) -> Player | None:
        effect = self._turn_effect(game)
        if effect is None:
            return None
        status = self.db.scalar(
            select(PlayerStatus).where(PlayerStatus.game_id == game.id, PlayerStatus.effect == effect)
        )
        return self.db.get(Player, status.player_id) if status else None

    def _turn_state(self, game: Game) -> dict:
        # rolled: a non-double was rolled, so the turn must end. acted: rolled at least once this turn.
        # direction: 1 = join order, -1 = reversed. last_ender: who ended the previous turn.
        # callout: the open "forgot to say UNO" vote, if any.
        base = {
            "rolled": False,
            "acted": False,
            "streak": 0,
            "last": None,
            "direction": 1,
            "last_ender": None,
            "callout": None,
            "callout_seq": 0,
        }
        return {**base, **(json.loads(game.dice) if game.dice else {})}

    def _save_turn(self, game: Game, state: dict) -> None:
        game.dice = json.dumps(state)

    def _give_turn(self, game: Game, player: Player) -> dict:
        effect = self._turn_effect(game) or "dice"
        for old in self._turn_statuses(game):
            self.db.delete(old)
        self.db.flush()
        self.db.add(PlayerStatus(game_id=game.id, player_id=player.id, effect=effect, turns_left=0))
        state = self._turn_state(game)
        state.update(rolled=False, acted=False, streak=0)
        self._save_turn(game, state)
        self.db.flush()
        text = f"{player.name} has the dice" if effect == "dice" else f"{player.name} is up: play a card"
        return self._event(game, "turn_passed", text)

    def ensure_turn(self, game: Game) -> list[dict]:
        """In modes with a turn effect someone always holds it: the first player in the sequence to start."""
        if not self._has_turn(game) or self._holder(game):
            return []
        sequence = self._sequence(game)
        return [self._give_turn(game, sequence[0])] if sequence else []

    def _advance_turn(self, game: Game, current: Player, skips: int = 0) -> list[dict]:
        """Pass the turn to the next player in the current direction.

        Players in Jail (who already chose to miss) are skipped and lose a turn. `skips` extra
        players are passed over as well (the Uno Skip card)."""
        sequence = self._sequence(game)
        if not sequence:
            return []
        direction = self._turn_state(game)["direction"]
        n = len(sequence)
        start = next((i for i, p in enumerate(sequence) if p.id == current.id), 0)
        events: list[dict] = []
        chosen: Player | None = None
        skipped = 0
        for step in range(1, n * (skips + 1) + 1):
            candidate = sequence[(start + direction * step) % n]
            jail = self._status(game, candidate, "jail")
            if jail is not None and jail.decided:
                events += self._jail_miss(
                    game, candidate, jail, EFFECTS["jail"]
                )  # a missed turn, no choice left
                continue
            if skipped < skips:
                skipped += 1
                events.append(self._event(game, "turn_skipped", f"{candidate.name} was skipped"))
                continue
            chosen = candidate  # free, or in Jail for the first time: their turn
            break
        if chosen is None:  # everyone is in Jail: just hand it on
            chosen = sequence[(start + direction) % n]
        events.append(self._give_turn(game, chosen))
        return events

    def _turn_actor(self, game: Game, me: Player) -> Player:
        self._require_active(game)
        if not self._has_turn(game):
            raise DomainError("This game mode has no turns to pass round", 400, "not_in_mode")
        holder = self._holder(game)
        if holder is None:
            raise DomainError("Nobody is up yet", 409, "conflict")
        if me.id != holder.id and me.role != "host":
            raise DomainError(f"It is {holder.name}'s turn", 403, "forbidden")
        return holder

    def _forfeit_jail_turn(self, game: Game, holder: Player) -> list[dict]:
        """If the turn is taken away from a jailed player, that counts as their missed turn."""
        jail = self._status(game, holder, "jail")
        return self._jail_miss(game, holder, jail, EFFECTS["jail"]) if jail else []

    def _finish_turn(self, game: Game, holder: Player, skips: int = 0, reverse: bool = False) -> Outcome:
        events = self._forfeit_jail_turn(game, holder)
        state = self._turn_state(game)
        state["callout"] = None  # a call-out only lasts until the next turn ends
        if reverse:
            state["direction"] = -state["direction"]
        state["last_ender"] = holder.id if self._mode_of(game).callouts else None
        self._save_turn(game, state)
        events += self._advance_turn(game, holder, skips)
        new_holder = self._holder(game)
        return Outcome({"holder_id": new_holder.id if new_holder else None}, events)

    # ---------- dice (Monopoly) ----------
    def roll_dice(self, game: Game, me: Player) -> Outcome:
        holder = self._turn_actor(game, me)
        if self._turn_effect(game) != "dice":
            raise DomainError("This game mode has no dice", 400, "not_in_mode")
        if self._status(game, holder, "jail"):
            raise DomainError(
                f"{holder.name} is in Jail: pay the fine or choose to miss the turn", 409, "in_jail"
            )
        state = self._turn_state(game)
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
            self._save_turn(game, state)
            events += self._advance_turn(game, holder)
        else:
            events.append(
                self._event(game, "dice_rolled", text + (" (doubles: roll again)" if double else ""))
            )
            state.update(rolled=not double, acted=True, streak=streak, last=last)
            self._save_turn(game, state)
        return Outcome(last, events)

    # ---------- ending a turn (both modes) ----------
    def end_turn(self, game: Game, me: Player) -> Outcome:
        holder = self._turn_actor(game, me)
        needs_roll = self._turn_effect(game) == "dice"
        if needs_roll and not self._turn_state(game)["acted"] and me.role != "host":
            raise DomainError("Roll the dice first", 409, "conflict")
        return self._finish_turn(game, holder)

    def skip_turn(self, game: Game, me: Player) -> Outcome:
        """Uno Skip card: end the turn and pass over the next player."""
        holder = self._turn_actor(game, me)
        self._require_cards(game)
        events_text = f"{holder.name} played Skip"
        outcome = self._finish_turn(game, holder, skips=1)
        outcome.events.insert(0, self._event(game, "card_played", events_text))
        return outcome

    def reverse_turn(self, game: Game, me: Player) -> Outcome:
        """Uno Reverse card: flip the direction of play and end the turn."""
        holder = self._turn_actor(game, me)
        self._require_cards(game)
        outcome = self._finish_turn(game, holder, reverse=True)
        direction = self._turn_state(game)["direction"]
        way = "back the way we came" if direction == -1 else "forwards again"
        outcome.events.insert(0, self._event(game, "card_played", f"{holder.name} played Reverse: {way}"))
        return outcome

    def _require_cards(self, game: Game) -> None:
        if self._turn_effect(game) != "card":
            raise DomainError("This game mode has no cards", 400, "not_in_mode")

    def pass_turn(self, game: Game, me: Player) -> Outcome:
        """Host override: hand the turn to the next player in the sequence."""
        self._require_host(me)
        return self._finish_turn(game, self._turn_actor(game, me))

    def assign_turn(self, game: Game, me: Player, player_id: int) -> Outcome:
        """Host override: give the turn to any player, out of sequence."""
        self._require_host(me)
        self._require_active(game)
        if not self._has_turn(game):
            raise DomainError("This game mode has no turns to pass round", 400, "not_in_mode")
        player = self._player(game, player_id)
        self._require_plays(player, "take a turn")
        state = self._turn_state(game)
        state["callout"] = None
        self._save_turn(game, state)
        return Outcome({"holder_id": player.id}, [self._give_turn(game, player)])

    def switch_turn_effect(self, game: Game, mode: GameMode) -> list[dict]:
        """Mode changed: carry the turn over (Dice <-> Card) or drop it (modes without turns)."""
        existing = self._turn_statuses(game)
        if mode.turn_effect is None:
            for status in existing:
                self.db.delete(status)
            game.dice = None
            self.db.flush()
            return []
        if existing:
            for status in existing:
                status.effect = mode.turn_effect
            state = self._turn_state(game)
            state.update(
                rolled=False, acted=False, streak=0, last=None, direction=1, last_ender=None, callout=None
            )
            self._save_turn(game, state)
            self.db.flush()
            return []
        return self.ensure_turn(game)

    # ---------- Uno call-outs: "you forgot to say UNO" ----------
    def _callout_mode(self, game: Game) -> None:
        self._require_active(game)
        if not self._mode_of(game).callouts:
            raise DomainError("Call-outs are not part of this game mode", 400, "not_in_mode")

    def start_callout(self, game: Game, me: Player) -> Outcome:
        """Accuse the player who just ended their turn. Everyone else then votes."""
        self._callout_mode(game)
        if not me.plays:
            raise DomainError("Only players can call someone out", 403, "forbidden")
        state = self._turn_state(game)
        target_id = state["last_ender"]
        if target_id is None:
            raise DomainError("Nobody has just ended a turn", 409, "conflict")
        if me.id == target_id:
            raise DomainError("You cannot call yourself out", 403, "forbidden")
        if state["callout"]:
            raise DomainError("A call-out is already open", 409, "conflict")
        target = self._player(game, target_id)
        if self._status(game, target, "jail"):
            raise DomainError(f"{target.name} is already in Jail", 409, "conflict")
        voters = [p.id for p in self._sequence(game) if p.id != target.id]
        callout_id = state["callout_seq"] + 1
        state["callout"] = {
            "id": callout_id,
            "target_id": target.id,
            "caller_id": me.id,
            "voters": voters,
            "agree": [me.id],  # the caller agrees with their own call-out
            "disagree": [],
        }
        state["callout_seq"] = callout_id
        self._save_turn(game, state)
        events = [self._event(game, "callout_started", f"{me.name} called out {target.name}: no UNO!")]
        events += self._settle_callout(game, state)
        return Outcome({"callout_id": callout_id}, events)

    def vote_callout(self, game: Game, me: Player, agree: bool) -> Outcome:
        self._callout_mode(game)
        state = self._turn_state(game)
        callout = state["callout"]
        if callout is None:
            raise DomainError("There is no call-out to vote on", 409, "conflict")
        if me.id not in callout["voters"]:
            raise DomainError("You cannot vote on this call-out", 403, "forbidden")
        if me.id in callout["agree"] or me.id in callout["disagree"]:
            raise DomainError("You already voted", 409, "conflict")
        callout["agree" if agree else "disagree"].append(me.id)
        self._save_turn(game, state)
        word = "agreed" if agree else "disagreed"
        events = [self._event(game, "callout_vote", f"{me.name} {word}")]
        events += self._settle_callout(game, state)
        return Outcome({"agree": agree}, events)

    def cancel_callout(self, game: Game, me: Player) -> Outcome:
        """Host override: drop an open call-out (for example if someone is not voting)."""
        self._require_host(me)
        self._callout_mode(game)
        state = self._turn_state(game)
        if state["callout"] is None:
            raise DomainError("There is no call-out to cancel", 409, "conflict")
        state["callout"] = None
        self._save_turn(game, state)
        return Outcome({}, [self._event(game, "callout_result", "The host cancelled the call-out")])

    def _settle_callout(self, game: Game, state: dict) -> list[dict]:
        """One 'no' ends it; if everyone agrees the player goes to Jail."""
        callout = state["callout"]
        if callout is None:
            return []
        target = self._player(game, callout["target_id"])
        if callout["disagree"]:
            who = self._player(game, callout["disagree"][0])
            state["callout"] = None
            self._save_turn(game, state)
            return [
                self._event(game, "callout_result", f"Call-out on {target.name} failed: {who.name} disagreed")
            ]
        if set(callout["voters"]) <= set(callout["agree"]):
            state["callout"] = None
            self._save_turn(game, state)
            if self._status(game, target, "jail") is None:
                self.db.add(
                    PlayerStatus(
                        game_id=game.id, player_id=target.id, effect="jail", turns_left=EFFECTS["jail"].turns
                    )
                )
                self.db.flush()
            return [
                self._event(
                    game,
                    "callout_result",
                    f"Everyone agreed: {target.name} forgot to say UNO and goes to Jail",
                )
            ]
        return []

    # ---------- what the clients see ----------
    def _turn_view(self, game: Game) -> dict | None:
        effect = self._turn_effect(game)
        if effect is None:
            return None
        holder = self._holder(game)
        state = self._turn_state(game)
        return {
            "effect": effect,
            "label": EFFECTS[effect].label,
            "holder_id": holder.id if holder else None,
            "direction": state["direction"],
            "rolled": state["rolled"],
            "acted": state["acted"],
            "streak": state["streak"],
            "last": state["last"],
            "last_ender": state["last_ender"],
            "callout": state["callout"],
        }
