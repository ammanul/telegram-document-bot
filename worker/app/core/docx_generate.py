"""
This module provides a function to convert a list of images into a DOCX document.
"""
import io
from typing import List

from docx import Document
from docx.shared import Inches, Pt
from PIL import Image

from worker.app.config import (
    EXPORT_PAGE_HEIGHT,
    EXPORT_PAGE_WIDTH,
    EXPORT_PAGE_PADDING_TOP,
    EXPORT_PAGE_PADDING_BOTTOM,
    EXPORT_PAGE_PADDING_LEFT,
    EXPORT_PAGE_PADDING_RIGHT,
    ID_SPACING_Y,
)


def images_to_docx_stream(images: List[Image.Image]) -> io.BytesIO:
    """
    Converts a list of PIL Images into a DOCX document as a byte stream.

    Args:
        images: A list of PIL Image objects.

    Returns:
        An in-memory byte stream (io.BytesIO) containing the DOCX document.

    Raises:
        ValueError: If any of the provided items is not a valid image or fails during processing.
    """
    document = Document()
    section = document.sections[0]

    # A4 page size
    section.page_height = Inches(EXPORT_PAGE_HEIGHT)
    section.page_width = Inches(EXPORT_PAGE_WIDTH)
    section.top_margin = Inches(EXPORT_PAGE_PADDING_TOP)
    section.bottom_margin = Inches(EXPORT_PAGE_PADDING_BOTTOM)
    section.left_margin = Inches(EXPORT_PAGE_PADDING_LEFT)
    section.right_margin = Inches(EXPORT_PAGE_PADDING_RIGHT)

    available_width_inches = (
        section.page_width.inches
        - section.left_margin.inches
        - section.right_margin.inches
    )
    available_height_inches = (
        section.page_height.inches
        - section.top_margin.inches
        - section.bottom_margin.inches
    )
    
    height_used_on_page = 0
    gutter_inches = ID_SPACING_Y

    for i, image in enumerate(images):
        if not isinstance(image, Image.Image):
            raise ValueError(f"Invalid image provided at index {i}")

        try:
            # Determine gutter for the current image
            current_gutter = gutter_inches if i > 0 else 0

            # Check for page break and recalculate available height
            if (
                height_used_on_page > 0
                and height_used_on_page + current_gutter > available_height_inches
            ):
                document.add_page_break()
                height_used_on_page = 0
                current_gutter = 0

            # Save image to a buffer as JPEG
            processed_image = image
            if processed_image.mode == "RGBA":
                background = Image.new("RGB", processed_image.size, (255, 255, 255))
                background.paste(processed_image, (0, 0), processed_image)
                processed_image = background
            elif processed_image.mode in ("P",):
                processed_image = processed_image.convert("RGB")
            
            jpeg_buffer = io.BytesIO()
            processed_image.save(jpeg_buffer, format="JPEG", quality=85)
            jpeg_buffer.seek(0)

            img_width, img_height = image.size
            aspect_ratio = img_height / img_width if img_width > 0 else 1
            new_width_inches = available_width_inches
            new_height_inches = new_width_inches * aspect_ratio

            # Add picture and adjust for gutter
            if height_used_on_page + current_gutter + new_height_inches > available_height_inches:
                document.add_page_break()
                height_used_on_page = 0
                current_gutter = 0

            document.add_picture(jpeg_buffer, width=Inches(new_width_inches))
            pic_para = document.paragraphs[-1]
            pic_para.paragraph_format.space_after = Pt(0)
            pic_para.paragraph_format.space_before = Inches(current_gutter) if current_gutter > 0 else Pt(0)

            height_used_on_page += new_height_inches + current_gutter

        except Exception as e:
            raise ValueError(f"Failed to process image {i} for DOCX: {e}")

    # Save the document to a byte stream
    docx_stream = io.BytesIO()
    document.save(docx_stream)
    docx_stream.seek(0)
    return docx_stream