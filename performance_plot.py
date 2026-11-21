import csv
import math
import matplotlib.pyplot as plt

sizes = []
times = []

with open("benchmark_results.csv", newline="", encoding="utf-8") as file:
    reader = csv.DictReader(file)

    for row in reader:
        sizes.append(int(row["n"]))
        times.append(float(row["wall_time"]))

# Calculate slope using linear regression on log-log data
x = [math.log(n) for n in sizes]
y = [math.log(t) for t in times]

x_mean = sum(x) / len(x)
y_mean = sum(y) / len(y)

numerator = sum(
    (a - x_mean) * (b - y_mean)
    for a, b in zip(x, y)
)

denominator = sum(
    (a - x_mean) ** 2
    for a in x
)

slope = numerator / denominator
intercept = y_mean - slope * x_mean

fitted_times = [
    math.exp(intercept + slope * math.log(n))
    for n in sizes
]

# Draw log-log graph
plt.figure(figsize=(8, 5))

plt.loglog(
    sizes,
    times,
    "o-",
    label="Measured join time"
)

plt.loglog(
    sizes,
    fitted_times,
    "--",
    label=f"Fitted slope = {slope:.3f}"
)

plt.xlabel("Tuples per relation (n)")
plt.ylabel("Wall time (seconds)")
plt.title("Nested-Loop Join Performance")
plt.grid(True, which="both", alpha=0.3)
plt.legend()
plt.tight_layout()

plt.savefig("join_loglog.png", dpi=200)
plt.close()

print(f"Log-log slope: {slope:.4f}")
print("Graph saved to join_loglog.png")

# Predict one-million-tuple join from largest measurement
largest_n = sizes[-1]
largest_time = times[-1]

predicted = largest_time * (1_000_000 / largest_n) ** 2

print(f"Predicted time: {predicted:,.2f} seconds")
print(f"Predicted days: {predicted / 86400:.2f}")