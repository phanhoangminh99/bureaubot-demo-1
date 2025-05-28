import os
import pathlib
import json
import textwrap
import fitz
import streamlit as st
import requests

# ─── SETUP ────────────────────────────────────────────

HF_TOKEN = st.secrets["HF_TOKEN"]
HF_API_URL = "https://api-inference.huggingface.co/models/tiiuae/falcon-7b-instruct"

HEADERS = {
    "Authorization": f"Bearer {HF_TOKEN}",
    "Content-Type": "application/json"
}

# ─── HUGGING FACE CALL ────────────────────────────────

def call_huggingface(prompt, max_tokens=256):
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_tokens,
            "return_full_text": False,
            "temperature": 0.2
        }
    }
    response = requests.post(HF_API_URL, headers=HEADERS, json=payload)
    result = response.json()
    return result[0]["generated_text"].strip()

# ─── FORM FUNCTIONS ───────────────────────────────────

def fetch_meta(form_key): return pathlib.Path("data", f"{form_key}_meta.json").read_text()

def parse_pdf(form_key):
    path = pathlib.Path("data", f"{form_key}.pdf")
    doc = fitz.open(str(path))
    text = "".join(page.get_text() for page in doc)
    doc.close()
    return text

def llm_select_form(case_info):
    prompt = f"""
You are an expert in U.S. government forms.
User situation: "{case_info}"
Reply with one of:
eoir_form_26, uscis_form_ar11, ice_form_i246, cbp_form_3299
"""
    return call_huggingface(prompt, max_tokens=16)

def llm_build_pdf_payload(form_key, case_info):
    meta = fetch_meta(form_key)
    pdf_text = parse_pdf(form_key)
    prompt = f"""
You're a form-filling expert.

FORM METADATA:
{meta}

USER SITUATION:
{case_info}

Return a JSON mapping each field name to its value.
"""
    return json.loads(call_huggingface(prompt, max_tokens=512))

def fill_pdf(form_key, answers):
    in_path = pathlib.Path("data", f"{form_key}.pdf")
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

# ─── CHAT LOGIC ───────────────────────────────────────

def handle_user_message(msg):
    st.session_state.history.append({"role": "user", "content": msg})
    stage = st.session_state.stage

    if stage == "ask_context":
        st.session_state.case_info = msg
        form_key = llm_select_form(msg)
        st.session_state.form_key = form_key
        st.session_state.stage = "confirm_form"
        return f"Looks like you need `{form_key}`. Want me to help fill it out? (yes/no)"

    if stage == "confirm_form":
        if msg.lower().strip() in ("yes", "y", "sure", "please"):
            st.session_state.stage = "complete"
            st.session_state.answers = llm_build_pdf_payload(
                st.session_state.form_key, st.session_state.case_info
            )
            return "Great—filling it out now…"
        else:
            st.session_state.stage = "ask_context"
            return "All good. Tell me what you need help with."

    if stage == "complete":
        return "Your form is ready! Download below."

    return "Hmm. Something broke. Try refreshing."

# ─── STREAMLIT UI ─────────────────────────────────────

if "history" not in st.session_state:
    st.session_state.history = [
        {"role": "assistant", "content": "📝 Hi! How can I help you today?"}
    ]
    st.session_state.stage = "ask_context"
    st.session_state.form_key = None
    st.session_state.case_info = ""
    st.session_state.answers = {}

st.title("🛠️ BureauBot (Hugging Face Raw API)")

for m in st.session_state.history:
    st.chat_message(m["role"]).write(m["content"])

if user_msg := st.chat_input("Your message…"):
    reply = handle_user_message(user_msg)
    st.session_state.history.append({"role": "assistant", "content": reply})
    st.chat_message("assistant").write(reply)

    if st.session_state.stage == "complete":
        out_pdf = fill_pdf(st.session_state.form_key, st.session_state.answers)
        with open(out_pdf, "rb") as f:
            st.download_button("📥 Download filled form", f, file_name=out_pdf.name)
