"""Image-quality metrics used in the security analysis."""
import numpy as np
from PIL import Image


def psnr(a: Image.Image, b: Image.Image) -> float:
    x = np.asarray(a.convert("RGB"), float); y = np.asarray(b.convert("RGB"), float)
    mse = ((x - y) ** 2).mean()
    return float("inf") if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def ssim(a: Image.Image, b: Image.Image) -> float:
    """Mean SSIM on luminance using 8x8 windows (Wang et al. 2004 constants)."""
    x = np.asarray(a.convert("L"), float); y = np.asarray(b.convert("L"), float)
    h, w = (x.shape[0] // 8) * 8, (x.shape[1] // 8) * 8
    x = x[:h, :w].reshape(h // 8, 8, w // 8, 8).transpose(0, 2, 1, 3).reshape(-1, 64)
    y = y[:h, :w].reshape(h // 8, 8, w // 8, 8).transpose(0, 2, 1, 3).reshape(-1, 64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mx, my = x.mean(1), y.mean(1)
    vx, vy = x.var(1), y.var(1)
    cov = ((x - mx[:, None]) * (y - my[:, None])).mean(1)
    s = ((2 * mx * my + c1) * (2 * cov + c2)) / ((mx ** 2 + my ** 2 + c1) * (vx + vy + c2))
    return float(s.mean())
