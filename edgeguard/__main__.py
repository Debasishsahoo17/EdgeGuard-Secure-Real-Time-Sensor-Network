"""Launch gateway, multi-agent sensor simulator or offline self-test."""
import argparse
import logging
from .config import Settings


def main():
    parser = argparse.ArgumentParser(description="EdgeGuard secure MQTT network")
    parser.add_argument("command", choices=("gateway", "simulate"))
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    parser.add_argument("--port", default=8080, type=int, help="Dashboard port, gateway only")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    settings = Settings()
    if args.command == "simulate":
        from .simulator import simulate
        simulate(settings)
    else:
        import uvicorn
        uvicorn.run("edgeguard.api:app", host="0.0.0.0", port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
