"""
Generates the numbers for the report's 'Testing & Security Analysis' section.
Run:  python analysis/security_analysis.py      -> writes analysis/results.md and analysis/*.csv
"""
import csv, io, os, sys, time, statistics, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image
from tracemark import crypto_core as cc, provenance as pv, lsb, robust_wm, metrics, samples, genai
import app as A

OUT = os.path.dirname(os.path.abspath(__file__))
kr = pv.Keyring(tempfile.mkdtemp())
sd = tempfile.mkdtemp(); names = samples.ensure(sd)
IDENT = {"account_id": "PF-10231", "username": "dark_lens_77", "upload_ip": "117.211.84.19"}


def timeit(fn, n=20):
    ts = []
    for _ in range(n):
        t = time.perf_counter(); fn(); ts.append((time.perf_counter() - t) * 1000)
    return statistics.mean(ts)


lines = ["# TraceMark - Security & Performance Analysis\n"]

# 1. crypto timings
pol = kr.private("police", "police@123"); court = kr.private("court", "court@123")
rows = [
    ("Ed25519 key generation", timeit(lambda: cc.generate_keypair("ed25519"))),
    ("RSA-3072 key generation", timeit(lambda: cc.generate_keypair("rsa"), 3)),
    ("Ed25519 sign (2 KB)", timeit(lambda: cc.sign(kr.platform_priv, b"x" * 2048))),
    ("Ed25519 verify", timeit(lambda: cc.verify(kr.platform_pub, cc.sign(kr.platform_priv, b"x"), b"x"))),
    ("RSA-3072-OAEP encrypt (32 B)", timeit(lambda: cc.rsa_encrypt(kr.police_pub, b"k" * 32))),
    ("RSA-3072-OAEP decrypt", timeit(lambda: cc.rsa_decrypt(pol, cc.rsa_encrypt(kr.police_pub, b"k" * 32)))),
    ("RSA-3072-PSS sign (warrant)", timeit(lambda: cc.sign(court, b"order"))),
    ("AES-256-GCM encrypt (1 KB)", timeit(lambda: cc.aes_encrypt(os.urandom(32), b"x" * 1024, b""))),
]
lines += ["## 1. Cryptographic operation cost (mean, ms)\n", "| Operation | Time (ms) |", "|---|---|"]
lines += [f"| {n} | {t:.3f} |" for n, t in rows]

# 2. imperceptibility
lines += ["\n## 2. Imperceptibility of tagging\n", "| Image | Size | PSNR (dB) | SSIM | Envelope (B) | Tag time (ms) |", "|---|---|---|---|---|---|"]
tagged = {}
for n in names:
    g = genai.generate(Image.open(os.path.join(sd, n)), "cinematic")
    t = time.perf_counter(); im, env, rid = pv.tag_image(kr, g, IDENT); ms = (time.perf_counter() - t) * 1000
    tagged[n] = (im, env, rid)
    lines.append(f"| {n} | {g.width}x{g.height} | {metrics.psnr(g, im):.2f} | {metrics.ssim(g, im):.4f} | {len(cc.canonical(env))} | {ms:.0f} |")

# 3. robustness
reg = {f"{v[2]:016x}": v[1] for v in tagged.values()}
lines += ["\n## 3. Robustness (survival over all 4 test images)\n", "| Transformation | LSB layer | Robust layer | Verified as AI-generated |", "|---|---|---|---|"]
with open(os.path.join(OUT, "robustness.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["transformation", "lsb_survival", "robust_survival", "verified"])
    for name, fn in A.TRANSFORMS:
        a = b = v = 0
        for im, env, rid in tagged.values():
            x = fn(im)
            a += lsb.extract(x) is not None
            b += robust_wm.extract(x)[0] == rid
            v += pv.analyze(kr, x, reg.get)["verdict"] == "AI_GENERATED"
        k = len(tagged)
        lines.append(f"| {name} | {a}/{k} | {b}/{k} | {v}/{k} |")
        w.writerow([name, a / k, b / k, v / k])

# 4. false positives
fp = sum(robust_wm.extract(Image.open(os.path.join(sd, n)))[0] is not None for n in names)
lines += [f"\n## 4. False positives\nUntagged images wrongly reported as tagged: {fp}/{len(names)} "
          f"(16-bit CRC → theoretical rate 1/65536, further filtered by registry lookup + pHash).\n"]

# 5. threat model
lines += ["## 5. Threat model\n", "| Threat | Attacker goal | Defence | Result |", "|---|---|---|---|",
          "| Forgery | Fake tag to frame an innocent person | Ed25519 platform signature | Rejected (FORGED) |",
          "| Tampering | Change label / identity in tag | Signature over whole envelope + AES-GCM tag | Rejected |",
          "| Transplant | Move a genuine tag onto another photo | Signed pHash + robust-ID cross-check | Detected (TRANSPLANTED) |",
          "| Eavesdropping | Learn creator identity from image | RSA-3072-OAEP + AES-256-GCM | Ciphertext only |",
          "| Abuse of power | Police unmask without due process | 2-of-2 key split with Court | Blocked without warrant |",
          "| Fake warrant | Forge court order | RSA-PSS court signature | Rejected |",
          "| Key theft | Use stolen key file | PKCS#8 passphrase encryption | Requires passphrase |",
          "| Stripping | Remove tag by re-encoding | Robust DCT watermark + registry | Survives JPEG ≥50, WhatsApp, resize |",
          "| Stripping (strong) | Crop / rotate / local AI model | — | **Limitation**: tag lost; see report |"]
open(os.path.join(OUT, "results.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
