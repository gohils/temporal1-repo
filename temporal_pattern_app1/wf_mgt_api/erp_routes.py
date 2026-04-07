from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from process_db import run_query  # Importing the reusable DB function

router = APIRouter(prefix="/erp", tags=["ERP"])

# --------------------------------------------------
# Fetch a purchase order with items
# --------------------------------------------------
@router.get("/purchase-orders")
async def get_po(po_number: str = "PO901101") -> Dict[str, Any]:
    """
    Fetch PO header and all associated items for a given PO number.
    """
    # Fetch PO header
    header = run_query(
        "SELECT * FROM po_header WHERE po_number = %s",
        (po_number,)
    )

    if not header:
        raise HTTPException(404, f"PO {po_number} not found")

    # Fetch PO items
    items = run_query(
        "SELECT * FROM po_line_items WHERE po_number = %s ORDER BY id",
        (po_number,)
    )

    return {
        "po_header": header[0],
        "po_items": items
    }


# --------------------------------------------------
# Fetch vendor info
# --------------------------------------------------
@router.get("/vendors")
async def get_vendor(vendor_name: str = "Fortune Global Ltd") -> Dict[str, Any]:
    """
    Fetch vendor details by name.
    """
    vendor = run_query(
        "SELECT * FROM vendor_master WHERE vendor_name = %s",
        (vendor_name,)
    )

    if not vendor:
        raise HTTPException(404, f"Vendor '{vendor_name}' not found")

    return vendor[0]