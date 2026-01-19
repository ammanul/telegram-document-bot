import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from dotenv import load_dotenv
from PIL import Image, ImageFont

load_dotenv()

@dataclass
class TextField:
    region: Tuple[int, int]
    lang: Literal["en", "amh"]
    font_size: int
    direction: Literal["h", "v"]
    content: Optional[str] = None

@dataclass
class ImageField:
    region: Tuple[int, int]
    size: Tuple[int, int]
    content: Optional[Image.Image] = None

@dataclass
class IDFormat:
    template: Optional[Image.Image]
    text_data: Dict[str, TextField]
    image_data: Dict[str, ImageField]
    regions: List[Tuple[int, int, int, int]]

ASSETS_DIR = Path(__file__).parent.parent / "assets"
if not ASSETS_DIR.exists():
    raise FileNotFoundError(f"Assets directory not found at {ASSETS_DIR}")

DATA_JSON_PATH = ASSETS_DIR / "data.json"
if not DATA_JSON_PATH.exists():
    raise FileNotFoundError(f"Data JSON file not found at {DATA_JSON_PATH}")

AMH_FONT = ImageFont.truetype(str(ASSETS_DIR / "fonts/NotoSansEthiopic/NotoSansEthiopic-SemiBold.ttf"))
EN_FONT = ImageFont.truetype(str(ASSETS_DIR / "fonts/Roboto/Roboto-SemiBold.ttf"))

def load_id_format(id_type: str) -> IDFormat:
    try:
        with open(DATA_JSON_PATH, "r", encoding="utf-8") as f:
            all_data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        raise RuntimeError(f"Failed to load or parse data.json: {e}")

    config = all_data.get(id_type)
    if not config:
        raise ValueError(f"Configuration for ID type '{id_type}' not found in data.json")

    template_path = ASSETS_DIR / config["template_path"]
    if not template_path.exists():
        raise FileNotFoundError(f"Template image not found for '{id_type}' at {template_path}")

    template_img = Image.open(template_path)
    text_data = {k: TextField(**v) for k, v in config["text_data"].items()}
    image_data = {k: ImageField(**v) for k, v in config["image_data"].items()}

    return IDFormat(
        template=template_img,
        text_data=text_data,
        image_data=image_data,
        regions=config.get("regions", []),
    )

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# --- REMBG (CPU-only) ---
# We always run rembg on CPU in this environment. The model can still be
# configured via REMBG_MODEL, but provider is fixed to CPU.
REMBG_MODEL = os.getenv("REMBG_MODEL", "birefnet-general-lite").lower()
REMBG_MATTING_SIZE = int(os.getenv("REMBG_MATTING_SIZE", "30"))


# --- Uploads ---
_uploads_prefix = os.getenv("UPLOADS_PREFIX", "uploads").strip("/")
UPLOADS_PREFIX = _uploads_prefix or "uploads"

# A4 =  8.268 x 11.693 inches

# #------  TEMPLATE 1 CONFIGS (inches) ------
# EXPORT_PAGE_WIDTH = 8.268
# EXPORT_PAGE_HEIGHT = 11.693
# EXPORT_PAGE_PADDING_TOP = 0.15
# EXPORT_PAGE_PADDING_BOTTOM = 0.1
# EXPORT_PAGE_PADDING_LEFT = 0.54
# EXPORT_PAGE_PADDING_RIGHT = 0.54
# ID_SPACING_X = 0.31
# ID_SPACING_Y = 0.1
# ID_WIDTH = 3.43
# ID_HEIGHT = 2.14
# ID_DPI = 400

#------  TEMPLATE 2 CONFIGS (inches) ------
EXPORT_PAGE_WIDTH = 7.87
EXPORT_PAGE_HEIGHT = 11.811
EXPORT_PAGE_PADDING_TOP = 0.15
EXPORT_PAGE_PADDING_BOTTOM = 0.05
EXPORT_PAGE_PADDING_LEFT = 0.43
EXPORT_PAGE_PADDING_RIGHT = 0.35
ID_SPACING_X = 0.22
ID_SPACING_Y = 0.1
ID_WIDTH = 3.43
ID_HEIGHT = 2.15
ID_DPI = 200


# Concurrency Limits (CPU-only)
JOB_CONCURRENCY_LIMIT = int(os.getenv("JOB_CONCURRENCY_LIMIT", "2"))

# Resource monitor thresholds & interval (percent)
CPU_HIGH_THRESHOLD = float(os.getenv("CPU_HIGH_THRESHOLD", "85.0"))  # >= this -> throttle
CPU_LOW_THRESHOLD = float(os.getenv("CPU_LOW_THRESHOLD", "60.0"))    # <= this -> un-throttle
RESOURCE_POLL_INTERVAL = float(os.getenv("RESOURCE_POLL_INTERVAL", "5.0"))  # seconds

# --- Database ---
DATABASE_URL = os.getenv("DATABASE_URL")
