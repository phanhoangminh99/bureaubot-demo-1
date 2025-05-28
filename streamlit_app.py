# streamlit_app.py

import os
import pathlib
import json
import textwrap

import fitz                # PyMuPDF
import streamlit as st
import requests

# ─── 1) Configuration ─────────────────────────────────────────────────────────

# Hugging Face token in Streamlit Cloud → Settings → Secrets as HF_TOKEN
HF_TOKEN = st.secrets["HF_TOKEN"]

# Use an open‐access instruction‐tuned model
HF_API_URL = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.1"

HEADERS = {
    "Authorization": f"Bearer {HF_TOKEN}",
    "Content-Type": "application/json"
}

# Ensure output directory exists
os.makedirs("output", exist_ok=True)


# ─── 2) Load form metadata ─────────────────────────────────────────────────────

FORM_KEYS = [
    "eoir_form_26",
    "uscis_form_ar11",
    "ice_form_i246",
    "cbp_form_3299"
]

# Preload all four meta JSONs from repo root
ALL_METAS = {
    key: pathlib.Path(f"{key}_meta.json").read_text()
    for key in FORM_KEYS
}


# ─── 3) Hugging Face helper ────────────────────────────────────────────────────

def call_huggingface(prompt: str, max_tokens: int = 256) -> str:
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_tokens,
            "return_full_text": False,
            "temperature": 0.2
        }
    }
    try:
        resp = requests.post(HF_API_URL, headers=HEADERS, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data[0]["generated_text"].strip()
    except requests.exceptions.HTTPError as e:
        # Show status code & body in the app
        st.error(f"❌ Hugging Face API error {resp.status_code}")
        st.code(resp.text)
        # Fallback so your code continues
        return "ERROR"
    except ValueError:
        # Non-JSON response
        st.error("❌ Hugging Face returned invalid JSON")
        st.code(resp.text)
        return "ERROR"


# ─── 4) Form‐selection using all metas ──────────────────────────────────────────

def llm_select_form(case_info: str) -> str:
    """
    Return one of FORM_KEYS if the case matches, or "NONE" otherwise.
    """
    catalog = "\n\n".join(
        f"---\nForm `{key}` metadata:\n```json\n{ALL_METAS[key]}\n```"
        for key in FORM_KEYS
    )

    prompt = textwrap.dedent(f"""
        You are an expert on U.S. government forms. I have exactly four forms:

        {catalog}

        If the user’s scenario clearly matches one of these forms,
        reply with the exact form key (one of: {', '.join(FORM_KEYS)}).
        Otherwise reply with ONLY: NONE

        User scenario:
        \"\"\"{case_info}\"\"\"
    """).strip()

    result = result.split()[0].strip()
    if result == "ERROR" or result not in FORM_KEYS + ["NONE"]:
    return "NONE"
    return result


# ─── 5) Build PDF payload ──────────────────────────────────────────────────────

def parse_pdf(form_key: str) -> str:
    path = pathlib.Path(f"{form_key}.pdf")
    doc = fitz.open(str(path))
    text = "".join(page.get_text() for page in doc)
    doc.close()
    return text

def llm_build_pdf_payload(form_key: str, case_info: str) -> dict:
    meta = ALL_METAS[form_key]
    pdf_text = parse_pdf(form_key)
    prompt = textwrap.dedent(f"""
        You are a CBP/EOIR/ICE/USCIS form‐filling expert.

        FORM METADATA:
        {meta}

        PDF TEXT (first 1000 chars):
        {pdf_text[:1000]}…

        USER SCENARIO:
        {case_info}

        Return a JSON object mapping each form field name to the exact value.
    """).strip()

    reply = call_huggingface(prompt, max_tokens=512)
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


# ─── 6) Conversation logic ─────────────────────────────────────────────────────

def handle_user_message(msg: str) -> str:
    st.session_state.history.append({"role":"user", "content":msg})
    stage = st.session_state.stage

    # 1) Identify the form or fallback
    if stage == "ask_context":
        st.session_state.case_info = msg
        choice = llm_select_form(msg)
        if choice == "NONE":
            st.session_state.stage = "end_unsupported"
            return (
                "I’m sorry, I don’t have a form for that scenario right now. "
                "You can browse all USCIS forms here:\n"
                "https://www.uscis.gov/forms"
            )
        st.session_state.form_key = choice
        st.session_state.stage = "confirm_form"
        return f"Based on your situation, it looks like you need `{choice}`. Would you like me to help fill it out? (yes/no)"

    # 2) Confirmation
    if stage == "confirm_form":
        if msg.lower().strip() in ("yes", "y", "sure", "please"):
            st.session_state.stage = "complete"
            st.session_state.answers = llm_build_pdf_payload(
                st.session_state.form_key,
                st.session_state.case_info
            )
            return "Great—I'm filling it out now. One moment…"
        else:
            st.session_state.stage = "ask_context"
            return "No problem. Tell me again how I can help you."

    # 3) Unsupported fallback end
    if stage == "end_unsupported":
        return "If you need anything else, just let me know!"

    # 4) Complete: final message (download button appears below)
    if stage == "complete":
        return "Your form is ready! Please download it below."

    return "🤖 Oops, I got lost. Please refresh the page."


# ─── 7) Streamlit UI ───────────────────────────────────────────────────────────

if "history" not in st.session_state:
    st.session_state.history   = [
        {"role":"assistant","content":"📝 Hi! How can I help you today?"}
    ]
    st.session_state.stage     = "ask_context"
    st.session_state.form_key  = None
    st.session_state.case_info = ""
    st.session_state.answers   = {}

st.title("🛠️ BureauBot Demo")

# Render past chat
for m in st.session_state.history:
    st.chat_message(m["role"]).write(m["content"])

# Handle new input
if user_msg := st.chat_input("Your message…"):
    reply = handle_user_message(user_msg)
    st.session_state.history.append({"role":"assistant","content":reply})
    st.chat_message("assistant").write(reply)

    # Once complete, offer download
    if st.session_state.stage == "complete":
        out_pdf = fill_pdf(st.session_state.form_key, st.session_state.answers)
        with open(out_pdf, "rb") as f:
            st.download_button("📥 Download filled form", f, file_name=out_pdf.name)
