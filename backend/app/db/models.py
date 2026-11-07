from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | ended
    mode: Mapped[str] = mapped_column(String(24), default="monopoly")
    dice: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: last roll and turn state
    settings: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: host settings (GameSettings)
    starting_balance: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="$")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    name: Mapped[str] = mapped_column(String(24))
    colour: Mapped[str] = mapped_column(String(7))
    role: Mapped[str] = mapped_column(String(8), default="player")  # host | player
    # False for a banker-only host: no balance, not payable, cannot pay.
    plays: Mapped[bool] = mapped_column(Boolean, default=True)
    # Seating / turn order, set by the host. Lower comes first.
    position: Mapped[int] = mapped_column(Integer, default=0)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    balance: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Transaction(Base):
    """Append-only ledger. from_id/to_id of None means the bank."""

    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("game_id", "idem_key", name="uq_tx_idem"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    from_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    to_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    amount: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # payment | bank_pay | bank_collect | reversal
    note: Mapped[str] = mapped_column(String(60), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("players.id"))
    idem_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)
    reverses_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BankRequest(Base):
    __tablename__ = "bank_requests"
    __table_args__ = (UniqueConstraint("game_id", "idem_key", name="uq_req_idem"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    amount: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|approved|denied
    idem_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Event(Base):
    """Per-game ordered event log; the sequence number lets phones catch up after a dropout."""

    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("game_id", "seq", name="uq_event_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(24))
    text: Mapped[str] = mapped_column(Text, default="")
    # None = public (everyone). Otherwise comma-separated player ids who may see it (host always can).
    involves: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlayerStatus(Base):
    """A status effect on a player (for example Jail) with the turns they still have to miss."""

    __tablename__ = "player_statuses"
    __table_args__ = (UniqueConstraint("player_id", "effect", name="uq_player_effect"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    effect: Mapped[str] = mapped_column(String(24))
    turns_left: Mapped[int] = mapped_column(Integer)
    # Jail: True once the player has used their one chance to pay the fine (by choosing to miss the turn).
    decided: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
