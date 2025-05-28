# streamlit_app.py

import streamlit as st
import fitz          # PyMuPDF
import io
import json
from pathlib import Path
from huggingface_hub import InferenceApi, login

# ─── 1. PAGE SETUP ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Legal Chat & Form Bot", layout="wide")
st.header("🗂️ Legal Chat & Form Bot")

# ─── 2. LOAD YOUR FORMS + METADATA ──────────────────────────────────────────────
FORM_DIR = Path("forms")
FORM_METADATA = {}
for pdf in FORM_DIR.glob("*.pdf"):
    key = pdf.stem  # e.g. "ice_form_i246"
    meta = FORM_DIR / f"{key}_meta.json"
    if meta.exists():
        spec = json.loads(meta.read_text())
        FORM_METADATA[key] = {
            "pdf": s
