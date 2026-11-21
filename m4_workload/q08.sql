SELECT p.product_id, s.supplier_id
FROM Products p
JOIN Suppliers s ON p.supplier_id = s.supplier_id
WHERE s.region = 2;
