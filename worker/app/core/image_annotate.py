from PIL import Image, ImageDraw
from worker.app.config import TextField, ImageField, List, AMH_FONT, EN_FONT


def annotate_text_on_image(annotations: List[TextField], image: Image.Image) -> Image.Image:
    """Annotate text using a single overlay."""
    image = image.convert("RGBA")
    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    for annotation in annotations:
        text = annotation.content
        position = annotation.region
        font_size = annotation.font_size
        direction = annotation.direction
        lang = annotation.lang

        font = (AMH_FONT if lang == "amh" else EN_FONT).font_variant(size=font_size)

        if direction == "v":
            bbox = font.getbbox(text)
            text_img = Image.new("RGBA", (bbox[2] - bbox[0], bbox[3] - bbox[1]), (255, 255, 255, 0))
            ImageDraw.Draw(text_img).text((-bbox[0], -bbox[1]), text, fill=(0,0,0,255), font=font)
            text_img = text_img.rotate(90, expand=True)
            overlay.paste(text_img, position, text_img)
        else:
            draw.text(position, text, fill=(0,0,0,255), font=font)

    return Image.alpha_composite(image, overlay)

def annotate_image_on_image(annotations: List[ImageField], image: Image.Image) -> Image.Image:
    """Annotate images using a single overlay."""
    base_img = image.convert("RGBA")
    overlay = Image.new("RGBA", base_img.size, (255, 255, 255, 0))

    for annotation in annotations:
        img_overlay = annotation.content
        if img_overlay is None:
            continue
        img_overlay = img_overlay.convert('RGBA')
        position = annotation.region
        size = annotation.size

        if size:
            img_overlay = img_overlay.resize(size, Image.Resampling.LANCZOS)

        overlay.paste(img_overlay, position, img_overlay)

    return Image.alpha_composite(base_img, overlay).convert("RGBA")