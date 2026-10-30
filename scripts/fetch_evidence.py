import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

# Find project paths
ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "data" / "split_claims.jsonl"
OUTPUT = ROOT / "data" / "evidence.jsonl"

# Wikidata API address
API = "https://www.wikidata.org/w/api.php"
SLEEP = 1.0  # Pause between calls to be polite
MAX_WORKERS = 1  # One fetcher: sustained concurrent load trips throttling
HEADERS = {"User-Agent": "KGClaimVerifier/1.0 (hackathon project)"}

# One shared connection, reused to avoid a slow handshake per call
_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)


def wait_time(headers, attempt):
    # Read the asked wait, default 5 seconds, max 60
    try:
        asked = int(headers.get("Retry-After", 5))
    except ValueError:
        asked = 5
    return min(asked, 60) + attempt * 5


def ask(params):
    # Send one request, retry if limited, busy, or network fails
    for attempt in range(10):
        time.sleep(SLEEP)
        try:
            r = _SESSION.get(API, params=params, timeout=30)
        except requests.exceptions.RequestException:
            time.sleep(min(5 + attempt * 5, 60))
            continue
        if r.status_code == 429:
            time.sleep(wait_time(r.headers, attempt))
            continue
        r.raise_for_status()
        data = r.json()
        if data.get("error", {}).get("code") == "cirrussearch-too-busy-error":
            time.sleep(min(5 + attempt * 5, 60))
            continue
        return data
    raise SystemExit("Wikidata did not answer, try again later")


# Past label answers, to avoid asking twice (same ids repeat across facts)
_label_cache = {}


def labels_for(ids):
    # Fetch English labels for entity and property ids, reusing past answers
    with _cache_lock:
        missing = sorted(set(ids) - set(_label_cache))
    for i in range(0, len(missing), 50):
        data = ask({
            "action": "wbgetentities",
            "ids": "|".join(missing[i:i + 50]),
            "props": "labels",
            "languages": "en",
            "format": "json",
        })
        with _cache_lock:
            for qid, ent in data.get("entities", {}).items():
                label = ent.get("labels", {}).get("en", {}).get("value")
                if label:
                    _label_cache[qid] = label
    with _cache_lock:
        return {i: _label_cache[i] for i in ids if i in _label_cache}


def plain_value(datavalue):
    # Turn a simple value into readable text, else None
    kind = datavalue.get("type")
    value = datavalue.get("value")
    if kind == "string":
        return value
    if kind == "monolingualtext":
        return value["text"]
    if kind == "time":
        return value["time"].lstrip("+").split("T")[0]
    if kind == "quantity":
        return value["amount"].lstrip("+")
    return None


# Past search answers, to avoid asking twice
search_cache = {}

# Past claims answers, to avoid asking twice (facts often share an entity)
_claims_cache = {}

# Guards the caches above plus _label_cache across fetch threads
_cache_lock = threading.Lock()


def search(query):
    # Search Wikidata once per query, reuse past answers
    with _cache_lock:
        if query in search_cache:
            return search_cache[query]
    hits = ask({
        "action": "wbsearchentities",
        "search": query,
        "language": "en",
        "format": "json",
    }).get("search", [])
    with _cache_lock:
        search_cache[query] = hits
    return hits


def find_entity(fact):
    # Find the main entity: try the fact text, then short prefixes.
    # A full sentence never matches a label, so shortening is needed.
    # Accept a match only when its label equals the query.
    words = fact.strip().rstrip(".,").split()
    queries = [" ".join(words)]
    for n in range(min(len(words) - 1, 5), 0, -1):
        queries.append(" ".join(words[:n]))
    for query in queries:
        if len(query) < 2:
            continue
        for hit in search(query)[:7]:
            if hit.get("label", "").lower() == query.lower():
                return hit
    return None


# Common words that carry no topic meaning, skipped when scoring
STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "by", "with",
    "and", "or", "as", "is", "was", "were", "are", "be", "been", "being",
    "from", "that", "this", "it", "its", "which", "who", "whom", "whose",
    "he", "she", "they", "them", "his", "her", "their", "we", "you",
    "not", "no", "do", "does", "did", "have", "has", "had", "will",
    "would", "can", "could", "should", "there", "here", "when", "where",
    "also", "into", "over", "after", "before", "between", "during",
    "about", "such", "other", "more", "most", "some", "any", "all",
}


