# Ellen Zheng | 10/26/26 | teammate-failure-eval
# run.py: generate instances and run episodes

import argparse
import asyncio
import json
import os
from collections import defaultdict

from tfe.env import generate_set, save_instances, load_instances
from tfe.runner import AnthropicClient, MockClient, Budget, run_all, CONDITIONS, MODELS, EFFORT

INST_PATH = "data/instances.json"
FULL_INSTANCES = 40


def cost_report(path):
    # avg cost per episode by model, plus what the full run would cost
    per = defaultdict(list)
    bad = 0
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            per[r["model"]].append(r.get("cost", 0) + r.get("judge_cost", 0))
            bad += r.get("empty", 0) + r.get("truncated", 0)
    total = 0
    for m, cs in per.items():
        avg = sum(cs) / len(cs)
        proj = avg * FULL_INSTANCES * len(CONDITIONS)
        total += proj
        print(f"  {m}: ${avg:.3f} per episode, about ${proj:.0f} for the full run")
    if len(per) == len(MODELS):
        print(f"  full run estimate: about ${total:.0f}")
    print(f"  empty or truncated replies: {bad}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=list(MODELS))
    ap.add_argument("--conditions", nargs="+", default=CONDITIONS)
    ap.add_argument("--instances", type=int, default=FULL_INSTANCES)
    ap.add_argument("--budget", type=float, default=60.0, help="usd cap for this run")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--effort", default=EFFORT, choices=["low", "medium", "high"])
    ap.add_argument("--out", default="results/episodes.jsonl")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="1 instance, every model, 2 conditions")
    ap.add_argument("--mock", action="store_true", help="offline fake model, no api calls")
    a = ap.parse_args()

    if not os.path.exists(INST_PATH):
        os.makedirs("data", exist_ok=True)
        save_instances(generate_set(100), INST_PATH)
    insts = load_instances(INST_PATH)[: a.instances]

    if a.smoke:
        insts, a.conditions, a.out = insts[:1], ["baseline", "replay"], "results/smoke.jsonl"
    if a.mock:
        client, a.out = MockClient(), "results/mock.jsonl"
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("set ANTHROPIC_API_KEY first")
        client = AnthropicClient(effort=a.effort)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    if (a.smoke or a.mock) and os.path.exists(a.out):
        os.remove(a.out)  # always start these fresh
    budget = Budget(a.budget)
    asyncio.run(run_all(client, insts, a.models, a.conditions, a.out, budget,
                        concurrency=a.concurrency, judge=not a.no_judge))
    print(f"spent about ${budget.spent:.2f} this run, results in {a.out}")
    if os.path.exists(a.out):
        cost_report(a.out)


if __name__ == "__main__":
    main()
