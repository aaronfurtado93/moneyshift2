from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base


def make_engine(url: str) -> Engine:
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    _ensure_columns(engine)


def _ensure_columns(engine: Engine) -> None:
    """Tiny stop-gap for columns added after first release (Alembic migrations are still to do)."""
    insp = inspect(engine)
    if "plays" not in {c["name"] for c in insp.get_columns("players")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE players ADD COLUMN plays BOOLEAN NOT NULL DEFAULT 1"))
    if insp.has_table("player_statuses") and "decided" not in {
        c["name"] for c in insp.get_columns("player_statuses")
    }:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE player_statuses ADD COLUMN decided BOOLEAN NOT NULL DEFAULT 0"))
    if "settings" not in {c["name"] for c in insp.get_columns("games")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE games ADD COLUMN settings TEXT"))
    if "dice" not in {c["name"] for c in insp.get_columns("games")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE games ADD COLUMN dice TEXT"))
    if "position" not in {c["name"] for c in insp.get_columns("players")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE players ADD COLUMN position INTEGER NOT NULL DEFAULT 0"))
            conn.execute(text("UPDATE players SET position = id"))  # keep the existing join order
    if "mode" not in {c["name"] for c in insp.get_columns("games")}:
        with engine.begin() as conn:
            # games created before modes existed get the default mode (Monopoly); the host can switch it
            conn.execute(text("ALTER TABLE games ADD COLUMN mode VARCHAR(24) NOT NULL DEFAULT 'monopoly'"))
    if "involves" not in {c["name"] for c in insp.get_columns("events")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE events ADD COLUMN involves VARCHAR(200)"))


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
