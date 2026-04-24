CREATE TABLE vendor_master (
    vendor_id VARCHAR(50) PRIMARY KEY,
    vendor_name VARCHAR(255),
    tax_id VARCHAR(50),
    status VARCHAR(20), -- ACTIVE / BLOCKED
    risk_flag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO vendor_master VALUES
('VEND-001', 'Fortune Global Ltd', '12 034 112 123', 'ACTIVE', FALSE, NOW()),
('VEND-002', 'Suspicious Supplies Pty Ltd', '99 999 999 999', 'BLOCKED', TRUE, NOW());

-- purchase order document
CREATE TABLE po_header (
    po_number VARCHAR(50) PRIMARY KEY,
    vendor_id VARCHAR(50),
    vendor_name VARCHAR(255),
    po_date DATE,
    currency VARCHAR(10),
    total_amount DECIMAL(12,2),
    status VARCHAR(20), -- APPROVED / PENDING / CLOSED
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- purchase order  line-level details
CREATE TABLE po_line_items (
    id SERIAL PRIMARY KEY,
    po_number VARCHAR(50),
    product_code VARCHAR(50),
    description TEXT,
    quantity INT,
    unit_price DECIMAL(12,2),
    line_total DECIMAL(12,2),
    FOREIGN KEY (po_number) REFERENCES po_header(po_number)
);

-- Header
INSERT INTO po_header VALUES
('PO901101', 'VEND-001', 'Fortune Global Ltd', '2023-12-20', 'AUD', 1573.00, 'APPROVED', NOW());

-- Line items
INSERT INTO po_line_items (po_number, product_code, description, quantity, unit_price, line_total)
VALUES
('PO901101', '510221', 'Apple iPhone 15 Black 128GB', 1, 1360.00, 1360.00),
('PO901101', '610997', 'iPhone 15 Clear Case', 1, 70.00, 70.00);
