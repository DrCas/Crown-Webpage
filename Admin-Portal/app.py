import os
from datetime import datetime, date
from dotenv import load_dotenv

from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

from orders_api import orders_api
app.register_blueprint(orders_api)

# Optional: where uploaded order files are stored
app.config["ORDER_UPLOAD_DIR"] = "/mnt/ssd/crowngfx/uploads/orders"

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "crown_portal.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize extensions
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

# ---- Progress stages ----
STAGES = [
    "Received",
    "Design",
    "Proof",
    "Production",
    "Install / Pickup",
    "Completed",
]


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

    # Fields requested
    customer_name = db.Column(db.String(120), nullable=False)
    business_name = db.Column(db.String(120), nullable=True)

    phone_number = db.Column(db.String(40), nullable=True)
    email_address = db.Column(db.String(160), nullable=True)

    job_title = db.Column(db.String(140), nullable=False)
    job_summary = db.Column(db.String(240), nullable=True)
    job_details = db.Column(db.Text, nullable=True)

    quote_amount = db.Column(db.Float, nullable=True)

    # Dates: received is user-entered; created is system timestamp
    received_date = db.Column(db.Date, nullable=False, default=date.today)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    stage = db.Column(db.String(40), default=STAGES[0], nullable=False)

    # PO format: MMDDYY-## based on received_date
    po_date_key = db.Column(db.String(6), nullable=False, index=True)  # MMDDYY
    po_seq = db.Column(db.Integer, nullable=False)  # 1..99

    # Website intake fields
    is_new = db.Column(db.Integer, default=1, nullable=False)  # 1 = new, 0 = reviewed
    source = db.Column(db.String(40), nullable=True)  # "website", "phone", "email", etc.
    intake_order_id = db.Column(db.String(80), nullable=True, index=True)  # from website intake
    submission_json = db.Column(db.Text, nullable=True)  # full submission payload
    uploaded_files_json = db.Column(db.Text, nullable=True)  # JSON array of file paths


class JobLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("job.id"), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    actor_username = db.Column(db.String(80), nullable=True)  # who did it
    action = db.Column(db.String(40), nullable=False)         # created / edited / stage_change
    details = db.Column(db.Text, nullable=True)

    job = db.relationship("Job", backref=db.backref("logs", lazy=True, order_by="desc(JobLog.timestamp)"))


# -------------------- Auth --------------------
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# -------------------- Helpers --------------------
@app.context_processor
def inject_globals():
    return {"STAGES": STAGES}


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
    """
    Accepts MM-DD-YYYY (preferred), also accepts MM/DD/YYYY.
    """
    if not value:
        raise ValueError("Empty date")
    value = value.strip().replace("/", "-")
    return datetime.strptime(value, "%m-%d-%Y").date()


def date_key_mmddyy(d: date) -> str:
    return d.strftime("%m%d%y")


def next_po_for_date(received: date) -> tuple[str, int]:
    """
    Returns (po_date_key, po_seq) where po_seq is 1..99 and is per-day.
    Wraps back to 1 after 99.
    """
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
        nxt = 1  # reset (rare edge: if >99 in same day, you'd collide; we can upgrade to 3 digits later)
    return key, nxt


def po_display(job: Job) -> str:
    return f"{job.po_date_key}-{job.po_seq:02d}"


