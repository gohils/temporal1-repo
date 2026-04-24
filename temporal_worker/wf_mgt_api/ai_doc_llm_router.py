import os
import json
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient
from openai import OpenAI

app = FastAPI(title="Enterprise Cognitive AI + LLM Reasoning API")
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any
import os
import json
from openai import OpenAI

# ---------------------------
# Environment Validation
# ---------------------------
def get_openai_key():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    return key

OPENAI_API_KEY = get_openai_key()
AZURE_ENDPOINT = os.getenv("AZURE_DOC_INT_API_ENDPOINT")
AZURE_API_KEY = os.getenv("AZURE_DOC_INT_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set")

if not AZURE_ENDPOINT or not AZURE_API_KEY:
    raise RuntimeError("Azure Document Intelligence credentials not set")

router = APIRouter(
    prefix="/ai_doc_llm",
    tags=["llm"]
)

# ---------------------------
# Clients
# ---------------------------
class AIClients:
    _llm_client = None
    _doc_client = None

    @classmethod
    def llm(cls):
        if cls._llm_client is None:
            cls._llm_client = OpenAI(
                api_key=get_openai_key()
            )
        return cls._llm_client

    @classmethod
    def doc_ai(cls):
        if cls._doc_client is None:
            cls._doc_client = DocumentAnalysisClient(
                endpoint=os.getenv("AZURE_DOC_INT_API_ENDPOINT"),
                credential=AzureKeyCredential(
                    os.getenv("AZURE_DOC_INT_API_KEY")
                )
            )
        return cls._doc_client

# ---------------------------
# LLM Reasoning
# ---------------------------
# ---------------------------
DEFAULT_PROMPT = """
You are an AI decision engine replacing a human decision-maker in a business workflow.
Return valid JSON only.
Workflow Context:
Invoice Details:
{ "invoice_number": "INV-2026-001",  "vendor": "ACME Supplies",  "invoice_date": "2026-03-01",
  "line_items": [ { "item": "Laptop", "quantity": 10, "unit_price": 13000} ],
  "total_amount": 13000 USD,
  "additional_notes": "Urgent procurement"
}

Business Rule:
- If invoice total > 10,000 USD → HIGH_VALUE , Otherwise → NORMAL

Task:
1. Review the full invoice context above.
2. Decide if this invoice is HIGH_VALUE or NORMAL.

Return JSON only with these keys:
{
  "invoice_key_details": {  },
  "invoice_valuation": "HIGH_VALUE | NORMAL",
  "details": "reasoning for audit"
}
"""

class LLMRequest(BaseModel):
    input_prompt: str = DEFAULT_PROMPT
    model: str = "gpt-4o-mini"
    temperature: float = 0
    max_tokens: int = 100

class LLMResponse(BaseModel):
    response_json: Dict[str, Any]
    response_raw_text: str
    input_context: str

@router.post("/ai-reasoning", response_model=LLMResponse)
async def ai_reasoning(request: LLMRequest):

    response = AIClients.llm().chat.completions.create(
        model=request.model,
        messages=[
            {"role": "system", "content": "You are an AI decision engine replacing a human decision-maker in a business workflow."},
            {"role": "user", "content": request.input_prompt}
        ],
        temperature=request.temperature,
        max_tokens=request.max_tokens
    )

    raw = response.choices[0].message.content
    # print("Received LLM reasoning request. Processing..request.input_prompt :\n", request.input_prompt)
    # print("Raw LLM response:\n", raw)
    try:
        output = json.loads(raw)
    except json.JSONDecodeError:
        output = {"decision": None, "confidence": None, "reasoning_trace": raw}

    return LLMResponse(
        response_json=output,
        response_raw_text=raw,
        input_context=request.input_prompt
    )

# ---------------------------
# OCR Request Model
# ---------------------------
class AnalyzeRequest(BaseModel):
    ai_model_name: str = "prebuilt-read"
    document_url: str = "https://zblobarchive.blob.core.windows.net/samples/aus-passport-sample1.png"
    response_format: str = "plain_text"

# ---------------------------
# Extraction Helpers
# ---------------------------
def extract_plain_text(result):
    return "\n\n".join(
        "\n".join(line.content for line in page.lines) for page in result.pages
    )

def extract_flat_fields(result):
    docs = []
    for doc in result.documents:
        data = {}
        for k, f in (doc.fields or {}).items():
            data[k] = (
                getattr(f, "value_string", None)
                or str(getattr(f, "value_date", None))
                or getattr(f, "value_number", None)
                or getattr(getattr(f, "value_currency", None), "amount", None)
                or getattr(f, "content", None)
            )
        docs.append(data)
    return docs

def extract_structured(result):
    docs = []
    for doc in result.documents:
        header, items = {}, []
        for k, f in doc.fields.items():
            if k.lower() != "items" and hasattr(f, "content"):
                header[k] = f.content
        items_field = doc.fields.get("Items")
        if items_field and hasattr(items_field, "value"):
            for item in items_field.value:
                items.append({k: getattr(v, "content", None) for k, v in item.value.items()})
        docs.append({"header": header, "items": items})
    return docs

# ---------------------------
# OCR Endpoint
# ---------------------------
@router.post("/analyze-document-prebuilt-model")
async def analyze_document(request: AnalyzeRequest):
    """Endpoint to analyze document using specified prebuilt model
       \nai_model_name : prebuilt-read, prebuilt-layout, prebuilt-idDocument, prebuilt-invoice, prebuilt-receipt
      \n return format : plain_text, flat, structured (in header-item format).
    """
    try:
        poller = AIClients.doc_ai().begin_analyze_document_from_url(
            model_id=request.ai_model_name,
            document_url=request.document_url
        )
        result = poller.result()

        if request.response_format == "plain_text":
            extracted = extract_plain_text(result)
        elif request.response_format == "flat":
            extracted = extract_flat_fields(result)
        elif request.response_format == "structured":
            extracted = extract_structured(result)
        else:
            raise HTTPException(400, "Invalid response_format")

        return {
            "model_used": request.ai_model_name,
            "response_format": request.response_format,
            "documents": extracted
        }

    except Exception as e:
        raise HTTPException(500, str(e))
