from __future__ import annotations

import json
from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def build_order_pdf_bytes(order, items_json: str) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w, h = letter

    margin = 50
    y = h - margin

    def line(txt, size=11, gap=14):
        nonlocal y
        c.setFont("Helvetica", size)
        c.drawString(margin, y, txt)
        y -= gap
        if y < margin:
            c.showPage()
            y = h - margin

    c.setTitle(f"Crown Order #{getattr(order,'id','')}")
    line("Crown Graphics — Order Submission", size=16, gap=22)
    line(f"Generated: {datetime.now().strftime('%m/%d/%Y %I:%M %p')}", size=10, gap=16)
    line(f"Order ID: {getattr(order,'id','')}")
    line(f"Order Type: {getattr(order,'order_type','')}")
    line("")

    # Customer block
    line("Customer", size=13, gap=18)
    line(f"Name: {getattr(order,'name','')}")
    line(f"Company: {getattr(order,'company','')}")
    line(f"Email: {getattr(order,'email','')}")
    line(f"Phone: {getattr(order,'phone','')}")
    line("")

    # Pull raw payload dict if available
    payload = getattr(order, "payload", None)
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = None

    if isinstance(payload, dict):
        # Common fields
        needed_by = payload.get("needed_by", "")
        summary = payload.get("summary", "")
        if needed_by:
            line(f"Needed By: {needed_by}")
        if summary:
            line("Summary:", size=12, gap=16)
            for chunk in _wrap(summary, 95):
                line(chunk, size=11, gap=14)
            line("")

    # Items table (simple)
    line("Requested Items", size=13, gap=18)
    try:
        items = json.loads(items_json or "[]")
    except Exception:
        items = []

    if not items:
        line("(none listed)")
    else:
        for i, it in enumerate(items, 1):
            qty = str(it.get("qty","")).strip()
            desc = str(it.get("desc","")).strip()
            mat = str(it.get("material","")).strip()
            notes = str(it.get("notes","")).strip()
            line(f"{i}) Qty: {qty}  Material: {mat}", size=11, gap=14)
            if desc:
                for chunk in _wrap(f"Desc: {desc}", 95):
                    line(chunk, size=11, gap=14)
            if notes:
                for chunk in _wrap(f"Notes: {notes}", 95):
                    line(chunk, size=11, gap=14)
            line("")

    c.showPage()
    c.save()
    return buf.getvalue()

def _wrap(text: str, width: int):
    # simple word-wrap without dependencies
    words = (text or "").split()
    lines = []
    cur = []
    cur_len = 0
    for w in words:
        if cur_len + len(w) + (1 if cur else 0) > width:
            lines.append(" ".join(cur))
            cur = [w]
            cur_len = len(w)
        else:
            cur.append(w)
            cur_len += len(w) + (1 if cur_len else 0)
    if cur:
        lines.append(" ".join(cur))
    return lines
