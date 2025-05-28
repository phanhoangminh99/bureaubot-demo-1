import json, pathlib, textwrap, fitz
import streamlit as st
from google import genai
from google.genai import types

# 1) Initialize Google GenAI
#   Put your Gemini API key into Streamlit secrets (or env var)
genai_client = genai.GenerativeAI()
genai_client.init(api_key=st.secrets["GEMINI_API_KEY"])

# 2) Helpers (adapted from notebook)
def fetch_meta(form_key): 
    return (pathlib.Path("data")/f"{form_key}_meta.json").read_text()

def parse_pdf(form_key):
    doc = fitz.open(str(pathlib.Path("data")/f"{form_key}.pdf"))
    text = "".join(p.get_text() for p in doc)
    doc.close()
    return text

def llm_build_pdf_payload(form_key, user_block):
    meta_json = fetch_meta(form_key)
    pdf_text = parse_pdf(form_key)
    prompt = textwrap.dedent(f"""
      You are a CBP/EOIR/ICE/USCIS form-filling expert.
      Here is the form metadata:
      {meta_json}
      Here is the user’s description of their case:
      {user_block}
      Return a JSON object mapping each field name to the exact value.
    """)
    resp = genai_client.chat.advance(
      model="models/text-bison-001",
      messages=[
        types.Message(role="system", content=prompt)
      ]
    )
    return json.loads(resp.last.message.content)

def fill_pdf(form_key, answers):
    in_path = pathlib.Path("data")/f"{form_key}.pdf"
    out_path = pathlib.Path("output")/f"{form_key}_filled.pdf"
    doc = fitz.open(in_path)
    for page in doc:
        for w in page.widgets() or []:
            name = w.field_name
            if name in answers:
                w.field_value = str(answers[name])
                w.update()
    doc.save(out_path, deflate=True)
    doc.close()
    return out_path

# 3) Session state for a chat
if "stage" not in st.session_state:
    st.session_state.stage = "select_form"
    st.session_state.case_info = ""
    st.session_state.form_key = None

st.title("📝 Form-Filling Bot")

# 4) Form selection UI
if st.session_state.stage == "select_form":
    choice = st.selectbox("Which form do you need?", [
      "eoir_form_26", "uscis_form_ar11", "ice_form_i246", "cbp_form_3299"
    ])
    if st.button("Choose form"):
        st.session_state.form_key = choice
        st.session_state.stage = "fill_info"

# 5) Ask case information
elif st.session_state.stage == "fill_info":
    user_block = st.text_area("Tell me about your situation…", height=150)
    if st.button("Submit"):
        st.session_state.case_info = user_block
        st.session_state.stage = "complete"

# 6) Generate & fill PDF
elif st.session_state.stage == "complete":
    with st.spinner("Building payload & filling PDF…"):
        answers = llm_build_pdf_payload(st.session_state.form_key,
                                        st.session_state.case_info)
        out_file = fill_pdf(st.session_state.form_key, answers)
    st.success("✅ Done! Here’s your filled form:")
    with open(out_file, "rb") as f:
        st.download_button("Download PDF", f, file_name=out_file.name)
