import streamlit as st
import json
from form_utils import fetch_meta, llm_build_pdf_payload, call_gemini

st.title("📄 Immigration Form Filler Demo")

# 1) Choose your form
form_key = st.selectbox("Select a form:", [
    "eoir_form_26", "uscis_form_ar11", "ice_form_i246", "cbp_form_3299"
])

# 2) Load its questions
meta = fetch_meta(form_key)
answers = {}
st.write("Fill in the fields below:")
for q in meta["questions"]:
    answers[q["name"]] = st.text_input(q["prompt"])

# 3) When ready, press to generate
if st.button("Generate filled JSON"):
    # Format answers as simple user_block
    user_block = "\n".join(f"{k}: {v}" for k, v in answers.items() if v)
    payload = llm_build_pdf_payload(form_key, user_block)
    st.subheader("Result")
    st.json(payload)
    st.download_button("Download JSON", json.dumps(payload, indent=2), f"{form_key}_filled.json")
