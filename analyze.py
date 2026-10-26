# Ellen Zheng | 10/26/26 | teammate-failure-eval
# analyze.py: summary table, outcome chart, example transcripts

import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from tfe.runner import CONDITIONS, MODELS

MODEL_NAME = {v: k.capitalize() for k, v in MODELS.items()}
COND_NAME = {"baseline": "No failure", "silent": "Goes silent", "amnesia": "Restarts, no memory",
             "replay": "Replays old message"}
OUTCOMES = [  # order, label, color
    ("correct", "Correct schedule", "#2a78d6"),
    ("escalated", "Escalated", "#eda100"),
    ("wrong", "Wrong schedule", "#e34948"),
    ("timeout", "Ran out of rounds", "#c3c2b7"),
]
INK, MUTED, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#e1e0d9"


def load(path):
    rows = [json.loads(l) for l in open(path)]
    df = pd.DataFrame(rows)
    df["result"] = df.apply(lambda r: "correct" if r.outcome == "submitted" and r.valid else
                            "wrong" if r.outcome == "submitted" else r.outcome, axis=1)
    df["model_name"] = df.model.map(MODEL_NAME).fillna(df.model)
    return df


def summary(df):
    g = df.groupby(["model_name", "condition"])
    t = pd.DataFrame({
        "n": g.size(),
        "correct": g.result.apply(lambda s: (s == "correct").mean()),
        "escalated": g.result.apply(lambda s: (s == "escalated").mean()),
        "wrong": g.result.apply(lambda s: (s == "wrong").mean()),
        "timeout": g.result.apply(lambda s: (s == "timeout").mean()),
        # of wrong schedules, share that were wrong only because of the lost update
        "wrong_from_lost_update": g.apply(lambda x: (x.reason == "missed_failing_update").sum() / max((x.result == "wrong").sum(), 1)),
        # submitted without every lead genuinely confirming it after updates
        "submitted_unconfirmed": g.apply(lambda x: ((x.outcome == "submitted") & (x.confirmed_by_all == False)).sum() / max((x.outcome == "submitted").sum(), 1)),
        "detected": g.apply(lambda x: x.detected.mean() if "detected" in x else float("nan")),
        "median_detect_latency": g.detect_latency.median() if "detect_latency" in df else float("nan"),
        "false_alarm": g.apply(lambda x: x.false_alarm.mean() if "false_alarm" in x else float("nan")),
        "avg_messages": g.messages.mean(),
    }).reset_index()
    order = {c: i for i, c in enumerate(CONDITIONS)}
    morder = {n: i for i, n in enumerate(MODEL_NAME.values())}
    t = t.sort_values(by=["model_name", "condition"], key=lambda s: s.map(morder if s.name == "model_name" else order))
    return t


def chart(df, path):
    models = [m for m in MODEL_NAME.values() if m in set(df.model_name)]
    conds = [c for c in CONDITIONS if c in set(df.condition)]
    fig, axes = plt.subplots(1, len(models), figsize=(4.2 * len(models), 3.4), sharey=True, squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    for ax, m in zip(axes[0], models):
        ax.set_facecolor(SURFACE)
        sub = df[df.model_name == m]
        for y, c in enumerate(conds):
            s = sub[sub.condition == c].result
            left = 0
            for key, _, color in OUTCOMES:
                w = (s == key).mean() * 100 if len(s) else 0
                if w > 0:
                    ax.barh(y, w, left=left, height=0.62, color=color, edgecolor=SURFACE, linewidth=2)
                    if w >= 12:
                        ax.text(left + w / 2, y, f"{w:.0f}%", ha="center", va="center", fontsize=9,
                                color=INK if key in ("escalated", "timeout") else "white")
                left += w
        ax.set_title(m, loc="left", fontsize=12, color=INK, fontweight="bold")
        ax.set_xlim(0, 100)
        ax.set_xticks([0, 50, 100])
        ax.set_xticklabels(["0%", "50%", "100%"], color=MUTED, fontsize=9)
        ax.tick_params(length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
    axes[0][0].set_yticks(range(len(conds)))
    axes[0][0].set_yticklabels([COND_NAME[c] for c in conds], color=INK, fontsize=10)
    axes[0][0].invert_yaxis()
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c in OUTCOMES]
    fig.legend(handles, [l for _, l, _ in OUTCOMES], loc="upper center", ncol=4, frameon=False,
               fontsize=9, bbox_to_anchor=(0.5, 1.0), labelcolor=INK)
    n = df.groupby(["model_name", "condition"]).size().min()
    fig.text(0.01, 0.01, f"Share of episodes by outcome, n={n} per bar. In failure conditions, Lead B or C breaks in round 2, right after getting a calendar update.",
             fontsize=8, color=MUTED)
    fig.tight_layout(rect=(0, 0.05, 1, 0.9))
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def _render(r):
    lines = [f"**{r.model_name}, {COND_NAME[r.condition]}, instance {r.instance}** (failing lead: {r.failing}, "
             f"outcome: {r.result}{', ' + r.reason if isinstance(r.reason, str) else ''})", ""]
    for m in r.log:
        who = "SYSTEM" if m["lead"] == "SYSTEM" else f"Lead {m['lead']}"
        tag = " *(replayed)*" if m["kind"] == "replay" else " *(restarted)*" if m["kind"] == "restarted" else ""
        text = m["text"].replace("\n", "\n> ")
        lines.append(f"> **[R{m['round']}] {who}{tag}:** {text}\n>")
    return "\n".join(lines) + "\n"


def examples(df, path, k=2):
    picks = []
    for cond, res in [("replay", "wrong"), ("silent", "wrong"), ("silent", "escalated"),
                      ("amnesia", "correct"), ("amnesia", "wrong"), ("replay", "escalated")]:
        hit = df[(df.condition == cond) & (df.result == res)]
        if len(hit):
            # prefer the strongest model that shows the behavior
            hit = hit.assign(rank=hit.model.map({v: i for i, v in enumerate(reversed(list(MODELS.values())))}))
            picks.append(hit.sort_values(["rank", "instance"]).iloc[0])
    with open(path, "w") as f:
        f.write("# Example transcripts\n\nPicked automatically by analyze.py, strongest model first.\n\n")
        for r in picks[: k * 3]:
            f.write(_render(r) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results/episodes.jsonl")
    ap.add_argument("--figures", default="figures")
    a = ap.parse_args()
    df = load(a.results)
    os.makedirs(a.figures, exist_ok=True)
    stem = os.path.splitext(a.results)[0]
    t = summary(df)
    t.to_csv(stem + "_summary.csv", index=False)
    chart(df, os.path.join(a.figures, "outcomes.png"))
    examples(df, stem + "_examples.md")
    pd.set_option("display.width", 200)
    print(t.round(2).to_string(index=False))
    print(f"\n{len(df)} episodes, {df.tokens_in.sum():,} input tokens, {df.tokens_out.sum():,} output tokens")


if __name__ == "__main__":
    main()
