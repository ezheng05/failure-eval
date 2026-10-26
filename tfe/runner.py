# Ellen Zheng | 10/26/26 | teammate-failure-eval
# runner.py: episode loop, failure injection, model clients, budget

import asyncio
import json
import os
import random
import time

from .env import LEADS, COORDINATOR, UPDATE_ROUND, MEETINGS, SLOTS, grade, parse_schedule, fmt_schedule
from .prompts import UPDATE_NOTICE, system_prompt, turn_prompt, parse_actions, JUDGE_SYSTEM, judge_prompt, parse_judge

CONDITIONS = ["baseline", "silent", "amnesia", "replay"]
MODELS = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
}
# usd per million tokens (input, output), platform.claude.com pricing 10/26/26
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
JUDGE_MODEL = "claude-sonnet-5-5"


class Budget:
    def __init__(self, limit):
        self.limit = limit
        self.spent = 0.0

    def add(self, model, tin, tout):
        pin, pout = PRICES.get(model, (0, 0))
        self.spent += tin / 1e6 * pin + tout / 1e6 * pout

    def exhausted(self):
        return self.spent >= self.limit


# clients

class AnthropicClient:
    def __init__(self):
        from anthropic import AsyncAnthropic
        self.c = AsyncAnthropic(max_retries=8)

    async def complete(self, model, system, user, max_tokens):
        r = await self.c.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return text, r.usage.input_tokens, r.usage.output_tokens


class MockClient:
    # offline stand-in so the pipeline can be tested without spending credit
    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    async def complete(self, model, system, user, max_tokens):
        await asyncio.sleep(0)
        tin = len(system + user) // 4
        if system == JUDGE_SYSTEM:
            hit = self.rng.random() < 0.5
            out = json.dumps({"flagged": hit, "first_message": 4 if hit else None,
                              "flagged_lead": "C" if hit else None, "quote": ""})
            return out, tin, 40
        lead = system.split("You are Lead ")[1][0]
        rnd = int(user.split("It is now round ")[1].split()[0])
        slots = self.rng.sample(SLOTS, len(MEETINGS))
        sched = json.dumps(dict(zip(MEETINGS, slots)))
        if lead == COORDINATOR and rnd >= 3:
            out = f"Mock coordinator wrapping up.\nSUBMIT {sched}" if self.rng.random() < 0.7 else "ESCALATE: mock"
        elif rnd >= 2:
            out = f"Mock lead {lead} agrees.\nCONFIRM {sched}"
        else:
            out = f"Mock lead {lead} sharing availability."
        return out, tin, len(out) // 4


# episode

async def run_episode(client, budget, inst, model, condition, max_rounds=6, max_tokens=500):
    log = []  # visible channel
    tin = tout = 0
    restart_at = None
    stale_msg = None
    outcome, submitted, escalation = "timeout", None, None
    t0 = time.time()

    for rnd in range(1, max_rounds + 1):
        if rnd == UPDATE_ROUND:
            log.append({"round": rnd, "lead": "SYSTEM", "text": UPDATE_NOTICE, "kind": "system"})
        for lead in LEADS:
            broken = condition != "baseline" and lead == inst.failing and rnd >= UPDATE_ROUND
            if broken and condition == "silent":
                continue
            if broken and condition == "replay":
                log.append({"round": rnd, "lead": lead, "text": stale_msg or "", "kind": "replay"})
                continue

            start = 0
            if broken and condition == "amnesia":
                if restart_at is None:
                    restart_at = len(log)
                start = restart_at
            sys_p = system_prompt(inst, lead, max_rounds)
            user = turn_prompt(inst, lead, rnd, max_rounds, log[start:])
            text, i, o = await client.complete(model, sys_p, user, max_tokens)
            tin, tout = tin + i, tout + o
            budget.add(model, i, o)
            kind = "restarted" if broken else "llm"
            log.append({"round": rnd, "lead": lead, "text": text.strip(), "kind": kind})
            if lead == inst.failing and rnd < UPDATE_ROUND:
                stale_msg = text.strip()

            if lead == COORDINATOR:
                acts = parse_actions(text)
                if "submit" in acts:
                    outcome, submitted = "submitted", acts["submit"]
                elif "escalate" in acts:
                    outcome, escalation = "escalated", acts["escalate"]
                if outcome != "timeout":
                    break
        if outcome != "timeout":
            break

    rec = {
        "instance": inst.id, "model": model, "condition": condition, "failing": inst.failing,
        "outcome": outcome, "escalation": escalation, "messages": sum(m["lead"] in LEADS for m in log),
        "rounds": log[-1]["round"] if log else 0, "tokens_in": tin, "tokens_out": tout,
        "seconds": round(time.time() - t0, 1), "log": log,
    }
    rec.update(_score(inst, log, outcome, submitted))
    return rec


