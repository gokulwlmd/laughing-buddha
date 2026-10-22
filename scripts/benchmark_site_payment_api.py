"""Measure public checkout API latency without preparing or submitting a payment.

Each round creates one isolated session and one synthetic draft quote. Reports
contain timings, response codes and public totals only, never session tokens,
session IDs, customer information, processor keys or raw response bodies. The
first plans request is not guaranteed to hit a cold server cache.

Run with the project's Python environment (httpx is a project dependency).
"""
import argparse
import json
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


DEFAULT_ORIGIN = "https://wlmd-site-api-demo-0f89b1bb.fly.dev"


def run(origin=DEFAULT_ORIGIN, rounds=1):
    origin = origin.rstrip("/")
    base = "/api/v1/sites/payment-test"
    observations = []
    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "rounds_requested": rounds,
        "financial_calls": 0,
        "connection_reused": True,
        "cache_note": "First plans request may already be cached; no cache purge is performed.",
        "measurements": observations,
    }

    # Keep TLS connections alive, as a browser does. Redirects are never followed.
    with httpx.Client(base_url=origin, timeout=120, follow_redirects=False) as client:
        def call(label, path, *, body=None, token=None, expected=200, round_number):
            headers = {"Accept": "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + token
            started = time.perf_counter()
            row = {"round": round_number, "operation": label}
            try:
                response = client.request(
                    "POST" if body is not None else "GET", path,
                    headers=headers, **({"json": body} if body is not None else {}),
                )
                row["status_code"] = response.status_code
                timing=re.fullmatch(r"app;dur=([0-9.]+)",response.headers.get("server-timing", ""))
                if timing:row["server_ms"]=float(timing.group(1))
                if response.status_code != expected:
                    raise ValueError("Unexpected response status")
                return response.json()
            except Exception as exc:
                # Exception strings can include private URLs or response values.
                row["error_type"] = type(exc).__name__
                raise
            finally:
                row["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
                observations.append(row)

        for number in range(1, rounds + 1):
            try:
                health = call("health", "/health", round_number=number)
                if not health.get("session_storage_configured"):
                    raise ValueError("Session storage unavailable")
                plans = call("plans_first", base + "/plans", round_number=number)
                call("plans_repeat", base + "/plans", round_number=number)
                if not any(plan.get("plan_id") == "sema-1m" for plan in plans.get("plans", [])):
                    raise ValueError("Benchmark plan unavailable")
                session = call("create_session", base + "/sessions",
                               body={"plan_id": "sema-1m"}, expected=201, round_number=number)
                path = base + "/sessions/" + session["session_id"]
                token = session["session_token"]
                cfg = call("configuration_first", path + "/configuration", token=token, round_number=number)
                call("configuration_repeat", path + "/configuration", token=token, round_number=number)
                shipping = cfg["shipping"][0]["id"] if len(cfg["shipping"]) == 1 else None
                total = call("quote", path + "/quote", token=token, round_number=number, body={
                    "contact": {
                        "name": "API Latency Test", "email": "api-latency@example.invalid",
                        "phone": "+12025550100", "address": "1 Test Way", "city": "San Francisco",
                        "region": "CA", "postal_code": "94105", "country": "US",
                    },
                    "shipping_id": shipping,
                })
                state = call("status", path, token=token, round_number=number)
                if state["status"] != "new" or state.get("payment_intent_id") is not None:
                    raise ValueError("Unexpected payment state")
                report["quote"] = {"amount": total["amount"], "currency": total["currency"]}
                report["rounds_completed"] = number
            except Exception as exc:
                report["error_type"] = type(exc).__name__
                report["ok"] = False
                break
        else:
            report["ok"] = True

    report["summary_ms"] = {}
    for operation in dict.fromkeys(row["operation"] for row in observations):
        values = [row["elapsed_ms"] for row in observations
                  if row["operation"] == operation and "error_type" not in row]
        if values:
            report["summary_ms"][operation] = {
                "min": min(values), "median": round(statistics.median(values), 1), "max": max(values),
            }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--rounds", type=int, default=1, choices=range(1, 11), metavar="1-10")
    parser.add_argument("--output", type=Path, help="Write sanitized JSON report to this local file")
    args = parser.parse_args()
    result = run(args.origin, args.rounds)
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
    raise SystemExit(0 if result["ok"] else 1)
