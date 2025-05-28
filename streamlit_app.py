# streamlit_app.py

import os
import pathlib
import json
import textwrap

import fitz         # PyMuPDF
import streamlit as st
import requests

# ─── 1) Configuration ───────────────────────────────────────────────────────────

# Your Hugging Face API token must be set in Streamlit Cloud → Settings → Secrets
HF_TOKEN = st.secrets["HF_TOKEN"]

# Use an open-access instruction-tuned model
HF_API_URL = "https://api-inference.huggingface.co/models/google/flan-t5-large"

HEADERS = {
    "Authorization": f"Bearer {HF_TOKEN}",
    "Content-Type": "application/json"
}

# Make sure we have a place to save filled PDFs
os.makedirs("output", exist_ok=True)


# ─── 2) Load your four forms’ metadata ─────────────────────────────────────────

FORM_KEYS = [
    "eoir_form_26",
    "uscis_form_ar11",
    "ice_form_i246",
    "cbp_form_3299"
]

# Pre-read each <form>_meta.json from repo root
ALL_METAS = {
    key: pathlib.Path(f"{key}_meta.json").read_text()
    for key in FORM_KEYS
}


# ─── 3) Hugging Face helper ─────────────────────────────────────────────────────

def call_huggingface(prompt: str, max_tokens: int = 256) -> str:
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_tokens,
            "return_full_text": False,
            "temperature": 0.2
        }
    }
    resp = requests.post(HF_API_URL, headers=HEADERS, json=payload)
    resp.raise_for_status()
    data = resp.json()
    return data[0]["generated_text"].strip()


# ─── 4) Which form? (rules + LLM) ───────────────────────────────────────────────

def llm_select_form(case_info: str) -> str:
    ci = case_info.lower()

    # RULE #1: address change → AR-11
    if "address" in ci:
        return "uscis_form_ar11"

    # RULE #2: unaccompanied articles → CBP-3299
    if "unaccompanied" in ci and "article" in ci:
        return "cbp_form_3299"

    # FALLBACK: ask the LLM
    catalog = "\n\n".join(
        f"---\nForm `{k}` metadata:\n```json\n{ALL_METAS[k]}\n```"
        for k in FORM_KEYS
    )
    prompt = textwrap.dedent(f"""
        You are an expert on U.S. government forms. I have exactly four forms:

        {catalog}

        Given the user’s scenario below, reply with the exact form key
        (one of: {', '.join(FORM_KEYS)}). If none apply, reply ONLY: NONE

        Scenario:
        \"\"\"{case_info}\"\"\"
    """).strip()

    result = call_huggingface(prompt, max_tokens=32).split()[0].strip()
    if result in FORM_KEYS:
        return result
    return "NONE"


# ─── 5) Build the JSON payload ─────────────────────────────────────────────────

def parse_pdf(form_key: str) -> str:
    path = pathlib.Path(f"{form_key}.pdf")
    doc = fitz.open(str(path))
    text = "".join(page.get_text() for page in doc)
    doc.close()
    return text

def llm_build_pdf_payload(form_key: str, case_info: str) -> dict:
    meta = ALL_METAS[form_key]
    # We no longer include the full PDF text—just metadata + scenario
    prompt = textwrap.dedent(f"""
        You are a CBP/EOIR/ICE/USCIS form-filling assistant.

        FORM METADATA:
        ```json
        {meta}
        ```

        USER SCENARIO:
        \"\"\"{case_info}\"\"\"

        Please reply with a JSON object mapping each form field
        name (as in the metadata) to the correct value.
    """).strip()

    reply = call_huggingface(prompt, max_tokens=256)
    return json.loads(reply)


def fill_pdf(form_key: str, answers: dict) -> pathlib.Path:
    in_path  = pathlib.Path(f"{form_key}.pdf")
    out_path = pathlib.Path("output", f"{form_key}_filled.pdf")
    doc = fitz.open(str(in_path))

    for page in doc:
