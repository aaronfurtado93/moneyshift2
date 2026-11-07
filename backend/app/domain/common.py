"""Small types shared by the game rules."""

from dataclasses import dataclass, field


class DomainError(Exception):
    """A rule was broken. Carries the HTTP status and a machine-readable code for the client."""

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
