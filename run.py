# Ellen Zheng | 10/26/26 | teammate-failure-eval
# run.py: generate instances and run episodes

import argparse
import asyncio
import os

from tfe.env import generate_set, save_instances, load_instances
from tfe.runner import AnthropicClient, MockClient, Budget, run_all, CONDITIONS, MODELS

INST_PATH = "data/instances.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=list(MODELS))
    ap.add_argument("--conditions", nargs="+", default=CONDITIONS)
    ap.add_argument("--instances", type=int, default=40)
    ap.add_argument("--budget", type=float, default=60.0, help="usd cap for this run")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--out", default="results/episodes.jsonl")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="2 instances on haiku, a few cents")
    ap.add_argument("--mock", action="store_true", help="offline fake model, no api calls")
    a = ap.parse_args()

    if not os.path.exists(INST_PATH):
        os.makedirs("data", exist_ok=True)
        save_instances(generate_set(100), INST_PATH)
    insts = load_instances(INST_PATH)[: a.instances]

    if a.smoke:
        insts, a.models, a.out = insts[:2], ["haiku"], "results/smoke.jsonl"
    if a.mock:
        client, a.out = MockClient(), "results/mock.jsonl"
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("set ANTHROPIC_API_KEY first")
        client = AnthropicClient()

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    budget = Budget(a.budget)
    asyncio.run(run_all(client, insts, a.models, a.conditions, a.out, budget,
                        concurrency=a.concurrency, judge=not a.no_judge))
    print(f"spent about ${budget.spent:.2f} this run, results in {a.out}")


if __name__ == "__main__":
    main()
