SELECT o.order_id, p.product_id, s.supplier_id
FROM Orders o
JOIN Products p ON o.product_id = p.product_id
JOIN Suppliers s ON p.supplier_id = s.supplier_id
WHERE p.category = 3 AND s.region = 2;
