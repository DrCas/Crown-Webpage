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
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from pdf_utils import build_order_pdf_bytes
from email_utils import send_order_emails

orders_api = Blueprint("orders_api", __name__, url_prefix="/api")

# ---- Upload allow-list (keep conservative; expand as needed)
ALLOWED_EXTS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp",
    ".ai", ".eps", ".psd", ".tif", ".tiff", ".svg",
    ".zip", ".rar", ".txt"
}

def _allowed(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTS


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
    order_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

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
        "email_sent": email_sent,
        "email_error": email_error,
    }), 201
