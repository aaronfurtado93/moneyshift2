from pydantic import BaseModel, Field, StrictBool, StrictInt


class CreateGame(BaseModel):
    host_name: str = Field(max_length=60)
    mode: str = Field(default="monopoly", max_length=24)
    # Omit to use the mode's defaults; send a value for house rules.
    starting_balance: StrictInt | None = None
    currency: str | None = Field(default=None, max_length=8)
    colour: str | None = None
    host_plays: StrictBool = True


class JoinGame(BaseModel):
    name: str = Field(max_length=60)
    colour: str | None = None


class PlayerOrder(BaseModel):
    order: list[StrictInt] = Field(min_length=1, max_length=40)


class SetColour(BaseModel):
    colour: str = Field(max_length=7)


class SettingsUpdate(BaseModel):
    # Only the fields that are sent are changed.
    siren_volume: StrictInt | None = Field(default=None, ge=0, le=100)


class CalloutVote(BaseModel):
    agree: StrictBool


class DiceAssign(BaseModel):
    player_id: StrictInt


class ApplyStatus(BaseModel):
    effect: str = Field(max_length=24)


class SetMode(BaseModel):
    mode: str = Field(max_length=24)


class Pay(BaseModel):
    to_id: StrictInt | None  # None = pay the bank (for example from a bank QR code)
    amount: StrictInt
    key: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=120)


class AskBank(BaseModel):
    amount: StrictInt
    key: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=120)


class Resolve(BaseModel):
    approve: StrictBool


class BankOp(BaseModel):
    player_id: StrictInt
    amount: StrictInt
    key: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=120)
