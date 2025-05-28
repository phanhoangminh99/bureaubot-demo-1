# streamlit_app.py

import streamlit as st
import openai
import fitz  # PyMuPDF
import io

# ─── 1. APP CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Legal Chat & Form Bot", layout="wide")

# Ask for API key once
if "api_key" not in st.session_state:
    st.session_state.api_key = st.text_input(
        "Enter your OpenAI API Key (sk-…)", type="password"
    )
if not st.session_state.api_key:
    st.stop()
openai.api_key = st.session_state.api_key

# ─── 2. FORMS METADATA ──────────────────────────────────────────────────────────
FORM_METADATA = {
    "eoir_form_26": {
        "path": "forms/EOIR-26.pdf",
        "name": "EOIR-26 (Stay of Removal)",
    },
    "uscis_form_ar11": {
        "path": "forms/AR-11.pdf",
        "name": "USCIS AR-11 (Change of Address)",
    },
    "ice_form_i246": {
        "path": "forms/I-246.pdf",
        "name": "ICE I-246 (Application for Release)",
    },
    "cbp_form_3299": {
        "path": "forms/CBP-3299.pdf",
        "name": "CBP-3299 (Withdrawal of Application)",
    },
}
FALLBACK_LINK = "https://www.uscis.gov/forms"

# ─── 3. LLM HELPERS ─────────────────────────────────────────────────────────────
def llm_chat(messages):
    """Run a ChatCompletion with gpt-4o-mini."""
    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()

def select_form(case_text: str) -> str:
    """Ask the LLM to choose a form_key or 'none'."""
    system = "You are a legal intake assistant. You know these form_keys: " + ", ".join(FORM_METADATA.keys())
    user = f"""User situation:
{case_text}

Which one form_key is appropriate? Reply with exactly one key, or 'none'."""
    return llm_chat([{"role":"system","content":system}, {"role":"user","content":user}])

# ─── 4. PDF FILLER ─────────────────────────────────────────────────────────────
def fill_pdf(form_path: str, answers: dict) -> bytes:
    doc = fitz.open(form_path)
    page = doc[0]
    for field, info in answers.items():
        x, y = info["pos"]
        page.insert_text((x, y), info["value"], fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

# ─── 5. STREAMLIT INTERFACE ────────────────────────────────────────────────────
st.header("🗂️ Legal Chat & Form Bot")

if "history" not in st.session_state:
    # initial prompt
    st.session_state.history = [
        {"role":"bot", "content":"Hi! Tell me what you need help with."}
    ]
    st.session_state.form_key = None
    st.session_state.filled = False

# render chat
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# user types
if user_msg := st.chat_input("…"):
    st.session_state.history.append({"role":"user","content":user_msg})

    # If we haven’t selected a form yet, try to match
    if st.session_state.form_key is None:
        key = select_form(user_msg)
        if key.lower() == "none":
            bot_txt = (
                "I don’t have that form in my demo. "
                f"Browse all forms here: [USCIS Forms]({FALLBACK_LINK})\n\n"
                "Feel free to ask me other legal questions, too."
            )
        else:
            st.session_state.form_key = key.strip()
            name = FORM_METADATA[key]["name"]
            bot_txt = (
                f"I think **{name}** is right. When you’re ready, we can fill it out. "
                "Just tell me your full name and date of birth."
            )
        st.session_state.history.append({"role":"bot","content":bot_txt})
        st.chat_message("bot").markdown(bot_txt)

    # If a form is chosen but not yet filled, collect fields
    elif not st.session_state.filled:
        # Try to parse name + dob from the last user message
        # (for demo simplicity, ask explicitly)
        st.session_state.history.append({"role":"bot","content":"Please enter your Full Name:"})
        name = st.text_input("Full Name", key="name")
        dob  = st.text_input("DOB (MM/DD/YYYY)", key="dob")
        if st.button("Generate Filled PDF"):
            answers = {
                "full_name": {"value": name, "pos": (100, 700)},
                "dob":       {"value": dob,  "pos": (100, 650)},
            }
            pdf_bytes = fill_pdf(FORM_METADATA[st.session_state.form_key]["path"], answers)
            st.session_state.history.append({"role":"bot","content":"Here’s your filled form:"})
            st.chat_message("bot").download_button(
                "📄 Download PDF",
                data=pdf_bytes,
                file_name=f"{st.session_state.form_key}_filled.pdf",
                mime="application/pdf"
            )
            st.session_state.filled = True

    # Otherwise, treat as a free-form legal Q&A
    else:
        # forward full history + this user msg to LLM
        msgs = [{"role":m["role"], "content":m["content"]} for m in st.session_state.history]
        bot_reply = llm_chat(msgs)
        st.session_state.history.append({"role":"bot","content":bot_reply})
        st.chat_message("bot").markdown(bot_reply)
