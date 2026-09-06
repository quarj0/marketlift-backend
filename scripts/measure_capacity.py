#!/usr/bin/env python3
"""Bounded, read-only HTTP load probe. Defaults to local targets only."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import statistics
import time
from urllib.parse import urlsplit
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base-url", default="http://127.0.0.1:8000")
parser.add_argument("--requests", type=int, default=100)
parser.add_argument("--concurrency", type=int, default=4)
parser.add_argument(
    "--allow-remote",
    action="store_true",
    help="Explicitly permit an operator-approved staging or production load probe",
)
parser.add_argument("--output", default="capacity-results.json")
args = parser.parse_args()
if (
    urlsplit(args.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}
    and not args.allow_remote
):
    parser.error("Remote load requires --allow-remote and operator approval.")
if not 1 <= args.requests <= 10000 or not 1 <= args.concurrency <= 32:
    parser.error("Requests must be 1–10000 and concurrency 1–32.")
paths = [
    "/api/v1/health/",
    "/api/v1/search/listings/?q=samsung&countryCode=BR&pageSize=24",
    "/api/v1/search/listings/?countryCode=BR&state=SP&city=S%C3%A3o%20Paulo&expandRegions=true&pageSize=24",
]


def probe(index):
    start = time.monotonic()
    try:
        with urlopen(
            args.base_url.rstrip("/") + paths[index % len(paths)], timeout=15
        ) as response:
            response.read()
            status = response.status
    except HTTPError as exc:
        status = exc.code
    except (URLError, TimeoutError):
        status = 0
    return {"status": status, "durationMs": round((time.monotonic() - start) * 1000, 2)}


started = time.monotonic()
with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
    rows = list(pool.map(probe, range(args.requests)))
latencies = sorted(row["durationMs"] for row in rows)
result = {
    "targetHost": urlsplit(args.base_url).hostname,
    "requests": len(rows),
    "concurrency": args.concurrency,
    "elapsedSeconds": round(time.monotonic() - started, 2),
    "medianMs": statistics.median(latencies),
    "p95Ms": latencies[min(len(rows) - 1, int(len(rows) * 0.95))],
    "errors": sum(row["status"] >= 400 or row["status"] == 0 for row in rows),
    "statuses": {
        str(code): sum(row["status"] == code for row in rows)
        for code in sorted({row["status"] for row in rows})
    },
}
with open(args.output, "w") as output:
    json.dump(result, output, indent=2)
print(json.dumps(result, indent=2))
