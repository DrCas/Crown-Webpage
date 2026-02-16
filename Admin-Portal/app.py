# Crown Admin Portal - Professional Estimate-Sheet Field Expansion
# - Adds pro estimate-sheet fields to Job
# - Adds JobLineItem table (normalized)
# - Adds Flask-Migrate (Alembic) for real migrations
# - Makes job_view view-only (edit happens in /jobs/<id>/edit)
# NOTE: This file is designed to be drop-in for your current Admin-Portal layout.
#       It intentionally keeps legacy fields (business_name, phone_number, etc.) for backward compatibility.

import os
import json
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
from sqlalchemy import text

from flask import Flask, render_template, request, redirect, url_for, flash, abort, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, login_required, logout_user, current_user,
)
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)
app.config["STATIC_VERSION"] = os.getenv("STATIC_VERSION", "1")
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

# Optional: where uploaded order files are stored (used by orders_api)
app.config["ORDER_UPLOAD_DIR"] = os.getenv("ORDER_UPLOAD_DIR", os.path.join(BASE_DIR, "uploads", "orders"))

# Template helper: parse JSON stored in DB (uploaded_files_json, etc.)
@app.template_filter("fromjson")
def _fromjson_filter(val):
    try:
        return json.loads(val) if val else None
    except Exception:
        return None

# Secure download endpoint for order uploads (admin-only)
@app.get("/uploads/orders/<path:filename>")
@login_required
def download_order_upload(filename):
    upload_dir = app.config.get("ORDER_UPLOAD_DIR")
    return send_from_directory(upload_dir, filename, as_attachment=True)


# DB
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "crown_portal.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize extensions
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

# -------------------- Template helpers --------------------
@app.template_filter("prettyjson")
def prettyjson_filter(value):
    # Kept for compatibility, but job_view no longer renders raw intake JSON.
    try:
        if value is None:
            return ""
        if isinstance(value, str):
            value = json.loads(value)
        return json.dumps(value, indent=2, ensure_ascii=False)
    except Exception:
        return str(value)

@app.template_filter("mmddyyyy_dt")
def mmddyyyy_dt(dt: datetime):
    if not dt:
        return ""
    return dt.strftime("%m-%d-%Y")

@app.template_filter("mmddyyyy_date")
def mmddyyyy_date(d: date):
    if not d:
        return ""
    return d.strftime("%m-%d-%Y")

def parse_mmddyyyy(value: str) -> date:
    """Accepts MM-DD-YYYY (preferred), also accepts MM/DD/YYYY."""
    if not value:
        raise ValueError("Empty date")
    value = value.strip().replace("/", "-")
    return datetime.strptime(value, "%m-%d-%Y").date()

def _parse_money(value: str | None) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        s = s.replace("$", "").replace(",", "")
        return float(Decimal(s))
    except (InvalidOperation, ValueError):
        return None

def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None

# ---- Progress stages ----
STAGES = ["Received", "Design", "Proof", "Production", "Install / Pickup", "Completed"]

@app.context_processor
def inject_globals():
    return {"STAGES": STAGES}

# -------------------- Models --------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="staff", nullable=False)  # "admin" or "staff"

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    def is_admin(self) -> bool:
        return self.role == "admin"


