
# Developer Guide: Managing State, Variables, and Parameter Propagation Across Multiple Workflow Activities

## Overview
This guide explains how to manage **state, variables, and parameter propagation** across multiple activities in Temporal workflows. It is focused on document processing use cases such as **passport, driver license, utility bill, and receipts**.  

Temporal workflows require a structured approach to **propagate information** between activities while keeping workflow execution deterministic. The recommended solution separates **activity-specific data (`payload`)** from **workflow-wide state (`context`)**, allowing:

- **Immutable activity inputs** (avoiding unintended side-effects)
- **Traceable context evolution** (easy debugging and auditing)
- **Flexible activity chaining** across multiple document types

---
## Core Concept: Payload vs Context

### Payload (Flowing Data)
- Moves from one activity → next
- Contains actual business data (OCR, invoice fields, etc.)

### Context (Accumulated State)
- Grows across workflow
- Used for tracing, audit, metadata, debugging

---

## Data Contracts

```python
@dataclass
class ActivityInput:
    payload: Dict
    context: Dict

@dataclass
class ActivityOutput:
    response: Dict
    context: Dict
```

### Explanation
- `payload` = current working data
- `context` = full workflow memory

---
## 🔑 Two Types of State

### 1. Payload (Business Data)

-   OCR results
-   Invoice fields
-   Validation status
-   Approval decision

👉 Changes at every step

------------------------------------------------------------------------

### 2. Context (System Metadata)

-   workflow_id
-   workflow_type
-   header_id
-   item_id
-   reference_id

👉 MUST NEVER be lost

------------------------------------------------------------------------

# ⚠️ Golden Rule

> Payload evolves. Context persists.

------------------------------------------------------------------------

# 🏗️ Architecture Pattern

    Preprocess → OCR → Normalize → Validate → Decision → ERP → Audit

Each step: - Reads from payload - Writes to payload - Uses context
(read-only mostly)

------------------------------------------------------------------------

# 📦 Data Contracts

``` python
@dataclass
class ActivityInput:
    payload: Dict
    context: Dict

@dataclass
class ActivityOutput:
    response: Dict
    context: Dict
```

------------------------------------------------------------------------

# 🔄 Context Management

## Base Context

``` python
def build_base_context(payload, wf_id):
    return {
        "workflow_id": wf_id,
        "workflow_type": payload.get("workflow_type"),
        "reference_id": payload.get("reference_id"),
        "header_id": payload.get("header_id"),
    }
```

------------------------------------------------------------------------

## Safe Merge

``` python
def merge_context(parent, child):
    return {
        **parent,
        **child,
        "workflow_id": parent.get("workflow_id"),
        "workflow_type": parent.get("workflow_type"),
        "reference_id": parent.get("reference_id"),
        "header_id": parent.get("header_id"),
        "item_id": child.get("item_id") or parent.get("item_id"),
    }
```

------------------------------------------------------------------------

# ⚙️ Execution Wrapper

``` python
async def execute_step(activity_fn, payload, context, step):

    print(f"➡️ {step} START")

    result = await workflow.execute_activity(
        activity_fn,
        ActivityInput(payload, context),
        start_to_close_timeout=timedelta(seconds=30),
    )

    payload = {**payload, **result.response}
    context = merge_context(context, result.context)

    print(f"✅ {step} DONE")

    return payload, context
```

------------------------------------------------------------------------

# 🧩 Activity Design Rules

## ✅ DO

-   Return only delta
-   Read only required fields
-   Use context for IDs only

## ❌ DON'T

-   Modify context randomly
-   Depend on previous activity structure
-   Store large data in context

------------------------------------------------------------------------

# 🧪 Example State Flow

## Step 1: Preprocess

Input:

    {
      "header_id": "H1",
      "items": [{"id": "I1", "document_url": "url"}]
    }

Output:

    payload → { "document_url": "url" }
    context → { "header_id": "H1", "item_id": "I1" }

------------------------------------------------------------------------

