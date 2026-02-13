from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

INTERNAL_TO_DEFAULT = os.getenv("CROWN_INTERNAL_TO", "orders@crowngfx.com")

def send_order_emails(order, pdf_bytes: bytes, uploaded_paths: list[str] | None = None):
    # You can attach uploads too, but keep sizes sane.
    uploaded_paths = uploaded_paths or []

    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    from_email = os.getenv("SMTP_FROM", smtp_user)

    if not all([smtp_host, smtp_user, smtp_pass, from_email]):
        raise RuntimeError("Missing SMTP env vars (SMTP_HOST/SMTP_USER/SMTP_PASS/SMTP_FROM)")

    order_id = getattr(order, "id", "")
    subject = f"New Crown Order #{order_id} ({getattr(order,'order_type','')})"

    # 1) internal email
    msg_internal = EmailMessage()
    msg_internal["Subject"] = subject
    msg_internal["From"] = from_email
    msg_internal["To"] = INTERNAL_TO_DEFAULT
    msg_internal.set_content(_internal_body(order))

    msg_internal.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=f"order_{order_id}.pdf")

    # 2) customer email
    msg_customer = EmailMessage()
    msg_customer["Subject"] = f"Thanks! We received your request (Order #{order_id})"
    msg_customer["From"] = from_email
    msg_customer["To"] = getattr(order, "email", "")
    msg_customer.set_content(_customer_body(order))

    msg_customer.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=f"order_{order_id}.pdf")

    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.send_message(msg_internal)
        s.send_message(msg_customer)

def _internal_body(order) -> str:
    return (
        "New order submission received.\n\n"
        f"Order ID: {getattr(order,'id','')}\n"
        f"Type: {getattr(order,'order_type','')}\n"
        f"Name: {getattr(order,'name','')}\n"
        f"Company: {getattr(order,'company','')}\n"
        f"Email: {getattr(order,'email','')}\n"
        f"Phone: {getattr(order,'phone','')}\n\n"
        "See attached PDF for full details.\n"
    )

def _customer_body(order) -> str:
    return (
        "Thanks for your request — we've received it!"
        
        f"Order ID: {getattr(order,'id','')}\n\n"
        "Next steps: we’ll review your details, confirm any missing info, and follow up.\n\n"
        "Your submission details are attached as a PDF.\n\n"
        "— Crown Graphics\n"
    )