class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # -------------------- Legacy fields (keep) --------------------
    customer_name = db.Column(db.String(120), nullable=False)
    business_name = db.Column(db.String(120), nullable=True)
    phone_number = db.Column(db.String(40), nullable=True)
    email_address = db.Column(db.String(160), nullable=True)
    job_title = db.Column(db.String(140), nullable=False)
    job_summary = db.Column(db.String(240), nullable=True)
    job_details = db.Column(db.Text, nullable=True)
    quote_amount = db.Column(db.Float, nullable=True)

    received_date = db.Column(db.Date, nullable=False, default=date.today)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    stage = db.Column(db.String(40), default=STAGES[0], nullable=False)

    po_date_key = db.Column(db.String(6), nullable=False, index=True)  # MMDDYY
    po_seq = db.Column(db.Integer, nullable=False)  # 1..99

    # Website intake fields (used for idempotency / attachments / auto-fill)
    is_new = db.Column(db.Integer, default=1, nullable=False)  # 1 = new, 0 = reviewed
    source = db.Column(db.String(40), nullable=True)
    intake_order_id = db.Column(db.String(80), nullable=True, index=True)
    submission_json = db.Column(db.Text, nullable=True)
    uploaded_files_json = db.Column(db.Text, nullable=True)

    # -------------------- Estimate-sheet fields (new) --------------------
    address_1 = db.Column(db.String(160), nullable=True)
    address_2 = db.Column(db.String(160), nullable=True)
    city = db.Column(db.String(80), nullable=True)
    state = db.Column(db.String(40), nullable=True)
    zip_code = db.Column(db.String(20), nullable=True)

    cell = db.Column(db.String(40), nullable=True)

    completed_date = db.Column(db.Date, nullable=True)
    pickup_date = db.Column(db.Date, nullable=True)
    needed_by_date = db.Column(db.Date, nullable=True)
    approval_date = db.Column(db.Date, nullable=True)
    scheduled_date = db.Column(db.Date, nullable=True)
    inspected_date = db.Column(db.Date, nullable=True)
    inspected_by = db.Column(db.String(80), nullable=True)

    mfd_date = db.Column(db.Date, nullable=True)
    vehicle_make = db.Column(db.String(80), nullable=True)
    vehicle_model = db.Column(db.String(80), nullable=True)
    vin = db.Column(db.String(80), nullable=True)
    unit_number = db.Column(db.String(80), nullable=True)

    proof_number = db.Column(db.String(80), nullable=True)
    proof_approved_date = db.Column(db.Date, nullable=True)
    size_location_proof = db.Column(db.String(160), nullable=True)

    work_order = db.Column(db.String(80), nullable=True)
    crown_rep = db.Column(db.String(80), nullable=True)

    summary_of_work = db.Column(db.Text, nullable=True)
    internal_notes = db.Column(db.Text, nullable=True)

    shipping_date = db.Column(db.Date, nullable=True)
    shipping_type = db.Column(db.String(80), nullable=True)
    tracking_number = db.Column(db.String(120), nullable=True)
    ship_to = db.Column(db.Text, nullable=True)
    pickup_name = db.Column(db.String(120), nullable=True)
    field_service_location = db.Column(db.String(160), nullable=True)
    field_charge = db.Column(db.Float, nullable=True)

    materials_total = db.Column(db.Float, nullable=True)
    labor_total = db.Column(db.Float, nullable=True)
    tax_rate = db.Column(db.Float, nullable=True)  # percent (8.25)
    sales_tax = db.Column(db.Float, nullable=True)
    shipping_handling = db.Column(db.Float, nullable=True)
    grand_total = db.Column(db.Float, nullable=True)


class JobLineItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("job.id"), nullable=False, index=True)

    qty = db.Column(db.Integer, nullable=True)
    description = db.Column(db.Text, nullable=True)
    material_price = db.Column(db.Float, nullable=True)
    labor_price = db.Column(db.Float, nullable=True)
    line_total = db.Column(db.Float, nullable=True)

    job = db.relationship("Job", backref=db.backref("line_items", lazy=True, cascade="all, delete-orphan"))


class JobLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("job.id"), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    actor_username = db.Column(db.String(80), nullable=True)
    action = db.Column(db.String(40), nullable=False)
    details = db.Column(db.Text, nullable=True)

    job = db.relationship("Job", backref=db.backref("logs", lazy=True, order_by="desc(JobLog.timestamp)"))


# -------------------- Auth --------------------
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# -------------------- Helpers --------------------
def date_key_mmddyy(d: date) -> str:
    return d.strftime("%m%d%y")

def next_po_for_date(received: date) -> tuple[str, int]:
    key = date_key_mmddyy(received)
    max_seq = (
        db.session.query(db.func.max(Job.po_seq))
        .filter(Job.po_date_key == key)
        .scalar()
    )
    if not max_seq:
        return key, 1
    nxt = max_seq + 1
    if nxt > 99:
        nxt = 1
    return key, nxt

def po_display(job: Job) -> str:
    try:
        if not getattr(job, "po_date_key", None) or getattr(job, "po_seq", None) is None:
            return ""
        return f"{job.po_date_key}-{job.po_seq:02d}"
    except Exception:
        return ""

