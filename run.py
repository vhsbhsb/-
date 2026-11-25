import argparse
import csv
import math
import random
import sqlite3
from statistics import median
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DAY = 86400


class MedianAmount:
    def __init__(self):
        self.values = []

    def step(self, value):
        self.values.append(value)

    def finalize(self):
        return median(self.values)


def simulated_rows():
    rng = random.Random(42)
    start = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    usual = [rng.lognormvariate(3.6, 0.9) for _ in range(1500)]
    for i in range(60 * 1200):
        customer = rng.randrange(len(usual))
        fraud = int(rng.random() < 0.012)
        amount = usual[customer] * rng.lognormvariate(0, 0.7)
        if fraud:
            # 同时模拟异常放大、统一大额和近似普通消费三种情况。
            kind = rng.randrange(3)
            if kind == 0:
                amount *= 5
            elif kind == 1:
                amount = rng.lognormvariate(5.6, 0.5)
        yield str(i), str(customer), start + i * 72, max(0.01, round(amount, 2)), fraud


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            dt = datetime.fromisoformat(row["TX_DATETIME"].replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            amount = float(row["TX_AMOUNT"])
            if not math.isfinite(amount) or amount <= 0:
                raise ValueError("TX_AMOUNT must be finite and positive")
            yield (row["TRANSACTION_ID"], row["CUSTOMER_ID"], int(dt.timestamp()),
                   amount, int(row["TX_FRAUD"]))


def write_csv(folder, name, headers, rows):
    with (folder / name).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, help="Handbook-style transaction CSV")
    args = parser.parse_args()
    folder = ROOT / ("csv_results" if args.csv else "demo_results")
    folder.mkdir(exist_ok=True)
    db = sqlite3.connect(":memory:")
    db.create_aggregate("median_amount", 1, MedianAmount)
    db.execute("""CREATE TABLE transactions(id TEXT PRIMARY KEY, customer TEXT NOT NULL,
               ts INTEGER NOT NULL, amount REAL NOT NULL CHECK(amount > 0),
               fraud INTEGER NOT NULL CHECK(fraud IN (0,1)))""")
    db.executemany("INSERT INTO transactions VALUES (?,?,?,?,?)",
                   csv_rows(args.csv) if args.csv else simulated_rows())
    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT date(ts,'unixepoch') FROM transactions ORDER BY 1")]
    if len(dates) < 3:
        raise ValueError("At least three distinct UTC dates required")
    test_day = dates[len(dates) * 2 // 3]
    cutoff = int(datetime.fromisoformat(test_day).replace(tzinfo=timezone.utc).timestamp())
    reference = db.execute("SELECT AVG(amount) FROM transactions WHERE ts < ?", (cutoff,)).fetchone()[0]
    for statement in (ROOT / "strategies.sql").read_text(encoding="utf-8").split(";"):
        if statement.strip():
            db.execute(statement, {"reference": reference, "test_start": cutoff})
    rows = []
    for budget in (50, 100, 200):
        for strategy, rank in (("amount", "amount_rank"), ("relative", "relative_rank"),
                               ("mean", "mean_rank"), ("median", "median_rank")):
            n, hits, covered, total = db.execute(f"""
                SELECT SUM({rank} <= ?), SUM(({rank} <= ?) * fraud),
                       SUM(({rank} <= ?) * fraud * amount), SUM(fraud * amount)
                FROM ranked""", (budget,) * 3).fetchone()
            rows.append((budget, strategy, n, hits, n-hits, round(100*hits/n, 2),
                         round(covered, 2), round(100*covered/total, 2) if total else ""))
    write_csv(folder, "comparison.csv",
              ["daily_budget","strategy","reviews","fraud_hits","normal_reviews",
               "hits_per_100","covered_amount","fraud_amount_coverage_pct"], rows)
    examples = db.execute("""SELECT date(ts,'unixepoch'),id,amount,prior_count,
        ROUND(prior_avg,2),amount_rank,relative_rank,fraud FROM ranked
        WHERE (amount_rank <= 100) != (relative_rank <= 100)
        ORDER BY ts,id LIMIT 40""")
    write_csv(folder, "disagreements.csv",
              ["date","id","amount","prior_count","prior_avg","amount_rank","relative_rank","fraud"], examples)
    print(f"Test: {test_day} to {dates[-1]} | outputs: {folder}")
    for row in rows:
        print(*row)


if __name__ == "__main__":
    main()

