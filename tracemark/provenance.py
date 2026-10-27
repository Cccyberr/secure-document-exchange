"""
TraceMark provenance protocol.

Envelope embedded in every AI-generated image:
{
  "v": 1,
  "pub":    { label, platform, model, record_id, created_at, phash, platform_key_fp },   <- anyone can read
  "sealed": { alg, police_share, court_share, nonce, ct },                                <- creator identity
  "sig":    Ed25519(platform_priv, canonical({pub, sealed}))
}

Sealing (hybrid, threshold):
  K  = random AES-256 key;  ct = AES-GCM(K, identity, aad = canonical(pub))
  K  = s1 XOR s2           (2-of-2 split)
  police_share = RSA-OAEP(police_pub, s1)
  court_share  = RSA-OAEP(court_pub,  s2)
=> Police alone cannot unmask anyone. A court warrant must release s2.
"""
import hashlib, json, os, secrets
from datetime import datetime, timezone
from PIL import Image

from . import crypto_core as cc
from . import lsb, robust_wm, phash as ph

PHASH_MATCH_MAX = 12        # Hamming distance (of 64) to call two images "the same picture"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_record_id() -> int:
    return secrets.randbits(63) | 1


class Keyring:
    """Loads the public keys of all roles + (optionally) the platform signing key."""

    def __init__(self, key_dir: str):
        self.key_dir = key_dir
        cc.ensure_keys(key_dir)
        self.platform_pub = cc.load_public(os.path.join(key_dir, "platform_public.pem"))
        self.police_pub = cc.load_public(os.path.join(key_dir, "police_public.pem"))
        self.court_pub = cc.load_public(os.path.join(key_dir, "court_public.pem"))
        self._platform_priv = None

    def private(self, role: str, passphrase: str):
        return cc.load_private(os.path.join(self.key_dir, f"{role}_private.pem"), passphrase)

    @property
    def platform_priv(self):
        if self._platform_priv is None:
            self._platform_priv = self.private("platform", cc.DEFAULT_PASSPHRASES["platform"])
        return self._platform_priv

    def info(self):
        return [
            {"role": "AI Platform (PixelForge AI)", "alg": "Ed25519 signature", "fp": cc.fingerprint(self.platform_pub),
             "use": "Signs every provenance tag so it cannot be forged"},
            {"role": "Cyber Police", "alg": "RSA-3072 OAEP", "fp": cc.fingerprint(self.police_pub),
             "use": "Receives key share #1 of the sealed creator identity"},
            {"role": "Court / Magistrate", "alg": "RSA-3072 OAEP + RSA-PSS", "fp": cc.fingerprint(self.court_pub),
             "use": "Holds key share #2; releases it only through a signed warrant"},
        ]


# ───────────────────────── creation (platform side) ─────────────────────────
def build_envelope(kr: Keyring, record_id: int, identity: dict, image_phash: str,
                   platform="PixelForge AI", model="pixelforge-diffusion-v3", signing_key=None):
    pub = {
        "label": "AI-GENERATED",
        "platform": platform,
        "model": model,
        "record_id": f"{record_id:016x}",
        "created_at": now_iso(),
        "phash": image_phash,
        "platform_key_fp": cc.fingerprint((signing_key or kr.platform_priv).public_key()),
    }
    k = os.urandom(32)
    s1, s2 = cc.split_key(k)
    nonce, ct = cc.aes_encrypt(k, cc.canonical(identity), aad=cc.canonical(pub))
    sealed = {
        "alg": "AES-256-GCM | key split 2-of-2 | RSA-3072-OAEP-SHA256",
        "police_share": cc.b64e(cc.rsa_encrypt(kr.police_pub, s1)),
        "court_share": cc.b64e(cc.rsa_encrypt(kr.court_pub, s2)),
        "nonce": cc.b64e(nonce),
        "ct": cc.b64e(ct),
    }
    body = {"pub": pub, "sealed": sealed}
    sig = cc.sign(signing_key or kr.platform_priv, cc.canonical(body))
    return {"v": 1, **body, "sig": cc.b64e(sig)}


def tag_image(kr: Keyring, img: Image.Image, identity: dict, record_id=None, signing_key=None):
    """Embed both layers. Returns (tagged_image, envelope, record_id)."""
    record_id = record_id or new_record_id()
    img = img.convert("RGB")
    marked = robust_wm.embed(img, record_id)           # Layer B (robust ID)
    env = build_envelope(kr, record_id, identity, ph.phash(marked), signing_key=signing_key)
    final = lsb.embed(marked, cc.canonical(env))       # Layer A (full envelope)
    return final, env, record_id


# ───────────────────────── forensic analysis ─────────────────────────
def verify_envelope(kr: Keyring, env: dict) -> bool:
    try:
        body = {"pub": env["pub"], "sealed": env["sealed"]}
        return cc.verify(kr.platform_pub, cc.b64d(env["sig"]), cc.canonical(body))
    except Exception:
        return False