## Step 2: OCR

    payload → + "ocr_data"

------------------------------------------------------------------------

## Step 3: Normalize

    payload → + "invoice_data"

------------------------------------------------------------------------

## Step 4: Validate

    payload → + "validation_status"

------------------------------------------------------------------------

# 📊 Payload vs Context

  Property         Payload   Context
  ---------------- --------- ---------
  Changes          ✅ Yes    ❌ No
  Size             Medium    Small
  Business Logic   ✅ Yes    ❌ No
  DB Keys          ❌ No     ✅ Yes

------------------------------------------------------------------------

# 🚨 Common Mistakes

## ❌ Context Pollution

    context["normalize"] = {...}

## ❌ Missing header_id

Breaks DB linkage

## ❌ Overloaded payload

Passing entire objects blindly

------------------------------------------------------------------------

# ✅ Best Practices

1.  Always preprocess input
2.  Keep activities stateless
3.  Use execution wrapper
4.  Log payload + context
5.  Preserve header/item always

------------------------------------------------------------------------
## Activity Example with Explanation

### OCR Extraction

```python
@activity.defn
async def extract_document_data(input: ActivityInput) -> ActivityOutput:
    raw_data = simulate_document_ocr(input.payload.get("document_url"))

    new_payload = {**input.payload, "extracted_data": raw_data}

    updated_context = input.context.copy()
    updated_context["extract_document_data"] = {"summary": "OCR complete"}

    return ActivityOutput(new_payload, updated_context)
```

### What’s Happening?

- Reads document_url from payload
- Adds extracted_data → payload (for next steps)
- Stores summary → context (for tracking only)

---

## Normalization Step

```python
normalized = {
    "invoice_id": extracted.get("InvoiceId"),
    "vendor": extracted.get("VendorName")
}
```

### Why?

- Payload evolves into structured business object
- Context stores only metadata (not full data duplication)

---

## Validation Step

```python
valid = all(normalized.values())
```

### Why?

- Business rule stays in payload
- Context stores decision history

---

## Workflow Execution Pattern

```python
payload.update(res.response)
context.update(res.context)
```

### Why This Pattern is BEST

- Payload = clean pipeline
- Context = audit trail
- No data loss
- Easy debugging

---

## Example State Evolution

### Step 1 Payload
```
{ "document_url": "..." }
```

### Step 2 Payload
```
{ "document_url": "...", "extracted_data": {...} }
```

### Step 3 Payload
```
{ ..., "normalized_data": {...} }
```

### Context Growth
```
{
  "workflow_id": "...",
  "extract_document_data": {...},
  "normalize_passport": {...}
}
```

---

## Data Classes for Workflow State
```python
from dataclasses import dataclass
from typing import Dict

@dataclass
class ActivityInput:
    payload: Dict       # Activity-specific input for this activity
    context: Dict       # Complete workflow-wide context so far

@dataclass
class ActivityOutput:
    response: Dict      # Activity-specific output
    context: Dict       # Updated workflow-wide context after this activity
```

**Explanation:**

- `payload`: only contains the **direct data needed for the activity** (e.g., OCR input, normalized fields).  
- `context`: **cumulative workflow state** including previous activity results and workflow metadata (workflow ID, audit info, decision flags).  
- This separation ensures **activities are reusable and deterministic** while the workflow context can carry **shared state across multiple activities**.

---

## Example Activities with State Sharing

### 1. Extract Document Data (OCR)
```python
from temporalio import activity

@activity.defn
async def extract_document_data(input: ActivityInput) -> ActivityOutput:
    raw_data = simulate_document_ocr(input.payload.get("document_url"))

    # Activity-specific payload
    new_payload = {**input.payload, "extracted_data": raw_data}

    # Update workflow context
    updated_context = input.context.copy()
    updated_context["extract_document_data"] = {"summary": summarize(raw_data)}

    print("➡️ [EXTRACT] Payload keys:", list(new_payload.keys()))
    print("➡️ [EXTRACT] Context keys:", list(updated_context.keys()))

    return ActivityOutput(response=new_payload, context=updated_context)
```
**Input Payload/Context:**
```json
{
  "payload": {"document_url": "https://example.com/passport.pdf"},
  "context": {"workflow_id": "WF123"}
}
```

