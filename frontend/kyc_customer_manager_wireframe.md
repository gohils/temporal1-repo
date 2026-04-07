# KYC Customer & Manager ReactJS UI Design

This document proposes a combined wireframe for **customer-facing pages** and **manager workflow review pages** in a minimal and intuitive style suitable for enterprise KYC workflows.

---

## Customer-Facing Pages

### 1️⃣ Customer Input / Submission Page
```
-------------------------------------------------
|       Customer Onboarding Form               |
-------------------------------------------------
| Customer Information                          |
| -------------------------------------------- |
| First Name: [___________]                     |
| Last Name:  [___________]                     |
| Email:      [___________]                     |
| Phone:      [___________]                     |
| Address:    [__________________________]     |
-------------------------------------------------
| Documents / Upload                             |
| -------------------------------------------- |
| Type           | Upload File                  | Status          |
|----------------|------------------------------|----------------|
| Driver License | [Choose File] [Upload]      | Not Submitted   |
| Passport       | [Choose File] [Upload]      | Not Submitted   |
| Utility Bill   | [Choose File] [Upload]      | Not Submitted   |
-------------------------------------------------
| Actions                                       |
| -------------------------------------------- |
| [Submit All]                                  |
| Status: "All documents submitted successfully"|
-------------------------------------------------
```
**FastAPI endpoints:**
* `/customer/onboarding` → submit personal info
* `/customer/document/upload` → upload documents

---

### 2️⃣ Customer Workflow Status Page
```
-------------------------------------------------
|       KYC Workflow Status                     |
-------------------------------------------------
| Customer Information                          |
| -------------------------------------------- |
| First Name: John                              |
| Last Name:  Doe                               |
| Email: john.doe@example.com                   |
| Phone: +61-400-000-000                        |
| Address: 15 Main Street, Melbourne, VIC 3000 |
-------------------------------------------------
| Documents / Items                             |
| -------------------------------------------- |
| Type           | Status      | Summary      | Action          |
|----------------|------------|--------------|----------------|
| Driver License | PROCESSING  | Name, DOB    | [View Details]  |
| Passport       | PROCESSING  | Name, Expiry | [View Details]  |
| Utility Bill   | PROCESSING  | Address      | [View Details]  |
-------------------------------------------------
| Workflow Status                               |
| -------------------------------------------- |
| Status: Workflow started: WF-12345          |
| Note: Your documents are being processed.    |
-------------------------------------------------
```
* `[View Details]` opens **read-only modal**.

---

### 3️⃣ Document Details Modal (Customer View)
```
-------------------- DOCUMENT DETAILS --------------------
| Document Type: Driver License                         |
| Status: PROCESSING                                    |
| Processing Notes: Name and DOB extracted via AI       |
--------------------------------------------------------
| Extracted Fields (Read-only):                        |
| First Name: John                                      |
| Last Name: Doe                                       |
| DOB: 01-Jan-1990                                      |
| Document Number: DL123456                             |
--------------------------------------------------------
| Document Image Preview                                |
| [IMAGE DISPLAY]                                       |
--------------------------------------------------------
| Actions                                               |
| [Close]                                              |
--------------------------------------------------------
```
* Endpoint: `/customer/document/{doc_id}` → fetch document + extracted fields

---

## Manager-Facing Pages

### 1️⃣ Manager Task Grid (All Pending Headers)
```
-------------------------------------------------
|           KYC Workflow Task List             |
-------------------------------------------------
| Header ID   | Customer Name | Submitted At   | Status          | Action          |
|-------------|---------------|---------------|----------------|----------------|
| WF-12345    | John Doe      | 01-Apr-2026   | Pending Approval | [Review]       |
| WF-12346    | Jane Smith    | 02-Apr-2026   | Pending Approval | [Review]       |
| WF-12347    | Bob Lee       | 03-Apr-2026   | Pending Approval | [Review]       |
-------------------------------------------------
| Filters / Search: [Customer Name] [Status]  |
-------------------------------------------------
```
* Endpoint: `/workflow/tasks`
* `[Review]` → opens **Individual Header Approval page**

---

### 2️⃣ Individual Header Review & Approval
```
-------------------------------------------------
|          KYC Workflow Review                 |
-------------------------------------------------
| Customer Information                          |
| -------------------------------------------- |
| First Name: John                              |
| Last Name:  Doe                               |
| Email: john.doe@example.com                   |
| Phone: +61-400-000-000                        |
| Address: 15 Main Street, Melbourne, VIC 3000 |
-------------------------------------------------
| Documents / Items                             |
| -------------------------------------------- |
| Type           | Status      | Summary      | Action          |
|----------------|------------|--------------|----------------|
| Driver License | COMPLETED   | Name, DOB    | [View Details]  |
| Passport       | COMPLETED   | Name, Expiry | [View Details]  |
| Utility Bill   | COMPLETED   | Address      | [View Details]  |
-------------------------------------------------
| Workflow Status                               |
| -------------------------------------------- |
| Status: Workflow completed: WF-12345        |
| Workflow Decision: Pending Manual Approval   |
-------------------------------------------------
| Actions                                       |
| -------------------------------------------- |
| [Approve Header]  [Reject Header]            |
| Manager Comments: [_______________________]  |
-------------------------------------------------
```
* Endpoints:
  * `/workflow/{header_id}` → fetch workflow + document details
  * `/workflow/signal` → approve/reject header

---

### 3️⃣ Document Details Modal (Manager View)
```
-------------------- DOCUMENT DETAILS --------------------
| Document Type: Driver License                         |
| Status: COMPLETED                                     |
| Processing Notes: Name and DOB extracted via AI       |
--------------------------------------------------------
| Extracted Fields:                                     |
| First Name: John                                      |
| Last Name: Doe                                       |
| DOB: 01-Jan-1990                                      |
| Document Number: DL123456                             |
--------------------------------------------------------
| Document Image Preview                                |
| [IMAGE DISPLAY]                                       |
--------------------------------------------------------
| Actions (Optional)                                    |
| [Approve Document]  [Reject Document]                |
| Comments: [_______________________]                  |
--------------------------------------------------------
```
* Endpoint: `/workflow/document/{doc_id}` → fetch single document details

---

## Flow Summary

**Customer:** Submission → Workflow Status → Document Details (read-only)

**Manager:** Task Grid → Header Review → Document Details Modal (with optional approval)

This setup keeps the UI **minimal, intuitive, and realistic for enterprise KYC workflows**.

