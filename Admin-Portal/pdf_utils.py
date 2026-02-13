from __future__ import annotations

# =========================================
# pdf_utils.py
# Crown Admin Portal - PDF generation helpers
# =========================================
# Produces a simple, printable PDF summary of an order using ReportLab.
# =========================================

from io import BytesIO
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


def _safe(s) -> str:
    if s is None:
        return ""
    return str(s)


def build_order_pdf_bytes(order: dict, items: list[dict]) -> bytes:
    """
    Returns PDF bytes.
    order: dict with keys like name, email, phone, company, order_id, order_type, created_at
    items: list of dict rows: qty/description/material/notes (best-effort)
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    # ---- Header
    margin = 0.6 * inch
    y = height - margin

    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, "Crown Graphics - Order Intake")
    y -= 0.28 * inch

    c.setFont("Helvetica", 10)
    c.drawString(margin, y, f"Order ID: {_safe(order.get('order_id'))}")
    c.drawRightString(width - margin, y, f"Type: {_safe(order.get('order_type')).upper()}")
    y -= 0.18 * inch

    created_at = _safe(order.get("created_at"))
    if created_at:
        # keep as-is; could parse/format if needed
        c.drawString(margin, y, f"Created: {created_at}")
    else:
        c.drawString(margin, y, f"Created: {datetime.utcnow().isoformat()}")
    y -= 0.30 * inch

    # ---- Customer block
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Customer")
    y -= 0.18 * inch

    c.setFont("Helvetica", 10)
    c.drawString(margin, y, f"Name: {_safe(order.get('name'))}")
    y -= 0.16 * inch
    c.drawString(margin, y, f"Email: {_safe(order.get('email'))}")
    y -= 0.16 * inch
    c.drawString(margin, y, f"Phone: {_safe(order.get('phone'))}")
    y -= 0.16 * inch
    c.drawString(margin, y, f"Company: {_safe(order.get('company'))}")
    y -= 0.28 * inch

    # ---- Items table header
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Requested Items")
    y -= 0.22 * inch

    c.setFont("Helvetica-Bold", 9)
    col_qty = margin
    col_desc = margin + 0.7 * inch
    col_mat = margin + 3.9 * inch
    col_notes = margin + 5.4 * inch

    c.drawString(col_qty, y, "Qty")
    c.drawString(col_desc, y, "Description")
    c.drawString(col_mat, y, "Material")
    c.drawString(col_notes, y, "Notes")
    y -= 0.12 * inch

    c.setLineWidth(0.5)
    c.line(margin, y, width - margin, y)
    y -= 0.14 * inch

    c.setFont("Helvetica", 9)

    if not items:
        c.drawString(margin, y, "(No items provided)")
        y -= 0.18 * inch
    else:
        for row in items:
            qty = _safe(row.get("qty", ""))
            desc = _safe(row.get("description", row.get("desc", "")))
            mat = _safe(row.get("material", ""))
            notes = _safe(row.get("notes", ""))

            # simple line wrap for long fields
            def wrap(text, max_chars):
                if len(text) <= max_chars:
                    return [text]
                words = text.split()
                lines, cur = [], ""
                for w in words:
                    if len(cur) + len(w) + 1 <= max_chars:
                        cur = (cur + " " + w).strip()
                    else:
                        if cur:
                            lines.append(cur)
                        cur = w
                if cur:
                    lines.append(cur)
                return lines

            desc_lines = wrap(desc, 42)
            notes_lines = wrap(notes, 28)
            row_lines = max(len(desc_lines), len(notes_lines), 1)

            for i in range(row_lines):
                if y < margin + 1.0 * inch:
                    c.showPage()
                    y = height - margin
                    c.setFont("Helvetica-Bold", 12)
                    c.drawString(margin, y, "Requested Items (cont.)")
                    y -= 0.22 * inch
                    c.setFont("Helvetica-Bold", 9)
                    c.drawString(col_qty, y, "Qty")
                    c.drawString(col_desc, y, "Description")
                    c.drawString(col_mat, y, "Material")
                    c.drawString(col_notes, y, "Notes")
                    y -= 0.12 * inch
                    c.line(margin, y, width - margin, y)
                    y -= 0.14 * inch
                    c.setFont("Helvetica", 9)

                if i == 0:
                    c.drawString(col_qty, y, qty)
                    c.drawString(col_mat, y, mat)

                c.drawString(col_desc, y, desc_lines[i] if i < len(desc_lines) else "")
                c.drawString(col_notes, y, notes_lines[i] if i < len(notes_lines) else "")
                y -= 0.14 * inch

            y -= 0.06 * inch

    # ---- Footer note
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(margin, margin * 0.8, "Generated automatically by Crown Admin Portal")

    c.showPage()
    c.save()

    buf.seek(0)
    return buf.read()
