from __future__ import annotations

# =========================================
# email_utils.py
# Crown Admin Portal - Email helpers
# =========================================
# Sends:
#  - Internal notification email (to INTERNAL_NOTIFY_EMAIL or ORDER_NOTIFY_EMAIL)
#  - Customer confirmation email (to order['email'])
#
# Configuration (Flask app.config or environment variables):
#   SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
#   SMTP_USE_TLS (true/false), SMTP_USE_SSL (true/false)
#   FROM_EMAIL (default: SMTP_USER)
#   INTERNAL_NOTIFY_EMAIL (or ORDER_NOTIFY_EMAIL)
#   BCC_EMAIL (optional)
# =========================================

import os
import smtplib
from email.message import EmailMessage
from typing import Optional


def _cfg(app, key: str, default=None):
    # Prefer Flask app.config, fall back to environment
    if app and key in app.config:
        return app.config.get(key, default)
    return os.getenv(key, default)


def _as_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def _build_internal_subject(order: dict) -> str:
    return f"[Crown] New {order.get('order_type','').upper()} order - {order.get('order_id','')}"


def _build_internal_body(order: dict, items: list[dict], uploaded_paths: list[str]) -> str:
    lines = []
    lines.append("A new order was received.")
    lines.append("")
    lines.append(f"Order ID: {order.get('order_id','')}")
    lines.append(f"Type: {order.get('order_type','')}")
    lines.append("")
    lines.append("Customer")
    lines.append(f"  Name: {order.get('name','')}")
    lines.append(f"  Email: {order.get('email','')}")
    lines.append(f"  Phone: {order.get('phone','')}")
    lines.append(f"  Company: {order.get('company','')}")
    lines.append("")
    lines.append("Items")
    if not items:
        lines.append("  (none)")
    else:
        for i, row in enumerate(items, start=1):
            lines.append(f"  {i}. Qty={row.get('qty','')}  Desc={row.get('description','')}  Mat={row.get('material','')}  Notes={row.get('notes','')}")
    lines.append("")
    lines.append("Uploads")
    if not uploaded_paths:
        lines.append("  (none)")
    else:
        for p in uploaded_paths:
            lines.append(f"  {p}")
    return "\n".join(lines)


def _build_customer_subject(order: dict) -> str:
    return f"Crown Graphics - We received your request ({order.get('order_id','')})"


def _build_customer_body(order: dict) -> str:
    return (
        f"Hi {order.get('name','')},\n\n"
        "We received your request and will review it shortly.\n"
        "If we need any clarification, we’ll reach out.\n\n"
        f"Order ID: {order.get('order_id','')}\n"
        f"Type: {order.get('order_type','')}\n\n"
        "Thanks,\n"
        "Crown Graphics\n"
    )


def _send_email(
    host: str,
    port: int,
    user: Optional[str],
    password: Optional[str],
    use_tls: bool,
    use_ssl: bool,
    msg: EmailMessage,
):
    if use_ssl:
        with smtplib.SMTP_SSL(host, port) as s:
            if user and password:
                s.login(user, password)
            s.send_message(msg)
        return

    with smtplib.SMTP(host, port) as s:
        s.ehlo()
        if use_tls:
            s.starttls()
            s.ehlo()
        if user and password:
            s.login(user, password)
        s.send_message(msg)


def send_order_emails(order: dict, items: list[dict], pdf_bytes: bytes, uploaded_paths: list[str]) -> bool:
    """
    Sends internal + customer emails. Returns True if internal email was sent successfully.
    Raises exceptions if SMTP misconfigured or send fails (caller can catch).
    """
    # Flask current_app is optional here; avoid import to prevent circulars
    try:
        from flask import current_app
        app = current_app._get_current_object()
    except Exception:
        app = None

    smtp_host = _cfg(app, "SMTP_HOST")
    smtp_port = int(_cfg(app, "SMTP_PORT", 587))
    smtp_user = _cfg(app, "SMTP_USER")
    smtp_pass = _cfg(app, "SMTP_PASS")
    use_tls = _as_bool(_cfg(app, "SMTP_USE_TLS", True))
    use_ssl = _as_bool(_cfg(app, "SMTP_USE_SSL", False))

    from_email = _cfg(app, "FROM_EMAIL", smtp_user)
    internal_to = _cfg(app, "INTERNAL_NOTIFY_EMAIL", _cfg(app, "ORDER_NOTIFY_EMAIL"))
    bcc_email = _cfg(app, "BCC_EMAIL", None)

    if not smtp_host:
        raise RuntimeError("SMTP_HOST is not configured")
    if not from_email:
        raise RuntimeError("FROM_EMAIL (or SMTP_USER) is not configured")
    if not internal_to:
        raise RuntimeError("INTERNAL_NOTIFY_EMAIL (or ORDER_NOTIFY_EMAIL) is not configured")

    # ---- Internal notification
    internal_msg = EmailMessage()
    internal_msg["Subject"] = _build_internal_subject(order)
    internal_msg["From"] = from_email
    internal_msg["To"] = internal_to
    if bcc_email:
        internal_msg["Bcc"] = bcc_email
    internal_msg.set_content(_build_internal_body(order, items, uploaded_paths))

    # attach PDF
    internal_msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=f"order_{order.get('order_id','')}.pdf",
    )

    _send_email(
        host=smtp_host,
        port=smtp_port,
        user=smtp_user,
        password=smtp_pass,
        use_tls=use_tls,
        use_ssl=use_ssl,
        msg=internal_msg,
    )

    # ---- Customer confirmation (best-effort; still raise if configured but fails)
    cust_email = (order.get("email") or "").strip()
    if cust_email:
        customer_msg = EmailMessage()
        customer_msg["Subject"] = _build_customer_subject(order)
        customer_msg["From"] = from_email
        customer_msg["To"] = cust_email
        if bcc_email:
            customer_msg["Bcc"] = bcc_email
        customer_msg.set_content(_build_customer_body(order))

        # attach PDF as receipt/summary
        customer_msg.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=f"order_{order.get('order_id','')}.pdf",
        )

        _send_email(
            host=smtp_host,
            port=smtp_port,
            user=smtp_user,
            password=smtp_pass,
            use_tls=use_tls,
            use_ssl=use_ssl,
            msg=customer_msg,
        )

    return True
