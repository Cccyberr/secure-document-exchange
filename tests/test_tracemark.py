"""Run:  python -m pytest -v"""
import io, json, os, sys
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tracemark import crypto_core as cc, lsb, robust_wm, phash as ph, provenance as pv, samples, genai

IDENTITY = {"account_id": "PF-1", "username": "tester", "upload_ip": "10.0.0.1"}


@pytest.fixture(scope="session")
def kr(tmp_path_factory):
    return pv.Keyring(str(tmp_path_factory.mktemp("keys")))


@pytest.fixture(scope="session")
def imgs(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("samples"))
    return {n: Image.open(os.path.join(d, n)).convert("RGB") for n in samples.ensure(d)}


@pytest.fixture(scope="session")
def tagged(kr, imgs):
    reg = {}
    img, env, rid = pv.tag_image(kr, genai.generate(imgs["sunset.png"], "cinematic"), IDENTITY)
    reg[f"{rid:016x}"] = env
    return img, env, rid, reg


def jpeg(img, q):
    b = io.BytesIO(); img.save(b, "JPEG", quality=q); return Image.open(io.BytesIO(b.getvalue())).convert("RGB")


# ── primitives ──
def test_signature_roundtrip_and_tamper(kr):
    msg = b"provenance"
    sig = cc.sign(kr.platform_priv, msg)
    assert cc.verify(kr.platform_pub, sig, msg)
    assert not cc.verify(kr.platform_pub, sig, msg + b"!")


def test_rsa_oaep_roundtrip(kr):
    priv = kr.private("police", cc.DEFAULT_PASSPHRASES["police"])
    assert cc.rsa_decrypt(priv, cc.rsa_encrypt(kr.police_pub, b"k" * 32)) == b"k" * 32


def test_wrong_passphrase_rejected(kr):
    with pytest.raises(PermissionError):
        kr.private("police", "not-the-password")


def test_key_split_needs_both_shares():
    k = os.urandom(32); s1, s2 = cc.split_key(k)
    assert cc.xor(s1, s2) == k and s1 != k and s2 != k


def test_lsb_roundtrip_and_absent(imgs):
    payload = os.urandom(1500)
    assert lsb.extract(lsb.embed(imgs["city.png"], payload)) == payload
    assert lsb.extract(imgs["city.png"]) is None


def test_lsb_capacity_error():
    with pytest.raises(ValueError):
        lsb.embed(Image.new("RGB", (20, 20)), os.urandom(5000))


@pytest.mark.parametrize("name", ["sunset.png", "ocean.png", "city.png", "forest.png"])
def test_robust_watermark_survives_whatsapp_jpeg(imgs, name):
    rid = 0x0123456789ABCDEF
    marked = robust_wm.embed(imgs[name], rid)
    assert robust_wm.extract(jpeg(marked, 60))[0] == rid


def test_robust_watermark_absent_on_clean(imgs):
    assert all(robust_wm.extract(im)[0] is None for im in imgs.values())


def test_phash_similarity(imgs):
    a = ph.phash(imgs["ocean.png"])
    assert ph.hamming(a, ph.phash(jpeg(imgs["ocean.png"], 50))) <= pv.PHASH_MATCH_MAX
    assert ph.hamming(a, ph.phash(imgs["city.png"])) > pv.PHASH_MATCH_MAX


# ── protocol ──
def test_genuine_tag_verifies(kr, tagged):
    img, env, rid, reg = tagged
    r = pv.analyze(kr, img, reg.get)
    assert r["verdict"] == "AI_GENERATED"
    assert "username" not in json.dumps(r["envelope"]["pub"])     # identity never public


def test_tag_recovered_after_whatsapp_forward(kr, tagged):
    img, env, rid, reg = tagged
    r = pv.analyze(kr, jpeg(img, 60), reg.get)
    assert r["verdict"] == "AI_GENERATED" and "registry" in r["source"]


def test_untagged_image(kr, imgs):
    assert pv.analyze(kr, imgs["forest.png"], {}.get)["verdict"] == "NO_TAG"


