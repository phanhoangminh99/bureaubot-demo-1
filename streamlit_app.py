import os
import pathlib
import json
import textwrap

import fitz  # PyMuPDF
import streamlit as st
from huggingface_hub import HFInference

# ─── Setup ────────────────────────────────────────────────────────────────

# Initialize Hugging Face inference with token from Streamlit secrets
hf = HFInference(api_key=st.secrets["HF_TOKEN"])
os.makedirs("output", exist_ok=True)

# ─── Helper Functions ─────────────────────────────────────────────────────

def fetch_meta(form_key: str) -> str:
    return pathlib.Path("data", f"{form_key}_meta.json").read_text()

def parse_pdf(form_key: str) -> str:
    path = pathlib.Path("data", f"{form_key}.pdf")
    doc = fitz.open(str(path))
    text = "".join(page.get_text() for page in doc)
    doc.close()
    return text

def llm_select_form(case_info: str) -> str:
    prompt = textwrap.dedent(f"""
        You are an expert in U.S. government forms.
        Based on the following situation, which form should the user fill out?

        Situation: "{case_info}"

        Reply with exactly one of:
        eoir_form_26, uscis_form_ar11, ice_form_i246, cbp_form_3299
    """).strip()

    resp = hf.text_generation(
        model="tiiuae/falcon-7b-instruct",
        inputs=prompt,
        parameters={"max_new_tokens":16, "temperature":0.2}
    )
    return resp[0]["generated_text"].strip()

def llm_build_pdf_payload(form_key: str, case_info: str) -> dict:
    meta = fetch_meta(form_key)
    pdf_text = parse_pdf(form_key)
    prompt = textwrap.dedent(f"""
        You are a CBP/EOIR/ICE/USCIS form-filling expert.

        FORM METADATA:
        {meta}

        USER SITUATION:
        {case_info}

        Return a JSON object that maps each form field to the exact value.
    """).strip()

    resp = hf.text_generation(
        model="tiiuae/falcon-7b-instruct",
        inputs=prompt,
        parameters={"max_new_tokens":512, "temperature":0.3}
    )
    return json.loads(resp[0]["generated_text"])

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

# ─── Chat Logic ───────────────────────────────────────────────────────────

def handle_user_message(msg: str) -> str:
    st.session_state.history.append({"role":"user", "content":msg})
    stage = st.session_state.stage

    if stage == "ask_context":
        st.session_state.case_info = msg
        form_key = llm_select_form(msg)
        st.session_state.form_key = form_key
        st.session_state.stage = "confirm_form"
        return (
            f"Sounds like you need `{form_key}`. "
            "Would you like me to help fill it out for you? (yes/no)"
        )

    if stage == "confirm_form":
        if msg.lower().strip() in ("yes", "y", "sure", "please"):
            st.session_state.stage = "complete"
            st.session_state.answers = llm_build_pdf_payload(
                st.session_state.form_key,
                st.session_state.case_info
            )
            return "Great—filling it out now… one moment."
        else:
            st.session_state.stage = "ask_context"
            return "No problem. Just tell me what you need help with."

    if stage == "complete":
        return "Your form is ready! Download it below."

    return "Oops. Something went wrong. Try refreshing the app."

# ─── Streamlit App ────────────────────────────────────────────────────────

if "history" not in st.session_state:
    st.session_state.history    = [
        {"role": "assistant", "content": "📝 Hi! How can I help you today?"}
    ]
    st.session_state.stage      = "ask_context"
    st.session_state.form_key   = None
    st.session_state.case_info  = ""
    st.session_state.answers    = {}

st.title("🛠️ BureauBot (Hugging Face Edition)")

# Display chat history
for m in st.session_state.history:
    st.chat_message(m["role"]).write(m["content"])

# Accept user input
if user_msg := st.chat_input("Your message…"):
    reply = handle_user_message(user_msg)
    st.session_state.history.append({"role":"assistant", "content":reply})
    st.chat_message("assistant").write(reply)

    # If form is filled, show download button
    if st.session_state.stage == "complete":
        out_pdf = fill_pdf(st.session_state.form_key, st.session_state.answers)
        with open(out_pdf, "rb") as f:
            st.download_button("📥 Download filled form", f, file_name=out_pdf.name)
