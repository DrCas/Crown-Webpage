import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, send_from_directory, session, abort
)

BASE_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = BASE_DIR.parent  # CROWN-WEBPAGE/
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

JOBS_FILE = DATA_DIR / "jobs.json"

# --- Flask app ---------------------------------------------------------------
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# --- Admin (demo credentials; change for prod) -------------------------------
ADMIN_USER = os.environ.get("CROWN_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("CROWN_ADMIN_PASS", "password123")

# --- Pricing helpers ---------------------------------------------------------
from pricing import PRICING, MODIFIERS, calculate_price  # noqa: E402

# --- Persistence -------------------------------------------------------------
def load_jobs():
    if JOBS_FILE.exists():
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_jobs(jobs):
    with open(JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)

# --- Filters -----------------------------------------------------------------
@app.template_filter("money")
def money_filter(v):
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return v

# --- Root site pages (outside /order/templates) ------------------------------
def _send_root_page(fname: str):
    path = PROJECT_ROOT / fname
    if not path.exists():
        abort(404)
    # Render these with the /order/templates/base.html chrome for consistency:
    # We read the raw HTML and drop it into a base slot.
    with open(path, "r", encoding="utf-8") as f:
        body = f.read()
    return render_template("index.html", raw_page=body, PRICING=PRICING)  # reuse index shell

@app.get("/")
def root_index():
    return _send_root_page("index.html")

@app.get("/about")
def root_about():
    return _send_root_page("about.html")

@app.get("/contact")
def root_contact():
    return _send_root_page("contact.html")

@app.get("/portfolio")
def root_portfolio():
    return _send_root_page("portfolio.html")

# --- Quick Order -------------------------------------------------------------
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

    return render_template(
        "quick_review.html",
        quote={
            "product": product, "size": size, "quantity": quantity,
            **opts, "total": total
        },
        PRICING=PRICING, MODIFIERS=MODIFIERS
    )

@app.post("/order/quick/submit")
def quick_submit():
    f = request.form
    job = {
        "id": str(uuid.uuid4()),
        "type": "quick_order",
        "status": "print-ready",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "customer": {
            "name": f.get("customer_name", "").strip(),
            "email": f.get("customer_email", "").strip()
        },
        "product": f.get("product"),
        "size": f.get("size"),
        "quantity": int(f.get("quantity", "0")),
        "options": {
            "paper": f.get("paper", "standard"),
            "color": f.get("color", "full_color"),
            "sides": f.get("sides", "single"),
            "turnaround": f.get("turnaround", "standard"),
        },
        "total": float(f.get("total", "0")),
        "notes": f.get("notes", "").strip(),
        "files": []
    }

    jobs = load_jobs()
    jobs.append(job)
    save_jobs(jobs)
    return render_template("quick_success.html", job=job)

# --- Proof Request ------------------------------------------------------------
@app.get("/order/proof")
def proof_request():
    return render_template("proof_request.html")

@app.post("/order/proof/review")
def proof_review():
    f = request.form
    files = request.files.getlist("files")
    temp_names = []
    for file in files:
        if not file or not file.filename:
            continue
        safe = f"tmp_{uuid.uuid4()}_{file.filename.replace(' ', '_')}"
        path = UPLOAD_DIR / safe
        file.save(path)
        temp_names.append(safe)

    # keep temporary names in session for final submission
    session["proof_tmp_files"] = temp_names

    data = {
        "customer_name": f.get("customer_name", "").strip(),
        "customer_email": f.get("customer_email", "").strip(),
        "phone": f.get("phone", "").strip(),
        "project": f.get("project", "").strip(),
        "specs": f.get("specs", "").strip(),
        "files": temp_names,
    }
    return render_template("proof_review.html", data=data)

@app.post("/order/proof/submit")
def proof_submit():
    f = request.form
    tmp_files = session.pop("proof_tmp_files", [])
    # rename tmp_ files to final names
    final_files = []
    for name in tmp_files:
        src = UPLOAD_DIR / name
        if src.exists():
            final_name = name.replace("tmp_", "", 1)
            src.rename(UPLOAD_DIR / final_name)
            final_files.append(final_name)

    job = {
        "id": str(uuid.uuid4()),
        "type": "proof_request",
        "status": "needs-proof",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "customer": {
            "name": f.get("customer_name", "").strip(),
            "email": f.get("customer_email", "").strip(),
            "phone": f.get("phone", "").strip(),
        },
        "project": f.get("project", "").strip(),
        "specs": f.get("specs", "").strip(),
        "files": final_files
    }
    jobs = load_jobs()
    jobs.append(job)
    save_jobs(jobs)
    return render_template("proof_success.html", job=job)

# --- Request Change (customer-facing) ----------------------------------------
@app.get("/order/request-change/<job_id>")
def request_change(job_id):
    return render_template("request_change.html", job_id=job_id)

@app.post("/order/request-change/<job_id>")
def submit_change(job_id):
    change_notes = request.form.get("change_notes", "").strip()
    jobs = load_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        flash("Order not found.", "error")
        return redirect(url_for("root_index"))
    # append a changes list
    job.setdefault("changes", [])
    job["changes"].append({
        "note": change_notes,
        "created_at": datetime.now().isoformat(timespec="seconds")
    })
    save_jobs(jobs)
    flash("Thanks! Your change request was recorded.", "success")
    return redirect(url_for("root_index"))

# --- Admin -------------------------------------------------------------------
def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin_ok"):
            return redirect(url_for("admin_login"))
        return fn(*a, **kw)
    return wrapper

@app.get("/order/admin/login")
def admin_login():
    return render_template("admin_login.html")

@app.post("/order/admin/login")
def admin_login_post():
    user = request.form.get("username", "")
    pw = request.form.get("password", "")
    if user == ADMIN_USER and pw == ADMIN_PASS:
        session["admin_ok"] = True
        return redirect(url_for("admin_dashboard"))
    flash("Invalid credentials.", "error")
    return redirect(url_for("admin_login"))

@app.get("/order/admin/logout")
def admin_logout():
    session.pop("admin_ok", None)
    flash("Logged out.", "success")
    return redirect(url_for("admin_login"))

@app.get("/order/admin")
@login_required
def admin_dashboard():
    jobs = load_jobs()
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return render_template("admin_dashboard.html", jobs=jobs)

@app.get("/order/admin/jobs/<job_id>")
@login_required
def admin_order(job_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        flash("Order not found.", "error")
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_order.html", job=job)

# --- Upload serving ----------------------------------------------------------
@app.get("/order/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False)

# --- Dev entry ---------------------------------------------------------------
if __name__ == "__main__":
    # FLASK_APP=order.app flask run --debug   (from project root), or:
    app.run(debug=True)
