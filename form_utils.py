# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.16.7
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: conda-base-py
# ---

# +
import json
from google.cloud import storage
from google import genai
from google.genai import types
import pathlib
import fitz

import json, re, time
import streamlit as st
import google.generativeai as genai
import json, re, time, textwrap

def llm_build_pdf_payload(form_key: str, user_block: str, tries: int = 3) -> dict:
    meta_json = fetch_meta(form_key)
    pdf_text = parse_pdf(form_key)

    base_prompt = textwrap.dedent(f"""
        You are a CBP/EOIR/USCIS/ICE-form-filling expert.

        Form metadata:
        {meta_json}
        
        Form text:
        {pdf_text}
        
        User answers:
        \"\"\"{user_block}\"\"\"

        TASK
        ----
        Return ONE JSON object.
        • Keys = field "name" from metadata that the user clearly answered
        • Values = the user’s answer exactly as written
        • Omit every un-answered field (do NOT output nulls)
        No markdown, no code fences, no prose.
    """)

    for attempt in range(1, tries + 1):
        raw = call_gemini(SYSTEM_PROMPT, base_prompt)
        clean = re.sub(r"^[`]{3}json|[`]{3}$", "", raw.strip(), flags=re.I|re.M).strip()

        try:
            return json.loads(clean)
        except json.JSONDecodeError as e:
            print(f"attempt {attempt}: invalid JSON → {e}")
            if attempt == tries:
                raise
            time.sleep(0.5)                # tiny back-off
            base_prompt = (
                "Your previous reply was not valid JSON. "
                "PLEASE resend only the JSON object, nothing else.\n\n"
                + base_prompt
            )


PROJECT_ID = "adsp-34002-ip07-the-four-musk"
LOCATION   = "us-central1"
MODEL      = "gemini-2.0-flash"
BUCKET     = "adsp-bureaubot-bucket"


storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET)

# Session State
class SessionState:
    def __init__(self):
        self.stage = "select_form"
        self.case_info = ""
        self.form_key = None
        self.fields = []    # list of {"name":…, "label":…}
        self.answers = {}
session = SessionState()

def call_gemini(system_prompt: str, user_prompt: str) -> str:
    # combined to a single user prompt
    combined_prompt = system_prompt.strip() + "\n\n" + user_prompt.strip()

    contents = [
        types.Content(role="user", parts=[types.Part(text=combined_prompt)])
    ]

    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    config = types.GenerateContentConfig(
        temperature=0.2,
        top_p=0.8,
        max_output_tokens=2040,
        response_modalities=["TEXT"],
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF")
        ],
    )

    response = client.models.generate_content_stream(
        model=MODEL, contents=contents, config=config
    )
    return "".join(chunk.text for chunk in response).strip()


SYSTEM_PROMPT = """You are a file filling expert with 30 years experience, extremely detail-oriented.
You help user choose CBP/USCIS/EOIR/ICE forms, list required fields, and guide them to fill.
"""

PROMPT_SELECT_FORM = """
Here is the user’s case description:
\"\"\"
{case_info}
\"\"\"
from only eoir_form_26, uscis_form_ar11, ice_form_i246, and cbp_form_3299
Which form should the user fill?
reply only the form_key (e.g. cbp_form_101)
"""

# PROMPT_SELECT_FORM = """
# You are a CBP form recommendation assistant.

# User description:
# \"\"\"
# {case_info}
# \"\"\"

# Please respond ONLY with one of these two JSON formats:

# 1) If you know exactly which CBP form applies, output:
# {{
#   "form_key": "cbp_form_7507"
# }}

# 2) If you need more information, output:
# {{
#   "clarify": [
#     "Question 1?",
#     "Question 2?",
#     ...
#   ]
# }}

# Do NOT include any additional text or explanation—only output a valid JSON object.
# """

