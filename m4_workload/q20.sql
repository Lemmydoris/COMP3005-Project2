SELECT o.order_id, o.amount
FROM Orders o
WHERE o.amount > 500
ORDER BY o.amount DESC
LIMIT 20;
