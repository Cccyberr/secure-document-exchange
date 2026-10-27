import io, json, os, queue, secrets, threading, time
from datetime import datetime

from flask import (Flask, Response, abort, flash, redirect, render_template, request,
                   send_from_directory, url_for)
from PIL import Image, ImageEnhance, ImageFilter

from tracemark import crypto_core as cc
from tracemark import genai, lsb, metrics, provenance as pv, robust_wm, samples
from tracemark.store import Store, now

BASE = os.path.dirname(os.path.abspath(__file__))


# ───────────────────────── live events (Server-Sent Events) ─────────────────────────
class Bus:
    def __init__(self):
        self.subs, self.lock = [], threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=50)
        with self.lock:
            self.subs.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

    def publish(self, kind, text):
        msg = json.dumps({"kind": kind, "text": text, "t": time.time()})
        with self.lock:
            for q in list(self.subs):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass


# ───────────────────────── image helpers ─────────────────────────
def load_img(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def to_png(img) -> bytes:
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()


def to_jpeg(img, q) -> bytes:
    b = io.BytesIO(); img.save(b, "JPEG", quality=q); return b.getvalue()


def whatsapp_forward(img):
    """Simulates WhatsApp/Instagram upload: resize to <=1280 px, strip metadata, JPEG q≈60."""
    w, h = img.size
    s = min(1.0, 1280 / max(w, h))
    if s < 1:
        img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    return to_jpeg(img, 60), "jpg"


def screenshot_repost(img):
    """Simulates a screenshot of the post, slightly scaled and re-encoded."""
    w, h = img.size
    return to_jpeg(img.resize((int(w * 0.8), int(h * 0.8)), Image.BILINEAR), 85), "jpg"


TRANSFORMS = [
    ("Original PNG (lossless copy)", lambda im: im),
    ("JPEG quality 95", lambda im: load_img(to_jpeg(im, 95))),
    ("JPEG quality 80", lambda im: load_img(to_jpeg(im, 80))),
    ("WhatsApp forward (≤1280px, JPEG 60)", lambda im: load_img(whatsapp_forward(im)[0])),
    ("JPEG quality 50", lambda im: load_img(to_jpeg(im, 50))),
    ("JPEG quality 30", lambda im: load_img(to_jpeg(im, 30))),
    ("Screenshot & repost (80%, JPEG 85)", lambda im: load_img(screenshot_repost(im)[0])),
    ("Upscale 150%", lambda im: im.resize((int(im.width * 1.5), int(im.height * 1.5)), Image.BICUBIC)),
    ("Downscale 50%", lambda im: im.resize((im.width // 2, im.height // 2), Image.BILINEAR)),
    ("Downscale 50% + JPEG 70", lambda im: load_img(to_jpeg(im.resize((im.width // 2, im.height // 2)), 70))),
    ("Brightness +15%", lambda im: ImageEnhance.Brightness(im).enhance(1.15)),
    ("Gaussian blur r=1", lambda im: im.filter(ImageFilter.GaussianBlur(1))),
    ("Crop 10% borders", lambda im: im.crop((im.width // 20, im.height // 20, im.width * 19 // 20, im.height * 19 // 20))),
    ("Rotate 2°", lambda im: im.rotate(2, resample=Image.BICUBIC)),
]


def create_app(data_dir=None, key_dir=None):
    app = Flask(__name__)
    app.secret_key = os.environ.get("TRACEMARK_SECRET", secrets.token_hex(16))
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    data_dir = data_dir or os.path.join(BASE, "data")
    key_dir = key_dir or os.path.join(BASE, "keys")
    store = Store(data_dir)
    kr = pv.Keyring(key_dir)
    bus = Bus()
    sample_dir = os.path.join(BASE, "static", "samples")
    sample_names = samples.ensure(sample_dir)
    app.extensions.update(store=store, kr=kr, bus=bus)

    def analyze_bytes(data: bytes):
        return pv.analyze(kr, load_img(data), store.lookup)

    def input_image():
        f = request.files.get("image")
        if f and f.filename:
            return f.read()
        s = request.form.get("sample")
        if s in sample_names:
            with open(os.path.join(sample_dir, s), "rb") as fh:
                return fh.read()
        pid = request.form.get("post_id")
        if pid:
            p = store.q("SELECT * FROM posts WHERE id=?", (pid,), one=True)
            if p:
                return store.read_image(p["file"])
        return None

    @app.context_processor
    def inject():
        pending = store.q("SELECT COUNT(*) n FROM warrants WHERE status='PENDING'", one=True)["n"]
        open_cases = store.q("SELECT COUNT(*) n FROM cases WHERE status NOT IN ('IDENTIFIED','CLOSED')", one=True)["n"]
        return {"nav_pending": pending, "nav_cases": open_cases, "samples": sample_names,
                "ID_ORDER": ["full_name", "username", "account_id", "phone", "email", "upload_ip", "ip_geolocation",
                             "registered_city", "device", "account_created", "session_id", "prompt", "generated_at"]}

    @app.template_filter("fromjson")
    def fromjson(s):
        return json.loads(s) if s else None

    # ─────────── general ───────────
    @app.route("/")
    def home():
        stats = {t: store.q(f"SELECT COUNT(*) n FROM {t}", one=True)["n"]
                 for t in ("generations", "posts", "cases", "warrants")}
        return render_template("home.html", stats=stats)

    @app.route("/img/<path:name>")
    def img(name):
        return send_from_directory(store.img_dir, name)

    @app.route("/keys")
    def keys():
        return render_template("keys.html", keys=kr.info())

    @app.route("/admin/reset", methods=["POST"])
    def reset():
        store.reset()
        bus.publish("reset", "Demo data cleared")
        flash("Demo data cleared (keys kept).", "ok")
        return redirect(url_for("home"))

    @app.route("/events")
    def events():
        q = bus.subscribe()

        def stream():
            try:
                yield "retry: 2000\n\n"
                while True:
                    try:
                        yield f"data: {q.get(timeout=15)}\n\n"
                    except queue.Empty:
                        yield ": ping\n\n"
            finally:
                bus.unsubscribe(q)
        return Response(stream(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ─────────── 1. AI platform ───────────
    @app.route("/platform", methods=["GET", "POST"])
    def platform():
        accounts = store.q("SELECT * FROM accounts")
        result = None
        if request.method == "POST":
            data = input_image()
            if not data:
                flash("Upload an image or pick a sample.", "err")
                return redirect(url_for("platform"))
            acc = store.q("SELECT * FROM accounts WHERE id=?", (request.form["account"],), one=True)
            prompt = request.form.get("prompt", "").strip() or "untitled"
            style = request.form.get("style", "cinematic")
            src = genai.fit(load_img(data))
            gen = genai.generate(src, style)
            identity = {
                "account_id": acc["id"], "username": acc["username"], "full_name": acc["full_name"],
                "phone": acc["phone"], "email": acc["email"], "registered_city": acc["city"],
                "upload_ip": acc["ip"], "ip_geolocation": acc["city"] + " (ISP lookup)",
                "device": acc["device"], "account_created": acc["signup"],
                "session_id": secrets.token_hex(6), "prompt": prompt, "generated_at": now(),
            }
            t0 = time.perf_counter()
            tagged, env, rid = pv.tag_image(kr, gen, identity)
            ms = (time.perf_counter() - t0) * 1000
            rid_hex = f"{rid:016x}"
            store.register(rid_hex, env)
            fname = store.save_image(f"gen_{rid_hex}.png", to_png(tagged))
            q = metrics.psnr(gen, tagged)
            gid = store.x("INSERT INTO generations (account_id,record_id,prompt,style,file,created_at,psnr) "
                          "VALUES (?,?,?,?,?,?,?)", (acc["id"], rid_hex, prompt, style, fname, now(), q))
            orig_name = store.save_image(f"gen_{rid_hex}_untagged.png", to_png(gen))
            result = {"gid": gid, "file": fname, "orig": orig_name, "env": env, "rid": rid_hex, "acc": acc,
                      "psnr": q, "ssim": metrics.ssim(gen, tagged), "ms": ms,
                      "env_bytes": len(cc.canonical(env)), "capacity": lsb.capacity(tagged)}
            bus.publish("generation", f"PixelForge: @{acc['username']} generated an image (record {rid_hex})")
        recent = store.q("SELECT g.*, a.username FROM generations g JOIN accounts a ON a.id=g.account_id "
                         "ORDER BY g.id DESC LIMIT 8")
        return render_template("platform.html", accounts=accounts, styles=genai.STYLES, result=result,
                               recent=recent)

    @app.route("/platform/share/<int:gid>", methods=["POST"])
    def share(gid):
        g = store.q("SELECT * FROM generations WHERE id=?", (gid,), one=True) or abort(404)
        handle = request.form.get("handle", "").strip().lstrip("@") or f"user_{secrets.token_hex(2)}"
        caption = request.form.get("caption", "").strip()
        pid = store.x("INSERT INTO posts (handle,caption,file,via,parent,created_at) VALUES (?,?,?,?,?,?)",
                      (handle, caption, g["file"], "Original upload (PNG)", None, now()))
        bus.publish("post", f"SocialSphere: @{handle} posted a new image (post #{pid})")
        flash(f"Posted to SocialSphere as @{handle}.", "ok")
        return redirect(url_for("feed") + f"#post-{pid}")

    # ─────────── 2. Social feed ───────────
    @app.route("/feed")
    def feed():
        posts = store.q("SELECT * FROM posts ORDER BY id DESC")
        return render_template("feed.html", posts=posts)

    @app.route("/feed/upload", methods=["POST"])
    def feed_upload():
        data = input_image()
        if not data:
            flash("Choose an image.", "err")
            return redirect(url_for("feed"))
        handle = request.form.get("handle", "").strip().lstrip("@") or "camera_user"
        name = store.save_image(f"post_{secrets.token_hex(5)}.jpg", to_jpeg(genai.fit(load_img(data)), 90))
        pid = store.x("INSERT INTO posts (handle,caption,file,via,parent,created_at) VALUES (?,?,?,?,?,?)",
                      (handle, request.form.get("caption", ""), name, "Direct camera upload", None, now()))
        bus.publish("post", f"SocialSphere: @{handle} posted a new image (post #{pid})")
        return redirect(url_for("feed") + f"#post-{pid}")

    @app.route("/feed/<int:pid>/<action>", methods=["POST"])
    def feed_action(pid, action):
        p = store.q("SELECT * FROM posts WHERE id=?", (pid,), one=True) or abort(404)
        if action in ("forward", "screenshot"):
            im = load_img(store.read_image(p["file"]))
            data, ext = whatsapp_forward(im) if action == "forward" else screenshot_repost(im)
            via = ("Forwarded via WhatsApp (re-compressed JPEG 60, metadata stripped)" if action == "forward"
                   else "Screenshot & re-post (scaled 80%, JPEG 85)")
            handle = request.form.get("handle", "").strip().lstrip("@") or f"fwd_{secrets.token_hex(2)}"
            name = store.save_image(f"post_{secrets.token_hex(5)}.{ext}", data)
            nid = store.x("INSERT INTO posts (handle,caption,file,via,parent,created_at) VALUES (?,?,?,?,?,?)",
                          (handle, p["caption"], name, via, pid, now()))
            bus.publish("post", f"SocialSphere: @{handle} re-shared post #{pid} → #{nid}")
            return redirect(url_for("feed") + f"#post-{nid}")
        if action == "report":
            cid = store.x("INSERT INTO cases (post_id,file,complainant,complaint,status,created_at,updated_at) "
                          "VALUES (?,?,?,?,?,?,?)",
                          (pid, p["file"], request.form.get("complainant", "Anonymous victim"),
                           request.form.get("complaint", "Morphed image of me is circulating."),
                           "NEW", now(), now()))
            bus.publish("case", f"Cyber Police: new complaint registered - Case #{cid}")
            flash(f"Complaint filed with Cyber Police as Case #{cid}.", "ok")
            return redirect(url_for("feed") + f"#post-{pid}")
        abort(404)

    # ─────────── 3. Public verifier ───────────
    @app.route("/verify", methods=["GET", "POST"])
    def verify():
        res, preview = None, None
        if request.method == "POST":
            data = input_image()
            if not data:
                flash("Upload an image or choose a post.", "err")
                return redirect(url_for("verify"))
            res = analyze_bytes(data)
            preview = "data:image;base64," + cc.b64e(data)
        posts = store.q("SELECT id, handle FROM posts ORDER BY id DESC")
        return render_template("verify.html", res=res, preview=preview, posts=posts)

    # ─────────── 4. Cyber Police ───────────
    @app.route("/police")
    def police():
        cases = store.q("SELECT * FROM cases ORDER BY id DESC")
        return render_template("police.html", cases=cases)

    @app.route("/police/upload", methods=["POST"])
    def police_upload():
        data = input_image()
        if not data:
            flash("Upload the evidence image.", "err")
            return redirect(url_for("police"))
        name = store.save_image(f"evidence_{secrets.token_hex(5)}.png", data)
        cid = store.x("INSERT INTO cases (post_id,file,complainant,complaint,status,created_at,updated_at) "
                      "VALUES (?,?,?,?,?,?,?)", (None, name, request.form.get("complainant", "Walk-in complaint"),
                                                 request.form.get("complaint", ""), "NEW", now(), now()))
        bus.publish("case", f"Cyber Police: new complaint registered - Case #{cid}")
        return redirect(url_for("case", cid=cid))

    @app.route("/police/case/<int:cid>")
    def case(cid):
        c = store.q("SELECT * FROM cases WHERE id=?", (cid,), one=True) or abort(404)
        if not c["analysis"]:
            data = store.read_image(c["file"])
            res = analyze_bytes(data)
            res["evidence_sha256"] = pv.sha256(data)
            res["analysed_at"] = now()
            rid = res["envelope"]["pub"]["record_id"] if res["envelope"] else None
            status = "TAG_FOUND" if res["verdict"] == "AI_GENERATED" else "NO_VALID_TAG"
            store.x("UPDATE cases SET analysis=?, record_id=?, status=?, updated_at=? WHERE id=?",
                    (json.dumps(res), rid, status, now(), cid))
            c = store.q("SELECT * FROM cases WHERE id=?", (cid,), one=True)
        res = json.loads(c["analysis"])
        warrants = store.q("SELECT * FROM warrants WHERE case_id=? ORDER BY id DESC", (cid,))
        post = store.q("SELECT * FROM posts WHERE id=?", (c["post_id"],), one=True) if c["post_id"] else None
        return render_template("case.html", c=c, res=res, warrants=warrants, post=post,
                               identity=json.loads(c["identity"]) if c["identity"] else None)

    @app.route("/police/case/<int:cid>/warrant", methods=["POST"])
    def request_warrant(cid):
        c = store.q("SELECT * FROM cases WHERE id=?", (cid,), one=True) or abort(404)
        if not c["record_id"]:
            abort(400)
        wid = store.x("INSERT INTO warrants (case_id,record_id,reason,officer,status,created_at) VALUES (?,?,?,?,?,?)",
                      (cid, c["record_id"], request.form.get("reason", ""),
                       request.form.get("officer", "SI, Cyber Cell"), "PENDING", now()))
        store.x("UPDATE cases SET status='WARRANT_REQUESTED', updated_at=? WHERE id=?", (now(), cid))
        bus.publish("warrant", f"Court: warrant request #{wid} received for Case #{cid}")
        flash("Warrant request sent to the Court.", "ok")
        return redirect(url_for("case", cid=cid))

    @app.route("/police/case/<int:cid>/unmask", methods=["POST"])
    def unmask(cid):
        c = store.q("SELECT * FROM cases WHERE id=?", (cid,), one=True) or abort(404)
        env = json.loads(c["analysis"])["envelope"]
        try:
            police_priv = kr.private("police", request.form.get("passphrase", ""))
        except PermissionError as e:
            flash(str(e), "err")
            return redirect(url_for("case", cid=cid))
        w = store.q("SELECT * FROM warrants WHERE case_id=? AND status='APPROVED' ORDER BY id DESC",
                    (cid,), one=True)
        try:
            if not w:
                pv.police_only_attempt(kr, police_priv, env)
            identity = pv.unmask(kr, police_priv, env, json.loads(w["warrant"]))
        except Exception as e:
            msg = ("Decryption FAILED: the police key share alone cannot open the sealed identity "
                   "(AES-GCM authentication failed). A court warrant is required." if not w else f"Unmask failed: {e}")
            flash(msg, "err")
            return redirect(url_for("case", cid=cid))
        store.x("UPDATE cases SET identity=?, status='IDENTIFIED', updated_at=? WHERE id=?",
                (json.dumps(identity), now(), cid))
        bus.publish("case", f"Cyber Police: Case #{cid} - creator identified")
        return redirect(url_for("case", cid=cid) + "#identity")

    @app.route("/police/case/<int:cid>/report")
    def report(cid):
        c = store.q("SELECT * FROM cases WHERE id=?", (cid,), one=True) or abort(404)
        w = store.q("SELECT * FROM warrants WHERE case_id=? AND status='APPROVED' ORDER BY id DESC",
                    (cid,), one=True)
        return render_template("report.html", c=c, res=json.loads(c["analysis"] or "{}"),
                               identity=json.loads(c["identity"]) if c["identity"] else None,
                               w=w, warrant=json.loads(w["warrant"]) if w else None, keys=kr.info(),
                               generated=now())

    # ─────────── 5. Court ───────────
    @app.route("/court")
    def court():
        ws = store.q("SELECT w.*, c.complaint, c.complainant, c.file FROM warrants w JOIN cases c ON c.id=w.case_id "
                     "ORDER BY CASE w.status WHEN 'PENDING' THEN 0 ELSE 1 END, w.id DESC")
        return render_template("court.html", warrants=ws)

    @app.route("/court/<int:wid>/<decision>", methods=["POST"])
    def court_decide(wid, decision):
        w = store.q("SELECT * FROM warrants WHERE id=?", (wid,), one=True) or abort(404)
        judge = request.form.get("judge", "Judicial Magistrate")
        if decision == "reject":
            store.x("UPDATE warrants SET status='REJECTED', judge=?, decided_at=? WHERE id=?", (judge, now(), wid))
            store.x("UPDATE cases SET status='WARRANT_REJECTED', updated_at=? WHERE id=?", (now(), w["case_id"]))
            bus.publish("warrant", f"Court: warrant #{wid} REJECTED")
            return redirect(url_for("court"))
        try:
            court_priv = kr.private("court", request.form.get("passphrase", ""))
        except PermissionError as e:
            flash(str(e), "err")
            return redirect(url_for("court"))
        env = store.lookup(w["record_id"])
        if env is None:
            c = store.q("SELECT analysis FROM cases WHERE id=?", (w["case_id"],), one=True)
            env = json.loads(c["analysis"])["envelope"]
        warrant = pv.issue_warrant(kr, court_priv, env, w["case_id"], judge, w["reason"])
        store.x("UPDATE warrants SET status='APPROVED', warrant=?, judge=?, decided_at=? WHERE id=?",
                (json.dumps(warrant), judge, now(), wid))
        store.x("UPDATE cases SET status='WARRANT_APPROVED', updated_at=? WHERE id=?", (now(), w["case_id"]))
        bus.publish("warrant", f"Court: warrant {warrant['order']['warrant_id']} APPROVED for Case #{w['case_id']}")
        flash(f"Warrant {warrant['order']['warrant_id']} signed and released to Cyber Police.", "ok")
        return redirect(url_for("court"))

    # ─────────── 6. Attack lab ───────────
    @app.route("/lab", methods=["GET", "POST"])
    def lab():
        gens = store.q("SELECT g.id, g.record_id, g.prompt, a.username FROM generations g "
                       "JOIN accounts a ON a.id=g.account_id ORDER BY g.id DESC")
        out = None
        if request.method == "POST":
            g = store.q("SELECT * FROM generations WHERE id=?", (request.form.get("gid"),), one=True)
            if not g:
                flash("Generate an image on PixelForge first.", "err")
                return redirect(url_for("lab"))
            out = run_lab(g)
        return render_template("lab.html", gens=gens, out=out)

    def run_lab(g):
        tagged = load_img(store.read_image(g["file"]))
        env = store.lookup(g["record_id"])
        # the "other" picture = the sample that looks least like the tagged image
        from tracemark import phash as ph
        tp = ph.phash(tagged)
        cands = [(ph.hamming(tp, ph.phash(Image.open(os.path.join(sample_dir, n)))), n) for n in sample_names]
        other_name = max(cands)[1]
        other = Image.open(os.path.join(sample_dir, other_name)).convert("RGB")
        attacks = []

        # A1 forged tag with attacker's own key
        attacker = cc.generate_keypair("ed25519")
        fake_identity = {"username": "innocent_person", "full_name": "Framed Victim"}
        forged_img, _, _ = pv.tag_image(kr, other, fake_identity, signing_key=attacker)
        r = pv.analyze(kr, forged_img, store.lookup)
        attacks.append(("A1 · Forge a tag with attacker's own key (to frame someone)", r["verdict"],
                        r["verdict"] == "FORGED", "Ed25519 signature does not verify under PixelForge's public key."))

        # A2 transplant a genuine tag onto a different picture
        trans = lsb.embed(other, cc.canonical(env))
        r = pv.analyze(kr, trans, store.lookup)
        attacks.append(("A2 · Copy a genuine tag onto a different picture", r["verdict"],
                        r["verdict"] == "TRANSPLANTED",
                        f"Perceptual fingerprint distance {r.get('phash_distance')}/64 → tag does not belong here."))

        # A3 tamper with sealed identity ciphertext
        bad = json.loads(json.dumps(env))
        ct = bytearray(cc.b64d(bad["sealed"]["ct"])); ct[5] ^= 0xFF
        bad["sealed"]["ct"] = cc.b64e(bytes(ct))
        r = pv.analyze(kr, lsb.embed(tagged, cc.canonical(bad)), lambda _: None)
        attacks.append(("A3 · Modify the sealed identity inside the tag", r["verdict"], r["verdict"] == "FORGED",
                        "Any changed byte breaks the platform signature (and the AES-GCM tag)."))

        # A4 change public label (e.g. remove 'AI-GENERATED')
        bad2 = json.loads(json.dumps(env)); bad2["pub"]["label"] = "REAL PHOTO"
        r = pv.analyze(kr, lsb.embed(tagged, cc.canonical(bad2)), lambda _: None)
        attacks.append(("A4 · Edit the public label to 'REAL PHOTO'", r["verdict"], r["verdict"] == "FORGED",
                        "Label is covered by the signature."))

        # A5 police try to unmask without a warrant
        try:
            pv.police_only_attempt(kr, kr.private("police", cc.DEFAULT_PASSPHRASES["police"]), env)
            ok, v = False, "DECRYPTED (!)"
        except Exception:
            ok, v = True, "BLOCKED"
        attacks.append(("A5 · Police decrypt identity without a court warrant", v, ok,
                        "Police share s1 alone ≠ AES key (K = s1 ⊕ s2) → AES-GCM authentication fails."))

        # A6 forged warrant signed by attacker RSA key
        fake_court = cc.generate_keypair("rsa")
        fw = pv.issue_warrant(kr, kr.private("court", cc.DEFAULT_PASSPHRASES["court"]), env, 0, "x", "x")
        fw["court_sig"] = cc.b64e(cc.sign(fake_court, cc.canonical(fw["order"])))
        ok = not pv.verify_warrant(kr, fw)
        attacks.append(("A6 · Present a warrant not signed by the Court", "REJECTED" if ok else "ACCEPTED", ok,
                        "RSA-PSS signature checked against the Court's public key."))

        # A7 wrong passphrase on police private key
        try:
            kr.private("police", "guess123"); ok = False
        except PermissionError:
            ok = True
        attacks.append(("A7 · Steal police key file, guess passphrase", "BLOCKED" if ok else "OPENED", ok,
                        "Private keys are PKCS#8 PEM encrypted with a passphrase."))

        # Robustness table
        rows = []
        for name, fn in TRANSFORMS:
            im = fn(tagged)
            t0 = time.perf_counter()
            r = pv.analyze(kr, im, store.lookup)
            rows.append({"name": name, "lsb": lsb.extract(im) is not None,
                         "robust": robust_wm.extract(im)[0] == int(g["record_id"], 16),
                         "verdict": r["verdict"], "ms": (time.perf_counter() - t0) * 1000})
        return {"g": g, "attacks": attacks, "rows": rows, "other": other_name}

    return app


app = create_app()

if __name__ == "__main__":
    print("\n  TraceMark running →  http://127.0.0.1:5000\n")
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False, threaded=True)