PROMPT_LIST_FIELDS = """
This is the metadata JSON for form {form_key}:
{meta_json}
This is the text parsed from the form {form_key}:
{pdf_text}
From this metadata and pdf text, which fields must the user fill? considering his specific use case, exclude system‐filled ones and keep fields that are only applicable to him
for example, if he said he is single you should not ask him to fill out spouse name. if he is an alien, you should not ask him to fill fields that are only required 
from a US person.
You should also not return fields that should only be filled by the organization, such as "For ICE use only"
reply directly to user, with only human readable field names.
such as
first name:
last name: ... etc
you can rephrase the names in the metadata and refer to text, because they might not be too readable for the user
delete something like Line one of two/line of eight, description of articles Row 2 of 9 because you only need to hint user
for check box or yes or no question, just ask yes or no because users are not access to the checkboxs
Ask him all the fields that needed to be filled
for checkbox ask yes or no
for other fields do not ask yes or no such as income, expense etc

The user will provide all the details in a message and once the user does that your task is 
TASK
        ----
        Return ONE JSON object.
        • Keys = field "name" from metadata that the user clearly answered
        • Values = the user’s answer exactly as written
        • Omit every un-answered field (do NOT output nulls)
        No markdown, no code fences, no prose.
"""


# PROMPT_LIST_FIELDS = """
# This is the metadata JSON for form {form_key}:
# {meta_json}
# From this metadata, which fields must the user fill (exclude system‐filled ones)?
# please strickly only response in json format no other text, so only square brackets and curly brackets
# Do NOT say anything else. ONLY return a JSON array.
# """

# PROMPT_ASK_FIELD = """Please provide the value for the field:
# {name} — {label}
# """



# +
def fetch_meta(form_key: str) -> str:
    meta_path = pathlib.Path("../data") / f"{form_key}_meta.json"
    return meta_path.read_text(encoding="utf-8")

def parse_pdf(form_key: str) -> str:
    pdf_path = pathlib.Path("../data") / f"{form_key}.pdf"
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text

def on_user_message(user_msg: str) -> str:
    if session.stage == "select_form":
        session.case_info += "\n" + user_msg
        prompt = PROMPT_SELECT_FORM.format(case_info=session.case_info)
        form_key = call_gemini(SYSTEM_PROMPT, prompt)
        session.form_key = form_key
        session.stage = "confirm_form"
        return f"I think you need to fill: {form_key}. Do you want me to fill it out with you? yes or no"

    # confirm_form
    if session.stage == "confirm_form":
        if user_msg.lower() in ["yes", "y"]:
            session.stage = "list_fields"
        else:
            session.stage = "select_form"
            session.case_info = ""
            return "OK, please describe your case again."

    # list_fields
    
    if session.stage == "list_fields":
        meta_json = fetch_meta(session.form_key)
        pdf_text = parse_pdf(session.form_key)
        
        prompt    = PROMPT_LIST_FIELDS.format(form_key=session.form_key,
                                              meta_json=meta_json,
                                             pdf_text=pdf_text)
        field_list_msg = call_gemini(SYSTEM_PROMPT, prompt)

        session.stage = "await_bulk_answers"   # <── change
        return field_list_msg                  # ask user to supply everything
#     if session.stage == "list_fields":
        meta_json = fetch_meta(session.form_key)
        # print(meta_json)
        pdf_text = parse_pdf(session.form_key)
#         prompt = PROMPT_LIST_FIELDS.format(form_key=session.form_key, meta_json=meta_json)
#         # print(prompt)
#         # print(call_gemini(SYSTEM_PROMPT, prompt))
#         # fields = json.loads(call_gemini(SYSTEM_PROMPT, prompt))
#         # fields = meta_json
#         # print(fields)
#         # session.fields = fields
#         # print('pass this stage1')
#         session.stage = "fill_fields"
#         # print('pass this stage2')

#         # f0 = fields[0]
#         return call_gemini(SYSTEM_PROMPT, prompt)
#         # return PROMPT_ASK_FIELD.format(name=f0["name"], label=f0["label"])
    # ── NEW BRANCH: user just sent the giant answer block ─────────
    if session.stage == "await_bulk_answers":
        pdf_payload = llm_build_pdf_payload(session.form_key, user_msg)

        if not pdf_payload:
            return ("Sorry — I couldn’t parse your answers into JSON. "
                    "Could you rephrase or supply the information again?")

#         fill_pdf(f"templates/{session.form_key}.pdf",
#                  f"output/{session.form_key}_filled.pdf",
#                  pdf_payload)
        session.stage = "complete"
        return " All set! Your form is filled."

