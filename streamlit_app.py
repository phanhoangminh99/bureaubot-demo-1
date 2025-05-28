# streamlit_app.py

import streamlit as st
import fitz    # PyMuPDF
import io
import json
from pathlib import Path

# ─── 1. PAGE SETUP ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Legal Chat & Form Bot", layout="wide")
st.header("🗂️ Legal Chat & Form Bot (Keyword‐Only, Safe)")

# ─── 2. LOAD FORMS + METADATA ────────────────────────────────────────────────────
FORM_DIR = Path("forms")
FORM_METADATA = {}
for pdf_path in FORM_DIR.glob("*.pdf"):
    key = pdf_path.stem  # e.g. "uscis_form_ar11"
    meta_path = FORM_DIR / f"{key}_meta.json"
    if meta_path.exists():
        spec = json.loads(meta_path.read_text())
        FORM_METADATA[key] = {
            "pdf": str(pdf_path),
            "title": spec.get("title", key),
            "fields": spec.get("fields", []),
        }

FALLBACK_LINK = "https://www.uscis.gov/forms"

# ─── 3. KEYWORD SELECTOR ─────────────────────────────────────────────────────────
def select_form_key(situation: str) -> str:
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

# ─── 4. PDF‐FILLER ───────────────────────────────────────────────────────────────
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

# ─── 5. CHAT STATE ────────────────────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = [
        {"role": "bot", "content": "Hi! Describe your situation and I’ll find the right form."}
    ]
    st.session_state.form_key = None
    st.session_state.filled   = False

# Render existing chat
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Handle new input
if user_input := st.chat_input("…"):
    # Echo user
    st.session_state.history.append({"role":"user","content":user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # A) Auto‐select form if not yet chosen
    if st.session_state.form_key is None:
        bot_txt = "Let me find the right form…"
        st.session_state.history.append({"role":"bot","content":bot_txt})
        st.chat_message("bot").markdown(bot_txt)

        key = select_form_key(user_input)
        # Guard: only accept if in metadata
        if key not in FORM_METADATA:
            bot_txt = (
                "Sorry, I couldn’t match any demo form.  \n\n"
                f"You can browse all USCIS forms here: [USCIS Forms]({FALLBACK_LINK})\n\n"
                "Try another description or ask a human for help."
            )
            st.session_state.history.append({"role":"bot","content":bot_txt})
            st.chat_message("bot").markdown(bot_txt)
        else:
            st.session_state.form_key = key
            title = FORM_METADATA[key].get("title", "<Unknown Form>")
            bot_txt = f"I found **{title}**.  Let’s fill it out—please answer the fields."
            st.session_state.history.append({"role":"bot","content":bot_txt})
            st.chat_message("bot").markdown(bot_txt)

    # B) Collect fields & generate PDF
    elif not st.session_state.filled:
        meta = FORM_METADATA.get(st.session_state.form_key, {})
        fields = meta.get("fields", [])
        answers = {}
        st.markdown("### 📝 Please fill these fields:")
        for fld in fields:
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
                st.error("Could not generate PDF—invalid form key.")

    # C) Completed
    else:
        done_txt = "✅ Done! Refresh to start again."
        st.session_state.history.append({"role":"bot","content":done_txt})
        with st.chat_message("bot"):
            st.markdown(done_txt)
