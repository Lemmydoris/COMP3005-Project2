SELECT c.cust_id, o.order_id, p.product_id
FROM Customers c
JOIN Orders o ON c.cust_id = o.cust_id
JOIN Products p ON o.product_id = p.product_id
WHERE c.region = 1 AND p.category = 3;