def job_display_name(job: Job) -> str:
    title = job.job_title or ""
    received = ""
    try:
        if getattr(job, "received_date", None):
            received = job.received_date.strftime("%m-%d-%Y")
    except Exception:
        received = ""
    po = ""
    try:
        po = po_display(job)
    except Exception:
        po = ""
    parts = [p for p in (title, received, po) if p]
    return " • ".join(parts)

def stage_index(job: Job) -> int:
    try:
        return STAGES.index(job.stage)
    except ValueError:
        return 0

def log_event(job_id: int, action: str, details: str | None = None):
    actor = current_user.username if current_user.is_authenticated else None
    entry = JobLog(job_id=job_id, actor_username=actor, action=action, details=details)
    db.session.add(entry)
    db.session.commit()

def admin_required():
    if not current_user.is_authenticated:
        return login_manager.unauthorized()
    if not getattr(current_user, "is_admin", lambda: False)():
        abort(403)

def _assign_job_fields_from_form(job: Job, form, *, creating: bool):
    customer_name = form.get("customer_name", "").strip()
    job_title = form.get("job_title", "").strip()
    if not customer_name or not job_title:
        raise ValueError("Customer Name and Job Title are required.")

    job.customer_name = customer_name
    job.business_name = form.get("business_name", "").strip() or None
    job.phone_number = form.get("phone_number", "").strip() or None
    job.cell = form.get("cell", "").strip() or None
    job.email_address = form.get("email_address", "").strip() or None

    job.address_1 = form.get("address_1", "").strip() or None
    job.address_2 = form.get("address_2", "").strip() or None
    job.city = form.get("city", "").strip() or None
    job.state = form.get("state", "").strip() or None
    job.zip_code = form.get("zip_code", "").strip() or None

    job.job_title = job_title
    job.job_summary = form.get("job_summary", "").strip() or None
    job.summary_of_work = form.get("summary_of_work", "").strip() or None
    job.job_details = form.get("job_details", "").strip() or None
    job.internal_notes = form.get("internal_notes", "").strip() or None

    def set_date(field_name: str, attr: str):
        raw = form.get(field_name, "").strip()
        if not raw:
            setattr(job, attr, None)
            return
        try:
            setattr(job, attr, parse_mmddyyyy(raw))
        except ValueError:
            raise ValueError(f"{field_name} must be in MM-DD-YYYY format.")

    received_raw = form.get("received_date", "").strip()
    if creating:
        received = parse_mmddyyyy(received_raw) if received_raw else date.today()
        job.received_date = received
    else:
        if received_raw:
            job.received_date = parse_mmddyyyy(received_raw)

    set_date("completed_date", "completed_date")
    set_date("pickup_date", "pickup_date")
    set_date("needed_by_date", "needed_by_date")
    set_date("approval_date", "approval_date")
    set_date("scheduled_date", "scheduled_date")
    set_date("inspected_date", "inspected_date")
    set_date("mfd_date", "mfd_date")
    set_date("proof_approved_date", "proof_approved_date")
    set_date("shipping_date", "shipping_date")

    job.inspected_by = form.get("inspected_by", "").strip() or None

    job.vehicle_make = form.get("vehicle_make", "").strip() or None
    job.vehicle_model = form.get("vehicle_model", "").strip() or None
    job.vin = form.get("vin", "").strip() or None
    job.unit_number = form.get("unit_number", "").strip() or None

    job.proof_number = form.get("proof_number", "").strip() or None
    job.size_location_proof = form.get("size_location_proof", "").strip() or None
    job.work_order = form.get("work_order", "").strip() or None
    job.crown_rep = form.get("crown_rep", "").strip() or None

    job.shipping_type = form.get("shipping_type", "").strip() or None
    job.tracking_number = form.get("tracking_number", "").strip() or None
    job.ship_to = form.get("ship_to", "").strip() or None
    job.pickup_name = form.get("pickup_name", "").strip() or None
    job.field_service_location = form.get("field_service_location", "").strip() or None

    job.quote_amount = _parse_money(form.get("quote_amount"))
    job.shipping_handling = _parse_money(form.get("shipping_handling"))
    job.field_charge = _parse_money(form.get("field_charge"))
    job.tax_rate = _parse_money(form.get("tax_rate"))
    job.sales_tax = _parse_money(form.get("sales_tax"))
    job.materials_total = _parse_money(form.get("materials_total"))
    job.labor_total = _parse_money(form.get("labor_total"))
    job.grand_total = _parse_money(form.get("grand_total"))

