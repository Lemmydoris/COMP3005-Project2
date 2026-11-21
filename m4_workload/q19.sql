SELECT c.region, COUNT(*) AS n
FROM Customers c
JOIN Orders o ON c.cust_id = o.cust_id
WHERE o.amount > 700
GROUP BY c.region;