def analyze(kr: Keyring, img: Image.Image, registry_lookup):
    """
    Read-only analysis that anyone can run. Never reveals the sealed identity.
    registry_lookup(record_id_hex) -> envelope dict or None
    """
    img = img.convert("RGB")
    res = {"layers": {}, "checks": [], "envelope": None, "verdict": "NO_TAG",
           "current_phash": ph.phash(img)}

    # Layer A
    env = None
    raw = lsb.extract(img)
    if raw:
        try:
            env = json.loads(raw)
            res["layers"]["lsb"] = "INTACT - full signed record read from pixels (file is an untouched original)"
        except Exception:
            res["layers"]["lsb"] = "DAMAGED"
    else:
        res["layers"]["lsb"] = "NOT PRESENT / DESTROYED (image was re-compressed, edited or never tagged)"

    # Layer B
    rid, conf = robust_wm.extract(img)
    if rid is not None:
        res["layers"]["robust"] = f"FOUND - record ID {rid:016x} (confidence {conf:.0%})"
    else:
        res["layers"]["robust"] = "NOT FOUND"

    reg_env = registry_lookup(f"{rid:016x}") if rid is not None else None
    if env is None and reg_env is not None:
        env = reg_env
        res["source"] = "Robust watermark -> platform registry lookup"
    elif env is not None:
        res["source"] = "LSB layer (embedded record)"

    if env is None:
        res["verdict"] = "NO_TAG"
        res["summary"] = ("No provenance tag found. The image is either a real camera photo, was produced by a "
                          "tool that does not take part, or the tag was destroyed (heavy crop/downscale).")
        return res

    res["envelope"] = env
    sig_ok = verify_envelope(kr, env)
    res["checks"].append(("Platform signature (Ed25519)", sig_ok,
                          "Valid - tag was issued by PixelForge AI and not modified" if sig_ok
                          else "INVALID - forged or tampered tag"))
    if rid is not None:
        same = env["pub"]["record_id"] == f"{rid:016x}"
        res["checks"].append(("Robust ID matches record", same, "Both layers agree" if same
                              else "Layers disagree - LSB record was copied from another image"))
    if reg_env is not None or rid is None:
        in_reg = registry_lookup(env["pub"]["record_id"]) is not None
        res["checks"].append(("Record exists in platform registry", in_reg,
                              "Registered" if in_reg else "Unknown record ID"))
    dist = ph.hamming(env["pub"]["phash"], res["current_phash"])
    pmatch = dist <= PHASH_MATCH_MAX
    res["checks"].append(("Perceptual fingerprint matches image", pmatch,
                          f"Hamming distance {dist}/64 " + ("(same picture)" if pmatch else
                                                            "(tag belongs to a DIFFERENT picture - transplanted)")))
    res["phash_distance"] = dist

    if not sig_ok:
        res["verdict"] = "FORGED"
        res["summary"] = "The tag fails signature verification. It was forged or altered - do not trust it."
    elif not all(ok for _, ok, _ in res["checks"]):
        res["verdict"] = "TRANSPLANTED"
        res["summary"] = "A genuine tag is present but it does not belong to this image."
    else:
        res["verdict"] = "AI_GENERATED"
        res["summary"] = (f"Verified AI-generated image, created on {env['pub']['platform']} at "
                          f"{env['pub']['created_at']}. Creator identity is sealed for law enforcement.")
    return res


# ───────────────────────── court warrant + unmasking ─────────────────────────
def issue_warrant(kr: Keyring, court_priv, env: dict, case_id: int, judge: str, reason: str):
    """Court decrypts its share and re-encrypts it for the police, then signs the order."""
    s2 = cc.rsa_decrypt(court_priv, cc.b64d(env["sealed"]["court_share"]))
    order = {
        "warrant_id": f"W-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}",
        "case_id": case_id,
        "record_id": env["pub"]["record_id"],
        "issued_at": now_iso(),
        "judge": judge,
        "reason": reason,
        "share_for_police": cc.b64e(cc.rsa_encrypt(kr.police_pub, s2)),
    }
    return {"order": order, "court_sig": cc.b64e(cc.sign(court_priv, cc.canonical(order)))}


def verify_warrant(kr: Keyring, warrant: dict) -> bool:
    try:
        return cc.verify(kr.court_pub, cc.b64d(warrant["court_sig"]), cc.canonical(warrant["order"]))
    except Exception:
        return False


def unmask(kr: Keyring, police_priv, env: dict, warrant: dict) -> dict:
    if not verify_envelope(kr, env):
        raise ValueError("Envelope signature invalid")
    if not verify_warrant(kr, warrant):
        raise ValueError("Warrant signature invalid - not issued by the court")
    if warrant["order"]["record_id"] != env["pub"]["record_id"]:
        raise ValueError("Warrant was issued for a different record")
    s1 = cc.rsa_decrypt(police_priv, cc.b64d(env["sealed"]["police_share"]))
    s2 = cc.rsa_decrypt(police_priv, cc.b64d(warrant["order"]["share_for_police"]))
    k = cc.xor(s1, s2)
    pt = cc.aes_decrypt(k, cc.b64d(env["sealed"]["nonce"]), cc.b64d(env["sealed"]["ct"]),
                        aad=cc.canonical(env["pub"]))
    return json.loads(pt)


def police_only_attempt(kr: Keyring, police_priv, env: dict):
    """Demonstrates that the police share alone is useless. Always raises."""
    s1 = cc.rsa_decrypt(police_priv, cc.b64d(env["sealed"]["police_share"]))
    cc.aes_decrypt(s1, cc.b64d(env["sealed"]["nonce"]), cc.b64d(env["sealed"]["ct"]),
                   aad=cc.canonical(env["pub"]))


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()
