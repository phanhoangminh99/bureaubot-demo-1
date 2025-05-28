import json
import os
import re
import time
import streamlit as st
import google.generativeai as genai

# --- Load metadata from local .json files ---
def fetch_meta(form_key: str) -> dict:
    path = f"{form_key}_meta.json"
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {"questions": []}

# --- Skip PDF parsing for now ---
def parse_pdf(form_key: str) -> str:
    return f"(PDF text for {form_key} skipped in cloud version)"

# --- Real Gemini call using API key ---
def call_gemini(system_prompt: str, user_prompt: str) -> str:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-pro")
    prompt = system_prompt.strip() + "\n\n" + user_prompt.strip()
    response = model.generate_content(prompt)
    return response.text.strip()

# --- Build filled form using Gemini ---
def llm_build_pdf_payload(form_key: str, user_block: str, tries: int = 3) -> dict:
    meta = fetch_meta(form_key)
    pdf_text = parse_pdf(form_key)

    base_prompt = f"""
You are a CBP/EOIR/USCIS/ICE-form-filling expert.

Form metadata:
{json.dumps(meta)}

Form text:
{pdf_text}

User answers:
"""{user_block}"""

TASK
----
Return ONE JSON object.
• Keys = field "name" from metadata that the user clearly answered
• Values = the user’s answer exactly as written
• Omit every un-answered field (do NOT output nulls)
No markdown, no code fences, no prose.
"""

    for attempt in range(1, tries + 1):
        raw = call_gemini("", base_prompt)
        clean = re.sub(r"^[`]{3}json|[`]{3}$", "", raw.strip(), flags=re.I|re.M).strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError as e:
            if attempt == tries:
                raise
            time.sleep(0.5)

    return {}