import streamlit as st
import json
import os
import google.generativeai as genai

# ——— Configuration ———
st.set_page_config(page_title="BureauBot")
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# ——— Supported forms ———
FORMS = {
    "eoir_form_26": "EOIR-26: Appeal a deportation decision",
    "uscis_form_ar11": "USCIS AR-11: Change of address",
    "ice_form_i246": "ICE I-246: Request stay of removal",
    "cbp_form_3299": "CBP Form 3299: Import personal effects"
}

def fetch_meta(form_key: str) -> list[dict]:
    """Load questions list from local JSON file."""
    path = f"{form_key}_meta.json"
    if os.path.exists(path):
        return json.load(open(path, "r", encoding="utf-8")).get("questions", [])
    return []

def call_gemini(prompt: str) -> str:
    model = genai.GenerativeModel("gemini-pro")
    return model.generate_content(prompt).text

def build_payload(form_key: str, answers: dict) -> dict:
    questions = fetch_meta(form_key)
    # Build a prompt if you want to use Gemini; here we skip LLM and just return answers
    return answers

# ——— UI ———
st.title("📝 Immigration Form Demo")

# 1) Form selector
form_key = st.selectbox("Choose which form to fill:", list(FORMS.keys()), format_func=lambda k: FORMS[k])

# 2) Load and display questions
questions = fetch_meta(form_key)
st.header("Please fill out these fields:")

answers = {}
for q in questions:
    answers[q["name"]] = st.text_input(q["prompt"])

# 3) Generate & download
if st.button("Generate JSON"):
    payload = build_payload(form_key, answers)
    st.subheader("Here’s your filled form data:")
    st.json(payload)
    st.download_button(
        "Download JSON",
        json.dumps(payload, indent=2),
        file_name=f"{form_key}_filled.json",
        mime="application/json"
    )
