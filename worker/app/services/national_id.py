import io
import logging
import fitz
from datetime import datetime
from random import randint
from PIL import Image, ImageEnhance, ImageStat
from rembg import remove
import re

from worker.app.core.pdf_crop import crop_pdf_region
from worker.app.core.ocr import extract_text_from_image
from worker.app.core.image_annotate import annotate_image_on_image, annotate_text_on_image
from worker.app.config import (
    ID_DPI,
    ID_HEIGHT,
    ID_SPACING_X,
    ID_WIDTH,
    REMBG_MATTING_SIZE,
    TextField,
    ImageField,
    load_id_format,
)

logger = logging.getLogger(__name__)

class NationalID:
   """
   Represents a National ID document. It loads its own configuration to ensure
   it is process-safe.
   """
   def __init__(
      self,
      document: bytes,
      id_type: str,
      grayscale: bool = False,
      mirror: bool = False,
      brightness: float = 1.0,
      saturation: float = 1.0,
      session=None,
   ) -> None:
      self.grayscale = grayscale
      self.mirror = mirror
      try:
         self.brightness = float(brightness)
      except (TypeError, ValueError):
         self.brightness = 1.0
      try:
         self.saturation = float(saturation)
      except (TypeError, ValueError):
         self.saturation = 1.0
      self.brightness = max(self.brightness, 0.0)
      self.saturation = max(self.saturation, 0.0)
      
      # Load a fresh copy of the config and template within the process
      self.id_format = load_id_format(id_type)

      if not session:
         raise ValueError("A rembg session must be provided during initialization.")

      with fitz.open(stream=document, filetype="pdf") as doc:
         if len(doc) == 0:
            raise ValueError("Empty PDF document provided.")
         self.page = doc[0]
         
         full_text_lines = self.page.get_text().splitlines()
         self.doc_content = [line.strip() for line in full_text_lines if line.strip()]

         if len(self.doc_content) < 16:
             raise ValueError(f"Invalid National ID: Not enough text content found. (Found {len(self.doc_content)} lines)")
         
         self.doc_content = self.doc_content[-16:]
         self.user = self.doc_content[15]

         doc_images = self.page.get_images(full=True)
         if len(doc_images) < 2:
             raise ValueError("Invalid National ID: Could not find required images (photo, QR code).")
         
         photo_img, qr_img = doc_images[:2]
         photo_byte = doc.extract_image(photo_img[0])["image"]
         qr_byte = doc.extract_image(qr_img[0])["image"]
         raw_photo = Image.open(io.BytesIO(photo_byte)).convert("RGBA")

         # Apply user-selected saturation and brightness before background removal
         enhancer_color = ImageEnhance.Color(raw_photo)
         raw_photo = enhancer_color.enhance(self.saturation)
         enhancer_brightness = ImageEnhance.Brightness(raw_photo)
         raw_photo = enhancer_brightness.enhance(self.brightness)

         with io.BytesIO() as enhanced_buffer:
            raw_photo.save(enhanced_buffer, format="PNG")
            enhanced_photo_bytes = enhanced_buffer.getvalue()
         raw_photo.close()

         photo = remove(
            data=enhanced_photo_bytes,
            session=session,
            alpha_matting=True,
            alpha_matting_erode_size=REMBG_MATTING_SIZE
         )

         # Open and keep alpha; convert to RGBA to maintain transparency
         photo = Image.open(io.BytesIO(photo)).convert("RGBA")
         if self._should_fallback_to_original(photo):
            logger.warning("rembg produced an invalid cut-out; using enhanced original photo instead.")
            photo = Image.open(io.BytesIO(enhanced_photo_bytes)).convert("RGBA")
         if self.grayscale:
            alpha = photo.getchannel("A")
            gray = photo.convert("L")
            photo = Image.merge("RGBA", (gray, gray, gray, alpha))

         # Ensure QR code is in RGBA as well
         qr_code = Image.open(io.BytesIO(qr_byte)).convert("RGBA")
         self.image_data = {}
         self.image_data["photo"] = self._fill_image_data("photo", photo)
         self.image_data["photo_sm"] = self._fill_image_data("photo_sm", photo)
         self.image_data["qr_code"] = self._fill_image_data("qr_code", qr_code)

         self._extract_data()

   def _extract_data(self):
      """Extracts text and image data from the document regions."""
      fan_barcode = crop_pdf_region(self.page, (438, 290, 503, 312))
      expiry_date_img = crop_pdf_region(self.page, (415, 275, 500, 285))
      issued_date_img = crop_pdf_region(self.page, (535, 120, 550, 210), rotate=-90)
      fin_img = crop_pdf_region(self.page, (496, 494, 540, 502))

      self.image_data["fan_barcode"] = self._fill_image_data("fan_barcode", fan_barcode)
      self.image_data["expiry_date"] = self._fill_image_data("expiry_date", expiry_date_img)
      self.image_data["issued_date"] = self._fill_image_data("issued_date", issued_date_img)
      self.image_data["fin"] = self._fill_image_data("fin", fin_img)

      # Safely handle Amharic dates which can have month 13
      bd_am_raw = self.doc_content[0]
      try:
         d_str, m_str, y_str = bd_am_raw.split('/')
         day, month, year = int(d_str), int(m_str), int(y_str)
         if month == 13:
            bd_am = f"{day:02d}/{month:02d}/{year}"
         else:
            bd_am = datetime.strptime(bd_am_raw, "%d/%m/%Y").strftime("%d/%m/%Y")
      except Exception:
         bd_am = bd_am_raw

      bd_en = datetime.strptime(self.doc_content[1], "%Y/%m/%d").strftime("%Y/%b/%d")
      date_now = datetime.now().strftime("%Y/%b/%d")
     
      expiry_text = extract_text_from_image(expiry_date_img, lang="eng")
      issued_text = extract_text_from_image(issued_date_img, lang="eng")
      fin_text = extract_text_from_image(fin_img, lang="eng")

      date_pattern = r'(\d{4}/\s*\w+/\s*\w+)\s*\W+\s*(\d{4}/\s*\w+/\s*\w+)'
      issued_match = re.search(date_pattern, issued_text)
      if issued_match:
         issued_date_amh = issued_match.group(1).replace(' ', '')
         issued_date_en = issued_match.group(2).replace(' ', '')
      else:
         issued_date_amh = ""
         issued_date_en = ""
      
      # Parse expiry date with regex
      expiry_match = re.search(date_pattern, expiry_text)
      if expiry_match:
         expiry_date_amh = expiry_match.group(1).replace(' ', '')
         expiry_date_en = expiry_match.group(2).replace(' ', '')
      else:
         expiry_date_amh = ""
         expiry_date_en = ""
               
      self.text_data = {}
      self.text_data["date"] = self._fill_text_data("date", date_now)
      self.text_data["birth_date_amh"] = self._fill_text_data("birth_date_amh", bd_am)
      self.text_data["birth_date_en"] = self._fill_text_data("birth_date_en", bd_en)
      self.text_data["name_amh"] = self._fill_text_data("name_amh", self.doc_content[14])
      self.text_data["name_en"] = self._fill_text_data("name_en", self.doc_content[15])
      self.text_data["birth_date"] = self._fill_text_data("birth_date", f"{bd_am} | {bd_en}")
      self.text_data["SN"] = self._fill_text_data("SN", str(randint(7019435, 7994728)))
      self.text_data["country"] = self._fill_text_data("country", f"{self.doc_content[4]} | {self.doc_content[5]}")
      self.text_data["sex"] = self._fill_text_data("sex", f"{self.doc_content[2]} | {self.doc_content[3]}")
      self.text_data["sex_amh"] = self._fill_text_data("sex_amh", self.doc_content[2])
      self.text_data["sex_en"] = self._fill_text_data("sex_en", self.doc_content[3])
      self.text_data["phone_number"] = self._fill_text_data("phone_number", self.doc_content[6])
      self.text_data["region_amh"] = self._fill_text_data("region_amh", self.doc_content[7])
      self.text_data["region_en"] = self._fill_text_data("region_en", self.doc_content[8])
      self.text_data["zone_amh"] = self._fill_text_data("zone_amh", self.doc_content[9])
      self.text_data["zone_en"] = self._fill_text_data("zone_en", self.doc_content[10])
      self.text_data["woreda_amh"] = self._fill_text_data("woreda_amh", self.doc_content[11])
      self.text_data["woreda_en"] = self._fill_text_data("woreda_en", self.doc_content[12])
      self.text_data["expiry_date"] = self._fill_text_data("expiry_date", ' | '.join(expiry_text.replace(' ', '').split('|')))
      self.text_data["expiry_date_amh"] = self._fill_text_data("expiry_date_amh", expiry_date_amh)
      self.text_data["expiry_date_en"] = self._fill_text_data("expiry_date_en", expiry_date_en)
      self.text_data["FCN"] = self._fill_text_data("FCN", self.doc_content[13])
      self.text_data["issued_date_amh"] = self._fill_text_data("issued_date_amh", issued_date_amh)
      self.text_data["issued_date_en"] = self._fill_text_data("issued_date_en", issued_date_en)
      self.text_data["fin"] = self._fill_text_data("fin", fin_text.replace(' ', ''))

   def generate(self) -> Image.Image:
      template = self.id_format.template
      if not template:
          raise ValueError("Template image not found in the loaded format.")
      
      template_copy = template.copy()

      text_annotations = [v for v in self.text_data.values() if v and v.content]
      image_annotations = [v for v in self.image_data.values() if v and v.content]

      annotated_image = annotate_image_on_image(image_annotations, template_copy)
      annotated_image = annotate_text_on_image(text_annotations, annotated_image)
      
      if not self.id_format.regions:
          raise ValueError("No regions defined in the ID format for cropping.")

      # Calculate target size in pixels
      target_width_px = int(ID_WIDTH * ID_DPI)
      target_height_px = int(ID_HEIGHT * ID_DPI)

      cropped_parts = [
          (annotated_image.crop(region)).resize((target_width_px, target_height_px), Image.LANCZOS)
          for region in self.id_format.regions
      ]

      # Calculate the size of the new image
      spacing_px = int(ID_SPACING_X * ID_DPI)
      total_width = sum(part.width for part in cropped_parts) + spacing_px * (len(cropped_parts) - 1)
      max_height = max(part.height for part in cropped_parts)

      # Create a new transparent image
      combined_image = Image.new('RGBA', (total_width, max_height), (0, 0, 0, 0))
      
      # Paste the cropped parts into the new image
      current_x = 0
      for part in cropped_parts:
         combined_image.paste(part, (current_x, 0))
         current_x += part.width + spacing_px
            
      if self.mirror:
         return combined_image.transpose(Image.FLIP_LEFT_RIGHT)
      return combined_image

   def _fill_text_data(self, field: str, value: str) -> TextField | None:
      if field in self.id_format.text_data:
         text_field = self.id_format.text_data[field]
         text_field.content = value
         return text_field
      return None
   
   def _fill_image_data(self, field: str, image: Image.Image) -> ImageField | None:
      if field in self.id_format.image_data:
         image_field = self.id_format.image_data[field]
         image_field.content = image
         return image_field
      return None

   @staticmethod
   def _should_fallback_to_original(photo: Image.Image) -> bool:
      """Detect empty/black cut-outs that should fall back to the original photo."""
      if not photo or photo.width == 0 or photo.height == 0:
         return True

      alpha = photo.getchannel("A")
      hist = alpha.histogram()
      opaque_pixels = sum(hist[96:])  # treat > ~38% alpha as visible
      total_pixels = photo.width * photo.height
      if total_pixels == 0:
         return True
      visible_ratio = opaque_pixels / total_pixels

      if visible_ratio < 0.02:  # almost fully transparent
         return True

      luminance = ImageStat.Stat(photo.convert("L")).mean[0]
      return luminance < 4.0