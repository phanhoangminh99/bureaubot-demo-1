# streamlit_app.py

import streamlit as st
import fitz          # PyMuPDF
import io
import json
from pathlib import Path
from huggingface_hub import InferenceApi, login

# ─── 1. APP CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Legal Chat & Form Bot", layout="wide")
st.header("🗂️ Legal Chat & Form Bot")

# ─── 2. LOAD FORMS + METADATA ──────────────────────────────────────────────────
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

# ─── 3. HUGGING FACE INFERENCE API ──────────────────────────────────────────────
hf_token = st.secrets.get("HF_TOKEN", "")
if not hf_token:
    hf_token = st.text_input("Hugging Face API Token", type="password")
if not hf_token:
    st.stop()

login(token=hf_token)

@st.cache_resource
def get_client():
    return InferenceApi(repo_id="google/flan-t5-small", token=hf_token)

client = get_client()

# ─── 4. LLM & KEYWORD FORM SELECTION ────────────────────────────────────────────
def llm_select(situation: str) -> str:
    prompt = (
        "You are a legal intake assistant.\n"
        f"User situation:\n{situation}\n\n"
        f"Reply with exactly one form key from [{', '.join(FORM_METADATA.keys())}], or 'none'."
    )
    try:
        out = client(inputs=prompt, raw_response=True)
        first_line = out.content.decode("utf-8").splitlines()[0]
        return first_line.strip().lower().strip(" .,'\"")
    except Exception as e:
        st.warning(f"LLM error: {e}")
        return "none"

def keyword_select(situation: str) -> str:
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

def auto_select(situation: str):
    # 1) Try LLM
    key = llm_select(situation)
    if key in FORM_METADATA:
        return key, "LLM"
    # 2) Fallback to keyword
    key2 = keyword_select(situation)
    if key2 in FORM_METADATA:
        return key2, "keyword"
    # 3) none
    return "none", "none"

# ─── 5. PDF FILLER ─────────────────────────────────────────────────────────────
def fill_pdf_bytes(form_key, answers):
    doc = fitz.open(FORM_METADATA[form_key]["pdf"])
    page = doc[0]
    for fld in FORM_METADATA[form_key]["fields"]:
        v = answers.get(fld["name"], "")
        if v:
            x, y = fld["rect"][:2]
            page.insert_text((x, y), v, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

# ─── 6. CHAT STATE ─────────────────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = [
        {"role":"bot", "content":"Hi! Describe your situation and I’ll find the right form."}
    ]
    st.session_state.form_key = None
    st.session_state.via       = None
    st.session_state.filled    = False

# Render entire chat
for m in st.session_state.history:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# Handle user input
if msg := st.chat_input("…"):
    st.session_state.history.append({"role":"user","content":msg})

    # --- Step A: auto-select form ---
    if st.session_state.form_key is None:
        st.session_state.history.append({"role":"bot","content":"Looking up the right form…"})
        key, via = auto_select(msg)
        st.session_state.via = via

        if key == "none":
            bot = (
                "Sorry, I couldn’t match any demo form.  "
                f"Browse all USCIS forms here: [USCIS Forms]({FALLBACK_LINK})\n\n"
                "You can ask another question or try a different description."
            )
        else:
            st.session_state.form_key = key
            title = FORM_METADATA[key]["title"]
            bot = f"I’ve selected **{title}** (via {via}). Let’s fill it out—please answer the following."

        st.session_state.history.append({"role":"bot","content":bot})
        st.chat_message("bot").markdown(bot)

    # --- Step B: collect fields & generate PDF ---
    elif not st.session_state.filled:
        spec = FORM_METADATA[st.session_state.form_key]
        answers = {}
        st.markdown("### 📝 Fill these fields:")
        for fld in spec["fields"]:
            answers[fld["name"]] = st.text_input(fld["prompt"], key=fld["name"])
        if st.button("Generate Filled PDF"):
            pdf_bytes = fill_pdf_bytes(st.session_state.form_key, answers)
            st.session_state.history.append({"role":"bot","content":"Here’s your filled form:"})
            st.chat_message("bot").download_button(
                "📄 Download PDF",
                data=pdf_bytes,
                file_name=f"{st.session_state.form_key}_filled.pdf",
                mime="application/pdf"
            )
            st.session_state.filled = True

    # --- Step C: finished ---
    else:
        # You could loop back to a new form here; for now we end.
        st.session_state.history.append({
            "role":"bot",
            "content":"✅ Done! Refresh the page to start again."
        })
        st.chat_message("bot").markdown("✅ Done! Refresh the page to start again.")
