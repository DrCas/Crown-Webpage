from __future__ import annotations

# =========================================
# orders_api.py
# Crown Admin Portal - Order Intake API
# =========================================
# - Accepts multipart/form-data (FormData) including optional file uploads
# - Builds a PDF summary (ReportLab) via pdf_utils.build_order_pdf_bytes()
# - Sends email(s) via email_utils.send_order_emails()
# - Does NOT require DB/models yet (order stored as dict + generated order_id)
# =========================================

import json
import os
import uuid
from datetime import datetime, timezone, date

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from pdf_utils import build_order_pdf_bytes
from email_utils import send_order_emails
from sqlalchemy.exc import IntegrityError

orders_api = Blueprint("orders_api", __name__, url_prefix="/api")

# ---- Upload allow-list (keep conservative; expand as needed)
ALLOWED_EXTS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp",
    ".ai", ".eps", ".psd", ".tif", ".tiff", ".svg",
    ".zip", ".rar", ".txt"
}

def _parse_ymd_date(val: str):
    """Parse YYYY-MM-DD from <input type="date">. Returns date or None."""
    if not val:
        return None
    try:
        return datetime.strptime(str(val).strip(), "%Y-%m-%d").date()
    except Exception:
        return None

def _format_items_for_text(items: list[dict]) -> str:
    if not items:
        return "(none)"
    lines = []
    for i, row in enumerate(items, start=1):
        qty = (row.get("qty") or "").strip()
        desc = (row.get("description") or row.get("desc") or "").strip()
        material = (row.get("material") or "").strip()
        notes = (row.get("notes") or "").strip()
        parts = []
        if qty: parts.append(f"Qty: {qty}")
        if desc: parts.append(f"Desc: {desc}")
        if material: parts.append(f"Material: {material}")
        if notes: parts.append(f"Notes: {notes}")
        lines.append(f"{i}. " + " | ".join(parts))
    return "\n".join(lines)


def _build_human_job_details(order_type: str, form_fields: dict, items: list, saved_files: list[str]) -> str:
    """Readable job details (what you'd type manually) — not raw JSON."""
    lines = []
    lines.append(f"Website intake ({order_type})")
    lines.append("")

    # ---- Quick-order fields
    if order_type == "quick":
        rit = (form_fields.get("requested_item_type") or "").strip()
        if rit:
            lines.append(f"Requested item: {rit}")
        nb = (form_fields.get("needed_by") or "").strip()
        if nb:
            lines.append(f"Needed by: {nb}")
        bcm = (form_fields.get("best_contact_method") or "").strip()
        if bcm:
            lines.append(f"Best contact method: {bcm}")
        lines.append("")

    # ---- Large-project fields
    if order_type == "large":
        for k, label in [
            ("project_type", "Project type"),
            ("service_needed", "Service needed"),
            ("design_status", "Design status"),
            ("existing_graphics", "Existing graphics"),
            ("measurements_ready", "Measurements ready"),
            ("site_visit_needed", "Site visit needed"),
            ("material_preference", "Material preference"),
            ("install_constraints", "Install constraints"),
        ]:
            v = (form_fields.get(k) or "").strip()
            if v:
                lines.append(f"{label}: {v}")
        lines.append("")

        # Install location block
        install_parts = []
        for k in ["install_address", "install_city", "install_state", "install_zip"]:
            v = (form_fields.get(k) or "").strip()
            if v:
                install_parts.append(v)
        if install_parts:
            lines.append("Install location:")
            lines.append("  " + ", ".join(install_parts))
            lines.append("")

        # Vehicle block
        veh = []
        for k, label in [("year","Year"),("make","Make"),("model","Model"),("vin","VIN"),("unit_number","Unit #")]:
            v = (form_fields.get(k) or "").strip()
            if v:
                veh.append(f"{label}: {v}")
        if veh:
            lines.append("Vehicle:")
            for x in veh:
                lines.append("  " + x)
            lines.append("")

        scope_list = (form_fields.get("scope_list") or "").strip()
        if scope_list:
            lines.append("Scope / measurements:")
            lines.append(scope_list)
            lines.append("")

    # ---- Items (both forms)
    lines.append("Requested items:")
    lines.append(_format_items_for_text(items))
    lines.append("")

    # ---- Uploaded files
    if saved_files:
        lines.append("Uploads:")
        for p in saved_files:
            lines.append(f" - {os.path.basename(p)}")
        lines.append("")

    return "\n".join(lines).strip()

