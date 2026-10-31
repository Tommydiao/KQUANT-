"""Bounded, authenticated gateway-to-backend liveness during the isolated run."""
import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from time import monotonic, sleep
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=300)
    args = parser.parse_args()
    samples = []
    with httpx.Client(base_url="http://127.0.0.1:8132", timeout=1) as client, args.out.with_suffix(".jsonl").open("w") as log:
        assert client.post("/api/auth/login", json={"email": "test-only@example.invalid",
            "password": "TEST_ONLY_not_a_user_password"}).status_code == 200
        started = monotonic()
        while monotonic() - started < args.seconds:
            before = monotonic()
            value = {"observed_at": datetime.now(UTC).isoformat(), "test_only": True}
            try:
                response = client.get("/api/stocks/health/live")
                value.update(status=response.status_code, seconds=monotonic() - before)
                if response.status_code == 200:
                    body = response.json()
                    value.update(worker=body.get("research_worker"), event_loop=body.get("event_loop"))
            except httpx.HTTPError as exc:
                value.update(error=type(exc).__name__, seconds=monotonic() - before)
            samples.append(value)
            log.write(json.dumps(value) + "\n")
            log.flush()
            sleep(1)
    times = sorted(item["seconds"] for item in samples)
    report = {"test_only": True, "gateway_to_actual_backend": True, "duration_seconds": monotonic() - started,
        "n": len(samples), "statuses": dict(Counter(str(item.get("status", item.get("error"))) for item in samples)),
        "p95_seconds": times[min(len(times) - 1, int(len(times) * .95))], "max_seconds": max(times),
        "no_live_sdk_connection": True, "not_a_full_60_minute_probe": args.seconds < 3600}
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
