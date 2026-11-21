SELECT c.cust_id, o.order_id, p.product_id, s.supplier_id
FROM Customers c
JOIN Orders o ON c.cust_id = o.cust_id
JOIN Products p ON o.product_id = p.product_id
JOIN Suppliers s ON p.supplier_id = s.supplier_id
WHERE c.region = 1 AND c.segment = 1;
