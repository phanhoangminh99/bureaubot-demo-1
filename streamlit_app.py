import streamlit as st
import fitz         # PyMuPDF
import io
import json
from pathlib import Path

# ─── 1. APP CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Legal Chat & Form Bot", layout="wide")
st.header("🗂️ Legal Chat & Form Bot")

# ─── 2. GET HF TOKEN ────────────────────────────────────────────────────────────
hf_token = st.secrets.get("HF_TOKEN", "")
if not hf_token:
    hf_token = st.text_input("Hugging Face API Token", type="password")
if not hf_token:
    st.stop()

# ─── 3. LOAD FORMS + META ───────────────────────────────────────────────────────
FORM_DIR = Path("forms")
FORM_METADATA = {}
for pdf_path in FORM_DIR.glob("*.pdf"):
    key = pdf_path.stem
    meta_path = FORM_DIR / f"{key}_meta.json"
    if meta_path.exists():
        spec = json.loads(meta_path.read_text())
        FORM_METADATA[key] = {
            "pdf":  str(pdf_path),
            "title": spec.get("title", key),
            "fields": spec["fields"]
        }

FALLBACK_LINK = "https://www.uscis.gov/forms"

# ─── 4. DYNAMIC HF LOADER WITH MULTI-FALLBACK ──────────────────────────────────
@st.cache_resource
def get_llm(token: str):
    from transformers import pipeline
    candidates = [
        "google/flan-t5-small",
        "t5-small",
        "EleutherAI/gpt-neo-125M"
    ]
    for model_name in candidates:
        try:
            st.info(f"Loading HF model `{model_name}`…")
            pipe = pipeline(
                "text2text-generation",
                model=model_name,
                device=-1,
                use_auth_token=token,
                max_length=128,
                truncation=True
            )
            st.success(f"✅ Loaded `{model_name}`")
            return pipe
        except Exception as e:
            st.warning(f"⚠️ Failed to load `{model_name}`: {e}")
    st.error("❌ All HF models failed. Falling back to keyword-only mode.")
    return None

llm = get_llm(hf_token)

# ─── 5. HELPERS ────────────────────────────────────────────────────────────────
def llm_generate(prompt: str) -> str:
    return llm(prompt)[0]["generated_text"].strip() if llm else prompt

def select_form_key_llm(situation: str) -> str:
    keys = ", ".join(FORM_METADATA.keys())
    prompt = (
        f"You are a legal assistant. User situation:\n{situation}\n\n"
        f"Reply with exactly one form key from [{keys}], or 'none'."
    )
    resp = llm_generate(prompt)
    return resp.split()[0].lower()

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
    if llm:
        key = select_form_key_llm(situation)
        if key in FORM_METADATA:
            return key
    return select_form_key_keyword(situation)

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

# ─── 6. STREAMLIT CHAT STATE ───────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.update({
        "history": [{"role":"bot","content":"Hi! Describe your situation and I’ll find the right form."}],
        "form_key": None,
        "filled": False
    })

# Render chat
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Handle user input
if user_msg := st.chat_input("…"):
    st.session_state.history.append({"role":"user","content":user_msg})

    # 1) Auto-select form
    if st.session_state.form_key is None:
        st.session_state.history.append({"role":"bot","content":"🔎 Finding the right form…"})
        key = select_form_key(user_msg)
        if key == "none":
            reply = (
                "I couldn’t match a form in the demo. "
                f"Browse all USCIS forms here: [USCIS Forms]({FALLBACK_LINK})\n\n"
                "You can still ask me other legal questions."
            )
        else:
            st.session_state.form_key = key
            reply = f"I think **{FORM_METADATA[key]['title']}** is it—let’s fill it out. I’ll ask each field."
        st.session_state.history.append({"role":"bot","content":reply})
        st.chat_message("bot").markdown(reply)

    # 2) Collect & fill PDF
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

    # 3) Free-form Q&A
    else:
        convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in st.session_state.history)
        prompt = convo + "\nBOT:"
        bot_reply = llm_generate(prompt) if llm else "I can’t chat right now—LLM offline."
        st.session_state.history.append({"role":"bot","content":bot_reply})
        st.chat_message("bot").markdown(bot_reply)
