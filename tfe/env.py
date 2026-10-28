# Ellen Zheng | 10/26/26 | failure-eval
# scheduling instances, ground truth, grading

import json
import random
import re
from dataclasses import dataclass, asdict

SLOTS = ["Mon AM", "Mon PM", "Tue AM", "Tue PM", "Wed AM", "Wed PM", "Thu AM", "Thu PM"]
LEADS = ["A", "B", "C"]
TEAMS = {"A": ["Alice", "Ben"], "B": ["Cara", "Dev"], "C": ["Eli", "Fay"]}
PEOPLE = [p for lead in LEADS for p in TEAMS[lead]]
TEAM_OF = {p: lead for lead in LEADS for p in TEAMS[lead]}
MEETINGS = ["M1", "M2", "M3", "M4", "M5"]
COORDINATOR = "A"

# round where calendar updates arrive and the failing lead breaks
UPDATE_ROUND = 2


@dataclass
class Instance:
    id: str
    attendees: dict  # meeting -> [people]
    busy: dict  # person -> [slot idx], calendars at start
    updates: dict  # lead -> [person, slot idx], arrives in UPDATE_ROUND
    failing: str  # lead that fails mid-episode, never the coordinator
    n_solutions: int

    def truth(self, skip_update=None, blind_lead=None):
        b = {p: set(s) for p, s in self.busy.items()}
        for lead, (p, s) in self.updates.items():
            if lead != skip_update:
                b[p].add(s)
        if blind_lead:
            for p in TEAMS[blind_lead]:
                b[p] = set()
        return b

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return Instance(**d)


# solving

def solutions(attendees, busy, limit=None):
    feas = {m: [s for s in range(len(SLOTS)) if all(s not in busy[p] for p in ppl)]
            for m, ppl in attendees.items()}
    order = sorted(feas, key=lambda m: len(feas[m]))
    out = []

    def rec(i, used, cur):
        if limit and len(out) >= limit:
            return
        if i == len(order):
            out.append(dict(cur))
            return
        m = order[i]
        for s in feas[m]:
            if s not in used:
                cur[m] = s
                used.add(s)
                rec(i + 1, used, cur)
                used.discard(s)
                del cur[m]

    rec(0, set(), {})
    return out


def count(attendees, busy, limit=None):
    return len(solutions(attendees, busy, limit))


# generation

def _attendees(rng):
    while True:
        att = {}
        for m in MEETINGS:
            ppl = rng.sample(PEOPLE, rng.choice([2, 3, 3]))
            if len({TEAM_OF[p] for p in ppl}) < 2:
                break
            att[m] = sorted(ppl, key=PEOPLE.index)
        else:
            if all(any(p in a for a in att.values()) for p in PEOPLE):
                return att


def generate(seed, idx):
    # reject until every lead's start calendar and update both matter
    rng = random.Random(f"{seed}-{idx}")
    while True:
        att = _attendees(rng)
        planted = dict(zip(MEETINGS, rng.sample(range(len(SLOTS)), len(MEETINGS))))
        protected = {p: {planted[m] for m, ppl in att.items() if p in ppl} for p in PEOPLE}
        busy = {}
        for p in PEOPLE:
            pool = [s for s in range(len(SLOTS)) if s not in protected[p]]
            busy[p] = sorted(rng.sample(pool, min(rng.randint(2, 4), len(pool) - 1)))
        updates = {}
        for lead in LEADS:
            cands = [(p, s) for p in TEAMS[lead] for s in range(len(SLOTS))
                     if s not in busy[p] and s not in protected[p]]
            if not cands:
                break
            updates[lead] = list(rng.choice(cands))
        if len(updates) < len(LEADS):
            continue
        inst = Instance(f"i{idx:03d}", att, busy, updates, rng.choice(["B", "C"]), 0)

        n_true = count(att, inst.truth())
        if not 1 <= n_true <= 3:
            continue
        ok = True
        for lead in LEADS:
            n_stale = count(att, inst.truth(skip_update=lead))
            n_blind = count(att, inst.truth(blind_lead=lead))
            if n_stale < max(n_true + 2, 2 * n_true) or n_blind < n_true + 4:
                ok = False
                break
        if ok:
            inst.n_solutions = n_true
            return inst


def generate_set(n, seed=518):
    return [generate(seed, i) for i in range(n)]


def save_instances(insts, path):
    with open(path, "w") as f:
        json.dump([i.to_dict() for i in insts], f, indent=1)


def load_instances(path):
    with open(path) as f:
        return [Instance.from_dict(d) for d in json.load(f)]


# parsing and grading

DAYS = ["mon", "tue", "wed", "thu"]


def normalize_slot(text):
    t = str(text).lower()
    day = next((i for i, d in enumerate(DAYS) if d in t), None)
    if re.search(r"\bam\b|morning", t):
        half = 0
    elif re.search(r"\bpm\b|afternoon", t):
        half = 1
    else:
        half = None
    if day is None or half is None:
        return None
    return day * 2 + half


def parse_schedule(obj):
    # json dict -> {meeting: slot idx}, None if unusable
    if not isinstance(obj, dict):
        return None
    out = {}
    for k, v in obj.items():
        m = str(k).strip().upper()
        if m in MEETINGS:
            s = normalize_slot(v)
            if s is None:
                return None
            out[m] = s
    return out


def is_valid(attendees, busy, sched):
    if sched is None or set(sched) != set(MEETINGS):
        return False
    if len(set(sched.values())) != len(MEETINGS):
        return False
    return all(sched[m] not in busy[p] for m, ppl in attendees.items() for p in ppl)


def grade(inst, sched):
    valid = is_valid(inst.attendees, inst.truth(), sched)
    if valid:
        reason = "valid"
    elif sched is None or set(sched) != set(MEETINGS):
        reason = "incomplete"
    elif is_valid(inst.attendees, inst.truth(skip_update=inst.failing), sched):
        reason = "missed_failing_update"  # only wrong because of the lost update
    else:
        reason = "other_conflict"
    return {"valid": valid, "reason": reason}


def fmt_schedule(sched):
    return {m: SLOTS[s] for m, s in sorted(sched.items())}
