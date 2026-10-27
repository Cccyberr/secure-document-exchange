"""Procedurally generated sample images (no copyrighted / personal photos needed)."""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 960, 640


def _noise(seed, scale=6):
    r = np.random.default_rng(seed)
    return r.normal(0, scale, (H, W, 1))


def sunset():
    y = np.linspace(0, 1, H)[:, None, None]
    sky = np.concatenate([255 - 60 * y, 120 + 60 * (1 - y) ** 2, 90 + 120 * y], -1) * np.ones((1, W, 1))
    img = Image.fromarray(np.clip(sky + _noise(1), 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    d.ellipse((600, 230, 720, 350), fill=(255, 220, 140))
    rng = np.random.default_rng(3)
    for layer, col in enumerate([(70, 50, 90), (45, 30, 60), (25, 18, 35)]):
        pts = [(0, H)]
        x = 0
        while x <= W:
            pts.append((x, 330 + layer * 70 + rng.integers(-60, 60)))
            x += rng.integers(40, 110)
        pts += [(W, H)]
        d.polygon(pts, fill=col)
    return img.filter(ImageFilter.SMOOTH)


def ocean():
    x = np.linspace(0, 1, W)[None, :]; y = np.linspace(0, 1, H)[:, None]
    waves = 20 * np.sin(40 * x + 25 * y ** 1.5) * y
    r = 20 + 30 * y + waves * 0.3; g = 90 + 80 * y + waves; b = 150 + 80 * (1 - y) + waves
    sky = y < 0.38
    r = np.where(sky, 180 + 60 * y, r); g = np.where(sky, 210 + 30 * y, g); b = np.where(sky, 245, b)
    a = np.stack([r, g, b], -1) + _noise(2)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.SMOOTH)


def city():
    y = np.linspace(0, 1, H)[:, None, None]
    a = np.concatenate([10 + 30 * y, 10 + 20 * y, 40 + 60 * y], -1) * np.ones((1, W, 1)) + _noise(4, 3)
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(7)
    x = 0
    while x < W:
        bw = int(rng.integers(50, 120)); bh = int(rng.integers(150, 450))
        d.rectangle((x, H - bh, x + bw, H), fill=(20, 22, 35))
        for wy in range(H - bh + 12, H - 10, 22):
            for wx in range(x + 8, x + bw - 10, 16):
                if rng.random() < 0.45:
                    d.rectangle((wx, wy, wx + 7, wy + 11), fill=(255, 210 + int(rng.integers(0, 40)), 120))
        x += bw + int(rng.integers(4, 18))
    d.ellipse((120, 60, 190, 130), fill=(235, 235, 210))
    return img


def forest():
    rng = np.random.default_rng(11)
    y = np.linspace(0, 1, H)[:, None, None]
    a = np.concatenate([150 - 80 * y, 200 - 70 * y, 170 - 100 * y], -1) * np.ones((1, W, 1)) + _noise(5)
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    for i in range(70):
        x = int(rng.integers(-40, W)); h = int(rng.integers(160, 420)); w = h // 3
        shade = int(rng.integers(20, 90))
        d.polygon([(x, H - h), (x - w // 2, H - 40), (x + w // 2, H - 40)], fill=(shade // 2, shade + 30, shade // 2 + 10))
        d.rectangle((x - 5, H - 40, x + 5, H), fill=(60, 40, 25))
    return img.filter(ImageFilter.SMOOTH)


SAMPLES = {"sunset.png": sunset, "ocean.png": ocean, "city.png": city, "forest.png": forest}


def ensure(dir_):
    os.makedirs(dir_, exist_ok=True)
    for name, fn in SAMPLES.items():
        p = os.path.join(dir_, name)
        if not os.path.exists(p):
            fn().save(p)
    return sorted(SAMPLES)
