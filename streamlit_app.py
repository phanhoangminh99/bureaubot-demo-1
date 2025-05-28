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
    return json.loads(resp.choices[0].message.content)

def fill_pdf(form_key: str, answers: dict) -> pathlib.Path:
    in_path  = pathlib.Path("data", f"{form_key}.pdf")
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


# ─── 3) Conversation Logic ──────────────────────────────────────────────────────

def handle_user_message(msg: str) -> str:
    st.session_state.history.append({"role":"user","content":msg})
    stage = st.session_state.stage

    if stage == "ask_context":
        # user gives scenario → classify form
        st.session_state.case_info = msg
        form = llm_select_form(msg)
        st.session_state.form_key = form
        st.session_state.stage = "confirm_form"
        return (
            f"Based on what you said, it sounds like you need `{form}`. " 
            "Would you like me to fill that out for you?"
        )

    if stage == "confirm_form":
        if msg.lower() in ("yes","y","sure","please do","ra"):
            st.session_state.stage = "complete"
            st.session_state.answers = llm_build_pdf_payload(
                st.session_state.form_key,
                st.session_state.case_info
            )
            return "Great—I'm filling it out now! Give me a moment…"
        else:
            st.session_state.stage = "ask_context"
            return "No problem! Tell me again how I can help."

    if stage == "complete":
        return "I've already generated your form. Use the download button below."

    # fallback
    return "🤖 Huh, I'm not sure how to proceed. Please refresh."


# ─── 4) Streamlit UI ────────────────────────────────────────────────────────────

# Initialize
if "history" not in st.session_state:
    st.session_state.history    = [
        {"role":"assistant",
         "content":"📝 Hi! How can I help you today?"}
    ]
    st.session_state.stage      = "ask_context"
    st.session_state.form_key   = None
    st.session_state.case_info  = ""
    st.session_state.answers    = {}

st.title("🛠️ Form-Filling Bot")

# render chat
for m in st.session_state.history:
    st.chat_message(m["role"]).write(m["content"])

# user input
if user_msg := st.chat_input("Your message…"):
    reply = handle_user_message(user_msg)
    st.session_state.history.append({"role":"assistant","content":reply})
    st.chat_message("assistant").write(reply)

    # once complete, offer PDF
    if st.session_state.stage == "complete":
        out_pdf = fill_pdf(st.session_state.form_key, st.session_state.answers)
        with open(out_pdf, "rb") as f:
            st.download_button("📥 Download your filled form", f, file_name=out_pdf.name)
