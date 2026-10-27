"""
Asymmetric cryptography core for TraceMark.

  * Platform signing key ........ Ed25519        (authenticity / non-repudiation of tags)
  * Cyber Police key ............ RSA-3072 OAEP  (confidential creator identity)
  * Court / Magistrate key ...... RSA-3072 OAEP + RSA-PSS (warrant: 2nd key share + signed order)
  * Bulk data ................... AES-256-GCM    (hybrid encryption)

All private keys are stored on disk as PKCS#8 PEM encrypted with a passphrase.
"""
import base64, hashlib, json, os
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa, padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidSignature

RSA_BITS = 3072
OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH)

# Demo passphrases (in a real deployment these live in an HSM / are typed by the officer)
DEFAULT_PASSPHRASES = {
    "platform": "platform@123",
    "police": "police@123",
    "court": "court@123",
}
ROLES = {"platform": "ed25519", "police": "rsa", "court": "rsa"}


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def b64d(s: str) -> bytes:
    return base64.b64decode(s.encode())


def canonical(obj) -> bytes:
    """Deterministic JSON encoding used for every signature."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


# ───────────────────────── key management ─────────────────────────
def generate_keypair(kind: str):
    if kind == "ed25519":
        return ed25519.Ed25519PrivateKey.generate()
    return rsa.generate_private_key(public_exponent=65537, key_size=RSA_BITS)


def save_private(key, path, passphrase: str):
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.BestAvailableEncryption(passphrase.encode()))
    with open(path, "wb") as f:
        f.write(pem)


def save_public(pub, path):
    with open(path, "wb") as f:
        f.write(pub.public_bytes(serialization.Encoding.PEM,
                                 serialization.PublicFormat.SubjectPublicKeyInfo))


def load_private(path, passphrase: str):
    with open(path, "rb") as f:
        data = f.read()
    try:
        return serialization.load_pem_private_key(data, password=passphrase.encode())
    except (ValueError, TypeError):
        raise PermissionError("Wrong passphrase - private key could not be unlocked.")


def load_public(path):
    with open(path, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def fingerprint(pub) -> str:
    der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    h = hashlib.sha256(der).hexdigest()[:32].upper()
    return ":".join(h[i:i + 4] for i in range(0, len(h), 4))


def ensure_keys(key_dir: str):
    """Create the three role key pairs on first run."""
    os.makedirs(key_dir, exist_ok=True)
    for role, kind in ROLES.items():
        priv_p = os.path.join(key_dir, f"{role}_private.pem")
        pub_p = os.path.join(key_dir, f"{role}_public.pem")
        if not os.path.exists(priv_p):
            k = generate_keypair(kind)
            save_private(k, priv_p, DEFAULT_PASSPHRASES[role])
            save_public(k.public_key(), pub_p)


# ───────────────────────── primitives ─────────────────────────
def sign(priv, data: bytes) -> bytes:
    if isinstance(priv, ed25519.Ed25519PrivateKey):
        return priv.sign(data)
    return priv.sign(data, PSS, hashes.SHA256())


def verify(pub, sig: bytes, data: bytes) -> bool:
    try:
        if isinstance(pub, ed25519.Ed25519PublicKey):
            pub.verify(sig, data)
        else:
            pub.verify(sig, data, PSS, hashes.SHA256())
        return True
    except InvalidSignature:
        return False


def rsa_encrypt(pub, data: bytes) -> bytes:
    return pub.encrypt(data, OAEP)


def rsa_decrypt(priv, data: bytes) -> bytes:
    return priv.decrypt(data, OAEP)


def aes_encrypt(key: bytes, plaintext: bytes, aad: bytes):
    nonce = os.urandom(12)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, aad)


def aes_decrypt(key: bytes, nonce: bytes, ct: bytes, aad: bytes) -> bytes:
    return AESGCM(key).decrypt(nonce, ct, aad)


def xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def split_key(key: bytes):
    """2-of-2 secret split: key = s1 XOR s2. Either share alone reveals nothing."""
    s1 = os.urandom(len(key))
    return s1, xor(key, s1)
