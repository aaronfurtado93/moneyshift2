from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Runtime configuration. Override with MONEYSHIFT_* environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="MONEYSHIFT_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'moneyshift.db'}"
    # Built Angular app. When unset, the first dist/*/browser folder found is used.
    static_dir: Path | None = None
    # Optional TLS (for a later HTTPS upgrade). Both must be set to enable HTTPS.
    ssl_certfile: Path | None = None
    ssl_keyfile: Path | None = None

    def resolve_static_dir(self) -> Path | None:
        if self.static_dir:
            return self.static_dir if self.static_dir.is_dir() else None
        for candidate in sorted((REPO_DIR / "frontend" / "dist").glob("*/browser")):
            if (candidate / "index.html").is_file():
                return candidate
        return None

    @property
    def tls_enabled(self) -> bool:
        return bool(self.ssl_certfile and self.ssl_keyfile)
