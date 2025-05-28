import streamlit as st
import json
import os
import re
import time
import google.generativeai as genai

# ——— Configuration ———
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
SUPPORTED_FORMS = [
    "eoir_form_26",
    "uscis_form_ar11",
    "ice_form_i246",
    "cbp_form_3299",
]

# ——— Helpers (inlined) ———
def fetch_meta(form_key: str) -> dict:
    path = f"{form_key}_meta.json"
    if os.path.exists(path):
        # Load the JSON string from disk, then parse it into a dict
        raw = open(path, "r", encoding="utf-8").read()
        return json.loads(raw)
    return {"questions": []}

def parse_pdf(form_key: str) -> str:
    """Stub—skip actual PDF parsing for demo."""
    return f"(PDF text for {form_key} skipped)"

def call_gemini(system_prompt: str, user_prompt: str) -> str:
    """Call Gemini and return raw text."""
    prompt = system_prompt.strip() + "\n\n" + user_prompt.strip()
    model = genai.GenerativeModel("gemini-pro")
    return model.generate_content(prompt).text.strip()

def llm_build_pdf_payload(form_key: str, user_block: str, tries: int = 3) -> dict:
    """Build the filled JSON payload."""
    meta = fetch_meta(form_key)
    pdf_text = parse_pdf(form_key)
    base_prompt = f"""
You are a form-filling expert.

Form metadata:
{json.dumps(meta)}

Form text:
{pdf_text}

User answers:
\"\"\"{user_block}\"\"\"

Return exactly one JSON object mapping each metadata 'name' to the user's answer. Omit any unanswered fields.
"""
    for i in range(tries):
        raw = call_gemini("", base_prompt)
        raw = re.sub(r"^[`]{3}json|[`]{3}$", "", raw, flags=re.I).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            time.sleep(0.5)
    raise ValueError("Failed to parse JSON from LLM response.")

# ——— Streamlit App ———
st.set_page_config(page_title="Immigration Form Assistant")
st.title("📝 Immigration Form Assistant (Demo)")

# 1) Select form
form_key = st.selectbox("Choose a form:", SUPPORTED_FORMS)

# 2) Load questions and collect answers
meta = fetch_meta(form_key)
st.subheader("Please answer the following:")
answers = {}
for q in meta.get("questions", []):
    answers[q["name"]] = st.text_input(q["prompt"])

# 3) Generate output
if st.button("Generate Filled JSON"):
    user_block = "\n".join(f"{k}: {v}" for k, v in answers.items() if v)
    result = llm_build_pdf_payload(form_key, user_block)
    st.subheader("Here’s your filled form data:")
    st.json(result)
    st.download_button(
        "Download JSON",
        data=json.dumps(result, indent=2),
        file_name=f"{form_key}_filled.json",
        mime="application/json",
    )
