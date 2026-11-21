SELECT o.order_id, p.product_id
FROM Orders o
JOIN Products p ON o.product_id = p.product_id
WHERE o.amount < 100 AND p.price > 700;
