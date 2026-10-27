"""
Layer A - Fragile LSB steganography (adapted from StegoVault, github.com/nabirudd/StegoVault-LSB-Steganography-Tool).

Changes from StegoVault:
  * vectorised with NumPy (fast on large images)
  * carries arbitrary bytes (the signed + encrypted provenance envelope), zlib-compressed
  * 4-byte magic "TMK1" + length header so we can tell "no tag" from "damaged tag"
  * deliberately FRAGILE: any re-compression destroys it, which tells the
    investigator the file is no longer the platform's original output.
"""
import struct, zlib
import numpy as np
from PIL import Image

MAGIC = b"TMK1"
HDR = len(MAGIC) + 4


def capacity(img: Image.Image) -> int:
    w, h = img.size
    return (w * h * 3) // 8 - HDR


def embed(img: Image.Image, payload: bytes) -> Image.Image:
    data = zlib.compress(payload, 9)
    blob = MAGIC + struct.pack(">I", len(data)) + data
    arr = np.asarray(img.convert("RGB"), dtype=np.uint8).copy()
    flat = arr.reshape(-1)
    bits = np.unpackbits(np.frombuffer(blob, dtype=np.uint8))
    if bits.size > flat.size:
        raise ValueError(f"Image too small: needs {len(blob)} bytes, capacity {capacity(img)} bytes")
    flat[:bits.size] = (flat[:bits.size] & 0xFE) | bits
    return Image.fromarray(arr)


def extract(img: Image.Image):
    """Return payload bytes, or None if no intact LSB tag is present."""
    flat = np.asarray(img.convert("RGB"), dtype=np.uint8).reshape(-1)
    if flat.size < HDR * 8:
        return None
    hdr = np.packbits(flat[:HDR * 8] & 1).tobytes()
    if hdr[:4] != MAGIC:
        return None
    n = struct.unpack(">I", hdr[4:8])[0]
    if n <= 0 or (HDR + n) * 8 > flat.size:
        return None
    data = np.packbits(flat[HDR * 8:(HDR + n) * 8] & 1).tobytes()
    try:
        return zlib.decompress(data)
    except zlib.error:
        return None
