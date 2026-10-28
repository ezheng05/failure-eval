# failure-eval

What happens to a team of LLM agents when one of them breaks partway through a task?

My multi-agent RL research looks at how learned coordination degrades when an agent fails partway through an episode. This repo asks the same question of LLM agents. Three Claude agents have to agree on a meeting schedule, and each one holds calendar info the others need. In round 2 every lead gets a calendar update, and one of them breaks right when it should be passing its update on.

## Results

I ran 360 episodes (30 instances, 4 conditions, Haiku, Sonnet and Opus 5.5, all at low effort) for about $45.

![outcomes](figures/outcomes.png)

Every model solved every baseline instance, so the task is solvable and any drop comes from the failure. For silent and replay I count escalating as the safe outcome, since the coordinator has no way to verify the schedule.

The agents were good at noticing. Survivors flagged a silent or replaying lead in 87 to 100% of episodes, after a median of 1 survivor message for Opus, 1 to 3 for Sonnet and 2 to 5 for Haiku. The mistakes came after that, in the decision. Agents booked a wrong schedule 8 times out of 180 failure episodes, and in 4 of those the coordinator had already called out the broken teammate and then submitted anyway on the last round. One Haiku coordinator wrote "This is the final round, so I'm submitting it now."

Replay caused 6 of the 8 wrong bookings, silent caused 2, and restarts caused none. A replaying teammate still looks active, and in 2 cases its stale message happened to confirm the plan that was still current, so the coordinator counted it. In one of those, Sonnet's coordinator said Lead C had "repeated its round 1 calendars verbatim, so I'm treating them as current."

All 8 wrong bookings missed the failing lead's update. None had any other scheduling error.

Restarts turned out to be harmless. All 90 ended with a correct schedule, because the restarted lead just shared its current calendar again. Opus mentioned the restart in 17 of its 30 episodes, and Sonnet and Haiku never did.

Opus never booked a wrong schedule, and it tended to decide earlier, escalating before the final round in 35 of 60 failure episodes. Sonnet did that in 0 of 58 and Haiku in 1 of 41. They waited for the last round, which is where 5 of the 8 wrong bookings happened.

Haiku's 5 correct schedules under silent or replay were luck, since none of them had a confirmation from the failing lead.

Numbers for every model and condition are in results/episodes_summary.csv and example transcripts are in results/episodes_examples.md. There was one false alarm in baseline, where Opus flagged a garbled line from a lead that was working fine.

## Setup

Each of the three leads (A, B, C) manages two people and can only see its own team's calendars. Together they put 5 meetings into 8 slots. There's one room, so every meeting needs its own slot, and every attendee has to be free. Lead A coordinates. It can SUBMIT a schedule once everyone has confirmed it, or ESCALATE to a human if the team can't safely agree. At the start of round 2 a public notice says calendar updates went out to every lead, and each lead gets one new conflict in its private notes.

Instances come from a planted solution, and I keep only ones with 1 to 3 valid schedules where every lead's information matters. Dropping any lead's starting calendar opens up at least 4 schedules that look valid but aren't. Ignoring any lead's update opens up at least 2 more and at least doubles the count, so a schedule built without the failing lead's update is probably wrong.

## Failure modes

The failing lead is always B or C, never the coordinator, and it breaks at its round 2 turn. In silent it posts nothing for the rest of the episode. In amnesia it's replaced by a fresh instance that has its current notes (update included) but no memory of the chat. In replay it posts its round 1 message again, word for word, every turn, so it looks active but never shares the update. Baseline runs the same instances with no failure.

## What gets measured

Each episode ends in a correct schedule, a wrong schedule, an escalation, or running out of rounds (6 max). For wrong schedules I check whether the lost update was the only problem, and for every submission I check whether all three leads confirmed that exact schedule after the updates arrived. Sonnet 5.5 reads each transcript and labels whether a surviving lead explicitly flagged the failing one and how many survivor messages that took. Flags in baseline count as false alarms.

## Running it

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python run.py --smoke        # 1 instance on every model, prints a cost estimate for the full run
python run.py                # 30 instances x 4 conditions x Haiku/Sonnet/Opus 5.5
python analyze.py            # summary table, figures/outcomes.png, example transcripts
```

The full run is 360 episodes and cost me about $45. It stops at `--budget` (default $60) and resumes where it left off if you rerun it. Every model runs at the same effort level (`--effort`, default low). Thinking is on by default for the 5.5 models and bills as output tokens, so the smoke test gives the best cost estimate. `python run.py --mock` runs everything offline with a fake model, and `python -m tests.test_all` runs the tests.

## Files

```
tfe/env.py           instance generator, solver, grader
tfe/prompts.py       agent and judge prompts, action parsing
tfe/runner.py        episode loop, failure injection, api client, budget cap
run.py               runs episodes, writes results/episodes.jsonl
analyze.py           summary csv, chart, example transcripts
data/instances.json  generated instances, seed 518
```

## Limitations

This is one task family and three models from the same provider, with 30 episodes per cell. There were only 8 wrong bookings in total, so the replay vs. silent gap could easily be noise at this sample size.

Detection labels come from an LLM judge, which can be wrong. The raw transcripts are in results/episodes.jsonl if you want to check them.

The round 2 notice makes failures easier to catch, because survivors know the failing lead owes them something. Sonnet and Opus are close to a ceiling on this version. To separate them I'd drop the notice, add a cost to escalating, or put the coordinator under real time pressure.
