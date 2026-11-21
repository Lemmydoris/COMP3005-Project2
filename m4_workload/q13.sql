SELECT p.product_id, s.supplier_id
FROM Products p, Suppliers s
WHERE p.supplier_id = s.supplier_id
  AND s.region = 1;