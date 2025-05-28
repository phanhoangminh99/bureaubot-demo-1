pip install google-genai

import os
import pathlib
import json
import textwrap

import fitz  # PyMuPDF
import streamlit as st
from google import genai
from google.genai import types

# ─── 1) Setup ───────────────────────────────────────────────────────────────────

# Ensure output directory exists
os.makedirs("output", exist_ok=True)

# Initialize Google GenAI client
genai_client = genai.GenerativeAI()
genai_client.init(api_key=st.secrets["GEMINI_API_KEY"])

# ─── 2) PDF & LLM Helpers ───────────────────────────────────────────────────────

def fetch_meta(form_key: str) -> str:
    path = pathlib.Path("data") / f"{form_key}_meta.json"
    return path.read_text()

def parse_pdf(form_key: str) -> str:
    path = pathlib.Path("data") / f"{form_key}.pdf"
    doc = fitz.open(str(path))
    text = "".join(page.get_text() for page in doc)
    doc.close()
    return text

def llm_build_pdf_payload(form_key: str, case_info: str) -> dict:
    meta_json = fetch_meta(form_key)
    pdf_text = parse_pdf(form_key)
    prompt = textwrap.dedent(f"""
        You are a CBP/EOIR/ICE/USCIS form-filling expert.
        Here is the form metadata:
        {meta_json}
        Here is the user’s description of their case:
        {case_info}
        Return a JSON object mapping each field name to the exact value.
    """)
    resp = genai_client.chat.advance(
        model="models/text-bison-001",
        messages=[types.Message(role="system", content=prompt)]
    )
    return json.loads(resp.last.message.content)

def fill_pdf(form_key: str, answers: dict) -> pathlib.Path:
    in_path = pathlib.Path("data") / f"{form_key}.pdf"
    out_path = pathlib.Path("output") / f"{form_key}_filled.pdf"
    doc = fitz.open(str(in_path))
    for page in doc:
        for widget in page.widgets() or []:
            name = widget.field_name
            if name in answers:
                widget.field_value = str(answers[name])
                widget.update()
    doc.save(str(out_path), deflate=True)
    doc.close()
    return out_path

# ─── 3) Chat Orchestration ─────────────────────────────────────────────────────

def handle_user_message(user_msg: str) -> str:
    stage = st.session_state.stage

    if stage == "select_form":
        key = user_msg.strip()
        valid = {"eoir_form_26", "uscis_form_ar11", "ice_form_i246", "cbp_form_3299"}
        if key in valid:
            st.session_state.form_key = key
            st.session_state.stage = "fill_info"
            return f"✅ `{key}` selected. Please describe your situation so I can fill the form."
        else:
            return "❌ I only support: eoir_form_26, uscis_form_ar11, ice_form_i246, cbp_form_3299. Try again."

    elif stage == "fill_info":
        st.session_state.case_info = user_msg
        st.session_state.stage = "complete"
        st.session_state.answers = llm_build_pdf_payload(
            st.session_state.form_key,
            st.session_state.case_info
        )
        return "🛠️ Got it! Building your filled form now…"

    return "🤖 Unexpected state. Please refresh the page."

# ─── 4) Streamlit UI ───────────────────────────────────────────────────────────

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content":
         "📝 Hi there! Which form would you like to fill? Options: "
         "`eoir_form_26`, `uscis_form_ar11`, `ice_form_i246`, `cbp_form_3299`"
        }
    ]
    st.session_state.stage = "select_form"
    st.session_state.form_key = None
    st.session_state.case_info = ""
    st.session_state.answers = {}

st.title("🛠️ Form-Filling Bot")

# Render chat history
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

# Handle new user input
if user_input := st.chat_input("Your message…"):
    # 1) record user message
    st.session_state.messages.append({"role": "user", "content": user_input})

    # 2) process and record assistant reply
    reply = handle_user_message(user_input)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.chat_message("assistant").write(reply)

    # 3) if complete, show download button
    if st.session_state.stage == "complete":
        out_pdf = fill_pdf(st.session_state.form_key, st.session_state.answers)
        with open(out_pdf, "rb") as f:
            st.download_button(
                label="📥 Download filled PDF",
                data=f,
                file_name=out_pdf.name
            )
