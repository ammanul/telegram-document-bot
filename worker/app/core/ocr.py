from PIL import Image, ImageOps, ImageFilter
import pytesseract
from concurrent.futures import ProcessPoolExecutor
from typing import List
import multiprocessing
import functools
import io

_DEF_TESS_CONFIG = "--oem 3 --psm 6"
_SPAWN_CONTEXT = multiprocessing.get_context("spawn")

def _prep(image: Image.Image) -> Image.Image:
    if max(image.size) > 1000:
        ratio = 1000 / max(image.size)
        new_size = (int(image.width * ratio), int(image.height * ratio))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
    
    image = ImageOps.grayscale(image)
    image = image.filter(ImageFilter.MedianFilter())
    image = ImageOps.autocontrast(image)
    return image

def extract_text_from_image(image: Image.Image, lang: str = "eng") -> str:
    """OCR text from a Pillow Image object."""
    image = _prep(image)
    return pytesseract.image_to_string(image, lang=lang, config=_DEF_TESS_CONFIG).strip()

def extract_texts_parallel(images: List[Image.Image], lang: str = "eng") -> List[str]:
    """Run OCR on multiple images in parallel using processes for CPU-bound work."""
    with ProcessPoolExecutor(mp_context=_SPAWN_CONTEXT) as executor:
        image_bytes_list = []
        for img in images:
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG', optimize=True)
            img_byte_arr.seek(0)
            image_bytes_list.append(img_byte_arr.getvalue())
        
        func = functools.partial(extract_text_from_image_bytes, lang=lang)
        results = list(executor.map(func, image_bytes_list))
    return results

def extract_text_from_image_bytes(image_bytes: bytes, lang: str = "eng") -> str:
    """Helper function for process pool to OCR text from image bytes."""
    image = Image.open(io.BytesIO(image_bytes))
    return extract_text_from_image(image, lang)