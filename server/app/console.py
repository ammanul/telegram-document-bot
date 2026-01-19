import logging
from rich.logging import RichHandler


def setup_logging():
    """
    Set up logging with RichHandler for pretty-printing.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("Job").setLevel(logging.INFO)