def chat_with_agent(user_message, history):
    backend_reply = on_user_message(user_message)
    history.append(
        types.Content(role="model", parts=[types.Part(text=backend_reply)])
    )
    return backend_reply, history


# -

# user_message = "I am an international student moving back to the US, I need to declare for unaccompaied articals, what form should I fill?" #cbp 3299
# user_message = "I am an alien worker working in the US, I want to change my address what form should I fill out?" # uscis ar11
# user_message = "I am an asylee in the US, but I am getting deported. Is there any form that I can file to get temporary expension for medical reason?" #ice i246
user_message = "My greencard application is denied by the immagration judge, what form should I file to appeal?" # eori 26
conversation_history = []
response, conversation_history = chat_with_agent(user_message, conversation_history)
print(response)

user_message = "yes"
response, conversation_history = chat_with_agent(user_message, conversation_history)
print(response)

user_message="""
Okay, here are my answers:

Page 1:
	•	Name (Last, First, Middle): Goyal, Kanav
	•	Alien (“A”) Number: A123456789
	•	Print name of alien filing the form: Kanav Goyal
	•	Signature of Alien Filing the Form: Kanav Goyal
	•	Date (of signature): 05/26/2025
	•	Income from Employment, including self-employment: $1,200.00
	•	Income from real property (such as rental income): $0.00
	•	Interest from checking and/or saving account(s): $0.00
	•	All other income (including alimony, child support, interest, dividends, social security, annuities, unemployment, public assistance, etc.): $0.00
	•	Total Average Monthly Income: $1,200.00

Page 2:
	•	Rent or home-mortgage payment(s): $800.00
	•	Utilities: $150.00
	•	Installment payments or outstanding debts: $100.00
	•	Living expenses: $300.00
	•	All other expenses: $0.00
	•	Total Average Monthly Expenses: $1,350.00
	•	Total Average Monthly Income (from page 1): $1,200.00
	•	Total Average Monthly Expenses (from page 2): $1,350.00
	•	Total (Income minus Expenses): -$150.00
	•	Provide any other information that will help explain why you cannot pay the filing fees:
I’m currently a full-time student with limited income. After covering basic living costs, I do not have enough left to pay the filing fees. I’m requesting a fee waiver due to financial hardship.
	•	Attorney or Representative present? No
	•	Signature of Attorney or Representative: N/A
	•	Print Name of Attorney or Representative: N/A
	•	EOIR ID Number of Attorney or Representative: N/A
	•	Date: N/A
    """

response, conversation_history = chat_with_agent(user_message, conversation_history)
print(response)



# +
# ------------------------------------------------------------------
# 1) Build the payload using the helper you already added
# ------------------------------------------------------------------
form_key    = "eoir_form_26"
pdf_payload = llm_build_pdf_payload(form_key, user_message)

# ------------------------------------------------------------------
# 2) Pretty-print it so you can inspect every key/value pair
# ------------------------------------------------------------------
import json, pprint
pprint.pp(pdf_payload, width=120)          # Python 3.9+ pretty-print
# or:
# print(json.dumps(pdf_payload, indent=2))   # JSON-style
# -

# !pwd

# !ls "/home/jupyter/adsp-bureaubot-bucket"

# !ls "/home/jupyter/adsp-bureaubot-bucket/data"

# +
import fitz, pathlib

# ---------------------------------------------------------
# 0)  Paths and the answers dict you already built
# ---------------------------------------------------------
pdf_path  = pathlib.Path("/home/jupyter/adsp-bureaubot-bucket/data/eoir_form_26.pdf")
save_path = pathlib.Path("/home/jupyter/Temp/EOIR-26A_filled2.pdf")

answers = pdf_payload

# ---------------------------------------------------------
# 1)  Open, iterate, and populate widgets
# ---------------------------------------------------------
doc = fitz.open(pdf_path)

for page in doc:
    for w in page.widgets() or []:
        name = w.field_name
        if name in answers:
            w.field_value = str(answers[name])
            w.update()

# ---------------------------------------------------------
# 2)  Save the filled PDF
# ---------------------------------------------------------
doc.save(save_path, deflate=True)   # deflate shrinks & flattens
doc.close()

print(f"✔ Filled form saved to: {save_path}")
# -


