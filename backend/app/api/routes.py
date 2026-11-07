import asyncio
from collections.abc import Callable

from fastapi import APIRouter, Header, Request, WebSocket, WebSocketDisconnect

from app.api import schemas
from app.domain.modes import DEFAULT_MODE, MODES
from app.domain.service import DomainError, GameService, Outcome
from app.net import lan_ip

router = APIRouter(prefix="/api")


class GameLocks:
    """One lock per game so concurrent payments are applied one at a time."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, code: str) -> asyncio.Lock:
        return self._locks.setdefault(code.upper(), asyncio.Lock())


async def _mutate(
    request: Request, code: str, token: str | None, fn: Callable[[GameService, object, object], Outcome]
) -> dict:
    state = request.app.state
    async with state.locks.get(code):
        with state.sessionmaker() as db:
            svc = GameService(db)
            game, me = svc.authenticate(code, token)
            try:
                outcome = fn(svc, game, me)
                db.commit()
            except Exception:
                db.rollback()
                raise
            game_id = game.id
    await _publish(state, game_id, outcome.events)
    return {"result": outcome.data, "duplicate": outcome.duplicate}


async def _publish(state, game_id: int, events: list[dict]) -> None:
    """Push events to phones. Private events (payments) reach only the people involved and the host."""
    for ev in events:
        involves = ev.get("involves")
        public = {k: v for k, v in ev.items() if k != "involves"}
        await state.hub.broadcast(game_id, {"kind": "event", **public}, involves)


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/modes")
async def list_modes() -> dict:
    return {"default": DEFAULT_MODE, "modes": [m.public() for m in MODES.values()]}


@router.get("/info")
async def info(request: Request) -> dict:
    settings = request.app.state.settings
    scheme = "https" if settings.tls_enabled else "http"
    ip = lan_ip()
    return {"lan_ip": ip, "port": settings.port, "base_url": f"{scheme}://{ip}:{settings.port}"}


@router.post("/games", status_code=201)
async def create_game(body: schemas.CreateGame, request: Request) -> dict:
    state = request.app.state
    with state.sessionmaker() as db:
        svc = GameService(db)
        try:
            game, host, events = svc.create_game(
                body.host_name,
                body.starting_balance,
                body.currency,
                body.colour,
                body.host_plays,
                body.mode,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {"code": game.code, "token": host.token, "player_id": host.id}


@router.post("/games/{code}/join", status_code=201)
async def join_game(code: str, body: schemas.JoinGame, request: Request) -> dict:
    state = request.app.state
    async with state.locks.get(code):
        with state.sessionmaker() as db:
            svc = GameService(db)
            try:
                game, player, events = svc.join(code, body.name, body.colour)
                db.commit()
            except Exception:
                db.rollback()
                raise
            game_id, out = game.id, {"code": game.code, "token": player.token, "player_id": player.id}
    await _publish(state, game_id, events)
    return out


@router.get("/games/{code}")
async def get_game(code: str, request: Request, x_player_token: str | None = Header(default=None)) -> dict:
    state = request.app.state
    with state.sessionmaker() as db:
        svc = GameService(db)
        game, me = svc.authenticate(code, x_player_token)
        return svc.snapshot(game, me, state.hub.connected(game.id))


@router.post("/games/{code}/transactions")
async def pay(
    code: str, body: schemas.Pay, request: Request, x_player_token: str | None = Header(default=None)
) -> dict:
    return await _mutate(
        request,
        code,
        x_player_token,
        lambda svc, g, me: svc.pay(g, me, body.to_id, body.amount, body.key, body.note),
    )


@router.post("/games/{code}/transactions/{tx_id}/reverse")
async def reverse(
    code: str, tx_id: int, request: Request, x_player_token: str | None = Header(default=None)
) -> dict:
    return await _mutate(request, code, x_player_token, lambda svc, g, me: svc.reverse(g, me, tx_id))


@router.post("/games/{code}/requests")
async def ask_bank(
    code: str,
    body: schemas.AskBank,
    request: Request,
    x_player_token: str | None = Header(default=None),
) -> dict:
    return await _mutate(
        request,
        code,
        x_player_token,
        lambda svc, g, me: svc.ask_bank(g, me, body.amount, body.key, body.note),
    )


@router.post("/games/{code}/requests/{request_id}/resolve")
async def resolve_request(
    code: str,
    request_id: int,
    body: schemas.Resolve,
    request: Request,
    x_player_token: str | None = Header(default=None),
) -> dict:
    return await _mutate(
        request,
        code,
        x_player_token,
        lambda svc, g, me: svc.resolve_request(g, me, request_id, body.approve),
    )


@router.post("/games/{code}/bank/pay")
async def bank_pay(
    code: str,
    body: schemas.BankOp,
    request: Request,
    x_player_token: str | None = Header(default=None),
) -> dict:
    return await _mutate(
        request,
        code,
        x_player_token,
        lambda svc, g, me: svc.bank_pay(g, me, body.player_id, body.amount, body.key, body.note),
    )


@router.post("/games/{code}/bank/collect")
async def bank_collect(
    code: str,
    body: schemas.BankOp,
    request: Request,
    x_player_token: str | None = Header(default=None),
) -> dict:
    return await _mutate(
        request,
        code,
        x_player_token,
        lambda svc, g, me: svc.bank_collect(g, me, body.player_id, body.amount, body.key, body.note),
    )


@router.post("/games/{code}/players/order")
async def reorder_players(
    code: str,
    body: schemas.PlayerOrder,
    request: Request,
    x_player_token: str | None = Header(default=None),
) -> dict:
    return await _mutate(
        request, code, x_player_token, lambda svc, g, me: svc.reorder_players(g, me, body.order)
    )


@router.post("/games/{code}/players/{player_id}/colour")
async def set_colour(
    code: str,
    player_id: int,
    body: schemas.SetColour,
    request: Request,
    x_player_token: str | None = Header(default=None),
) -> dict:
    return await _mutate(
        request, code, x_player_token, lambda svc, g, me: svc.set_colour(g, me, player_id, body.colour)
    )


@router.post("/games/{code}/players/{player_id}/status")
async def apply_status(
    code: str,
    player_id: int,
    body: schemas.ApplyStatus,
    request: Request,
    x_player_token: str | None = Header(default=None),
) -> dict:
    return await _mutate(
        request, code, x_player_token, lambda svc, g, me: svc.apply_status(g, me, player_id, body.effect)
    )


@router.post("/games/{code}/players/{player_id}/status/{effect}/turn")
async def miss_turn(
    code: str,
    player_id: int,
    effect: str,
    request: Request,
    x_player_token: str | None = Header(default=None),
) -> dict:
    return await _mutate(
        request, code, x_player_token, lambda svc, g, me: svc.miss_turn(g, me, player_id, effect)
    )


@router.post("/games/{code}/players/{player_id}/status/{effect}/pay")
async def pay_status_fine(
    code: str,
    player_id: int,
    effect: str,
    request: Request,
    x_player_token: str | None = Header(default=None),
) -> dict:
    return await _mutate(
        request, code, x_player_token, lambda svc, g, me: svc.pay_status_fine(g, me, player_id, effect)
    )


@router.post("/games/{code}/players/{player_id}/status/{effect}/clear")
async def clear_status(
    code: str,
    player_id: int,
    effect: str,
    request: Request,
    x_player_token: str | None = Header(default=None),
) -> dict:
    return await _mutate(
        request, code, x_player_token, lambda svc, g, me: svc.clear_status(g, me, player_id, effect)
    )


@router.post("/games/{code}/dice/roll")
async def roll_dice(code: str, request: Request, x_player_token: str | None = Header(default=None)) -> dict:
    return await _mutate(request, code, x_player_token, lambda svc, g, me: svc.roll_dice(g, me))


@router.post("/games/{code}/dice/end")
async def end_turn(code: str, request: Request, x_player_token: str | None = Header(default=None)) -> dict:
    return await _mutate(request, code, x_player_token, lambda svc, g, me: svc.end_turn(g, me))


@router.post("/games/{code}/dice/pass")
async def pass_dice(code: str, request: Request, x_player_token: str | None = Header(default=None)) -> dict:
    return await _mutate(request, code, x_player_token, lambda svc, g, me: svc.pass_dice(g, me))


@router.post("/games/{code}/dice/assign")
async def assign_dice(
    code: str,
    body: schemas.DiceAssign,
    request: Request,
    x_player_token: str | None = Header(default=None),
) -> dict:
    return await _mutate(
        request, code, x_player_token, lambda svc, g, me: svc.assign_dice(g, me, body.player_id)
    )


@router.post("/games/{code}/mode")
async def set_mode(
    code: str,
    body: schemas.SetMode,
    request: Request,
    x_player_token: str | None = Header(default=None),
) -> dict:
    return await _mutate(request, code, x_player_token, lambda svc, g, me: svc.set_mode(g, me, body.mode))


@router.post("/games/{code}/end")
async def end_game(code: str, request: Request, x_player_token: str | None = Header(default=None)) -> dict:
    return await _mutate(request, code, x_player_token, lambda svc, g, me: svc.end_game(g, me))


@router.websocket("/games/{code}/ws")
async def game_ws(websocket: WebSocket, code: str, token: str = "", since: int = 0) -> None:
    state = websocket.app.state
    with state.sessionmaker() as db:
        svc = GameService(db)
        try:
            game, me = svc.authenticate(code, token)
        except DomainError:
            await websocket.close(code=4401)
            return
        game_id, player_id, is_host = game.id, me.id, me.role == "host"
    await websocket.accept()
    state.hub.add(game_id, player_id, websocket, is_host)
    await state.hub.broadcast(game_id, {"kind": "presence"})
    try:
        with state.sessionmaker() as db:
            svc = GameService(db)
            game = svc.get_game(code)
            missed = svc.events_since(game, since, player_id, is_host) if since else []
            seq = svc.last_seq(game)
        for ev in missed:
            await websocket.send_json({"kind": "event", **{k: v for k, v in ev.items() if k != "involves"}})
        await websocket.send_json({"kind": "hello", "seq": seq})
        while True:
            await websocket.receive_text()  # clients may send pings; content is ignored
    except WebSocketDisconnect:
        pass
    finally:
        state.hub.remove(game_id, player_id, websocket)
        await state.hub.broadcast(game_id, {"kind": "presence"})
