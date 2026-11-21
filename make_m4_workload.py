from pathlib import Path
import csv
import shutil

DATA = Path("m4_data")
WORK = Path("m4_workload")

for folder in (DATA, WORK):
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir()

# ============================================================
# DATASET
# ============================================================

# Customers:
# region and segment are intentionally strongly correlated.
# 95% of rows have segment == region.
with open(DATA / "Customers.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    for i in range(1, 5001):
        region = ((i - 1) % 10) + 1

        if i % 20 == 0:
            segment = (region % 10) + 1
        else:
            segment = region

        age = 18 + ((i * 7) % 63)

        w.writerow([
            i,
            region,
            segment,
            age,
        ])

# Orders
with open(DATA / "Orders.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    for i in range(1, 20001):
        cust_id = ((i * 37) % 5000) + 1
        product_id = ((i * 53) % 2000) + 1
        amount = 20 + ((i * 29) % 980)

        w.writerow([
            i,
            cust_id,
            product_id,
            amount,
        ])

# Products
with open(DATA / "Products.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    for i in range(1, 2001):
        category = ((i - 1) % 20) + 1
        supplier_id = ((i * 17) % 200) + 1
        price = 10 + ((i * 23) % 990)

        w.writerow([
            i,
            category,
            supplier_id,
            price,
        ])

# Suppliers
with open(DATA / "Suppliers.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    for i in range(1, 201):
        region = ((i - 1) % 10) + 1
        rating = ((i - 1) % 5) + 1

        w.writerow([
            i,
            region,
            rating,
        ])

# ============================================================
# 20-QUERY WORKLOAD
# ============================================================

queries = {
    "q01.sql": """
SELECT c.cust_id
FROM Customers c
WHERE c.region = 1;
""",

    "q02.sql": """
SELECT p.product_id
FROM Products p
WHERE p.price > 500;
""",

    # Strongly correlated predicates
    "q03.sql": """
SELECT c.cust_id
FROM Customers c
WHERE c.region = 1 AND c.segment = 1;
""",

    "q04.sql": """
SELECT c.cust_id
FROM Customers c
WHERE c.region = 1 AND c.segment = 2;
""",

    "q05.sql": """
SELECT c.cust_id, o.order_id
FROM Customers c
JOIN Orders o ON c.cust_id = o.cust_id
WHERE c.region = 1;
""",

    # Correlation + join
    "q06.sql": """
SELECT c.cust_id, o.order_id
FROM Customers c
JOIN Orders o ON c.cust_id = o.cust_id
WHERE c.region = 1 AND c.segment = 1;
""",

    "q07.sql": """
SELECT o.order_id, p.product_id
FROM Orders o
JOIN Products p ON o.product_id = p.product_id
WHERE p.category = 3;
""",

    "q08.sql": """
SELECT p.product_id, s.supplier_id
FROM Products p
JOIN Suppliers s ON p.supplier_id = s.supplier_id
WHERE s.region = 2;
""",

    "q09.sql": """
SELECT c.cust_id, o.order_id, p.product_id
FROM Customers c
JOIN Orders o ON c.cust_id = o.cust_id
JOIN Products p ON o.product_id = p.product_id
WHERE c.region = 1 AND p.category = 3;
""",

    "q10.sql": """
SELECT o.order_id, p.product_id, s.supplier_id
FROM Orders o
JOIN Products p ON o.product_id = p.product_id
JOIN Suppliers s ON p.supplier_id = s.supplier_id
WHERE p.category = 3 AND s.region = 2;
""",

    # Four-relation query for DP table
    "q11.sql": """
SELECT c.cust_id, o.order_id, p.product_id, s.supplier_id
FROM Customers c
JOIN Orders o ON c.cust_id = o.cust_id
JOIN Products p ON o.product_id = p.product_id
JOIN Suppliers s ON p.supplier_id = s.supplier_id
WHERE c.region = 1 AND c.segment = 1;
""",

    "q12.sql": """
SELECT c.cust_id, o.order_id, p.product_id, s.supplier_id
FROM Customers c
JOIN Orders o ON c.cust_id = o.cust_id
JOIN Products p ON o.product_id = p.product_id
JOIN Suppliers s ON p.supplier_id = s.supplier_id
WHERE c.region = 2 AND p.category = 4;
""",

    # Equivalent comma-style join to exercise cross -> join rewrite
    "q13.sql": """
SELECT c.cust_id, o.order_id
FROM Customers c, Orders o
WHERE c.cust_id = o.cust_id AND c.region = 1;
""",

    "q14.sql": """
SELECT c.cust_id, o.order_id
FROM Customers c
JOIN Orders o ON c.cust_id = o.cust_id
WHERE c.region = 3 AND o.amount > 900;
""",

    "q15.sql": """
SELECT o.order_id, p.product_id
FROM Orders o
JOIN Products p ON o.product_id = p.product_id
WHERE o.amount < 100 AND p.price > 700;
""",

    # Projection pushdown is useful here
    "q16.sql": """
SELECT c.cust_id, s.supplier_id
FROM Customers c
JOIN Orders o ON c.cust_id = o.cust_id
JOIN Products p ON o.product_id = p.product_id
JOIN Suppliers s ON p.supplier_id = s.supplier_id
WHERE c.region = 5;
""",

    "q17.sql": """
SELECT p.product_id
FROM Products p
WHERE p.category = 7 AND p.price > 600;
""",

    # GROUP BY exercises grouping estimates/rewrite behavior
    "q18.sql": """
SELECT c.region, COUNT(*) AS n
FROM Customers c
WHERE c.age > 40
GROUP BY c.region;
""",

    "q19.sql": """
SELECT c.region, COUNT(*) AS n
FROM Customers c
JOIN Orders o ON c.cust_id = o.cust_id
WHERE o.amount > 700
GROUP BY c.region;
""",

    # Sort / limit
    "q20.sql": """
SELECT o.order_id, o.amount
FROM Orders o
WHERE o.amount > 500
ORDER BY o.amount DESC
LIMIT 20;
""",
}

for filename, sql in queries.items():
    (WORK / filename).write_text(
        sql.strip() + "\n",
        encoding="utf-8",
    )

print("Created dataset:")
print("  Customers: 5,000 rows")
print("  Orders:    20,000 rows")
print("  Products:   2,000 rows")
print("  Suppliers:    200 rows")
print()
print("Created", len(queries), "SQL workload queries.")
print()
print("Correlation:")
print("  Customers.region and Customers.segment")
print("  match for 95% of customer rows.")
