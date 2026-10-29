import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Find project paths
ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "data" / "evidence.jsonl"
OUTPUT = ROOT / "data" / "verdicts.jsonl"

# Models: Spark judges first, Wonder reviews hard cases
SPARK_MODEL = "muse-spark-1.3"
WONDER_MODEL = "muse-wonder-1.0"

SUPPORTS = "SUPPORTS"
REFUTES = "REFUTES"
NEI = "NOT ENOUGH INFO"
VERDICTS = (SUPPORTS, REFUTES, NEI)


def parse_verdict(text):
    # Normalize one model reply to exactly one verdict label
    upper = (text or "").upper()
    found = [(upper.find(v), v) for v in VERDICTS if v in upper]
    if not found:
        return NEI
    return sorted(found)[0][1]


def aggregate(verdicts):
    # Any refute wins; else all support wins; else not enough info
    if not verdicts:
        return NEI
    if REFUTES in verdicts:
        return REFUTES
    if all(v == SUPPORTS for v in verdicts):
        return SUPPORTS
    return NEI


def build_messages(fact, triples):
    # One fact plus its evidence triples only, with a triples-only rule
    if triples:
        evidence = "\n".join(f"- {t}" for t in triples)
    else:
        evidence = "(none found)"
    return [
        {"role": "system", "content": (
            "You judge whether evidence triples support or refute a fact. "
            "Use only the triples given.")},
        {"role": "user", "content": (
            f"Atomic fact: {fact}\n\nEvidence triples:\n{evidence}\n\n"
            "Judge ONLY from the triples above. If no triple directly "
            "supports or refutes the fact, say NOT ENOUGH INFO. "
            "Never use outside knowledge. Reply with exactly one of: "
            "SUPPORTS, REFUTES, NOT ENOUGH INFO.")},
    ]


def judge(client, model, fact, triples):
    # One verdict per call, retrying transient failures
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=build_messages(fact, triples),
            )
            return parse_verdict(response.choices[0].message.content)
        except Exception:
            if attempt == 2:
                raise SystemExit("Model API did not answer, try again later")
            time.sleep(5)


def main():
    # Load settings from local .env file
    load_dotenv(ROOT / ".env")

    # Check that all required settings exist
    required = ["MODEL_API_KEY", "MODEL_API_BASE_URL"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)}")

    # Connect to the model API
    client = OpenAI(
        base_url=os.getenv("MODEL_API_BASE_URL"),
        api_key=os.getenv("MODEL_API_KEY"),
    )

    # Read evidence rows, one JSON object per line
    with open(INPUT) as f:
        rows = [json.loads(line) for line in f if line.strip()]

    # Skip claims already done, so a rerun resumes
    done = set()
    if OUTPUT.exists():
        with open(OUTPUT) as f:
            for line in f:
                if line.strip():
                    done.add(json.loads(line)["claim_id"])

    # Verify each claim, save each one right away
    count = 0
    with open(OUTPUT, "a") as f:
        for row in rows:
            if row["claim_id"] in done:
                continue
            atomic = []
            for fact, triples in zip(row["atomic_claims"], row["evidence"]):
                if triples:
                    verdict = judge(client, SPARK_MODEL, fact, triples)
                else:
                    verdict = NEI
                source = "spark"
                if verdict == NEI:
                    verdict = judge(client, WONDER_MODEL, fact, triples)
                    source = "wonder"
                atomic.append(
                    {"fact": fact, "verdict": verdict, "source": source})
            item = {
                "claim_id": row["claim_id"],
                "claim": row["claim"],
                "label": row["label"],
                "atomic_verdicts": atomic,
                "claim_verdict": aggregate([a["verdict"] for a in atomic]),
            }
            f.write(json.dumps(item) + "\n")
            f.flush()
            count += 1
            if count % 10 == 0:
                print(f"Done {count + len(done)}/{len(rows)} claims",
                      flush=True)

    print(f"Verified {len(rows)} claims into {OUTPUT}")

    # Score claim verdicts against FEVER labels, verbatim
    with open(OUTPUT) as f:
        scored = [json.loads(line) for line in f if line.strip()]
    correct = sum(1 for r in scored if r["claim_verdict"] == r["label"])
    print(f"Accuracy: {correct}/{len(scored)} = {correct / len(scored):.3f}")
    for gold in VERDICTS:
        group = [r for r in scored if r["label"] == gold]
        hits = sum(1 for r in group if r["claim_verdict"] == gold)
        print(f"{gold}: {hits}/{len(group)} correct")
    wonder_facts = sum(
        1 for r in scored for a in r["atomic_verdicts"]
        if a["source"] == "wonder")
    print(f"Facts reviewed by Wonder: {wonder_facts}")


if __name__ == "__main__":
    main()
