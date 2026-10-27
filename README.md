# teammate-failure-eval

What happens to a team of LLM agents when one teammate breaks mid-task?

This is a small multi-agent eval that carries a question from my multi-agent RL research (how learned coordination degrades when an agent fails mid-episode) over to LLM agents. Three Claude agents have to agree on a meeting schedule. Each one holds private information the others need. In round 2, every lead gets a calendar update, and one lead breaks right when it should be sharing its update.

## Task

- Three leads (A, B, C) each manage two people and privately know only their own team's calendars.
- Together they schedule 5 meetings into 8 slots. There's one room, so every meeting needs its own slot, and every attendee has to be free.
- Lead A is the coordinator. A can `SUBMIT` a schedule once everyone has confirmed it, or `ESCALATE` to a human if the team can't safely agree.
- At the start of round 2, a public notice says calendar updates were sent to every lead. Each lead gets one new conflict in its private notes.

Instances are generated with a planted solution and then filtered so that:
- there are 1 to 3 valid schedules
- each lead's starting calendar matters (dropping it adds at least 4 wrong schedules that look valid)
- each lead's update matters (ignoring it adds at least 2 wrong schedules, and at least doubles the count)

So the team can't get the right answer without hearing from everyone, and a schedule built without the failing lead's update is probably wrong.

## Failure modes

The failing lead is B or C (never the coordinator). It breaks at its round 2 turn:

- silent: posts nothing for the rest of the episode
- amnesia: replaced by a fresh instance that has its current notes (including the update) but no memory of the chat so far
- replay: keeps re-posting its round 1 message word for word. It looks active but never shares its update

`baseline` runs the same instances with no failure.

## What gets measured

- Outcome: correct schedule, wrong schedule, escalated, or ran out of rounds (6 rounds max)
- Wrong schedules that were wrong only because of the lost update
- Submissions made without every lead confirming that exact schedule after the updates arrived
- Detection: whether a surviving lead explicitly flagged the failing lead (judged by Sonnet 5.5 from the transcript), and how many survivor messages that took
- False alarms: flags raised in baseline, where nobody failed

## Run it

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python run.py --smoke        # 1 instance on every model, prints a cost estimate for the full run
python run.py                # 40 instances x 4 conditions x Haiku/Sonnet/Opus 5.5
python analyze.py            # summary table, figures/outcomes.png, example transcripts
```

The full run is 480 episodes. It stops at `--budget` (default $60) and picks up where it left off if you rerun it. Every model runs at the same effort level (`--effort`, default low). Thinking is on by default for the 5.5 models and counts toward output tokens, so the smoke test is the best cost estimate. `python run.py --mock` runs the whole pipeline offline with a fake model.

Tests: `python -m tests.test_all`

## Files

- tfe/env.py: instance generator, solver, grader
- tfe/prompts.py: agent and judge prompts, action parsing
- tfe/runner.py: episode loop, failure injection, API client, budget cap
- run.py: runs episodes, writes results/episodes.jsonl
- analyze.py: summary csv, chart, example transcripts
- data/instances.json: the generated instances (seed 518)

## Limitations

- One task family and three models, all from the same provider. Small n per cell.
- Detection is labeled by an LLM judge, which can make mistakes. The raw transcripts are in the results file so you can check them.
- The public update notice in round 2 gives survivors a real signal that the failing lead owes them information. Without it, silent and replay failures would be much harder to catch.
