import logging

from app.jobs import run_scheduled_scrape


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = run_scheduled_scrape()
    logging.getLogger(__name__).info("Scheduled scrape result=%s", result)
    if result["status"] not in {"completed", "partial"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
