SELECT c.region, COUNT(*) AS n
FROM Customers c
WHERE c.age > 40
GROUP BY c.region;
