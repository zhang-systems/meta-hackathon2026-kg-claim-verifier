import json
import random
from pathlib import Path

from datasets import load_dataset

# Load the FEVER dev split (needs datasets<3 for script datasets)
ds = load_dataset("fever/fever", "v1.0", split="labelled_dev", trust_remote_code=True)

# Keep the first row for each id
seen = set()
rows = []
for row in ds:
    if row["id"] not in seen:
        seen.add(row["id"])
        rows.append(row)

# Pick 100 random claims
random.seed(42)
sample = random.sample(rows, 100)

# Write one JSON object per line
out = Path(__file__).resolve().parent.parent / "data" / "sample.jsonl"
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w") as f:
    for row in sample:
        f.write(json.dumps({"id": row["id"], "claim": row["claim"], "label": row["label"]}) + "\n")

print(f"Wrote {len(sample)} claims to {out}")