def _content_words(text):
    # Lowercase alphanumeric words, minus stopwords, lightly singularized
    # so plurals like "grammies" still match "grammy"
    words = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOPWORDS or len(w) <= 1:
            continue
        if w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            w = w[:-1]
        words.add(w)
    return words


def _relevance(fact_words, prop_label, val_label):
    # Shared content words between the fact and property + value labels
    triple_words = _content_words(f"{prop_label} {val_label}")
    return len(fact_words & triple_words)


def rank_triples(fact, labeled):
    # Score every candidate, keep the 5 best; ties keep original order.
    # labeled: list of (property label, value label, triple text)
    fact_words = _content_words(fact)
    scored = [
        (_relevance(fact_words, prop, val), i, triple)
        for i, (prop, val, triple) in enumerate(labeled)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [triple for _, _, triple in scored[:5]]


_ID_WORD = re.compile(r"\bID\b", re.IGNORECASE)


def _is_identifier_prop(prop_label):
    # True for external-id properties, e.g. "Metacritic ID" or "GRIDID"
    text = (prop_label or "").strip()
    lowered = text.lower()
    return (
        "identifier" in lowered
        or lowered.endswith("id")
        or _ID_WORD.search(text) is not None
    )


def evidence_for(fact):
    # Search Wikidata for the main entity of the fact
    match = find_entity(fact)
    if not match:
        return []
    qid = match["id"]

    # Fetch the entity claims, reusing past answers for repeat entities
    with _cache_lock:
        claims = _claims_cache.get(qid)
    if claims is None:
        claims = ask({
            "action": "wbgetclaims",
            "entity": qid,
            "format": "json",
        }).get("claims", {})
        with _cache_lock:
            _claims_cache[qid] = claims
    if not claims:
        return []

    # Gather every candidate triple and note labels we need
    picks = []  # List of (property id, value text or entity id)
    need = {qid}
    for pid, statements in claims.items():
        for st in statements:
            snak = st.get("mainsnak", {})
            if snak.get("snaktype") != "value":
                continue
            datavalue = snak.get("datavalue", {})
            if datavalue.get("type") == "wikibase-entityid":
                picks.append((pid, datavalue["value"]["id"]))
                need.add(pid)
                need.add(datavalue["value"]["id"])
            else:
                text = plain_value(datavalue)
                if text is None:
                    continue
                picks.append((pid, text))
                need.add(pid)
    if not picks:
        return []

    # Fetch labels, drop identifier triples, keep the 5 most relevant
    labels = labels_for(need)
    subject = labels.get(qid, match.get("label", qid))
    labeled = []
    for pid, val in picks:
        prop = labels.get(pid, pid)
        if _is_identifier_prop(prop):
            continue
        value = labels.get(val, val)
        labeled.append((prop, value, f"{subject} | {prop} | {value}"))
    return rank_triples(fact, labeled)


def main():
    # Read split claims, one JSON object per line
    with open(INPUT) as f:
        rows = [json.loads(line) for line in f if line.strip()]

    # Skip claims already done, so a rerun resumes
    done = set()
    if OUTPUT.exists():
        with open(OUTPUT) as f:
            for line in f:
                if line.strip():
                    done.add(json.loads(line)["claim_id"])

    # Fetch rows concurrently (same read-only calls), write in input order
    todo = [row for row in rows if row["claim_id"] not in done]

    def fetch_row(row):
        return {
            "claim_id": row["claim_id"],
            "claim": row["claim"],
            "label": row["label"],
            "atomic_claims": row["atomic_claims"],
            "evidence": [evidence_for(fact) for fact in row["atomic_claims"]],
        }

    base = len(rows) - len(todo)
    pending = {}
    next_i = 0
    with open(OUTPUT, "a") as f, ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        waiting = {pool.submit(fetch_row, row): n for n, row in enumerate(todo)}
        for future in as_completed(waiting):
            pending[waiting[future]] = future.result()
            while next_i in pending:
                f.write(json.dumps(pending.pop(next_i)) + "\n")
                f.flush()
                next_i += 1
                if next_i % 5 == 0:
                    print(f"Done {base + next_i}/{len(rows)} claims", flush=True)

    print(f"Fetched evidence for {len(rows)} claims into {OUTPUT}")


if __name__ == "__main__":
    main()