**Output Payload/Context:**
```json
{
  "response": {
    "document_url": "https://example.com/passport.pdf",
    "extracted_data": {"name": "John Doe", "dob": "1990-01-01", "passport_no": "X1234567"}
  },
  "context": {"extract_document_data": {"summary": "OCR complete"}}
}
```

**How Input is Used:**
- Payload: Reads `"document_url"` to fetch and OCR the document.
- Context: Reads `"workflow_id"` for audit/tracking if needed.

**State Change:**
- Payload: adds `"extracted_data"`
- Context: adds `"extract_document_data.summary"`

**Explanation:**

- The **activity outputs both payload and context**.  
- `payload` carries the actual OCR data needed for downstream normalization.  
- `context` stores a summarized version for logging, auditing, or conditional branching in the workflow.
---

### 2. Normalize Passport Data
```python
@activity.defn
async def normalize_passport(input: ActivityInput) -> ActivityOutput:
    extracted = input.payload.get("extracted_data", {})

    normalized = {
        "full_name": extracted.get("name"),
        "dob": extracted.get("dob"),
        "passport_number": extracted.get("passport_no")
    }

    new_payload = {**input.payload, "normalized_data": normalized}
    updated_context = input.context.copy()
    updated_context["normalize_passport"] = {"fields_count": len(normalized)}

    print("✅ [NORMALIZE] Payload keys:", list(new_payload.keys()))
    print("✅ [NORMALIZE] Context keys:", list(updated_context.keys()))

    return ActivityOutput(response=new_payload, context=updated_context)
```

**Input Payload/Context:**
```json
{
  "payload": {"document_url": "https://example.com/passport.pdf", "extracted_data": {"name": "John Doe", "dob": "1990-01-01", "passport_no": "X1234567"}},
  "context": {"workflow_id": "WF123", "extract_document_data": {"summary": "OCR complete"}}
}
```

**Output Payload/Context:**
```json
{
  "response": {
    "document_url": "https://example.com/passport.pdf",
    "extracted_data": {"name": "John Doe", "dob": "1990-01-01", "passport_no": "X1234567"},
    "normalized_data": {"full_name": "John Doe", "dob": "1990-01-01", "passport_number": "X1234567"}
  },
  "context": {"normalize_passport": {"fields_count": 3}}
}
```
**How Input is Used:**
- Payload: Reads `"extracted_data"` from OCR step.
- Context: Can read `"workflow_id"` for logging/audit.

**State Change:**
- Payload: adds `"normalized_data"`
- Context: adds `"normalize_passport.fields_count"`

**Explanation:**

- Converts raw OCR data into a **structured, normalized format**.  
- Updates `context` to store metadata (`fields_count`) for auditing or workflow branching.

---

### 3. Validate Document Data
```python
@activity.defn
async def validate_document(input: ActivityInput) -> ActivityOutput:
    normalized = input.payload.get("normalized_data")
    valid = True if normalized and all(normalized.values()) else False

    new_payload = {**input.payload, "validation_status": "VALID" if valid else "INVALID"}
    updated_context = input.context.copy()
    updated_context["validate_document"] = {"valid": valid}

    print("✅ [VALIDATE] Payload keys:", list(new_payload.keys()))
    print("✅ [VALIDATE] Context keys:", list(updated_context.keys()))

    return ActivityOutput(response=new_payload, context=updated_context)
```
**Input Payload/Context:**
```json
{
  "payload": {"document_url": "https://example.com/passport.pdf", "extracted_data": {...}, "normalized_data": {...}},
  "context": {"workflow_id": "WF123", "extract_document_data": {...}, "normalize_passport": {...}}
}
```