def job_display_name(job: Job) -> str:
    # Job Title • Date Received • PO
    return f"{job.job_title} • {job.received_date.strftime('%m-%d-%Y')} • {po_display(job)}"


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
    active_jobs = (
        Job.query.filter(Job.stage != "Completed")
        .order_by(Job.received_date.desc(), Job.created_at.desc())
        .all()
    )
    return render_template(
        "dashboard.html",
        jobs=active_jobs,
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
    return render_template(
        "index.html",
        jobs=jobs,
        po_display=po_display,
        job_display_name=job_display_name,
    )


@app.route("/jobs/new", methods=["GET", "POST"])
@login_required
def job_new():
    if request.method == "POST":
        customer_name = request.form.get("customer_name", "").strip()
        business_name = request.form.get("business_name", "").strip() or None

        phone_number = request.form.get("phone_number", "").strip() or None
        email_address = request.form.get("email_address", "").strip() or None

        job_title = request.form.get("job_title", "").strip()
        job_summary = request.form.get("job_summary", "").strip() or None
        job_details = request.form.get("job_details", "").strip() or None

        quote_amount_raw = request.form.get("quote_amount", "").strip()
        quote_amount = float(quote_amount_raw) if quote_amount_raw else None

        received_raw = request.form.get("received_date", "").strip()

        if not customer_name or not job_title:
            flash("Customer Name and Job Title are required.", "error")
            return redirect(url_for("job_new"))

        try:
            received = parse_mmddyyyy(received_raw) if received_raw else date.today()
        except ValueError:
            flash("Date Received must be in MM-DD-YYYY format.", "error")
            return redirect(url_for("job_new"))

        po_key, po_seq = next_po_for_date(received)

        new_job = Job(
            customer_name=customer_name,
            business_name=business_name,
            phone_number=phone_number,
            email_address=email_address,
            job_title=job_title,
            job_summary=job_summary,
            job_details=job_details,
            quote_amount=quote_amount,
            received_date=received,
            po_date_key=po_key,
            po_seq=po_seq,
            stage=STAGES[0],
        )

        db.session.add(new_job)
        db.session.commit()

        log_event(new_job.id, "created", f"Created job {job_display_name(new_job)}")

        flash("Job created.", "success")
        return redirect(url_for("job_view", job_id=new_job.id))

    return render_template("job_new.html")


@app.route("/jobs/<int:job_id>", methods=["GET", "POST"])
@login_required
def job_view(job_id):
    job = Job.query.get_or_404(job_id)

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

        if action == "save_edits":
            # Staff can edit fields, including Date Received (which impacts PO)
            customer_name = request.form.get("customer_name", "").strip()
            job_title = request.form.get("job_title", "").strip()

            if not customer_name or not job_title:
                flash("Customer Name and Job Title are required.", "error")
                return redirect(url_for("job_view", job_id=job.id))

            # Capture old snapshot for admin log
            before = {
                "customer_name": job.customer_name,
                "business_name": job.business_name,
                "phone_number": job.phone_number,
                "email_address": job.email_address,
                "job_title": job.job_title,
                "job_summary": job.job_summary,
                "job_details": job.job_details,
                "quote_amount": job.quote_amount,
                "received_date": job.received_date.strftime("%m-%d-%Y"),
                "po": po_display(job),
            }

            job.customer_name = customer_name
            job.business_name = request.form.get("business_name", "").strip() or None
            job.phone_number = request.form.get("phone_number", "").strip() or None
            job.email_address = request.form.get("email_address", "").strip() or None
            job.job_title = job_title
            job.job_summary = request.form.get("job_summary", "").strip() or None
            job.job_details = request.form.get("job_details", "").strip() or None

            quote_amount_raw = request.form.get("quote_amount", "").strip()
            job.quote_amount = float(quote_amount_raw) if quote_amount_raw else None

            received_raw = request.form.get("received_date", "").strip()
            try:
                new_received = parse_mmddyyyy(received_raw) if received_raw else job.received_date
            except ValueError:
                flash("Date Received must be in MM-DD-YYYY format.", "error")
                return redirect(url_for("job_view", job_id=job.id))

            # If received date changed, re-assign PO based on new date
            if new_received != job.received_date:
                job.received_date = new_received
                po_key, po_seq = next_po_for_date(new_received)
                job.po_date_key = po_key
                job.po_seq = po_seq

            db.session.commit()

            after = {
                "customer_name": job.customer_name,
                "business_name": job.business_name,
                "phone_number": job.phone_number,
                "email_address": job.email_address,
                "job_title": job.job_title,
                "job_summary": job.job_summary,
                "job_details": job.job_details,
                "quote_amount": job.quote_amount,
                "received_date": job.received_date.strftime("%m-%d-%Y"),
                "po": po_display(job),
            }

            # Compact log detail: only list differences
            changes = []
            for k in before:
                if before[k] != after[k]:
                    changes.append(f"{k}: {before[k]} → {after[k]}")

            log_event(job.id, "edited", "; ".join(changes) if changes else "Saved (no changes)")

            flash("Job updated.", "success")
            return redirect(url_for("job_view", job_id=job.id))

    logs = []
    if current_user.is_admin():
        logs = JobLog.query.filter_by(job_id=job.id).order_by(JobLog.timestamp.desc()).all()

    return render_template(
        "job_view.html",
        job=job,
        logs=logs,
        po_display=po_display,
        job_display_name=job_display_name,
        stage_index=stage_index,
    )


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

    # Admin can reset anyone, including other admins.
    # But if admin is resetting themselves, that's fine too.
    if request.method == "POST":
        new_pass = request.form.get("password", "").strip()
        if not new_pass:
            flash("Password cannot be empty.", "error")
            return redirect(url_for("user_reset_password", user_id=user.id))

        user.set_password(new_pass)
        db.session.commit()
        flash(f"Password updated for {user.username}.", "success")
        return redirect(url_for("users"))

    return render_template("user_reset_password.html", user=user)


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def user_delete(user_id):
    admin_required()

    user = User.query.get_or_404(user_id)

    # Block deleting yourself (prevents locking yourself out)
    if user.id == current_user.id:
        flash("You can't delete your own account while logged in.", "error")
        return redirect(url_for("users"))

    # Block deleting the last admin
    if user.role == "admin":
        admin_count = User.query.filter_by(role="admin").count()
        if admin_count <= 1:
            flash("You can't delete the last admin account.", "error")
            return redirect(url_for("users"))

    db.session.delete(user)
    db.session.commit()
    flash(f"Deleted user: {user.username}", "success")
    return redirect(url_for("users"))


@app.route("/jobs/<int:job_id>/delete", methods=["POST"])
@login_required
def job_delete(job_id):
    """Admin-only: delete a job and its logs."""
    admin_required()

    job = Job.query.get_or_404(job_id)

    # record deletion action before removing rows
    log_event(job.id, "deleted", f"Job deleted: {job_display_name(job)}")

    # remove associated logs first (avoid FK issues)
    JobLog.query.filter_by(job_id=job.id).delete()

    db.session.delete(job)
    db.session.commit()

    flash(f"Deleted job: {job.job_title}", "success")
    return redirect(url_for("dashboard"))


# -------------------- One-time init --------------------
@app.route("/init-db")
def init_db():
    db.create_all()

    # seed admin from env, if missing
    admin_user = os.getenv("ADMIN_USER", "admin")
    admin_pass = os.getenv("ADMIN_PASS", "admin123")

    existing = User.query.filter_by(username=admin_user).first()
    if not existing:
        u = User(username=admin_user, role="admin")
        u.set_password(admin_pass)
        db.session.add(u)
        db.session.commit()
        return f"DB initialized. Admin user created: {admin_user}"

    return "DB initialized. Admin user already exists."


if __name__ == "__main__":
    app.run(debug=True)
