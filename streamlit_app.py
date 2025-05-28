# app.py
# aaa

import streamlit as st
import time, json, re, textwrap, pathlib
import fitz
from google.cloud import storage
from google import genai
from google.genai import types
import os
from google.auth.credentials import AnonymousCredentials
# from google.genai.client import ClientOptions
import google.generativeai as genai
api_key = os.environ.get("GOOGLE_API_KEY")
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

# —————— 配置參數 ——————
PROJECT_ID = "adsp-34002-ip07-the-four-musk"
LOCATION   = "us-central1"
MODEL      = "gemini-2.0-flash"
BUCKET     = "adsp-bureaubot-bucket"

SYSTEM_PROMPT = """You are a file filling expert with 30 years experience, extremely detail-oriented.
You help user choose CBP/USCIS/EOIR/ICE forms, list required fields, and guide them to fill.
"""

PROMPT_SELECT_FORM = """
Here is the user’s case description:
\"\"\"{case_info}\"\"\"
from only eoir_form_26, uscis_form_ar11, ice_form_i246, and cbp_form_3299
Which form should the user fill?
reply only the form_key (e.g. cbp_form_101)
"""

PROMPT_LIST_FIELDS = """
This is the metadata JSON for form {form_key}:
{meta_json}
This is the text parsed from the form {form_key}:
{pdf_text}
From this metadata and pdf text, which fields must the user fill?
…
Reply directly to user, with only human readable field names.
"""

# —————— 工具函式 ——————
def fetch_meta(form_key: str) -> str:
    return pathlib.Path(f"{form_key}_meta.json").read_text(encoding="utf-8")

def parse_pdf(form_key: str) -> str:
    doc = fitz.open(f"{form_key}.pdf")
    txt = "".join([p.get_text() for p in doc])
    doc.close()
    return txt

def call_gemini(system_prompt: str, user_prompt: str) -> str:
    combined = system_prompt.strip() + "\n\n" + user_prompt.strip()
    # client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    # client = genai.Client(
    # credentials=AnonymousCredentials(),
    # client_options=ClientOptions(api_key=api_key),
    # project=PROJECT_ID,
    # location=LOCATION,
    # )
    # contents = [ types.Content(role="user", parts=[types.Part(text=combined)]) ]
    # cfg = types.GenerateContentConfig(
    #     temperature=0.2, top_p=0.8, max_output_tokens=2040,
    #     response_modalities=["TEXT"],
    #     safety_settings=[
    #         types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
    #         # … 其他設定 …
    #     ],
    # )
    # stream = client.models.generate_content_stream(model=MODEL, contents=contents, config=cfg)
    model = genai.GenerativeModel("gemini-1.5-flash")  # 你也可以改成 gemini-pro

    response = model.generate_content(combined)

    return response.text.strip()
    # return "".join(ch.text for ch in stream).strip()

def llm_build_pdf_payload(form_key: str, user_block: str, tries: int = 3) -> dict:
    meta_json = fetch_meta(form_key)
    pdf_text = parse_pdf(form_key)
    base = textwrap.dedent(f"""
        You are a CBP/EOIR/USCIS/ICE-form-filling expert.
        Form metadata:
        {meta_json}
        Form text:
        {pdf_text}
        User answers:
        \"\"\"{user_block}\"\"\"
        TASK
        ----
        Return ONE JSON object…
    """)
    for i in range(tries):
        raw = call_gemini(SYSTEM_PROMPT, base)
        clean = re.sub(r"^[`]{3}json|[`]{3}$", "", raw, flags=re.I).strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            time.sleep(0.5)
    st.error("Failed to parse JSON from LLM.")
    return {}

# —————— Session State ——————
if "stage" not in st.session_state:
    st.session_state.stage     = "select_form"
    st.session_state.case_info = ""
    st.session_state.form_key  = ""
    st.session_state.answers   = {}

# —————— Streamlit UI ——————
st.title("🗂️ Form-Filling Assistant")

# 歷史訊息顯示
if "history" not in st.session_state:
    st.session_state.history = []

for msg in st.session_state.history:
    speaker = "You" if msg["role"]=="user" else "Bot"
    st.write(f"**{speaker}:** {msg['text']}")

# 使用者輸入
user_input = st.text_input("Your message:", key="inp")
if st.button("Send") and user_input:
    # 顯示使用者訊息
    st.session_state.history.append({"role":"user", "text":user_input})

    # 呼叫後端
    reply = ""
    # 選表單階段
    if st.session_state.stage == "select_form":
        st.session_state.case_info += "\n" + user_input
        prompt = PROMPT_SELECT_FORM.format(case_info=st.session_state.case_info)
        fk = call_gemini(SYSTEM_PROMPT, prompt)
        st.session_state.form_key = fk
        st.session_state.stage = "confirm_form"
        reply = f"I think you need to fill: **{fk}**. Confirm? (yes/no)"

    # 確認階段
    elif st.session_state.stage == "confirm_form":
        if user_input.lower().startswith("y"):
            st.session_state.stage = "list_fields"
            reply = "Great—let me list the fields."
        else:
            st.session_state.stage = "select_form"
            st.session_state.case_info = ""
            reply = "Okay, describe your case again."

    # 列欄位階段
    elif st.session_state.stage == "list_fields":
        meta = fetch_meta(st.session_state.form_key)
        pdf  = parse_pdf(st.session_state.form_key)
        prompt = PROMPT_LIST_FIELDS.format(
            form_key=st.session_state.form_key,
            meta_json=meta, pdf_text=pdf
        )
        reply = call_gemini(SYSTEM_PROMPT, prompt)
        st.session_state.stage = "await_bulk_answers"

    # 填寫欄位階段
    elif st.session_state.stage == "await_bulk_answers":
        payload = llm_build_pdf_payload(st.session_state.form_key, user_input)
        if payload:
            st.session_state.answers = payload
            st.session_state.stage = "complete"
            reply = "✅ All set! Your form is filled."
        else:
            reply = "Sorry, could not parse your answers. Try again?"

    else:
        reply = "Session completed. Refresh to start over."

    st.session_state.history.append({"role":"bot", "text":reply})
    st.experimental_rerun()
