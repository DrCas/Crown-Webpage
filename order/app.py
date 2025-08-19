import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session

BASE_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)
JOBS_FILE = DATA_DIR / "jobs.json"

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(PROJECT_ROOT / "static"),
    static_url_path="/static",
)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

ADMIN_USER = os.environ.get("CROWN_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("CROWN_ADMIN_PASS", "password123")

from pricing import PRICING, MODIFIERS, calculate_price

def load_jobs():
    if JOBS_FILE.exists():
        try:
            return json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_jobs(jobs):
    JOBS_FILE.write_text(json.dumps(jobs, indent=2), encoding="utf-8")

@app.template_filter("money")
def money_filter(v):
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return v

# ------------------------- ORDER LANDING -------------------------
@app.get("/order")
def order_home():
    # Landing with two options (Quick Order, Proof Request)
    return render_template("order_home.html")

# ------------------------- QUICK ORDER --------------------------
@app.get("/order/quick")
def quick_order():
    return render_template("quick_order.html", PRICING=PRICING, MODIFIERS=MODIFIERS)

@app.post("/order/quick/review")
def quick_review():
    form = request.form
    try:
        product = form["product"]
        size = form["size"]
        quantity = int(form.get("quantity", "0"))
        paper = form.get("paper", "standard")
        color = form.get("color", "full_color")
        sides = form.get("sides", "single")
        turnaround = form.get("turnaround", "standard")
    except KeyError:
        flash("Missing fields. Please complete the form.", "error")
        return redirect(url_for("quick_order"))

    opts = {"paper": paper, "color": color, "sides": sides, "turnaround": turnaround}
    total = calculate_price(product, size, quantity, opts)
    quote = dict(product=product, size=size, quantity=quantity, total=total, **opts)
    return render_template("quick_review.html", quote=quote)

@app.post("/order/quick/submit")
def quick_submit():
    form = request.form
    product = form["product"]
    size = form["size"]
    quantity = int(form["quantity"])
    opts = {
        "paper": form.get("paper", "standard"),
        "color": form.get("color", "full_color"),
        "sides": form.get("sides", "single"),
        "turnaround": form.get("turnaround", "standard"),
    }
    total = calculate_price(product, size, quantity, opts)

    job = {
        "id": uuid.uuid4().hex[:10].upper(),
        "type": "quick_order",
        "status": "submitted",
        "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "product": product,
        "size": size,
        "quantity": quantity,
        "total": total,
        "options": opts,
        "customer": {"name": "Quick Order", "email": ""},
        "files": [],
        "notes": "",
    }
    jobs = load_jobs()
    jobs.append(job)
    save_jobs(jobs)
    return render_template("quick_success.html", job=job)

# ------------------------- PROOF REQUEST ------------------------
@app.get("/order/proof")
def proof_request():
    return render_template("proof_request.html")

@app.post("/order/proof/submit")
def proof_submit():
    form = request.form
    files = request.files.getlist("files")
    saved = []
    for f in files:
        if not f or not getattr(f, "filename", ""):
            continue
        name = f"{uuid.uuid4().hex[:8]}_{f.filename}"
        dest = UPLOAD_DIR / name
        f.save(dest)
        saved.append(name)

    job = {
        "id": uuid.uuid4().hex[:10].upper(),
        "type": "proof_request",
        "status": "awaiting-proof",
        "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "customer": {
            "name": form.get("customer_name", ""),
            "email": form.get("customer_email", ""),
            "phone": form.get("phone", ""),
        },
        "project": form.get("project", ""),
        "specs": form.get("specs", ""),
        "files": saved,
        "notes": "",
    }
    jobs = load_jobs()
    jobs.append(job)
    save_jobs(jobs)
    return render_template("proof_success.html", job=job)

# ------------------------------ ADMIN --------------------------
@app.get("/order/admin")
def admin_dashboard():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    jobs = load_jobs()
    jobs = sorted(jobs, key=lambda j: j.get("created_at", ""), reverse=True)
    return render_template("admin_dashboard.html", jobs=jobs)

@app.get("/order/admin/login")
def admin_login():
    return render_template("admin_login.html")

@app.post("/order/admin/login")
def admin_login_post():
    user = request.form.get("username", "")
    pw = request.form.get("password", "")
    if user == ADMIN_USER and pw == ADMIN_PASS:
        session["is_admin"] = True
        return redirect(url_for("admin_dashboard"))
    flash("Invalid credentials", "error")
    return redirect(url_for("admin_login"))

@app.get("/order/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Logged out", "info")
    return redirect(url_for("admin_login"))

@app.get("/order/admin/jobs/<job_id>")
def admin_order(job_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    jobs = load_jobs()
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job:
        flash("Order not found.", "error")
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_order.html", job=job)

if __name__ == "__main__":
    app.run(debug=True)
