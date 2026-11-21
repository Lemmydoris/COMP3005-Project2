SELECT c.cust_id, o.order_id
FROM Customers c
JOIN Orders o ON c.cust_id = o.cust_id
WHERE c.region = 3 AND o.amount > 900;
