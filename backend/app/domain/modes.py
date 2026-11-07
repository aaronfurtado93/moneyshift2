"""Game modes: presets for starting money, currency, quick amounts and one-tap bank actions.

A mode only supplies defaults and shortcuts; the ledger and rules are the same for every mode.
To add a game, add an entry to MODES.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BankAction:
    """A one-tap bank shortcut for the host, e.g. 'Pass GO' pays the selected player 200."""

    id: str
    label: str
    kind: str  # "pay" (bank pays the player) or "collect" (player pays the bank)
    amount: int


@dataclass(frozen=True)
class StatusEffect:
    """A condition a player can be under, such as Monopoly's Jail: miss `turns` turns or pay `fine`."""

    id: str
    label: str
    description: str
    turns: int
    fine: int
    # "penalty": a condition with turns to miss and a fine (Jail).
    # "turn": one holder at a time that moves round the table in player order (Dice).
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
}


@dataclass(frozen=True)
class GameMode:
    id: str
    name: str
    description: str
    starting_balance: int
    currency: str
    quick_amounts: list[int] = field(default_factory=list)
    bank_actions: list[BankAction] = field(default_factory=list)
    status_effects: list[str] = field(default_factory=list)  # ids from EFFECTS

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "starting_balance": self.starting_balance,
            "currency": self.currency,
            "quick_amounts": self.quick_amounts,
            "bank_actions": [
                {"id": a.id, "label": a.label, "kind": a.kind, "amount": a.amount} for a in self.bank_actions
            ],
            "status_effects": [EFFECTS[i].public() for i in self.status_effects],
        }


DEFAULT_MODE = "monopoly"

MODES: dict[str, GameMode] = {
    "monopoly": GameMode(
        id="monopoly",
        name="Monopoly",
        description="Classic board game money: start with 1,500, collect 200 for passing GO.",
        starting_balance=1500,
        currency="$",
        quick_amounts=[1, 5, 10, 20, 50, 100, 500],
        bank_actions=[
            BankAction("go", "Pass GO", "pay", 200),
            BankAction("income_tax", "Income tax", "collect", 200),
            BankAction("luxury_tax", "Luxury tax", "collect", 75),
            BankAction("jail", "Jail fine", "collect", 50),
        ],
        status_effects=["jail", "dice"],
    ),
    "custom": GameMode(
        id="custom",
        name="Custom",
        description="Any game: choose your own starting money and symbol.",
        starting_balance=1000,
        currency="$",
        quick_amounts=[10, 50, 100, 500, 1000],
    ),
}


def get_mode(mode_id: str | None) -> GameMode | None:
    return MODES.get(mode_id or DEFAULT_MODE)
