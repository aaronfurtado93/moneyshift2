"""Per-game settings the host can change. Stored with the game and sent to every device."""

import json
from dataclasses import asdict, dataclass


@dataclass
class GameSettings:
    # Loudness of the call-out siren on every player's device, 0 (silent) to 100 (full).
    siren_volume: int = 40

    @classmethod
    def from_json(cls, text: str | None) -> "GameSettings":
        """Read stored settings; anything missing or invalid falls back to the defaults."""
        settings = cls()
        try:
            data = json.loads(text) if text else {}
        except ValueError:
            data = {}
        volume = data.get("siren_volume")
        if isinstance(volume, int) and not isinstance(volume, bool) and 0 <= volume <= 100:
            settings.siren_volume = volume
        return settings

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    def to_dict(self) -> dict:
        return asdict(self)