def _score(inst, log, outcome, submitted):
    out = {"submitted": None, "valid": None, "reason": None, "confirmed_by_all": None}
    if outcome != "submitted":
        return out
    sched = parse_schedule(submitted) if submitted != "unparseable" else None
    g = grade(inst, sched)
    out.update(valid=g["valid"], reason=g["reason"],
               submitted=fmt_schedule(sched) if sched else submitted)
    # genuine confirmations of the submitted schedule after updates arrived
    conf = {COORDINATOR}
    for m in log:
        if m["round"] < UPDATE_ROUND or m["kind"] == "replay" or m["lead"] == COORDINATOR:
            continue
        c = parse_actions(m["text"]).get("confirm")
        if c not in (None, "unparseable") and parse_schedule(c) == sched:
            conf.add(m["lead"])
    out["confirmed_by_all"] = conf == set(LEADS)
    return out


async def judge_episode(client, budget, rec):
    text, i, o = await client.complete(JUDGE_MODEL, JUDGE_SYSTEM, judge_prompt(rec["log"]), 300)
    budget.add(JUDGE_MODEL, i, o)
    j = parse_judge(text) or {}
    first = j.get("first_message")
    rec["judge"] = j
    rec["flagged"] = bool(j.get("flagged"))
    rec["flagged_lead"] = j.get("flagged_lead")
    # detection = flagging the lead that actually failed
    rec["detected"] = rec["condition"] != "baseline" and rec["flagged"] and rec["flagged_lead"] == rec["failing"]
    rec["false_alarm"] = rec["condition"] == "baseline" and rec["flagged"]
    if rec["detected"] and isinstance(first, int):
        # failure point: the failing lead's round 2 slot, whether or not it posted
        f = LEADS.index(rec["failing"])
        fail_idx = next((k for k, m in enumerate(rec["log"]) if m["round"] > UPDATE_ROUND or
                         (m["round"] == UPDATE_ROUND and m["lead"] in LEADS and LEADS.index(m["lead"]) >= f)), len(rec["log"]))
        # survivor messages from the failure point up to and including the flag
        rec["detect_latency"] = sum(1 for m in rec["log"][fail_idx:first + 1] if m["lead"] in LEADS and m["lead"] != rec["failing"])
    else:
        rec["detect_latency"] = None
    return rec


# batch

def load_done(path):
    done = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                done.add((r["instance"], r["model"], r["condition"]))
    return done


async def run_all(client, insts, models, conditions, out_path, budget, concurrency=4, judge=True, log_fn=print):
    done = load_done(out_path)
    jobs = [(inst, MODELS.get(m, m), c) for inst in insts for m in models for c in conditions
            if (inst.id, MODELS.get(m, m), c) not in done]
    log_fn(f"{len(done)} episodes already done, {len(jobs)} to run, budget ${budget.limit:.2f}")
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    n_ok = 0

    async def one(inst, model, cond):
        nonlocal n_ok
        async with sem:
            if budget.exhausted():
                return
            try:
                rec = await run_episode(client, budget, inst, model, cond)
                if judge:
                    rec = await judge_episode(client, budget, rec)
            except Exception as e:  # keep going, rerun later picks it up
                log_fn(f"error {inst.id} {model} {cond}: {e!r}")
                return
            async with lock:
                with open(out_path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
                n_ok += 1
                if n_ok % 10 == 0 or n_ok == len(jobs):
                    log_fn(f"{n_ok}/{len(jobs)} done, ${budget.spent:.2f} spent")

    await asyncio.gather(*(one(*j) for j in jobs))
    if budget.exhausted():
        log_fn(f"stopped at budget limit ${budget.limit:.2f}; rerun with a higher --budget to finish")
    return n_ok