def _build_job_title(order_type: str, form_fields: dict) -> str:
    if order_type == "quick":
        rit = (form_fields.get("requested_item_type") or "").strip()
        return "Website Quick Order" + (f" — {rit}" if rit else "")
    # large
    pt = (form_fields.get("project_type") or "").strip()
    sn = (form_fields.get("service_needed") or "").strip()
    core = pt or sn
    return "Website Large Project" + (f" — {core}" if core else "")

def _allowed(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTS


def _po_key_for_date(d: date) -> str:
    """Generate PO key in MMDDYY format"""
    return d.strftime("%m%d%y")


def _next_po_seq(po_date_key: str) -> int:
    """Get next sequence number for a given PO date key"""
    from app import db, Job
    
    result = db.session.query(db.func.max(Job.po_seq)).filter(
        Job.po_date_key == po_date_key
    ).scalar()
    return (result or 0) + 1


def _insert_job_from_intake(
    order_id: str,
    order_type: str,
    form_fields: dict,
    items: list,
    saved_files: list,
) -> int:
    """Insert a new job from website intake form"""
    from app import db, Job, JobLog
    
    received = date.today()
    created = datetime.now()

    needed_by_date = _parse_ymd_date(form_fields.get('needed_by'))

    po_key = _po_key_for_date(received)
    po_seq = _next_po_seq(po_key)

    customer_name = (form_fields.get("name") or "").strip() or "Website Customer"
    business_name = (form_fields.get("company") or "").strip()
    phone_number = (form_fields.get("phone") or "").strip()
    email_address = (form_fields.get("email") or "").strip()

    summary = (form_fields.get("summary") or "").strip()
    job_title = _build_job_title(order_type, form_fields)

    # Store both a readable summary and the raw JSON payload
    submission_payload = {
        "order_id": order_id,
        "order_type": order_type,
        "fields": form_fields,
        "items": items,
        "saved_files": saved_files,
        "received_date": received.isoformat(),
        "created_at": created.isoformat(sep=" "),
    }

    job_details = _build_human_job_details(order_type, form_fields, items, saved_files)

    # Create the job
    job = Job(
        customer_name=customer_name,
        business_name=business_name if business_name else None,
        phone_number=phone_number if phone_number else None,
        email_address=email_address if email_address else None,
        job_title=job_title,
        job_summary=summary if summary else None,
        job_details=job_details,
        needed_by_date=needed_by_date,
        address_1=(form_fields.get("address") or "").strip() or None,
        city=(form_fields.get("city") or "").strip() or None,
        state=(form_fields.get("state") or "").strip() or None,
        zip_code=(form_fields.get("zip") or "").strip() or None,
        cell=(form_fields.get("cell") or "").strip() or None,
        vehicle_make=(form_fields.get("make") or "").strip() or None,
        vehicle_model=(form_fields.get("model") or "").strip() or None,
        vin=(form_fields.get("vin") or "").strip() or None,
        unit_number=(form_fields.get("unit_number") or "").strip() or None,
        mfd_date=_parse_ymd_date(form_fields.get("mfd_date")),
        quote_amount=None,
        received_date=received,
        created_at=created,
        stage="Received",
        po_date_key=po_key,
        po_seq=po_seq,
        is_new=1,
        source="website",
        intake_order_id=order_id,
        submission_json=json.dumps(submission_payload),
        uploaded_files_json=json.dumps(saved_files),
    )

    db.session.add(job)
    db.session.flush()  # Flush to get the job_id before commit
    job_id = job.id

    # Create line items from intake rows
    try:
        from app import JobLineItem
        for row in items or []:
            qty_raw = (row.get('qty') or '').strip()
            try:
                qty_val = int(qty_raw) if qty_raw else None
            except Exception:
                qty_val = None
            desc = (row.get('description') or row.get('desc') or '').strip()
            material = (row.get('material') or '').strip()
            notes = (row.get('notes') or '').strip()
            parts = [desc] if desc else []
            if material:
                parts.append(f"Material: {material}")
            if notes:
                parts.append(f"Notes: {notes}")
            li = JobLineItem(job_id=job_id, qty=qty_val, description='\n'.join(parts) if parts else None)
            db.session.add(li)
        db.session.flush()
    except Exception:
        current_app.logger.exception('Failed to create line items from intake')

    # Create the log entry
    log_entry = JobLog(
        job_id=job_id,
        timestamp=created,
        actor_username="website",
        action="created",
        details=f"Created from website intake order_id={order_id}",
    )

    db.session.add(log_entry)
    db.session.commit()

    return job_id


@orders_api.post("/orders")
def create_order():
    """
    POST /api/orders
    Expects multipart/form-data (FormData), fields include:
      - order_type: "quick" or "large"
      - name, email, phone (optional), company (optional)
      - items_json: JSON string (array of rows)
      - files: 0..N uploads in field name "files"
    """
    # -----------------------------
    # Parse form fields
    # -----------------------------
    form = request.form.to_dict(flat=True)
    order_type = (form.get("order_type", "") or "").strip().lower()
    if order_type not in {"quick", "large"}:
        return jsonify({"ok": False, "error": "Invalid order_type (must be 'quick' or 'large')"}), 400

    customer_name = (form.get("name", "") or "").strip()
    customer_email = (form.get("email", "") or "").strip()
    if not customer_name or not customer_email:
        return jsonify({"ok": False, "error": "Missing required customer info (name/email)"}), 400

    items_json = form.get("items_json", "[]") or "[]"

    # -----------------------------
    # Save uploads (optional)
    # -----------------------------
    upload_dir = current_app.config.get("ORDER_UPLOAD_DIR", "uploads/orders")
    os.makedirs(upload_dir, exist_ok=True)

    saved_files: list[str] = []
    for f in request.files.getlist("files"):
        if not f or not getattr(f, "filename", ""):
            continue
        fname = secure_filename(f.filename)
        if not fname:
            continue
        if not _allowed(fname):
            # silently ignore disallowed ext (or return 400 if you prefer)
            continue

        uid = uuid.uuid4().hex[:10]
        stored = f"{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uid}_{fname}"
        path = os.path.join(upload_dir, stored)
        f.save(path)
        saved_files.append(path)

    # -----------------------------
    # Build in-memory order object (no DB yet)
    # -----------------------------
    order_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

    order_data = {
        "order_id": order_id,
        "order_type": order_type,
        "name": customer_name,
        "email": customer_email,
        "phone": form.get("phone", "") or "",
        "company": form.get("company", "") or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "items_json": items_json,
        "uploaded_files": saved_files,
        "payload": dict(form),
    }

    # -----------------------------
    # Parse items_json into a list for PDF/email
    # -----------------------------
    items: list[dict] = []
    try:
        parsed = json.loads(items_json) if items_json else []
        if isinstance(parsed, list):
            # ensure dict rows
            items = [row for row in parsed if isinstance(row, dict)]
    except Exception:
        current_app.logger.exception("Invalid items_json; defaulting to empty list")
        items = []

    # -----------------------------
    # Save to database (insert first to avoid double-email on duplicate)
    # -----------------------------
    job_id = None
    db_error = None
    deduped = False
    try:
        job_id = _insert_job_from_intake(
            order_id=order_id,
            order_type=order_type,
            form_fields=form,
            items=items,
            saved_files=saved_files,
        )
    except IntegrityError:
        # Likely duplicate intake_order_id - fetch existing job and skip re-sending emails
        current_app.logger.warning("Duplicate intake_order_id detected; deduping")
        from app import db, Job
        existing = db.session.query(Job).filter_by(intake_order_id=order_id).first()
        job_id = existing.id if existing else None
        deduped = True
    except Exception as e:
        current_app.logger.exception("Database insert failed")
        db_error = str(e)
        return jsonify({"ok": False, "error": "DB insert failed", "db_error": db_error}), 500

    if deduped:
        return jsonify({"ok": True, "order_id": order_id, "job_id": job_id, "deduped": True}), 200

    # -----------------------------
    # Build PDF (if PDF build fails, treat as server error)
    # -----------------------------
    pdf_bytes = build_order_pdf_bytes(order_data, items=items)

    # -----------------------------
    # Send emails (do NOT fail request if email fails)
    # -----------------------------
    email_sent = False
    email_error = None
    try:
        send_order_emails(
            order=order_data,
            items=items,
            pdf_bytes=pdf_bytes,
            uploaded_paths=saved_files,
        )
        email_sent = True
    except Exception as e:
        current_app.logger.exception("Order email failed")
        email_error = str(e)

    # -----------------------------
    # Response
    # -----------------------------
    return jsonify({
        "ok": True,
        "order_id": order_id,
        "job_id": job_id,
        "email_sent": email_sent,
        "email_error": email_error,
        "db_error": db_error,
    }), 201
