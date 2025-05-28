import streamlit as st
import fitz         # PyMuPDF
import io
import json
from pathlib import Path
from transformers import pipeline

# 1. APP CONFIG
st.set_page_config(page_title="Legal Chat & Form Bot", layout="wide")
st.header("🗂️ Legal Chat & Form Bot")

# 2. LOAD YOUR FORMS + METADATA
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

# 3. LOAD A PUBLIC HF MODEL
@st.cache_resource
def get_llm():
    return pipeline(
        "text2text-generation",
        model="google/flan-t5-base",
        device=-1  # CPU
    )

llm = get_llm()

# 4. LLM HELPERS
def llm_generate(prompt: str) -> str:
    out = llm(prompt, max_length=256, do_sample=False)[0]["generated_text"]
    return out.strip()

def select_form_key(situation: str) -> str:
    choices = ", ".join(FORM_METADATA.keys())
    prompt = (
        f"You are a legal intake assistant.\n"
        f"User situation:\n{situation}\n"
        f"Based on the above, reply with exactly one form key from [{choices}], "
        f"or 'none' if no match."
    )
    resp = llm_generate(prompt)
    return resp.split()[0]

# 5. PDF-FILLER
def fill_pdf_bytes(form_key, answers):
    doc = fitz.open(FORM_METADATA[form_key]["pdf"])
    page = doc[0]
    for fld in FORM_METADATA[form_key]["fields"]:
        name = fld["name"]
        val  = answers.get(name, "")
        if not val:
            continue
        x, y = fld["rect"][:2]
        page.insert_text((x, y), val, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

# 6. STREAMLIT CHAT STATE
if "history" not in st.session_state:
    st.session_state.history = [
        {"role":"bot", "content":"Hi there! Describe your situation and I’ll find the right form."}
    ]
    st.session_state.form_key = None
    st.session_state.filled   = False

# Render chat
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Handle new user input
if user_msg := st.chat_input("…"):
    st.session_state.history.append({"role":"user","content":user_msg})

    # 6a. Auto‐select form
    if st.session_state.form_key is None:
        st.session_state.history.append({"role":"bot","content":"Let me find the right form…"})
        form_key = select_form_key(user_msg)
        if form_key.lower() == "none" or form_key not in FORM_METADATA:
            bot_txt = (
                "I couldn't match a demo form. Browse all USCIS forms here:\n\n"
                f"[USCIS Forms]({FALLBACK_LINK})\n\n"
                "You can also ask me other legal questions."
            )
        else:
            st.session_state.form_key = form_key
            title = FORM_METADATA[form_key]["title"]
            bot_txt = f"I think **{title}** is right. Let’s fill it out—I'll ask each field."
        st.session_state.history.append({"role":"bot","content":bot_txt})
        st.chat_message("bot").markdown(bot_txt)

    # 6b. Collect & fill
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
