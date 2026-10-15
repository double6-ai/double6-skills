"""render.py <pptx> <outdir> [label]: LibreOffice -> PDF -> PNG pages + contact sheet."""
import subprocess, sys, tempfile, shutil, os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def render(pptx, outdir, label=None, cols=4, width=480):
    pptx = Path(pptx); outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    prof = tempfile.mkdtemp(prefix="lo")
    subprocess.run(["soffice", f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(pptx)], check=True, capture_output=True, timeout=300)
    shutil.rmtree(prof, ignore_errors=True)
    pdf = outdir / (pptx.stem + ".pdf")
    for f in outdir.glob(pptx.stem + "-*.png"): f.unlink()
    subprocess.run(["pdftoppm", "-png", "-r", "60", str(pdf), str(outdir / pptx.stem)], check=True)
    pages = sorted(outdir.glob(pptx.stem + "-*.png"))
    ims = [Image.open(p).convert("RGB") for p in pages]
    ims = [im.resize((width, int(im.height * width / im.width))) for im in ims]
    h = max(im.height for im in ims); rows = (len(ims) + cols - 1) // cols; top = 30
    sheet = Image.new("RGB", (cols * (width + 10) + 10, rows * (h + 26) + top + 10), "white")
    d = ImageDraw.Draw(sheet)
    try: font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 16)
    except Exception: font = None
    d.text((10, 6), label or pptx.name, fill="black", font=font)
    for i, im in enumerate(ims):
        x = 10 + (i % cols) * (width + 10); y = top + (i // cols) * (h + 26)
        sheet.paste(im, (x, y)); d.rectangle([x - 1, y - 1, x + im.width, y + im.height], outline="#999")
        d.text((x, y + im.height + 3), f"{i+1}", fill="black", font=font)
    out = outdir / (pptx.stem + "_sheet.png"); sheet.save(out); return out, len(pages)

if __name__ == "__main__":
    print(render(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