**Output Payload/Context:**
```json
{
  "response": {
    "payload": {...},
    "validation_status": "VALID"
  },
  "context": {"validate_document": {"valid": true}}
}
```
**How Input is Used:**
- Payload: Reads `"normalized_data"` for validation.
- Context: Reads `"workflow_id"` if needed for logging.

**State Change:**
- Payload: adds `"validation_status"`
- Context: adds `"validate_document.valid"`

**Explanation:**

- Validates normalized data.  
- Both the `payload` and `context` are updated, so downstream activities **do not need to recalculate validation**.  
- This **separation makes validation results accessible for branching, notifications, or conditional approval logic**.

---

### 4. Store Document in DB
```python
@activity.defn
async def store_document(input: ActivityInput) -> ActivityOutput:
    doc_type = input.payload.get("document_type")
    doc_data = input.payload.get("normalized_data")

    doc_id = store_to_db(doc_type, doc_data, input.workflow_id)

    new_payload = {**input.payload, "doc_id": doc_id}
    updated_context = input.context.copy()
    updated_context["store_document"] = {"stored_doc_id": doc_id}

    print("✅ [STORE] Payload keys:", list(new_payload.keys()))
    print("✅ [STORE] Context keys:", list(updated_context.keys()))

    return ActivityOutput(response=new_payload, context=updated_context)
```
**Input Payload/Context:**
```json
{
  "payload": {
    "document_type": "passport", "document_url": "...", "extracted_data": {...}, "normalized_data": {...},
    "validation_status": "VALID"
  },
  "context": {
    "workflow_id": "WF123", "extract_document_data": {...}, "normalize_passport": {...}, "validate_document": {...}
  }
}
```

**Output Payload/Context:**
```json
{
  "response": {
    "payload": {...},
    "doc_id": "DOC789"
  },
  "context": {
    "store_document": {
      "stored_doc_id": "DOC789"
    }
  }
}
```

**How Input is Used:**
- Payload: Reads `"normalized_data"` and `"document_type"` to store document.
- Context: Reads `"workflow_id"` for DB storage reference.

**State Change:**
- Payload: adds `"doc_id"`
- Context: adds `"store_document.stored_doc_id"`

**Explanation:**

- Persists the document to the database.  
- `context` stores a reference (`stored_doc_id`) that can be used by later activities (like ERP posting, audit, or notification).  
- This prevents **activities from relying on global mutable state**, ensuring workflow determinism.

---

### 5. Audit Logging
```python
@activity.defn
async def store_audit(input: ActivityInput) -> ActivityOutput:
    audit_entry = {
        "workflow_id": input.context.get("workflow_id"),
        "payload_snapshot": input.payload,
        "context_snapshot": input.context
    }
    log_to_db(audit_entry)

    return ActivityOutput(response={"status": "AUDIT_STORED"}, context=input.context)
```
**Input Payload/Context:**
```json
{
  "payload": {"document_type": "passport", "document_url": "...", "extracted_data": {...}, "normalized_data": {...}, "validation_status": "VALID", "doc_id": "DOC789"},
  "context": { "workflow_id": "WF123", "extract_document_data": {...}, "normalize_passport": {...},  "validate_document": {...}, "store_document": {...}}
}
```

**Output Payload/Context:**
```json
{
  "response": { "status": "AUDIT_STORED" },
  "context": {}
}
```
**How Input is Used:**
- Payload: Reads full payload snapshot for auditing.
- Context: Reads full context snapshot for auditing.

**State Change:**
- Payload: adds `"status": "AUDIT_STORED"`
- Context: unchanged

**Explanation:**

- Uses **full workflow context** to create a complete audit trail.  
- No changes to `context` since auditing is **side-effect only**, preserving workflow immutability.

---

