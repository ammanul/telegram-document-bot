import fitz
from PIL import Image
import io
from typing import Tuple, Optional

def crop_pdf_region(
    page: fitz.Page,
    coords: Tuple[float, float, float, float],
    dpi: int = 600,
    rotate: Optional[int] = 0
) -> Image.Image:
    """
    Crop a single rectangular region from a given PDF page.
    Expects a pre-opened fitz.Page. Returns a Pillow Image.
    """
    rect = fitz.Rect(*coords)
    pix = page.get_pixmap(clip=rect, dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))

    if rotate:
        img = img.rotate(rotate, expand=True)
    return img