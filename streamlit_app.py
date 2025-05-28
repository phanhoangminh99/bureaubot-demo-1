# streamlit_app.py

import streamlit as st
import fitz         # PyMuPDF
import io
import json
from pathlib import Path

# ─── 1. APP CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Legal Chat & Form Bot", layout="wide")
st.header("🗂️ Legal Chat & Form Bot")

# ─── 2. GET YOUR HF TOKEN ───────────────────────────────────────────────────────
# First try secrets, else ask at runtime
hf_token = st.secrets.get("HF_TOKEN", "")
if not hf_token:
    hf_token = st.text_input("Hugging Face API Token", type="password")
if not hf_token:
    st.stop()

# ─── 3. LOAD YOUR FORMS + METADATA ──────────────────────────────────────────────
FORM_DIR = Path("forms")
FORM_KEYS = [p.stem for p in FORM_DIR.glob("*.pdf")]
FORM_METADATA = {}
for key in FORM_KEYS:
    meta_path = FORM_DIR / f"{key}_meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            spec = json.load(f)
        FORM_METADATA[key] = {
            "pdf": str(FORM_DIR / f"{key}.pdf"),
            "title": spec.get("title", key),
            "fields": spec["fields"]
        }

FALLBACK_LINK = "https://www.uscis.gov/forms"

# ─── 4. INITIALIZE HF PIPELINE ─────────────────────────────────────────────────
@st.cache_resource
def get_llm(token: str):
    from transformers import pipeline
    return pipeline(
        "text2text-generation",
        model="google/flan-t5-small",   # or your private model path
        device=-1,
        use_auth_token=token,
        max_length=128,
        truncation=True
    )

llm = get_llm(hf_token)

# ─── 5. LLM HELPERS ─────────────────────────────────────────────────────────────
def llm_generate(prompt: str) -> str:
    out = llm(prompt)[0]["generated_text"]
    return out.strip()

def select_form_key_via_llm(situation: str) -> str:
    choices = ", ".join(FORM_METADATA.keys())
    prompt = (
        "You are a legal intake assistant.\n"
        f"User situation:\n{situation}\n\n"
        f"Reply with exactly one form key from [{choices}], or 'none'."
    )
    resp = llm_generate(prompt)
    return resp.split()[0].lower()

# Keyword fallback
def select_form_key_keyword(situation: str) -> str:
    txt = situation.lower()
    if "address" in txt or "move" in txt:
        return "uscis_form_ar11"
    if "medical" in txt or "release" in txt or "hospital" in txt:
        return "ice_form_i246"
    if "deport" in txt or "asylum" in txt or "removal" in txt:
        return "eoir_form_26"
    if "withdraw" in txt or "cbp" in txt:
        return "cbp_form_3299"
    return "none"

def select_form_key(situation: str) -> str:
    key = select_form_key_via_llm(situation)
    return key if key in FORM_METADATA else select_form_key_keyword(situation)

# ─── 6. PDF-FILLER ─────────────────────────────────────────────────────────────
def fill_pdf_bytes(form_key, answers):
    doc = fitz.open(FORM_METADATA[form_key]["pdf"])
    page = doc[0]
    for fld in FORM_METADATA[form_key]["fields"]:
        name = fld["name"]
        val  = answers.get(name, "")
        if val:
            x, y = fld["rect"][:2]
            page.insert_text((x, y), val, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

# ─── 7. STREAMLIT CHAT STATE ───────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = [
        {"role":"bot", "content":"Hi! Describe your situation and I’ll find the right form."}
    ]
    st.session_state.form_key = None
    st.session_state.filled   = False

# Render chat history
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Handle user input
if user_msg := st.chat_input("…"):
    st.session_state.history.append({"role":"user","content":user_msg})

    # 7a. Auto‐select form
    if st.session_state.form_key is None:
        st.session_state.history.append({"role":"bot","content":"Let me find the right form…"})
        form_key = select_form_key(user_msg)
        if form_key == "none":
            bot_txt = (
                "Sorry, I don’t have that form in my demo.  "
                f"Browse all USCIS forms here: [USCIS Forms]({FALLBACK_LINK})\n\n"
                "You can still ask me other legal questions."
            )
        else:
            st.session_state.form_key = form_key
            title = FORM_METADATA[form_key]["title"]
            bot_txt = f"I think **{title}** is it—let’s fill it out. I’ll ask each field."
        st.session_state.history.append({"role":"bot","content":bot_txt})
        st.chat_message("bot").markdown(bot_txt)

    # 7b. Collect & fill fields
    elif not st.session_state.filled:
        spec = FORM_METADATA[st.session_state.form_key]
        answers = {}
        st.markdown("### 📝 Please fill these fields:")
        for fld in spec["fields"]:
            answers[fld["name"]] = st.text_input(fld["prompt"], key=fld["name"])
        if st.button("Generate Filled PDF"):
            pdf_bytes = fill_pdf_bytes(st.session_state.form_key, answers)
            st.session_state.history.append({"role":"bot","content":"Here's your filled form:"})
            st.chat_message("bot").download_button(
                "📄 Download PDF",
                data=pdf_bytes,
                file_name=f"{st.session_state.form_key}_filled.pdf",
                mime="application/pdf"
            )
            st.session_state.filled = True

    # 7c. Free‐form Q&A
    else:
        convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in st.session_state.history)
        prompt = convo + "\nBOT:"
        reply = llm_generate(prompt)
        st.session_state.history.append({"role":"bot","content":reply})
        st.chat_message("bot").markdown(reply)
