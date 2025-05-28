# streamlit_app.py

import streamlit as st
import fitz          # PyMuPDF
import io
import json
from pathlib import Path
from huggingface_hub import InferenceApi, login

# ─── 1. PAGE SETUP ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Legal Chat & Form Bot", layout="wide")
st.header("🗂️ Legal Chat & Form Bot")

# ─── 2. LOAD FORMS + METADATA ────────────────────────────────────────────────────
FORM_DIR = Path("forms")
FORM_METADATA = {}
for pdf in FORM_DIR.glob("*.pdf"):
    key = pdf.stem
    meta = FORM_DIR / f"{key}_meta.json"
    if meta.exists():
        spec = json.loads(meta.read_text())
        FORM_METADATA[key] = {
            "pdf": str(pdf),
            "title": spec.get("title", key),
            "fields": spec["fields"],
        }

FALLBACK_LINK = "https://www.uscis.gov/forms"

# ─── 3. HUGGING FACE ZERO-SHOT CLIENT ─────────────────────────────────────────────
hf_token = st.secrets.get("HF_TOKEN", "")
if not hf_token:
    hf_token = st.text_input("Hugging Face API Token", type="password")
if not hf_token:
    st.stop()

login(token=hf_token)

@st.cache_resource
def get_zs_client():
    return InferenceApi(repo_id="facebook/bart-large-mnli", token=hf_token)

zs_client = get_zs_client()

# ─── 4. ZERO-SHOT FORM SELECTOR ───────────────────────────────────────────────────
def select_form_key(situation: str, threshold: float = 0.3) -> str:
    labels = list(FORM_METADATA.keys())
    try:
        payload = {
            "inputs": situation,
            "parameters": {
                "candidate_labels": labels,
                "multi_label": False
            }
        }
        # single-arg call
        response = zs_client(payload)
        # response is {"labels": [...], "scores": [...]}
        top_label = response["labels"][0]
        top_score = response["scores"][0]
        if top_score >= threshold:
            return top_label
    except Exception as e:
        st.warning(f"Zero-shot API error: {e}")
    return "none"

# ─── 5. PDF-FILLER ───────────────────────────────────────────────────────────────
def fill_pdf_bytes(form_key, answers):
    meta = FORM_METADATA.get(form_key)
    if not meta:
        return None
    doc = fitz.open(meta["pdf"])
    page = doc[0]
    for fld in meta["fields"]:
        val = answers.get(fld["name"], "")
        if not val:
            continue
        x, y = fld["rect"][:2]
        page.insert_text((x, y), val, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

# ─── 6. STREAMLIT CHAT STATE ────────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = [
        {"role": "bot", "content": "Hi! Describe your situation and I’ll find the right form."}
    ]
    st.session_state.form_key = None
    st.session_state.filled   = False

# render conversation
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# handle new user message
if user_msg := st.chat_input("…"):
    # echo user
    st.session_state.history.append({"role": "user", "content": user_msg})
    with st.chat_message("user"):
        st.markdown(user_msg)

    # Step A: select form
    if st.session_state.form_key is None:
        st.session_state.history.append({"role":"bot","content":"Let me find the right form…"})
        with st.chat_message("bot"):
            st.markdown("Let me find the right form…")

        key = select_form_key(user_msg)
        if key == "none":
            bot = (
                "Sorry, I couldn’t confidently pick a demo form.\n\n"
                f"Browse all USCIS forms here: [USCIS Forms]({FALLBACK_LINK})\n\n"
                "Try another question or adjust your wording."
            )
        else:
            st.session_state.form_key = key
            bot = f"I’ve selected **{FORM_METADATA[key]['title']}**. Let’s fill it out—please answer the fields."

        st.session_state.history.append({"role":"bot","content":bot})
        st.chat_message("bot").markdown(bot)

    # Step B: prompt & fill fields
    elif not st.session_state.filled:
        meta = FORM_METADATA[st.session_state.form_key]
        answers = {}
        st.markdown("### 📝 Please fill these fields:")
        for fld in meta["fields"]:
            answers[fld["name"]] = st.text_input(fld["prompt"], key=fld["name"])
        if st.button("Generate Filled PDF"):
            pdf_bytes = fill_pdf_bytes(st.session_state.form_key, answers)
            if pdf_bytes:
                st.session_state.history.append({"role":"bot","content":"Here’s your filled form:"})
                with st.chat_message("bot"):
                    st.download_button(
                        "📄 Download PDF",
                        data=pdf_bytes,
                        file_name=f"{st.session_state.form_key}_filled.pdf",
                        mime="application/pdf"
                    )
                st.session_state.filled = True
            else:
                st.error("Error generating PDF.")

    # Step C: done
    else:
        done = "✅ Done! Refresh to start again."
        st.session_state.history.append({"role":"bot","content":done})
        with st.chat_message("bot"):
            st.markdown(done)
