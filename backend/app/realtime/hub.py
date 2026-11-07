from collections import defaultdict

from fastapi import WebSocket


class Hub:
    """In-memory WebSocket rooms, one per game. Fine for a single process on the host device."""

    def __init__(self) -> None:
        self._rooms: dict[int, dict[int, set[WebSocket]]] = defaultdict(lambda: defaultdict(set))
        self._hosts: set[tuple[int, int]] = set()

    def add(self, game_id: int, player_id: int, ws: WebSocket, is_host: bool = False) -> None:
        self._rooms[game_id][player_id].add(ws)
        if is_host:
            self._hosts.add((game_id, player_id))

    def remove(self, game_id: int, player_id: int, ws: WebSocket) -> None:
        room = self._rooms.get(game_id)
        if not room:
            return
        room[player_id].discard(ws)
        if not room[player_id]:
            del room[player_id]
            self._hosts.discard((game_id, player_id))
        if not room:
            self._rooms.pop(game_id, None)

    def connected(self, game_id: int) -> set[int]:
        return set(self._rooms.get(game_id, {}).keys())

    async def broadcast(self, game_id: int, message: dict, involves: list[int] | None = None) -> None:
        """Send to everyone in the game, or only to the host and the players listed in `involves`."""
        dead: list[tuple[int, WebSocket]] = []
        for player_id, sockets in list(self._rooms.get(game_id, {}).items()):
            if involves is not None and player_id not in involves and (game_id, player_id) not in self._hosts:
                continue
            for ws in list(sockets):
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append((player_id, ws))
        for player_id, ws in dead:
            self.remove(game_id, player_id, ws)
