"""In-memory diagnostic PDFs only. No construction-document fixtures or business facts."""

import io
import zlib

from PIL import Image, ImageDraw


def diagnostic_pdf(numbered=False, padding_bytes=0, page_size=(300, 200)):
    """Two pages: selectable generic text, then an image-only page."""
    image = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 50), "IMAGE PAGE TWO", fill="black", font_size=36)
    draw.rectangle((40, 130, 360, 230), outline="black", width=3)
    raster = zlib.compress(image.tobytes())
    image.close()
    text = b"BT /F1 22 Tf 30 150 Td (TEXT PAGE ONE) Tj ET"
    if numbered:
        text = b"BT /F1 12 Tf 20 170 Td (ITEM DESCRIPTION) Tj 0 -25 Td (X01 First diagnostic row) Tj 0 -25 Td (X02 Second diagnostic row) Tj 0 -25 Td (X03 Third diagnostic row) Tj ET"
    image_commands = b"q 300 0 0 200 0 0 cm /Im1 Do Q"
    box = f'[0 0 {page_size[0]} {page_size[1]}]'.encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox " + box + b" /Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream",
        b"<< /Type /Page /Parent 2 0 R /MediaBox " + box + b" /Resources << /XObject << /Im1 8 0 R >> >> /Contents 6 0 R >>",
        b"<< /Length " + str(len(image_commands)).encode() + b" >>\nstream\n" + image_commands + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /XObject /Subtype /Image /Width 600 /Height 400 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length " + str(len(raster)).encode() + b" >>\nstream\n" + raster + b"\nendstream",
    ]
    if padding_bytes:
        objects.append(b'<< /Length ' + str(padding_bytes).encode() + b' >>\nstream\n' + b' ' * padding_bytes + b'\nendstream')
    output = io.BytesIO()
    output.write(b"%PDF-1.7\n")
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(f"{index} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return output.getvalue()
