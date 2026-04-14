import os, uuid
from dotenv import load_dotenv

from fastapi import APIRouter, UploadFile, HTTPException
from azure.storage.blob import BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient

router = APIRouter(prefix="/ai_doc", tags=["AI Document Analysis"])

# --- ENV ---
CONNECT_STR = os.getenv("blob_storage_connect_str")
CONTAINER = os.getenv("container_name", "documents")
ENDPOINT = os.getenv("AZURE_DOC_INT_API_ENDPOINT")
API_KEY = os.getenv("AZURE_DOC_INT_API_KEY")


# --- SINGLETON CLIENTS ---
class AzureClients:
    _doc_client = None
    _blob_client = None

    @classmethod
    def doc_client(cls):
        if cls._doc_client:
            return cls._doc_client

        cls._doc_client = DocumentAnalysisClient(
            endpoint=ENDPOINT,
            credential=AzureKeyCredential(API_KEY)
        )
        return cls._doc_client

    @classmethod
    def blob_service(cls):
        if cls._blob_client:
            return cls._blob_client

        cls._blob_client = BlobServiceClient.from_connection_string(CONNECT_STR)
        return cls._blob_client


# --- SAFE HELPERS ---

def safe(field, attr="content"):
    """Safely extract Azure field values"""
    if not field:
        return None
    return getattr(field, attr, None)


def analyze(url: str, model: str):
    return AzureClients.doc_client() \
        .begin_analyze_document_from_url(model, url) \
        .result()


# --- GENERIC FIELD EXTRACTION ---

def extract(doc, fields):
    data = {}
    for f in fields:
        val = doc.fields.get(f)
        if val:
            data[f] = safe(val)
    return data


def extract_all(result, fields):
    out = {}
    for d in result.documents:
        out.update(extract(d, fields))
    return out


# --- DOCUMENT ENDPOINT ---

@router.get("/analyse_document")
async def analyse_document(url: str):
    result = analyze(url, "prebuilt-idDocument")

    doc = result.documents[0]
    addr = doc.fields.get("Address")

    addr_dict = addr.value.to_dict() if addr and addr.value else {}

    return {
        "first_name": safe(doc.fields.get("FirstName"), "value"),
        "last_name": safe(doc.fields.get("LastName"), "value"),
        "license_number": safe(doc.fields.get("DocumentNumber"), "value"),
        "date_of_birth": str(safe(doc.fields.get("DateOfBirth"), "value")),
        "date_of_expiry": str(safe(doc.fields.get("DateOfExpiration"), "value")),
        "street_address": addr_dict.get("street_address"),
        "suburb": addr_dict.get("suburb"),
        "postal_code": addr_dict.get("postal_code"),
        "state": addr_dict.get("state"),
    }


# --- GENERIC ROUTES FACTORY ---

def register(route: str, model: str, fields: list):

    @router.get(route)
    async def endpoint(url: str):
        result = analyze(url, model)
        return extract_all(result, fields)


register("/analyse_licence", "zvicroad1",
    ['zdocumentType','issuedBy','FirstName','LastName','DocumentNumber','Address','DateOfBirth','DateOfExpiration'])

register("/analyse_passport", "zpassport1",
    ['DocumentName','Country','FirstName','LastName','DocumentNumber','DateOfBirth',
     'DateOfExpiration','DateOfIssue','Nationality','PlaceOfBirth','Sex'])

register("/analyse_electricity", "zelectricity1",
    ['retailer','address','account_number','issue_date'])

register("/analyse_directdebit", "zddmodel1",
    ['FirstName','LastName','BankName','BankAddress','AccountName','BSBNumber',
     'AccountNumber','HomeAddress','MobileNo','Email','SignedDate'])


# --- RECEIPT ---

@router.get("/process_receipt")
async def process_receipt(url: str):
    try:
        result = analyze(url, "prebuilt-receipt")
    except Exception as e:
        raise HTTPException(500, str(e))

    output = {"items": []}

    for r in result.documents:
        f = r.fields

        def get(name):
            return safe(f.get(name), "content")

        output.update({
            "merchant_name": get("MerchantName"),
            "merchant_address": get("MerchantAddress"),
            "transaction_date": get("TransactionDate"),
            "subtotal": get("Subtotal"),
            "total": get("Total"),
            "tax": get("TotalTax"),
        })

        if f.get("Items"):
            for item in f["Items"].value:
                v = item.value
                output["items"].append({
                    "description": safe(v.get("Description"), "value"),
                    "quantity": safe(v.get("Quantity"), "value"),
                    "price": safe(v.get("TotalPrice"), "value"),
                })

    return output


# --- INVOICE ---

@router.get("/process_invoice")
async def process_invoice(url: str):
    try:
        result = analyze(url, "prebuilt-invoice")
    except Exception as e:
        raise HTTPException(500, str(e))

    output = {"items": []}

    for inv in result.documents:
        f = inv.fields

        def get(name):
            return safe(f.get(name), "content")

        output.update({
            "vendor_name": get("VendorName"),
            "invoice_id": get("InvoiceId"),
            "invoice_date": get("InvoiceDate"),
            "total": get("InvoiceTotal"),
            "customer_name": get("CustomerName"),
            "billing_address": get("BillingAddress"),
            "shipping_address": get("ShippingAddress"),
        })

        if f.get("Items"):
            for item in f["Items"].value:
                v = item.value
                output["items"].append({
                    "description": safe(v.get("Description"), "content"),
                    "quantity": safe(v.get("Quantity"), "content"),
                    "amount": safe(v.get("Amount"), "content"),
                })

    return output


# --- CLASSIFICATION (FIXED BUG) ---

@router.get("/classify_document")
async def classify_document(url: str):
    result = AzureClients.doc_client().begin_classify_document_from_url(
        classifier_id="doc-classfication-model-v2",
        document_url=url
    ).result()

    for doc in result.documents:
        confidence = doc.confidence * 100
        return {
            "doc_type": doc.doc_type if confidence > 60 else "invalid document",
            "confidence_pct": confidence
        }


# --- UPLOAD (FIXED SINGLETON USAGE) ---

@router.post("/azure-image")
async def upload(file: UploadFile):
    if not file:
        return {"message": "No file"}

    # ext = os.path.splitext(file.filename)[1]
    file_name = f"{uuid.uuid4()}-{file.filename}"

    blob_client = AzureClients.blob_service().get_blob_client(
        container=CONTAINER,
        blob=file_name
    )

    try:
        blob_client.upload_blob(file.file.read(), overwrite=True)
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {str(e)}")
    finally:
        file.file.close()

        file_url = "https://zblobarchive.blob.core.windows.net/documents/" + str(file_name)
        return {"fileUrl": file_url}