def _upsert_line_items(job: Job, form):
    JobLineItem.query.filter_by(job_id=job.id).delete()

    qty_list = form.getlist("item_qty[]")
    desc_list = form.getlist("item_desc[]")
    mat_list = form.getlist("item_material[]")
    lab_list = form.getlist("item_labor[]")

    materials_sum = 0.0
    labor_sum = 0.0

    rows = max(len(qty_list), len(desc_list), len(mat_list), len(lab_list))
    for i in range(rows):
        qty = _parse_int(qty_list[i]) if i < len(qty_list) else None
        desc = (desc_list[i].strip() if i < len(desc_list) else "") or None
        mat = _parse_money(mat_list[i]) if i < len(mat_list) else None
        lab = _parse_money(lab_list[i]) if i < len(lab_list) else None
        if not any([qty, desc, mat, lab]):
            continue
        line_total = (mat or 0.0) + (lab or 0.0)
        if mat: materials_sum += mat
        if lab: labor_sum += lab

        db.session.add(JobLineItem(
            job_id=job.id,
            qty=qty,
            description=desc,
            material_price=mat,
            labor_price=lab,
            line_total=line_total,
        ))

    if materials_sum > 0 and job.materials_total is None:
        job.materials_total = materials_sum
    if labor_sum > 0 and job.labor_total is None:
        job.labor_total = labor_sum

    pre_tax = materials_sum + labor_sum + (job.shipping_handling or 0.0) + (job.field_charge or 0.0)
    if job.tax_rate is not None and job.sales_tax is None:
        job.sales_tax = round(pre_tax * (job.tax_rate / 100.0), 2)
    if pre_tax > 0 and job.grand_total is None:
        job.grand_total = round(pre_tax + (job.sales_tax or 0.0), 2)

# -------------------- Blueprints --------------------
from orders_api import orders_api
app.register_blueprint(orders_api)

# -------------------- Routes --------------------
@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Invalid login.", "error")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    # Pagination
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 12, type=int)
    per_page = max(6, min(per_page, 36))

    query = Job.query.filter(Job.stage != "Completed").order_by(Job.received_date.desc(), Job.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        "dashboard.html",
        jobs=pagination.items,
        pagination=pagination,
        per_page=per_page,
        po_display=po_display,
        job_display_name=job_display_name,
        stage_index=stage_index,
    )

@app.route("/jobs/completed")
@login_required
def completed_jobs():
    jobs = (
        Job.query.filter(Job.stage == "Completed")
        .order_by(Job.received_date.desc(), Job.created_at.desc())
        .all()
    )
    return render_template("index.html", jobs=jobs, po_display=po_display, job_display_name=job_display_name)

@app.route("/jobs/new", methods=["GET", "POST"])
@login_required
def job_new():
    if request.method == "POST":
        try:
            received_raw = request.form.get("received_date", "").strip()
            received = parse_mmddyyyy(received_raw) if received_raw else date.today()
        except ValueError:
            flash("Date Received must be in MM-DD-YYYY format.", "error")
            return redirect(url_for("job_new"))

        po_key, po_seq = next_po_for_date(received)

        new_job = Job(
            received_date=received,
            po_date_key=po_key,
            po_seq=po_seq,
            stage=STAGES[0],
        )

        try:
            _assign_job_fields_from_form(new_job, request.form, creating=True)
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("job_new"))

        db.session.add(new_job)
        db.session.commit()

        _upsert_line_items(new_job, request.form)
        db.session.commit()

        log_event(new_job.id, "created", f"Created job {job_display_name(new_job)}")
        flash("Job created.", "success")
        return redirect(url_for("job_view", job_id=new_job.id))

    return render_template("job_new.html")

