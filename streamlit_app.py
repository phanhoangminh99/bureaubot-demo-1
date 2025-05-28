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
        for w in page.widgets() or []:
            if w.field_name in answers:
                w.field_value = str(answers[w.field_name])
                w.update()

    doc.save(str(out_path), deflate=True)
    doc.close()
    return out_path


# ─── 6) Chat flow ────────────────────────────────────────────────────────────────

def handle_user_message(msg: str) -> str:
    st.session_state.history.append({"role":"user", "content":msg})
    stage = st.session_state.stage

    # 1) Figure out which form to use
    if stage == "ask_context":
        st.session_state.case_info = msg
        choice = llm_select_form(msg)
        if choice == "NONE":
            st.session_state.stage = "end_unsupported"
            return (
                "I’m sorry—I don’t have a form for that scenario right now.  \n"
                "You can browse all USCIS forms here: https://www.uscis.gov/forms"
            )
        st.session_state.form_key = choice
        st.session_state.stage    = "confirm_form"
        return (
            f"Based on your situation, it looks like you need `{choice}`.  \n"
            "Would you like me to help fill it out? (yes/no)"
        )

    # 2) User confirms or says no
    if stage == "confirm_form":
        if msg.lower().strip() in ("yes","y","sure","please"):
            st.session_state.stage   = "complete"
            st.session_state.answers = llm_build_pdf_payload(
                st.session_state.form_key,
                st.session_state.case_info
            )
            return "Great—I'm filling it out now…"
        else:
            st.session_state.stage = "ask_context"
            return "Okay, no problem. How else can I help you?"

    # 3) Fallback end for unsupported scenarios
    if stage == "end_unsupported":
        return "If there’s anything else I can do, just let me know!"

    # 4) Completed: PDF is ready to download
    if stage == "complete":
        return "Your form is ready! Use the download button below."

    return "🤖 I got lost—please refresh the page."


# ─── 7) Streamlit UI ───────────────────────────────────────────────────────────

if "history" not in st.session_state:
    st.session_state.history    = [
        {"role":"assistant","content":"📝 Hi! How can I help you today?"}
    ]
    st.session_state.stage      = "ask_context"
    st.session_state.form_key   = None
    st.session_state.case_info  = ""
    st.session_state.answers    = {}

st.title("🛠️ BureauBot Demo")

# Show past messages
for m in st.session_state.history:
    st.chat_message(m["role"]).write(m["content"])

# Accept new user input
if user_msg := st.chat_input("Your message…"):
    reply = handle_user_message(user_msg)
    st.session_state.history.append({"role":"assistant","content":reply})
    st.chat_message("assistant").write(reply)

    # After filling, show download button
    if st.session_state.stage == "complete":
        out_pdf = fill_pdf(st.session_state.form_key, st.session_state.answers)
        with open(out_pdf, "rb") as f:
            st.download_button(
                label="📥 Download filled form",
                data=f,
                file_name=out_pdf.name
            )
