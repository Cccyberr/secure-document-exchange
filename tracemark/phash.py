"""64-bit perceptual hash (DCT pHash). Similar-looking images -> small Hamming distance."""
import numpy as np
from PIL import Image

_N = 32


def _dct_mat(n):
    k = np.arange(n)[:, None]; i = np.arange(n)[None, :]
    m = np.sqrt(2 / n) * np.cos(np.pi * (2 * i + 1) * k / (2 * n))
    m[0] /= np.sqrt(2)
    return m


_M = _dct_mat(_N)


def phash(img: Image.Image) -> str:
    g = np.asarray(img.convert("L").resize((_N, _N), Image.LANCZOS), dtype=np.float64)
    d = (_M @ g @ _M.T)[:8, :8].reshape(-1)
    med = np.median(d[1:])
    bits = (d > med).astype(int)
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return f"{v:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")