@app.route("/jobs/<int:job_id>", methods=["GET", "POST"])
@login_required
def job_view(job_id):
    job = Job.query.get_or_404(job_id)

    if job.is_new:
        job.is_new = 0
        db.session.commit()

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "update_stage":
            new_stage = request.form.get("stage", STAGES[0])
            if new_stage not in STAGES:
                flash("Invalid stage.", "error")
                return redirect(url_for("job_view", job_id=job.id))
            old = job.stage
            job.stage = new_stage
            db.session.commit()
            log_event(job.id, "stage_change", f"Stage changed: {old} → {new_stage}")
            if job.stage == "Completed":
                flash("Job marked Completed and moved to Completed list.", "success")
                return redirect(url_for("completed_jobs"))
            flash("Progress updated.", "success")
            return redirect(url_for("job_view", job_id=job.id))

        flash("Unknown action.", "error")
        return redirect(url_for("job_view", job_id=job.id))

    logs = []
    if current_user.is_admin():
        logs = JobLog.query.filter_by(job_id=job.id).order_by(JobLog.timestamp.desc()).all()

    idx = stage_index(job)
    progress_percent = int((idx / (len(STAGES) - 1)) * 100) if len(STAGES) > 1 else 0

    return render_template(
        "job_view.html",
        job=job,
        logs=logs,
        po_display=po_display,
        job_display_name=job_display_name,
        stage_index=stage_index,
    )

@app.route("/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@login_required
def job_edit(job_id):
    job = Job.query.get_or_404(job_id)

    if request.method == "POST":
        before_po = po_display(job)
        old_received = job.received_date

        try:
            _assign_job_fields_from_form(job, request.form, creating=False)
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("job_edit", job_id=job.id))

        if job.received_date != old_received:
            po_key, po_seq = next_po_for_date(job.received_date)
            job.po_date_key = po_key
            job.po_seq = po_seq

        _upsert_line_items(job, request.form)
        db.session.commit()

        after_po = po_display(job)
        detail = f"Edited job. PO {before_po} → {after_po}" if before_po != after_po else "Edited job."
        log_event(job.id, "edited", detail)

        flash("Job updated.", "success")
        return redirect(url_for("job_view", job_id=job.id))

    return render_template("job_edit.html", job=job, po_display=po_display)

# -------------------- Admin: User Management --------------------
@app.route("/users")
@login_required
def users():
    admin_required()
    users = User.query.order_by(User.role.desc(), User.username.asc()).all()
    return render_template("users.html", users=users)

@app.route("/users/new", methods=["GET", "POST"])
@login_required
def user_new():
    admin_required()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "staff").strip()
        if not username or not password:
            flash("Username and password required.", "error")
            return redirect(url_for("user_new"))
        if role not in ["admin", "staff"]:
            role = "staff"
        if User.query.filter_by(username=username).first():
            flash("That username already exists.", "error")
            return redirect(url_for("user_new"))
        u = User(username=username, role=role)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        flash("User created.", "success")
        return redirect(url_for("users"))
    return render_template("user_new.html")

@app.route("/users/<int:user_id>/reset-password", methods=["GET", "POST"])
@login_required
def user_reset_password(user_id):
    admin_required()
    user = User.query.get_or_404(user_id)
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        if not password:
            flash("Password required.", "error")
            return redirect(url_for("user_reset_password", user_id=user.id))
        user.set_password(password)
        db.session.commit()
        flash("Password reset.", "success")
        return redirect(url_for("users"))
    return render_template("user_reset_password.html", user=user)

@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def user_delete(user_id):
    admin_required()
    if current_user.id == user_id:
        flash("You can't delete yourself.", "error")
        return redirect(url_for("users"))
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash("User deleted.", "success")
    return redirect(url_for("users"))

@app.route("/jobs/<int:job_id>/delete", methods=["POST"])
@login_required
def job_delete(job_id):
    admin_required()
    job = Job.query.get_or_404(job_id)
    log_event(job.id, "deleted", f"Job deleted: {job_display_name(job)}")
    JobLog.query.filter_by(job_id=job.id).delete()
    JobLineItem.query.filter_by(job_id=job.id).delete()
    db.session.delete(job)
    db.session.commit()
    flash("Job deleted.", "success")
    return redirect(url_for("dashboard"))

# -------------------- One-time init --------------------
@app.route("/init-db")
def init_db():
    db.create_all()

    admin_user = os.getenv("ADMIN_USER", "admin")
    admin_pass = os.getenv("ADMIN_PASS", "admin123")
    existing = User.query.filter_by(username=admin_user).first()
    if not existing:
        u = User(username=admin_user, role="admin")
        u.set_password(admin_pass)
        db.session.add(u)
        db.session.commit()
        created_msg = f"DB initialized. Admin user created: {admin_user}"
    else:
        created_msg = "DB initialized. Admin user already exists."

    try:
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_job_intake_order_id ON job(intake_order_id);"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    return created_msg

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)