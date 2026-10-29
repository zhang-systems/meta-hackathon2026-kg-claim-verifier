import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Find project paths
ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "data" / "sample.jsonl"
OUTPUT = ROOT / "data" / "split_claims.jsonl"

# Load settings from local .env file
load_dotenv(ROOT / ".env")

# Check that all required settings exist
required = ["MODEL_API_KEY", "MODEL_API_BASE_URL", "MODEL_API_MODEL"]
missing = [name for name in required if not os.getenv(name)]
if missing:
    raise SystemExit(f"Missing in .env: {', '.join(missing)}")

# Connect to the model API
client = OpenAI(
    base_url=os.getenv("MODEL_API_BASE_URL"),
    api_key=os.getenv("MODEL_API_KEY"),
)
model = os.getenv("MODEL_API_MODEL")

# Read input claims, one JSON object per line
with open(INPUT) as f:
    rows = [json.loads(line) for line in f if line.strip()]

results = []
for row in rows:
    # Ask the model to split one claim
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": "You split a claim into the smallest checkable atomic facts."},
            {
                "role": "user",
                "content": (
                    "Split this claim into the smallest checkable atomic facts. "
                    "Each atomic fact has one entity and one relation or value. "
                    "Do not add new information. "
                    "Do not infer anything beyond the claim. "
                    "Write one atomic fact per line, no numbering, no extra text.\n\n"
                    f"Claim: {row['claim']}"
                ),
            },
        ],
    )
    # Keep each non-empty line as one atomic fact
    text = response.choices[0].message.content
    atomic = [line.strip() for line in text.splitlines() if line.strip()]

    # Keep id and label unchanged
    results.append(
        {
            "claim_id": row["id"],
            "claim": row["claim"],
            "label": row["label"],
            "atomic_claims": atomic,
        }
    )

# Write one JSON object per line
with open(OUTPUT, "w") as f:
    for item in results:
        f.write(json.dumps(item) + "\n")

print(f"Split {len(results)} claims into {OUTPUT}")
