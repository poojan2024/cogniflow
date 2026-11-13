"""Build small test files in memory (no binary fixtures needed)."""
import io
from typing import List


def make_text_pdf(lines: List[str]) -> bytes:
    """A minimal valid one-page PDF with REAL embedded text (so no OCR is needed)."""

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content = "BT /F1 12 Tf 72 740 Td 16 TL\n" + "\n".join(f"({esc(line)}) Tj T*" for line in lines) + "\nET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF".encode()
    return bytes(out)


def _font(size: int):
    from PIL import ImageFont

    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def make_text_image_obj(lines: List[str], size: int = 44):
    """A white page image with black text, similar to a clean scan."""
    from PIL import Image, ImageDraw

    font = _font(size)
    img = Image.new("RGB", (1400, 120 + len(lines) * (size + 30)), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((60, 60 + i * (size + 30)), line, fill="black", font=font)
    return img


def make_text_image(lines: List[str], fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    make_text_image_obj(lines).save(buf, format=fmt)
    return buf.getvalue()


def make_image_pdf(lines: List[str]) -> bytes:
    """A PDF that contains only a picture of text (like a scanned document): no embedded text."""
    buf = io.BytesIO()
    make_text_image_obj(lines).save(buf, format="PDF")
    return buf.getvalue()