def test_forged_tag_rejected(kr, imgs):
    attacker = cc.generate_keypair("ed25519")
    img, _, _ = pv.tag_image(kr, imgs["city.png"], {"username": "victim"}, signing_key=attacker)
    assert pv.analyze(kr, img, {}.get)["verdict"] == "FORGED"


def test_modified_label_rejected(kr, tagged):
    img, env, rid, reg = tagged
    bad = json.loads(json.dumps(env)); bad["pub"]["label"] = "REAL PHOTO"
    assert pv.analyze(kr, lsb.embed(img, cc.canonical(bad)), {}.get)["verdict"] == "FORGED"


def test_transplanted_tag_detected(kr, tagged, imgs):
    img, env, rid, reg = tagged
    other = lsb.embed(imgs["city.png"], cc.canonical(env))
    assert pv.analyze(kr, other, reg.get)["verdict"] == "TRANSPLANTED"


def test_police_alone_cannot_unmask(kr, tagged):
    _, env, _, _ = tagged
    with pytest.raises(Exception):
        pv.police_only_attempt(kr, kr.private("police", "police@123"), env)


def test_full_warrant_flow_unmasks(kr, tagged):
    _, env, _, _ = tagged
    w = pv.issue_warrant(kr, kr.private("court", "court@123"), env, 1, "Judge", "reason")
    assert pv.verify_warrant(kr, w)
    ident = pv.unmask(kr, kr.private("police", "police@123"), env, w)
    assert ident == IDENTITY


def test_fake_warrant_rejected(kr, tagged):
    _, env, _, _ = tagged
    w = pv.issue_warrant(kr, kr.private("court", "court@123"), env, 1, "Judge", "reason")
    w["court_sig"] = cc.b64e(cc.sign(cc.generate_keypair("rsa"), cc.canonical(w["order"])))
    with pytest.raises(ValueError):
        pv.unmask(kr, kr.private("police", "police@123"), env, w)


def test_warrant_for_other_record_rejected(kr, tagged, imgs):
    _, env, _, _ = tagged
    _, env2, _ = pv.tag_image(kr, imgs["ocean.png"], {"username": "someone else"})
    w = pv.issue_warrant(kr, kr.private("court", "court@123"), env2, 1, "Judge", "reason")
    with pytest.raises(ValueError):
        pv.unmask(kr, kr.private("police", "police@123"), env, w)


def test_identity_bound_to_public_part(kr, tagged):
    """Swapping the public part (AAD) makes AES-GCM decryption fail even with a valid warrant."""
    _, env, _, _ = tagged
    w = pv.issue_warrant(kr, kr.private("court", "court@123"), env, 1, "J", "r")
    pol = kr.private("police", "police@123")
    s1 = cc.rsa_decrypt(pol, cc.b64d(env["sealed"]["police_share"]))
    s2 = cc.rsa_decrypt(pol, cc.b64d(w["order"]["share_for_police"]))
    fake_pub = dict(env["pub"], created_at="2000-01-01")
    with pytest.raises(Exception):
        cc.aes_decrypt(cc.xor(s1, s2), cc.b64d(env["sealed"]["nonce"]), cc.b64d(env["sealed"]["ct"]),
                       aad=cc.canonical(fake_pub))


def test_web_app_end_to_end(tmp_path):
    import app as A
    a = A.create_app(data_dir=str(tmp_path / "d"), key_dir=str(tmp_path / "k"))
    c = a.test_client()
    assert c.post("/platform", data={"account": "PF-10231", "prompt": "t", "style": "oil",
                                     "sample": "ocean.png"}).status_code == 200
    c.post("/platform/share/1", data={"handle": "anon"})
    c.post("/feed/1/forward")
    c.post("/feed/2/report", data={"complainant": "v", "complaint": "c"})
    assert b"VERIFIED AI-GENERATED" in c.get("/police/case/1").data
    c.post("/police/case/1/warrant", data={"reason": "r"})
    c.post("/court/1/approve", data={"passphrase": "court@123", "judge": "J"})
    r = c.post("/police/case/1/unmask", data={"passphrase": "police@123"}, follow_redirects=True)
    assert b"Creator identified" in r.data
