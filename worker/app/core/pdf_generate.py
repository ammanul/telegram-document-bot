from reportlab.pdfgen import canvas
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import inch
from PIL import Image
import io
from typing import List

from worker.app.config import (
    EXPORT_PAGE_HEIGHT,
    EXPORT_PAGE_WIDTH,
    EXPORT_PAGE_PADDING_TOP,
    EXPORT_PAGE_PADDING_BOTTOM,
    EXPORT_PAGE_PADDING_LEFT,
    EXPORT_PAGE_PADDING_RIGHT,
    ID_SPACING_Y,
)

def images_to_pdf_stream(images: List[Image.Image]) -> io.BytesIO:
    if not images:
        raise ValueError("Image list cannot be empty.")

    pdf_buffer = io.BytesIO()
    page_width_in = EXPORT_PAGE_WIDTH * inch
    page_height_in = EXPORT_PAGE_HEIGHT * inch
    c = canvas.Canvas(pdf_buffer, pagesize=(page_width_in, page_height_in))

    top_margin = EXPORT_PAGE_PADDING_TOP * inch
    bottom_margin = EXPORT_PAGE_PADDING_BOTTOM * inch
    left_margin = EXPORT_PAGE_PADDING_LEFT * inch
    right_margin = EXPORT_PAGE_PADDING_RIGHT * inch
    gutter = ID_SPACING_Y * inch

    usable_width = page_width_in - left_margin - right_margin
    x = left_margin
    y = page_height_in - top_margin

    for i, image in enumerate(images):
        img_width, img_height = image.size
        aspect_ratio = img_height / img_width if img_width > 0 else 1
        new_width = usable_width
        new_height = new_width * aspect_ratio

        current_gutter = gutter if i > 0 else 0

        if y - new_height - current_gutter < bottom_margin:
            c.showPage()
            y = page_height_in - top_margin
            current_gutter = 0

        if current_gutter > 0:
            y -= current_gutter
        y -= new_height

        img_buffer = io.BytesIO()
        processed_image = image
        if processed_image.mode == "RGBA":
            white_bg = Image.new("RGB", processed_image.size, (255, 255, 255))
            white_bg.paste(processed_image, mask=processed_image.getchannel("A"))
            processed_image = white_bg
        else:
            processed_image = processed_image.convert("RGB")
        
        processed_image.save(img_buffer, format="JPEG", quality=85)
        img_buffer.seek(0)
        rl_img = ImageReader(img_buffer)

        c.drawImage(rl_img, x, y, width=new_width, height=new_height)

    c.save()
    pdf_buffer.seek(0)
    return pdf_buffer