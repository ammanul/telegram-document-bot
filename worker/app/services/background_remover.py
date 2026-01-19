from typing import Optional

from rembg import new_session

from worker.app.config import REMBG_MODEL


class BackgroundRemover:
    """CPU-only background remover helper.

    In the current deployment environment we always run rembg on CPU, so this
    helper exposes a simple way to create a CPU-only session when needed.
    """

    def __init__(self):
        self.session: Optional[object] = None

    def create_session(self) -> object:
        """Create and return a CPU-only rembg session."""
        providers = ["CPUExecutionProvider"]
        return new_session(model_name=REMBG_MODEL, providers=providers)
