# TraceMark - Security & Performance Analysis

## 1. Cryptographic operation cost (mean, ms)

| Operation | Time (ms) |
|---|---|
| Ed25519 key generation | 0.036 |
| RSA-3072 key generation | 206.257 |
| Ed25519 sign (2 KB) | 0.088 |
| Ed25519 verify | 0.175 |
| RSA-3072-OAEP encrypt (32 B) | 0.063 |
| RSA-3072-OAEP decrypt | 1.217 |
| RSA-3072-PSS sign (warrant) | 1.100 |
| AES-256-GCM encrypt (1 KB) | 0.007 |

## 2. Imperceptibility of tagging

| Image | Size | PSNR (dB) | SSIM | Envelope (B) | Tag time (ms) |
|---|---|---|---|---|---|
| city.png | 960x640 | 38.97 | 0.9304 | 1650 | 74 |
| forest.png | 960x640 | 39.21 | 0.9378 | 1650 | 68 |
| ocean.png | 960x640 | 39.11 | 0.9355 | 1650 | 66 |
| sunset.png | 960x640 | 39.56 | 0.9273 | 1650 | 65 |

## 3. Robustness (survival over all 4 test images)

| Transformation | LSB layer | Robust layer | Verified as AI-generated |
|---|---|---|---|
| Original PNG (lossless copy) | 4/4 | 4/4 | 4/4 |
| JPEG quality 95 | 0/4 | 4/4 | 4/4 |
| JPEG quality 80 | 0/4 | 4/4 | 4/4 |
| WhatsApp forward (≤1280px, JPEG 60) | 0/4 | 4/4 | 4/4 |
| JPEG quality 50 | 0/4 | 4/4 | 4/4 |
| JPEG quality 30 | 0/4 | 4/4 | 4/4 |
| Screenshot & repost (80%, JPEG 85) | 0/4 | 4/4 | 4/4 |
| Upscale 150% | 0/4 | 4/4 | 4/4 |
| Downscale 50% | 0/4 | 4/4 | 4/4 |
| Downscale 50% + JPEG 70 | 0/4 | 4/4 | 4/4 |
| Brightness +15% | 0/4 | 4/4 | 4/4 |
| Gaussian blur r=1 | 0/4 | 4/4 | 4/4 |
| Crop 10% borders | 0/4 | 0/4 | 0/4 |
| Rotate 2° | 0/4 | 0/4 | 0/4 |

## 4. False positives
Untagged images wrongly reported as tagged: 0/4 (16-bit CRC → theoretical rate 1/65536, further filtered by registry lookup + pHash).

## 5. Threat model

| Threat | Attacker goal | Defence | Result |
|---|---|---|---|
| Forgery | Fake tag to frame an innocent person | Ed25519 platform signature | Rejected (FORGED) |
| Tampering | Change label / identity in tag | Signature over whole envelope + AES-GCM tag | Rejected |
| Transplant | Move a genuine tag onto another photo | Signed pHash + robust-ID cross-check | Detected (TRANSPLANTED) |
| Eavesdropping | Learn creator identity from image | RSA-3072-OAEP + AES-256-GCM | Ciphertext only |
| Abuse of power | Police unmask without due process | 2-of-2 key split with Court | Blocked without warrant |
| Fake warrant | Forge court order | RSA-PSS court signature | Rejected |
| Key theft | Use stolen key file | PKCS#8 passphrase encryption | Requires passphrase |
| Stripping | Remove tag by re-encoding | Robust DCT watermark + registry | Survives JPEG ≥50, WhatsApp, resize |
| Stripping (strong) | Crop / rotate / local AI model | — | **Limitation**: tag lost; see report |
