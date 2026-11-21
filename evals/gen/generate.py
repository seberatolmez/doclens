"""Generate a small synthetic document set with known answers.

Usage: python evals/gen/generate.py [out_dir]   (default: evals/data)
Writes the documents plus answers.json: [{doc, id, tag, question, answer}].
Tags: text | table | image | structure | notes. "image" answers exist only inside a picture.
"""

import io
import json
import sys
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Inches


def _font(size):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def _bar_chart(title, bars):
    img = Image.new("RGB", (800, 500), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 15), title, fill="black", font=_font(28))
    top = max(v for _, v in bars)
    w = 700 // len(bars)
    for i, (label, value) in enumerate(bars):
        x0 = 50 + i * w
        h = int(330 * value / top)
        d.rectangle([x0, 450 - h, x0 + w - 40, 450], fill=(60, 110, 200))
        d.text((x0, 455), label, fill="black", font=_font(22))
        d.text((x0, 450 - h - 32), f"{value}M", fill="black", font=_font(24))
    return _png(img)


def _org_chart(rows):
    img = Image.new("RGB", (800, 120 + 70 * len(rows)), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 15), "Team leads", fill="black", font=_font(30))
    for i, (team, lead) in enumerate(rows):
        y = 80 + i * 70
        d.rectangle([20, y, 780, y + 55], outline="black", width=2)
        d.text((35, y + 12), f"{team}: {lead}", fill="black", font=_font(26))
    return _png(img)


def _png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def spec_docx(path):
    doc = Document()
    doc.add_heading("Payments Service Spec v2", 0)
    doc.add_heading("Limits", 1)
    doc.add_paragraph("The maximum upload size for receipts is 25 MB. Requests time out after 40 seconds.")
    doc.add_heading("Ownership", 1)
    t = doc.add_table(rows=1, cols=3)
    for c, h in zip(t.rows[0].cells, ["Component", "Owner", "Deadline"]):
        c.text = h
    for row in [("Billing", "Ayse Demir", "2026-03-14"), ("Refunds", "Kerem Yilmaz", "2026-04-02"),
                ("Ledger", "Selin Kaya", "2026-05-19")]:
        for c, v in zip(t.add_row().cells, row):
            c.text = v
    doc.add_heading("Revenue", 1)
    doc.add_paragraph("Quarterly revenue is shown below.")
    doc.add_picture(_bar_chart("Revenue 2025", [("Q1", 3.1), ("Q2", 3.8), ("Q3", 4.7), ("Q4", 5.2)]), width=Inches(5))
    doc.save(path)
    return [
        ("text", "What is the maximum upload size for receipts?", "25 MB"),
        ("table", "Who owns the Refunds component?", "Kerem Yilmaz"),
        ("table", "What is the deadline for the Ledger component?", "2026-05-19"),
        ("image", "According to the revenue chart, what was Q3 revenue (in millions)?", "4.7"),
    ]


def requirements_docx(path):
    doc = Document()
    doc.add_heading("Mobile App Requirements", 0)
    sections = {
        "Security": ["Biometric login", "Session expiry after 15 minutes", "Certificate pinning"],
        "Offline": ["Cache last 50 orders", "Queue writes until online"],
        "Accessibility": ["Dynamic type", "Screen reader labels", "Minimum contrast 4.5:1", "Reduced motion"],
    }
    for name, items in sections.items():
        doc.add_heading(name, 1)
        for item in items:
            doc.add_paragraph(item, style="List Bullet")
    doc.save(path)
    return [
        ("structure", "How many requirements are listed under Accessibility? Answer with a number.", "4"),
        ("text", "After how many minutes does a session expire?", "15"),
        ("structure", "Which section contains 'Queue writes until online'?", "Offline"),
    ]


def sales_xlsx(path):
    wb = Workbook()
    data = {
        "2025": [("North", 120, 135, 150, 160), ("West", 90, 95, 101, 110), ("South", 70, 72, 80, 85)],
        "2026": [("North", 165, 170, 182, 190), ("West", 115, 121, 133, 140), ("South", 88, 90, 97, 99)],
    }
    wb.remove(wb.active)
    for sheet, rows in data.items():
        ws = wb.create_sheet(sheet)
        ws.append(["Region", "Q1", "Q2", "Q3", "Q4"])
        for r in rows:
            ws.append(r)
    wb.save(path)
    return [
        ("table", "In the 2025 sheet, what were West region Q3 sales?", "101"),
        ("table", "In the 2026 sheet, what were South region Q4 sales?", "99"),
        ("structure", "Which region had the highest Q1 sales in 2026?", "North"),
    ]


def inventory_xlsx(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Stock"
    ws.append(["SKU", "Name", "Warehouse", "Qty", "Unit price"])
    for i in range(1, 41):
        ws.append([f"SKU-{1000 + i}", f"Part {i}", ["IST", "ANK", "IZM"][i % 3], (i * 37) % 500, round(i * 1.75, 2)])
    wb.save(path)
    return [
        ("table", "What is the quantity of SKU-1023?", str((23 * 37) % 500)),
        ("table", "Which warehouse stores SKU-1031?", ["IST", "ANK", "IZM"][31 % 3]),
    ]


def deck_pptx(path):
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Project Atlas Kickoff"
    s.placeholders[1].text = "Q1 2026 planning"
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Timeline"
    s.placeholders[1].text = "Beta in March\nGA after security review"
    s.notes_slide.notes_text_frame.text = "Say out loud: the GA launch date is 2026-06-09."
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Teams"
    pic = s.shapes.add_picture(_org_chart([("Platform", "Deniz Arslan"), ("Mobile", "Ece Sahin"),
                                           ("Data", "Mert Aydin")]), Inches(1), Inches(1.6), width=Inches(8))
    pic._element.nvPicPr.cNvPr.set("descr", "Org chart")
    prs.save(path)
    return [
        ("text", "What is the title of the first slide?", "Project Atlas Kickoff"),
        ("notes", "According to the speaker notes, what is the GA launch date?", "2026-06-09"),
        ("image", "Who leads the Platform team?", "Deniz Arslan"),
    ]


GENERATORS = {
    "spec.docx": spec_docx,
    "requirements.docx": requirements_docx,
    "sales.xlsx": sales_xlsx,
    "inventory.xlsx": inventory_xlsx,
    "deck.pptx": deck_pptx,
}


def generate(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    answers = []
    for name, fn in GENERATORS.items():
        for i, (tag, q, a) in enumerate(fn(out / name)):
            answers.append({"doc": name, "id": f"{name}#{i}", "tag": tag, "question": q, "answer": a})
    (out / "answers.json").write_text(json.dumps(answers, indent=2), encoding="utf-8")
    return answers


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "data"
    print(f"{len(generate(out))} questions -> {out}")
