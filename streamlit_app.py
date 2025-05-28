# streamlit_app.py

import os
import pathlib
import json
import textwrap

import fitz                 # PyMuPDF
import streamlit as st
import google.generativeai as genai

# ─── 1) Setup ───────────────────────────────────────────────────────────────────

# Ensure output directory exists
os.makedirs("output", exist_ok=True)

# Configure Gemini API key
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])


# ─── 2) Helpers ─────────────────────────────────────────────────────────────────

def fetch_meta(form_key: str) -> str:
    """Read the form’s metadata JSON from disk."""
    return pathlib.Path("data", f"{form_key}_meta.json").read_text()

def parse_pdf(form_key: str) -> str:
    """Extract all text from the blank PDF for context."""
    path = pathlib.Path("data", f"{form_key}.pdf")
    doc = fitz.open(str(path))
    text = "".join(page.get_text() for page in doc)
    doc.close()
    return text

def llm_select_form(case_info: str) -> str:
    """
    Ask Gemini which of our 4 form-keys the user scenario requires.
    Returns one of: eoir_form_26, uscis_form_ar11, ice_form_i246, cbp_form_3299
    """
    prompt = textwrap.dedent(f"""
        You are an expert in US government forms.
        User scenario: "{case_info}"
        Reply with exactly one of: eoir_form_26, uscis_form_ar11, ice_form_i246, cbp_form_3299
    """).strip()

    resp = genai.ChatCompletion.create(
        model="chat-bison-001",
        messages=[{"author": "system", "content": prompt}]
    )
    return resp.choices[0].message.content.strip()

def llm_build_pdf_payload(form_key: str, case_info: str) -> dict:
    """
    Build a JSON payload of field → value by asking Gemini to fill out
    the form based on metadata + user scenario.
    """
    meta = fetch_meta(form_key)
    prompt = textwrap.dedent(f"""
        You are a CBP/EOIR/ICE/USCIS form-filling expert.
        
        FORM METADATA:
        {meta}
        
        USER SCENARIO:
        {case_info}
        
        Return a JSON object mapping each form field name to the exact value.
    """).strip()

    resp = genai.ChatCompletion.create(
        model="chat-bison-001",
        messages=[{"author": "system", "content": prompt}]
    )
    return json.loads(resp.choices[0].message.content)

def fill_pdf(form_key: str, answers: dict) -> pathlib.Path:
    """
    Take the original PDF, inject `answers` into its form widgets,
    and write a flattened filled PDF to output/.
    """
    in_path  = pathlib.Path("data", f"{form_key}.pdf")
    out_path = pathlib.Path("output", f"{form_key}_filled.pdf")
    doc = fitz.open(str(in_path))

    for page in doc:
        for w in page.widgets() or []:
            name = w.field_name
            if name in answers:
                w.field_value = str(answers[name])
                w.update()

    doc.save(str(out_path), deflate=True)
    doc.close()
    return out_path


# ─── 3) Conversation Logic ──────────────────────────────────────────────────────

def handle_user_message(msg: str) -> str:
    """
    Advance through three stages:
      1) ask_context   → get user scenario, pick form
      2) confirm_form  → ask user to confirm filling that form
      3) complete      → fill PDF and show download
    """
    st.session_state.history.append({"role": "user", "content": msg})
    stage = st.session_state.stage

    # 1) User describes situation
    if stage == "ask_context":
        st.session_state.case_info = msg
        form_key = llm_select_form(msg)
        st.session_state.form_key = form_key
        st.session_state.stage = "confirm_form"
        return (
            f"Based on that, it sounds like you need `{form_key}`. "
            "Would you like me to fill it out for you? (yes/no)"
        )

    # 2) User confirms or denies
    if stage == "confirm_form":
        if msg.lower().strip() in ("yes", "y", "sure", "please"):
            st.session_state.stage = "complete"
            st.session_state.answers = llm_build_pdf_payload(
                st.session_state.form_key,
                st.session_state.case_info
            )
            return "Great—I'm filling it out now. One sec…"
        else:
            st.session_state.stage = "ask_context"
            return "No problem. How can I help you today?"

    # 3) Already complete
    if stage == "complete":
        return "I've already prepared your form. Use the download button below."

    return "Oops, I got confused. Please refresh the page."


# ─── 4) Streamlit UI ────────────────────────────────────────────────────────────

# Initialize session
if "history" not in st.session_state:
    st.session_state.history   = [
        {"role": "assistant", "content": "📝 Hi! How can I help you today?"}
    ]
    st.session_state.stage     = "ask_context"
    st.session_state.form_key  = None
    st.session_state.case_info = ""
    st.session_state.answers   = {}

st.title("BureauBot Demo")

# Render chat history
for m in st.session_state.history:
    st.chat_message(m["role"]).write(m["content"])

# Accept new input
if user_msg := st.chat_input("Your message…"):
    reply = handle_user_message(user_msg)
    st.session_state.history.append({"role": "assistant", "content": reply})
    st.chat_message("assistant").write(reply)

    # Once complete, show download button
    if st.session_state.stage == "complete":
        out_pdf = fill_pdf(st.session_state.form_key, st.session_state.answers)
        with open(out_pdf, "rb") as f:
            st.download_button(
                label="📥 Download your filled form",
                data=f,
                file_name=out_pdf.name
            )
