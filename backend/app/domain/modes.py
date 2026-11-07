"""Game modes as classes.

`GameMode` is the abstract root. `MonopolyGameMode` is the base game: money, the bank, Jail and the
dice. `UnoPolyGameMode` derives from it and swaps the dice for physical Uno cards. A mode only
supplies defaults, shortcuts and which status effects apply; the ledger rules are shared by all.
To add a game, subclass one of these and add an instance to MODES.
"""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class BankAction:
    """A one-tap bank shortcut for the host, e.g. 'Pass GO' pays the selected player 200."""

    id: str
    label: str
    kind: str  # "pay" (bank pays the player) or "collect" (player pays the bank)
    amount: int

    def public(self) -> dict:
        return {"id": self.id, "label": self.label, "kind": self.kind, "amount": self.amount}


@dataclass(frozen=True)
class StatusEffect:
    """A condition on a player. kind "penalty": miss `turns` turns or pay `fine` (Jail).
    kind "turn": one holder at a time that moves round the table in player order (Dice, Card)."""

    id: str
    label: str
    description: str
    turns: int
    fine: int
    kind: str = "penalty"

    def public(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "turns": self.turns,
            "fine": self.fine,
            "kind": self.kind,
        }


EFFECTS: dict[str, StatusEffect] = {
    "jail": StatusEffect(
        id="jail",
        label="Jail",
        description="Miss 3 turns or pay the fine to get out.",
        turns=3,
        fine=50,
    ),
    "dice": StatusEffect(
        id="dice",
        label="Dice",
        description="Whoever holds the dice rolls; it then passes round the table in player order.",
        turns=0,
        fine=0,
        kind="turn",
    ),
    "card": StatusEffect(
        id="card",
        label="Card",
        description="Whoever holds the card plays their Uno card; the turn then passes round the table.",
        turns=0,
        fine=0,
        kind="turn",
    ),
}


class GameMode:
    """Abstract root of every game mode. Subclasses override the class attributes they care about."""

    id: ClassVar[str] = "base"
    name: ClassVar[str] = "Game"
    description: ClassVar[str] = ""
    starting_balance: ClassVar[int] = 1000
    currency: ClassVar[str] = "$"
    quick_amounts: ClassVar[tuple[int, ...]] = (10, 50, 100, 500)
    bank_actions: ClassVar[tuple[BankAction, ...]] = ()
    status_effects: ClassVar[tuple[str, ...]] = ()  # ids from EFFECTS
    turn_effect: ClassVar[str | None] = None  # the "turn" effect that goes round the table, if any
    callouts: ClassVar[bool] = False  # can players "call out" someone for forgetting to say UNO?

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "starting_balance": self.starting_balance,
            "currency": self.currency,
            "quick_amounts": list(self.quick_amounts),
            "bank_actions": [a.public() for a in self.bank_actions],
            "status_effects": [EFFECTS[i].public() for i in self.status_effects],
            "turn_effect": self.turn_effect,
            "callouts": self.callouts,
        }


class CustomGameMode(GameMode):
    id = "custom"
    name = "Custom"
    description = "Any game: choose your own starting money and symbol."
    quick_amounts = (10, 50, 100, 500, 1000)


class MonopolyGameMode(GameMode):
    """The base game. Other Monopoly-style modes derive from this one."""

    id = "monopoly"
    name = "Monopoly"
    description = "Classic board game money: start with 1,500, collect 200 for passing GO."
    starting_balance = 1500
    quick_amounts = (1, 5, 10, 20, 50, 100, 500)
    bank_actions = (
        BankAction("go", "Pass GO", "pay", 200),
        BankAction("income_tax", "Income tax", "collect", 200),
        BankAction("luxury_tax", "Luxury tax", "collect", 75),
        BankAction("jail", "Jail fine", "collect", 50),
    )
    status_effects = ("jail", "dice")
    turn_effect = "dice"


class UnoPolyGameMode(MonopolyGameMode):
    """Monopoly money and Jail, but the turn is driven by Uno cards held in hand instead of dice."""

    id = "unopoly"
    name = "UnoPoly"
    description = (
        "Monopoly money with Uno cards instead of dice: end your turn, skip the next player or reverse "
        "the order. Players can call out someone who forgot to say UNO."
    )
    status_effects = ("jail", "card")
    turn_effect = "card"
    callouts = True


DEFAULT_MODE = MonopolyGameMode.id

MODES: dict[str, GameMode] = {
    mode.id: mode for mode in (MonopolyGameMode(), UnoPolyGameMode(), CustomGameMode())
}


def get_mode(mode_id: str | None) -> GameMode | None:
    return MODES.get(mode_id or DEFAULT_MODE)
