"""Turns the sample .txt notes into real PDFs in ./sample_pdfs so you can test PDF upload.
Run:  python make_sample_pdfs.py
"""
import re
from pathlib import Path

from tests.pdf_factory import build_simple_pdf

out = Path("sample_pdfs")
out.mkdir(exist_ok=True)
for txt in sorted(Path("sample_docs").glob("*.txt")):
    parts = re.split(r"^---\s*page\s+\d+\s*---\s*$", txt.read_text(encoding="utf-8"), flags=re.M | re.I)
    pages = [p.strip() for p in parts if p.strip()]
    (out / f"{txt.stem}.pdf").write_bytes(build_simple_pdf(pages))
    print("Created", out / f"{txt.stem}.pdf", f"({len(pages)} pages)")
