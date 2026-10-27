"""
Layer B - Robust watermark (survives JPEG re-compression and resizing).

Technique: block-DCT Quantization Index Modulation (QIM) on the luminance (Y)
channel, computed on a normalised 512x512 grid so that the mark survives
resizing. A 64-bit record ID + 16-bit CRC is repeated across all 8x8 blocks
and recovered by majority voting.

Only a short ID fits here (~80 bits). The full encrypted + signed provenance
record lives in the platform registry and is looked up with this ID.
"""
import zlib
import numpy as np
from PIL import Image

GRID = 512            # normalised working size
B = 8                 # DCT block size
COEFS = [(0, 1), (1, 0), (1, 1), (0, 2), (2, 0)]   # low-frequency AC positions (survive resizing/JPEG)
STEP = 30.0           # QIM quantisation step (strength)
ID_BITS = 64
CRC_BITS = 16
N_BITS = ID_BITS + CRC_BITS


def _dct_matrix(n=B):
    m = np.zeros((n, n))
    for k in range(n):
        for i in range(n):
            a = np.sqrt(1 / n) if k == 0 else np.sqrt(2 / n)
            m[k, i] = a * np.cos(np.pi * (2 * i + 1) * k / (2 * n))
    return m


_D = _dct_matrix()


def _blocks_dct(y):
    h, w = y.shape
    t = y.reshape(h // B, B, w // B, B).transpose(0, 2, 1, 3)
    return _D @ t @ _D.T                        # (hb, wb, 8, 8)


def _blocks_idct(c):
    t = _D.T @ c @ _D
    hb, wb = t.shape[:2]
    return t.transpose(0, 2, 1, 3).reshape(hb * B, wb * B)


def _crc16(v: int) -> int:
    return zlib.crc32(v.to_bytes(8, "big")) & 0xFFFF


def _id_to_bits(record_id: int):
    word = (record_id << CRC_BITS) | _crc16(record_id)
    return np.array([(word >> (N_BITS - 1 - i)) & 1 for i in range(N_BITS)], dtype=np.int8)


def _slot_map(n_slots):
    # slot i carries bit (i mod N_BITS); fixed permutation spreads bits spatially
    rng = np.random.default_rng(20261027)
    order = rng.permutation(n_slots)
    return order % N_BITS


def _y_channel(img: Image.Image):
    ycc = np.asarray(img.convert("YCbCr"), dtype=np.float64)
    return ycc


def embed(img: Image.Image, record_id: int) -> Image.Image:
    img = img.convert("RGB")
    W, H = img.size
    ycc = _y_channel(img)
    y = ycc[:, :, 0]
    # work on a normalised grid
    yg = np.asarray(Image.fromarray(y).resize((GRID, GRID), Image.BICUBIC), dtype=np.float64)
    c = _blocks_dct(yg)
    flat = c.reshape(-1, B, B)
    n_slots = flat.shape[0] * len(COEFS)
    bits = _id_to_bits(record_id)[_slot_map(n_slots)]
    s = 0
    for blk in range(flat.shape[0]):
        for (u, v) in COEFS:
            x = flat[blk, u, v]
            bit = bits[s]; s += 1
            # dither-QIM: bit 0 -> lattice k*STEP, bit 1 -> k*STEP + STEP/2
            off = 0.0 if bit == 0 else STEP / 2
            flat[blk, u, v] = np.round((x - off) / STEP) * STEP + off
    yg2 = _blocks_idct(flat.reshape(c.shape))
    delta = yg2 - yg
    # bring the change back to original resolution and add it
    d_full = np.asarray(Image.fromarray(delta.astype(np.float32)).resize((W, H), Image.BICUBIC))
    ycc[:, :, 0] = np.clip(y + d_full, 0, 255)
    ch = [Image.fromarray(np.round(ycc[:, :, i]).astype(np.uint8)) for i in range(3)]
    out = Image.merge("YCbCr", ch).convert("RGB")
    return out


def extract(img: Image.Image):
    """Return (record_id or None, confidence 0..1)."""
    y = _y_channel(img.convert("RGB"))[:, :, 0]
    yg = np.asarray(Image.fromarray(y).resize((GRID, GRID), Image.BICUBIC), dtype=np.float64)
    flat = _blocks_dct(yg).reshape(-1, B, B)
    n_slots = flat.shape[0] * len(COEFS)
    smap = _slot_map(n_slots)
    votes = np.zeros(N_BITS); counts = np.zeros(N_BITS)
    s = 0
    for blk in range(flat.shape[0]):
        for (u, v) in COEFS:
            x = flat[blk, u, v]
            r = (x / STEP) % 1.0          # ~0 -> bit 0 lattice, ~0.5 -> bit 1 lattice
            d0 = min(r, 1 - r); d1 = abs(r - 0.5)
            votes[smap[s]] += (1 if d1 < d0 else 0)
            counts[smap[s]] += 1
            s += 1
    frac = votes / counts
    bits = (frac > 0.5).astype(int)
    conf = float(np.mean(np.abs(frac - 0.5) * 2))
    word = 0
    for b in bits:
        word = (word << 1) | int(b)
    rid, crc = word >> CRC_BITS, word & 0xFFFF
    if _crc16(rid) != crc:
        return None, conf
    return rid, conf
