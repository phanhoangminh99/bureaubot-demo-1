# streamlit_app.py

import streamlit as st
import fitz          # PyMuPDF
import io
import json
from pathlib import Path
from huggingface_hub import InferenceApi, HfApi, HfFolder, login

# ─── 1. APP CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Legal Chat & Form Bot", layout="wide")
st.header("🗂️ Legal Chat & Form Bot")

# ─── 2. LOAD YOUR FORMS + METADATA ──────────────────────────────────────────────
FORM_DIR = Path("forms")
FORM_KEYS = [p.stem for p in FORM_DIR.glob("*.pdf")]
FORM_METADATA = {}
for key in FORM_KEYS:
    meta_path = FORM_DIR / f"{key}_meta.json"
    if meta_path.exists():
        spec = json.loads(meta_path.read_text())
        FORM_METADATA[key] = {
            "pdf": str(FORM_DIR / f"{key}.pdf"),
            "title": spec.get("title", key),
            "fields": spec["fields"],
        }

FALLBACK_LINK = "https://www.uscis.gov/forms"

# ─── 3. HUGGINGFACE TOKEN & CLIENT ─────────────────────────────────────────────
hf_token = st.secrets.get("HF_TOKEN", "")
if not hf_token:
    hf_token = st.text_input("Hugging Face API Token", type="password")
if not hf_token:
    st.stop()

# Log in for convenience (stores token)
login(token=hf_token)

# Create an Inference API client for your chosen model
@st.cache_resource
def get_inference_client():
    # you can swap to a private or larger model here
    return InferenceApi(repo_id="google/flan-t5-small", token=hf_token)

inference_client = get_inference_client()


# ─── 4. LLM HELPERS ─────────────────────────────────────────────────────────────
def llm_generate(prompt: str) -> str:
    """
    Calls HF Inference API to generate text for our prompt.
    Falls back to returning the prompt if the call errors.
    """
    try:
        # Hugging Face Text2Text endpoints expect the prompt as-is
        output = inference_client(inputs=prompt)
        # API returns either a string or a dict {"generated_text": ...}
        if isinstance(output, dict) and "generated_text" in output:
            return output["generated_text"]
        return output if isinstance(output, str) else str(output)
    except Exception as e:
        st.warning(f"LLM API call failed: {e}")
        return prompt  # dumb fallback

def select_form_key_via_llm(situation: str) -> str:
    choices = ", ".join(FORM_METADATA.keys())
    prompt = (
        "You are a legal intake assistant.\n"
        f"User situation:\n{situation}\n\n"
        f"Reply with exactly one form key from [{choices}], or 'none'."
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
    key = select_form_key_via_llm(situation)
    # if LLM picked something we don't have, fallback to keywords
    if key in FORM_METADATA:
        return key
    return select_form_key_keyword(situation)


# ─── 5. PDF-FILLER ─────────────────────────────────────────────────────────────
def fill_pdf_bytes(form_key, answers):
    doc = fitz.open(FORM_METADATA[form_key]["pdf"])
    page = doc[0]
    for fld in FORM_METADATA[form_key]["fields"]:
        txt = answers.get(fld["name"], "")
        if not txt:
            continue
        x, y = fld["rect"][:2]
        page.insert_text((x, y), txt, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ─── 6. STREAMLIT CHAT STATE ───────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = [
        {"role":"bot", "content":"Hi! Describe your situation and I’ll find the right form."}
    ]
    st.session_state.form_key = None
    st.session_state.filled   = False

# Render history
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Handle input
if user_msg := st.chat_input("…"):
    st.session_state.history.append({"role":"user","content":user_msg})

    # 6a. Auto‐select form
    if st.session_state.form_key is None:
        st.session_state.history.append({"role":"bot","content":"Let me find the right form…"})
        key = select_form_key(user_msg)
        if key == "none":
            bot = (
                "Sorry, I don’t have that form in my demo.  "
                f"Browse all USCIS forms here: [USCIS Forms]({FALLBACK_LINK})\n\n"
                "You can still ask me other legal questions."
            )
        else:
            st.session_state.form_key = key
            bot = f"I think **{FORM_METADATA[key]['title']}** is right—let’s fill it out.  I’ll ask each field."
        st.session_state.history.append({"role":"bot","content":bot})
        st.chat_message("bot").markdown(bot)

    # 6b. Collect & fill
    elif not st.session_state.filled:
        spec = FORM_METADATA[st.session_state.form_key]
        answers = {}
        st.markdown("### 📝 Please fill these fields:")
        for fld in spec["fields"]:
            answers[fld["name"]] = st.text_input(fld["prompt"], key=fld["name"])
        if st.button("Generate Filled PDF"):
            pdf = fill_pdf_bytes(st.session_state.form_key, answers)
            st.session_state.history.append({"role":"bot","content":"Here's your filled form:"})
            st.chat_message("bot").download_button(
                "📄 Download PDF",
                data=pdf,
                file_name=f"{st.session_state.form_key}_filled.pdf",
                mime="application/pdf"
            )
            st.session_state.filled = True

    # 6c. Free‐form Q&A
    else:
        convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in st.session_state.history)
        prompt = convo + "\nBOT:"
        reply = llm_generate(prompt)
        st.session_state.history.append({"role":"bot","content":reply})
        st.chat_message("bot").markdown(reply)
