# Ellen Zheng | 10/26/26 | teammate-failure-eval
# test_all.py: run with `python -m tests.test_all` or pytest

import asyncio
import json

from tfe.env import (LEADS, MEETINGS, SLOTS, TEAMS, UPDATE_ROUND, count, generate_set, grade,
                     is_valid, normalize_slot, parse_schedule, solutions)
from tfe.prompts import parse_actions
from tfe.runner import Budget, MockClient, run_episode

INSTS = generate_set(15, seed=7)


def test_generator_properties():
    for inst in INSTS:
        n = count(inst.attendees, inst.truth())
        assert 1 <= n <= 3 and n == inst.n_solutions
        assert inst.failing in ("B", "C")
        for lead in LEADS:
            # every lead's update and starting calendar change the answer
            assert count(inst.attendees, inst.truth(skip_update=lead)) >= n + 2
            assert count(inst.attendees, inst.truth(blind_lead=lead)) >= n + 4


def test_grading():
    inst = INSTS[0]
    good = solutions(inst.attendees, inst.truth())[0]
    assert grade(inst, good)["valid"]
    stale = [s for s in solutions(inst.attendees, inst.truth(skip_update=inst.failing))
             if not is_valid(inst.attendees, inst.truth(), s)]
    assert stale and grade(inst, stale[0])["reason"] == "missed_failing_update"
    dup = dict(good, M2=good["M1"])
    assert not grade(inst, dup)["valid"]
    assert grade(inst, {"M1": 0})["reason"] == "incomplete"


def test_parsing():
    assert normalize_slot("Tue PM") == 3
    assert normalize_slot("wednesday morning") == 4
    assert normalize_slot("Thu") is None
    text = 'Sounds good.\n**SUBMIT** {"M1": "Mon AM", "M2": "Mon PM", "M3": "Tue AM", "M4": "Tue PM", "M5": "Wed AM"}'
    acts = parse_actions(text)
    assert parse_schedule(acts["submit"]) == {"M1": 0, "M2": 1, "M3": 2, "M4": 3, "M5": 4}
    assert parse_actions("ESCALATE: Lead C has not replied since round 1")["escalate"].startswith("Lead C")
    assert parse_actions("I can CONFIRM that works") == {}


class Recorder(MockClient):
    def __init__(self):
        super().__init__(seed=1)
        self.calls = []

    async def complete(self, model, system, user, max_tokens):
        self.calls.append((system, user))
        return await super().complete(model, system, user, max_tokens)


def _run(cond, inst):
    client = Recorder()
    rec = asyncio.run(run_episode(client, Budget(1), inst, "mock", cond, max_rounds=4))
    assert rec["empty"] == 0 and rec["truncated"] == 0
    return rec, client


def test_failure_modes():
    inst = INSTS[0]
    f = inst.failing
    rec, _ = _run("silent", inst)
    assert not [m for m in rec["log"] if m["lead"] == f and m["round"] >= UPDATE_ROUND]
    rec, _ = _run("replay", inst)
    mine = [m["text"] for m in rec["log"] if m["lead"] == f]
    assert len(mine) >= 2 and len(set(mine)) == 1
    rec, client = _run("amnesia", inst)
    restarted = [u for s, u in client.calls if f"You are Lead {f}" in s and "round 2 " in u]
    assert restarted and "(no messages yet)" in restarted[0]
    assert "UPDATES:" in restarted[0]
    rec, _ = _run("baseline", inst)
    assert any(m["lead"] == f and m["round"] >= UPDATE_ROUND for m in rec["log"])
    assert any(m["lead"] == "SYSTEM" for m in rec["log"])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
