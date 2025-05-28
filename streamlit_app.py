# streamlit_app.py

import os
import pathlib
import json
import textwrap

import fitz                 # PyMuPDF
import streamlit as st
import google.generativeai as genai

# ─── 1) Setup ───────────────────────────────────────────────────────────────────

os.makedirs("output", exist_ok=True)
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])


# ─── 2) Helpers ─────────────────────────────────────────────────────────────────

def fetch_meta(form_key: str) -> str:
    return pathlib.Path("data", f"{form_key}_meta.json").read_text()

def parse_pdf(form_key: str) -> str:
    doc = fitz.open(str(pathlib.Path("data", f"{form_key}.pdf")))
    text = "".join(p.get_text() for p in doc)
    doc.close()
    return text

def llm_select_form(case_info: str) -> str:
    """Ask Gemini which of our 4 keys the user needs."""
    prompt = textwrap.dedent(f"""
        You're an expert in US government forms.
        User scenario: "{case_info}"
        Reply **only** with one of:
        eoir_form_26, uscis_form_ar11, ice_form_i246, cbp_form_3299
    """).strip()
    resp = genai.chat.completions.create(
        model="chat-bison-001",
        messages=[{"author":"system","content":prompt}]
    )
    return resp.choices[0].message.content.strip()

def llm_build_pdf_payload(form_key: str, case_info: str) -> dict:
    meta = fetch_meta(form_key)
    prompt = textwrap.dedent(f"""
        You are a CBP/EOIR/ICE/USCIS form-filling expert.
        FORM METADATA:
        {meta}

        USER SCENARIO:
        {case_info}

        Return a **JSON** mapping each form field to its value.
    """).strip()
    resp = genai.chat.completions.create(
        model="chat-bison-001",
        messages=[{"author":"system","content":prompt}]
    )
    return json.loads(res
