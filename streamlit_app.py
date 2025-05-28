# streamlit_app.py

import streamlit as st
import fitz    # PyMuPDF
import io
import json
from pathlib import Path

# ─── 1. PAGE SETUP ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Legal Chat & Form Bot", layout="wide")
st.header("🗂️ Legal Chat & Form Bot (Keyword-Only)")

# ─── 2. LOAD FORMS + METADATA ────────────────────────────────────────────────────
FORM_DIR = Path("forms")
FORM_METADATA = {}
for pdf in FORM_DIR.glob("*.pdf"):
    key = pdf.stem  # e.g. "uscis_form_ar11"
    meta = FORM_DIR / f"{key}_meta.json"
    if meta.exists():
        spec = json.loads(meta.read_text())
        FORM_METADATA[key] = {
            "pdf": str(pdf),
            "title": spec.get("title", key),
            "fields": spec["fields"]
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
    doc = fitz.open(FORM_METADATA[form_key]["pdf"])
    page = doc[0]
    for fld in FORM_METADATA[form_key]["fields"]:
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
        {"role": "bot",  "content": "Hi! Describe your situation and I’ll find the right form."}
    ]
    st.session_state.form_key = None
    st.session_state.filled   = False

# render all previous messages
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# new user input
if user_input := st.chat_input("…"):
    # 1) echo user
    st.session_state.history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 2) select form
    if st.session_state.form_key is None:
        st.session_state.history.append({"role":"bot","content":"Let me find the right form…"})
        with st.chat_message("bot"):
            st.markdown("Let me find the right form…")

        key = select_form_key(user_input)
        if key == "none":
            bot_txt = (
                "Sorry, I couldn’t match any demo form.  \n\n"
                f"You can browse all USCIS forms here: [USCIS Forms]({FALLBACK_LINK})\n\n"
                "Try another description or ask a human for help."
            )
            st.session_state.history.append({"role":"bot","content":bot_txt})
            st.chat_message("bot").markdown(bot_txt)

        else:
            st.session_state.form_key = key
            title = FORM_METADATA[key]["title"]
            bot_txt = f"I found **{title}**.  Let’s fill it out—please answer the fields."
            st.session_state.history.append({"role":"bot","content":bot_txt})
            st.chat_message("bot").markdown(bot_txt)

    # 3) fill fields (if form selected, before PDF generated)
    elif not st.session_state.filled:
        spec = FORM_METADATA[st.session_state.form_key]
        answers = {}
        st.markdown("### 📝 Please fill these fields:")
        for fld in spec["fields"]:
            answers[fld["name"]] = st.text_input(fld["prompt"], key=fld["name"])
        if st.button("Generate Filled PDF"):
            pdf = fill_pdf_bytes(st.session_state.form_key, answers)
            st.session_state.history.append({"role":"bot","content":"Here’s your filled form:"})
            with st.chat_message("bot"):
                st.download_button(
                    "📄 Download PDF",
                    data=pdf,
                    file_name=f"{st.session_state.form_key}_filled.pdf",
                    mime="application/pdf"
                )
            st.session_state.filled = True

    # 4) done
    else:
        done_txt = "✅ Done! Refresh to start again."
        st.session_state.history.append({"role":"bot","content":done_txt})
        with st.chat_message("bot"):
            st.markdown(done_txt)
