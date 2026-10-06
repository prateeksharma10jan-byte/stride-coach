"""LLM grounding evals.

    OPENAI_API_KEY=... python -m evals.run_evals --samples 5 --threshold 0.95

For every fixture it samples the real analyst prompt N times and scores each reply:
  grounded   - no number outside FACTS (the app's runtime guard, applied offline)
  concise    - <= 220 words
  pr_called  - if FACTS contain a PR, the reply mentions it
Exit code 1 if the grounded rate is below --threshold (use it as a CI/regression gate when you
change prompts or models)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app import guard
from app.bot import llm_view
from evals.fixtures import ALL

PROMPT = (Path(__file__).parent.parent / "app" / "prompts" / "analyst.md").read_text()


def evaluate(llm, samples: int = 3) -> dict:
    rows = []
    for name, facts in ALL.items():
        for _ in range(samples):
            out = llm.complete(PROMPT, [{"role": "user",
                                         "content": f"FACTS:\n{json.dumps(llm_view(facts))}"}])
            bad = guard.ungrounded_numbers(out, llm_view(facts))
            rows.append({
                "case": name, "ungrounded": bad, "grounded": not bad,
                "concise": len(out.split()) <= 220,
                "pr_called": (not facts.get("prs")) or "pr" in out.lower(),
            })
    n = len(rows)
    summary = {k: round(sum(r[k] for r in rows) / n, 3) for k in ("grounded", "concise", "pr_called")}
    return {"summary": summary, "rows": rows, "n": n}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--threshold", type=float, default=0.95)
    ap.add_argument("--model", default="gpt-4o-mini")
    a = ap.parse_args()
    from app.clients.llm import LLM
    res = evaluate(LLM(a.model), a.samples)
    print(json.dumps(res["summary"], indent=2))
    for r in res["rows"]:
        if not r["grounded"]:
            print(f"UNGROUNDED in {r['case']}: {r['ungrounded']}")
    return 0 if res["summary"]["grounded"] >= a.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
