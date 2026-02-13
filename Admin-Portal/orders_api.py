from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename


from pdf_utils import build_order_pdf_bytes
from email_utils import send_order_emails

orders_api = Blueprint("orders_api", __name__, url_prefix="/api")

ALLOWED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".ai", ".eps", ".psd", ".tif", ".tiff", ".svg", ".zip", ".rar", ".txt"}

def _allowed(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTS

@orders_api.post("/orders")
def create_order():
    # Accept multipart/form-data (FormData from browser)
    form = request.form.to_dict(flat=True)

    # Items table arrives as JSON string (we’ll set this on the front-end)
    items_json = form.get("items_json", "[]")

    order_type = form.get("order_type", "").strip()  # "quick" or "large"
    if order_type not in {"quick", "large"}:
        return jsonify({"ok": False, "error": "Invalid order_type"}), 400

    customer_email = form.get("email", "").strip()
    customer_name = form.get("name", "").strip()
    if not customer_email or not customer_name:
        return jsonify({"ok": False, "error": "Missing required customer info"}), 400

    # Save uploads (optional)
    upload_dir = current_app.config.get("ORDER_UPLOAD_DIR", "uploads/orders")
    os.makedirs(upload_dir, exist_ok=True)

    saved_files = []
    for f in request.files.getlist("files"):
        if not f or not f.filename:
            continue
        fname = secure_filename(f.filename)
        if not _allowed(fname):
            continue
        uid = uuid.uuid4().hex[:10]
        stored = f"{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uid}_{fname}"
        path = os.path.join(upload_dir, stored)
        f.save(path)
        saved_files.append(path)

    # Create DB record
    order = Order(
        order_type=order_type,
        name=customer_name,
        email=customer_email,
        phone=form.get("phone", ""),
        company=form.get("company", ""),
        payload=form,            # store raw form fields (JSON column recommended)
        items_json=items_json,   # store raw items JSON (string)
        uploaded_files=saved_files,  # JSON column recommended
        status="NEW",
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(order)
    db.session.commit()

    # Build PDF
    pdf_bytes = build_order_pdf_bytes(order, items_json=items_json)

    # Send emails (internal + customer)
    send_order_emails(
        order=order,
        pdf_bytes=pdf_bytes,
        uploaded_paths=saved_files,
    )

    return jsonify({"ok": True, "order_id": order.id})
