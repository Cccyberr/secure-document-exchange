"""
Simulated 'AI image generator' for the demo.
In a real deployment this is a diffusion model; here we apply visible style
transforms so the output is clearly a *new, synthetic* image.
"""
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

STYLES = {
    "cinematic": "Cinematic colour grade",
    "oil": "Oil painting",
    "poster": "Comic / poster art",
    "dream": "Dreamy glow",
}


def _vignette(img, strength=0.45):
    w, h = img.size
    y, x = np.ogrid[:h, :w]
    d = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2)
    mask = np.clip(1 - strength * d ** 2, 0, 1)[..., None]
    return Image.fromarray((np.asarray(img, float) * mask).astype(np.uint8))


def generate(img: Image.Image, style: str) -> Image.Image:
    img = img.convert("RGB")
    if style == "cinematic":
        a = np.asarray(ImageEnhance.Contrast(img).enhance(1.25), float)
        a[..., 0] *= 1.08; a[..., 2] *= 0.88
        out = _vignette(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)))
    elif style == "oil":
        out = img.filter(ImageFilter.ModeFilter(7)).filter(ImageFilter.SMOOTH_MORE)
        out = ImageEnhance.Color(out).enhance(1.4)
    elif style == "poster":
        base = ImageOps.posterize(ImageEnhance.Color(img).enhance(1.6), 3)
        edges = img.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v < 40 else 0)
        out = Image.composite(base, Image.new("RGB", img.size, (15, 15, 25)), edges)
    else:  # dream
        glow = img.filter(ImageFilter.GaussianBlur(8))
        out = Image.blend(ImageEnhance.Brightness(img).enhance(1.1), glow, 0.45)
        out = ImageEnhance.Color(out).enhance(1.3)
    return out


def fit(img: Image.Image, max_side=1280) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    s = min(1.0, max_side / max(w, h))
    if s < 1:
        img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    # make sure there is room for the LSB envelope
    if img.size[0] * img.size[1] < 160 * 160:
        img = img.resize((max(img.size[0], 320), max(img.size[1], 320)))
    return img