## Workflow Example
```python
from temporalio import workflow
from datetime import timedelta

@workflow.defn
class DocumentProcessingWorkflow:

    @workflow.run
    async def run(self, initial_payload: Dict):
        workflow_id = workflow.info().workflow_id
        payload = initial_payload.copy()
        context = {"workflow_id": workflow_id}

        # 1️⃣ Extract
        extract_res = await workflow.execute_activity(
            extract_document_data,
            ActivityInput(payload, context),
            start_to_close_timeout=timedelta(seconds=60)
        )
        payload.update(extract_res.response)
        context.update(extract_res.context)

        # 2️⃣ Normalize
        normalize_res = await workflow.execute_activity(
            normalize_passport,
            ActivityInput(payload, context),
            start_to_close_timeout=timedelta(seconds=30)
        )
        payload.update(normalize_res.response)
        context.update(normalize_res.context)

        # 3️⃣ Validate
        validate_res = await workflow.execute_activity(
            validate_document,
            ActivityInput(payload, context),
            start_to_close_timeout=timedelta(seconds=30)
        )
        payload.update(validate_res.response)
        context.update(validate_res.context)

        # 4️⃣ Store
        store_res = await workflow.execute_activity(
            store_document,
            ActivityInput(payload, context),
            start_to_close_timeout=timedelta(seconds=60)
        )
        payload.update(store_res.response)
        context.update(store_res.context)

        # 5️⃣ Audit
        await workflow.execute_activity(
            store_audit,
            ActivityInput(payload, context),
            start_to_close_timeout=timedelta(seconds=30)
        )

        return {
            "payload": payload,
            "context": context
        }
```

**Explanation of State Flow:**

1. Each activity receives the **current `payload` and `context`**.  
2. Activities update **payload for their own output** and **context for workflow-wide shared state**.  
3. Workflow updates the **next activity’s inputs** with `payload.update()` and `context.update()` after every step.  
4. This **immutable + cumulative approach** ensures deterministic workflow execution, traceability, and simplified debugging.

---
## Payload & Context Evolution Table

| Step      | Payload Keys                                        | Context Keys                        |
|----------|----------------------------------------------------|-------------------------------------|
| Initial  | `"document_url"`                                   | `"workflow_id"`                     |
| Extract  | `"document_url"`, `"extracted_data"`              | `"workflow_id"`, `"extract_document_data"` |
| Normalize| + `"normalized_data"`                              | + `"normalize_passport"`            |
| Validate | + `"validation_status"`                            | + `"validate_document"`             |
| Store    | + `"doc_id"`                                      | + `"store_document"`                |
| Audit    | + `"status"`                                      | (unchanged)                         |

---

✅ Key Points:

- Activities only return deltas.
- Workflow merges contexts after each step.
- Payload evolves step-by-step; context accumulates metadata.
- Deterministic, traceable, easy to debug.


## Example Document Types & Activity Flow

| Document Type   | Activity Flow                                      |
|----------------|--------------------------------------------------|
| Passport        | OCR → Normalize → Validate → Store → Audit      |
| Driver License  | OCR → Normalize → Verify Identity → Store → Audit|
| Utility Bill    | OCR → Extract Billing Info → Match Customer → Store → Audit|
| Receipt         | OCR → Normalize → Categorize Expense → Store → Audit|

---

## Advantages of This State-Sharing Approach

1. **Determinism & Reliability**: Context carries all necessary shared state without relying on mutable globals.  
2. **Debugging & Auditing**: Every activity logs payload and context; audit trails are straightforward.  
3. **Reusability**: Activities can be reused across document types; only the payload changes.  
4. **Scalability**: Multiple activities can run in sequence or parallel without losing workflow-wide state.  
5. **Error Handling**: Failed activities can be retried safely; context ensures retries are consistent.  
6. **Extensibility**: New activities can be added easily with minimal impact on existing workflow logic.

---

### ✅ Summary

- Use **payload** for **activity-local data**.  
- Use **context** for **workflow-wide shared state**.  
- Update both at the end of every activity to ensure **consistent propagation**.  
- Log both payload and context at each step for **traceability and observability**.

