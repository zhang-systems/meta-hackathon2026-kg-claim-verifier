# Knowledge-Graph Claim Verifier

Verify AI answers against Wikidata triples. Built for the Meta Global AI Developer Hackathon (Build for Your World).

AI answers sound confident even when they are wrong. This verifier checks a claim the way a fact-checker would: split it into atomic facts, fetch evidence triples from Wikidata, and judge each fact only from those triples. If the evidence is too weak, it says NOT ENOUGH INFO instead of guessing.

## How it works

1. **Sample.** 100 claims from FEVER (labelled_dev, deduped by id, seed 42).
2. **Split.** Muse Spark splits each claim into atomic facts (189 total, 1.89 per claim).
3. **Fetch evidence.** For each atomic fact, search Wikidata, take the best-matching entity, and keep the 5 triples most relevant to the fact (word overlap). Identifier triples (external IDs) are filtered out.
4. **Verify.** Muse Spark judges each fact SUPPORTS / REFUTES / NOT ENOUGH INFO using only the triples given. Facts judged NOT ENOUGH INFO go to Muse Wonder for a second review under the same triples-only rule.
5. **Score.** Claim verdicts aggregate from atomic verdicts (all SUPPORTS -> SUPPORTS; any REFUTES -> REFUTES; else NOT ENOUGH INFO) and are compared with the FEVER labels verbatim.

## Results (100-claim sample, preliminary)

Overall: 39/100 (0.390). SUPPORTS: 3/42. NOT ENOUGH INFO: 30/33. REFUTES: 6/25.

171 of 189 facts retrieved at least one triple; 169 of 189 facts went to second review. The verifier is conservative by design: it answers NOT ENOUGH INFO when the evidence is weak. The bottleneck is retrieval, not the judge model: Wikidata entities return broad triples, and content triples do not always reach the top 5. When the right triple is retrieved, the mechanism works. Example: "There were grammies won by Stadium Arcadium" verifies via `award received | Grammy Award for Best Rock Album`.

## Run it

Python 3.12. Install dependencies:

pip install datasets==2.21.0 python-dotenv openai pytest

Set up the key (never commit it):

cp .env.example .env

Fill in MODEL_API_KEY (Meta API key), MODEL_API_BASE_URL, and MODEL_API_MODEL in .env.

Run the pipeline in order:

python scripts/sample_fever.py
python scripts/split_claims.py
python scripts/fetch_evidence.py
python scripts/verify_claims.py

Run the tests:

python -m pytest tests/

## Repo layout

scripts/: sample_fever.py, split_claims.py, fetch_evidence.py, verify_claims.py. data/: sample.jsonl, split_claims.jsonl, evidence.jsonl, verdicts.jsonl (evidence_v1_noisy.jsonl and evidence_v2_ranked.jsonl are earlier runs, kept for comparison). tests/: pytest suite covering verdict parsing, aggregation, prompt contents, relevance ranking, and the identifier filter.

## Data and models

Claims: FEVER (Thorne et al., 2018), CC BY-SA 3.0. Sample: 100 claims, seed 42. Labels: SUPPORTS 42 / NOT ENOUGH INFO 33 / REFUTES 25. Evidence: Wikidata (CC0), via the public wbsearchentities and wbgetclaims APIs. No triples are invented; facts with no evidence get NOT ENOUGH INFO. Models (Meta): Muse Spark 1.3 (muse-spark-1.3) for splitting and first verification; Muse Wonder 1.0 (muse-wonder-1.0) for second review of hard cases. All code in this repo was written during the hackathon building period (Oct 26 - Nov 4, 2026).

## Limitations

100-claim sample; results are preliminary. Retrieval is the bottleneck: broad and category triples crowd out content triples, and refutation especially suffers because knowledge-graph triples rarely carry negative evidence. The verifier judges only from the triples given; it does not use outside knowledge.
