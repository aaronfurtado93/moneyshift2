"""Start the MoneyShift host server:  python -m app   (or `make run` from the repo root)."""

import uvicorn

from app.config import Settings
from app.main import create_app
from app.net import lan_ip


def banner(settings: Settings) -> None:
    scheme = "https" if settings.tls_enabled else "http"
    url = f"{scheme}://{lan_ip()}:{settings.port}"
    print("\n  MoneyShift host server")
    print(f"  Players open:  {url}")
    print(f"  This laptop:   {scheme}://localhost:{settings.port}")
    if settings.resolve_static_dir() is None:
        print("  (frontend not built yet: run `make build` for the app UI)")
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except Exception:  # QR is a convenience only
        pass
    print("  Press Ctrl+C to stop.\n")


def main() -> None:
    settings = Settings()
    banner(settings)
    kwargs = {}
    if settings.tls_enabled:
        kwargs = {"ssl_certfile": str(settings.ssl_certfile), "ssl_keyfile": str(settings.ssl_keyfile)}
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, **kwargs)


if __name__ == "__main__":
    main()
