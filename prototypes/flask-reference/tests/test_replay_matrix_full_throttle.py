from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from test_replay_matrix import (
    APP_DIR,
    LOGS_PATH,
    SOURCE_DB_PATH,
    FlaskReplayRunner,
    ReplayCase,
    ReplayResult,
    build_historical_cases,
    copy_db,
    ensure_clean_dir,
    latency_stats,
    normalize_text,
    parse_logs,
    results_to_jsonable,
    run_replay_batch,
    summarize_historical,
    top_slowest,
)


ARTIFACT_DIR = APP_DIR / "artifacts" / "replay_matrix_full_throttle_500"
REPLAY_DB_PATH = ARTIFACT_DIR / "full_throttle_replay.db"


@dataclass
class TopicSpec:
    slug: str
    canonical: str
    aliases: list[str]
    typos: list[str]
    expected_tokens: list[str]
    note_texts: list[str]
    semantic_queries: list[str]


@dataclass
class ProbeSpec:
    case: ReplayCase
    focus_area: str
    severity: str
    expected_kind: str
    allowed_kinds: list[str]
    expected_tokens: list[str]
    target_table: str | None = None
    rationale: str | None = None
    ignore_hint_if_failed: str = "scope_decision_needed"


def build_topics() -> list[TopicSpec]:
    return [
        TopicSpec(
            slug="vivekananda",
            canonical="vivekananda",
            aliases=["vivekananda", "swami vivekananda"],
            typos=["vivekanda", "vivekananada"],
            expected_tokens=["vivekananda", "vivekanda", "meditation", "travel", "health"],
            note_texts=[
                "note: vivekananda likely declined through constant travel, fatigue, and neglected health rather than a sudden mystical meditation event",
                "note: my vivekananda note says the travel-exhaustion explanation sounds more credible than the mythic meditation story",
                "note: vivekananda kept pushing hard, travelled a lot, and did not seem to protect his body enough",
                "remember this about vivekananda: the self-care and health angle matters more than the dramatic meditation story",
            ],
            semantic_queries=[
                "what note did i save about vivekananda and meditation versus health",
                "find the saved note where i linked vivekananda with heavy travel and exhaustion",
                "which note says vivekananda did not simply die in meditation",
                "show the note about vivekananda and self-care",
            ],
        ),
        TopicSpec(
            slug="fundera_park",
            canonical="fundera park",
            aliases=["fundera park"],
            typos=["fundra park", "fundera prk"],
            expected_tokens=["fundera park", "fundra park", "visit", "good"],
            note_texts=[
                "note: fundera park might be good for one more visit, but i still do not feel fully convinced",
                "note: my fundera park note says i need another visit before making up my mind",
                "note: fundera park felt interesting but i am not ready to call it clearly good yet",
                "remember this about fundera park: i still need more confidence before recommending it",
            ],
            semantic_queries=[
                "what note says fundera park needs another visit before a conclusion",
                "find the note where i was unsure whether fundera park is really good",
                "show the saved note about fundera park and hesitation",
                "which note talks about needing more confidence about fundera park",
            ],
        ),
        TopicSpec(
            slug="mcp",
            canonical="mcp",
            aliases=["mcp", "model context protocol"],
            typos=["mpc", "mcp progress"],
            expected_tokens=["mcp", "amit", "progress", "status"],
            note_texts=[
                "note: mcp progress should be summarized clearly before i update Amit again",
                "note: my mcp note says i still need a concise status update for Amit",
                "note: mcp understanding is improving, but the explanation to Amit should stay simple",
                "remember this about mcp: status, clarity, and a short update to Amit matter most",
            ],
            semantic_queries=[
                "find the saved note about mcp progress for Amit",
                "which note says the mcp update to Amit should stay concise",
                "show the note where i mentioned mcp status and clarity",
                "what note did i save about explaining mcp simply to Amit",
            ],
        ),
        TopicSpec(
            slug="cipla",
            canonical="cipla",
            aliases=["cipla"],
            typos=["sipla", "ciplla"],
            expected_tokens=["cipla", "study", "decision", "notes"],
            note_texts=[
                "note: cipla needs better study notes before any decision is taken",
                "note: my cipla note says not to rush into a conclusion without stronger notes",
                "note: cipla still feels incomplete in my notes and needs more research",
                "remember this about cipla: slow down and deepen the note quality before deciding anything",
            ],
            semantic_queries=[
                "find the saved note where i said cipla needs more study before a decision",
                "show the note about cipla and not rushing a conclusion",
                "which note says cipla research is still incomplete",
                "what did i write about cipla and stronger notes",
            ],
        ),
        TopicSpec(
            slug="tmb",
            canonical="tamilnad mercentile bank",
            aliases=["tamilnad mercentile bank", "tmb"],
            typos=["tamilnad mercentile bk", "tamilnadu mercentile bank"],
            expected_tokens=["tamilnad mercentile bank", "tmb", "review", "bank"],
            note_texts=[
                "note: tamilnad mercentile bank needs a deeper review note before i form any view",
                "note: my tamilnad mercentile bank note is still shallow and needs more details",
                "note: tamilnad mercentile bank deserves a slower, more careful review",
                "remember this about tamilnad mercentile bank: not enough depth yet",
            ],
            semantic_queries=[
                "find the note about tamilnad mercentile bank needing a deeper review",
                "show the saved note where i said tmb still lacks depth",
                "which note talks about reviewing tamilnad mercentile bank more carefully",
                "what did i write about not having enough detail on tamilnad mercentile bank",
            ],
        ),
        TopicSpec(
            slug="peter_lynch",
            canonical="peter lynch",
            aliases=["peter lynch"],
            typos=["peter lunch", "peter lynh"],
            expected_tokens=["peter lynch", "low pe", "stock"],
            note_texts=[
                "note: peter lynch seems to favour low pe stock ideas more than flashy stories",
                "note: my peter lynch note says low pe matters more than hype",
                "note: peter lynch keeps pulling me back toward simple valuation discipline",
                "remember this about peter lynch: low pe and simplicity keep coming up",
            ],
            semantic_queries=[
                "find the note where i said peter lynch favours low pe stock ideas",
                "show the note about peter lynch and valuation discipline",
                "which saved note says peter lynch prefers low pe over hype",
                "what did i write about peter lynch and simple valuation",
            ],
        ),
        TopicSpec(
            slug="nightshade",
            canonical="nightshade veggies",
            aliases=["nightshade veggies", "nightshade vegetables"],
            typos=["nightshde veggies", "night shade veggies"],
            expected_tokens=["nightshade", "veggies", "vegetables", "avoid"],
            note_texts=[
                "note: avoid nightshade veggies for now and keep watching whether symptoms calm down",
                "note: my nightshade veggies note says to stay cautious with those vegetables",
                "note: nightshade vegetables are on the avoid list until i get more clarity",
                "remember this about nightshade veggies: caution first, experimentation later",
            ],
            semantic_queries=[
                "find the note where i said to avoid nightshade vegetables",
                "show the saved note about caution with nightshade veggies",
                "which note says nightshade vegetables are on the avoid list",
                "what did i write about symptoms and nightshade veggies",
            ],
        ),
        TopicSpec(
            slug="datascience_iit",
            canonical="datascience in iit chennai",
            aliases=["datascience in iit chennai", "iit chennai datascience"],
            typos=["data science in iit chennai", "datascience at iit chennai"],
            expected_tokens=["datascience", "iit chennai", "explore"],
            note_texts=[
                "note: explore the datascience angle in iit chennai more carefully before talking to Maddy again",
                "note: my iit chennai datascience note needs a clearer action plan",
                "note: datascience in iit chennai is still a rough idea and needs better structure",
                "remember this about iit chennai datascience: explore first, summarize later",
            ],
            semantic_queries=[
                "find the note about exploring datascience in iit chennai",
                "show the saved note where i said the iit chennai datascience idea needs structure",
                "which note mentions talking to Maddy after more exploration on iit chennai datascience",
                "what did i write about the iit chennai datascience action plan",
            ],
        ),
        TopicSpec(
            slug="second_brain_latency",
            canonical="second brain latency",
            aliases=["second brain latency", "latency in second brain"],
            typos=["second brain latecy", "secnd brain latency"],
            expected_tokens=["latency", "second brain", "cold-start", "warm-up"],
            note_texts=[
                "note: second brain latency still looks dominated by cold-start work and warm-up costs",
                "note: my second brain latency note says note retrieval should stay faster than planner-heavy reads",
                "note: cold-start latency is the sharpest product pain in second brain right now",
                "remember this about second brain latency: warm-up and retrieval path design matter most",
            ],
            semantic_queries=[
                "find the note about second brain latency and cold-start cost",
                "show the saved note where i said note retrieval should stay faster than planner reads",
                "which note talks about warm-up cost in second brain",
                "what did i write about latency being the sharpest product pain",
            ],
        ),
        TopicSpec(
            slug="planner_sql",
            canonical="planner sql safety",
            aliases=["planner sql safety", "read only sql planner"],
            typos=["planner sql safty", "read only sql planr"],
            expected_tokens=["sql", "planner", "read-only", "safety"],
            note_texts=[
                "note: planner sql must stay read-only and safety-gated no matter how helpful the planner becomes",
                "note: my planner sql safety note says approved tables only and no mutating sql",
                "note: read-only sql is useful only if the safety gate stays strict",
                "remember this about planner sql safety: approved views, no mutation, no shortcuts",
            ],
            semantic_queries=[
                "find the note about planner sql staying read-only and safety-gated",
                "show the saved note where i mentioned approved tables only for planner sql",
                "which note talks about no mutating sql in the planner",
                "what did i write about strict safety gates for read-only sql",
            ],
        ),
    ]


class ProbeBuilder:
    def __init__(self, existing_inputs: set[str]) -> None:
        self.seen = set(existing_inputs)
        self.specs: list[ProbeSpec] = []

    def add(
        self,
        text: str,
        *,
        focus_area: str,
        severity: str,
        expected_kind: str,
        allowed_kinds: list[str] | None = None,
        expected_tokens: list[str] | None = None,
        target_table: str | None = None,
        rationale: str | None = None,
        ignore_hint_if_failed: str = "scope_decision_needed",
    ) -> bool:
        normalized = normalize_text(text)
        if not normalized or normalized in self.seen:
            return False
        self.seen.add(normalized)
        case = ReplayCase(
            case_id=f"FT{len(self.specs) + 1:03d}",
            text=text,
            source="generated_full_throttle",
            mode="stateful",
            probe_family=focus_area,
            scenario=severity,
            anchor_text=text,
            notes=rationale,
        )
        spec = ProbeSpec(
            case=case,
            focus_area=focus_area,
            severity=severity,
            expected_kind=expected_kind,
            allowed_kinds=allowed_kinds or [expected_kind],
            expected_tokens=expected_tokens or [],
            target_table=target_table,
            rationale=rationale,
            ignore_hint_if_failed=ignore_hint_if_failed,
        )
        self.specs.append(spec)
        return True


def build_note_specs(builder: ProbeBuilder) -> None:
    topics = build_topics()
    note_query_templates = [
        ("{canonical} notes", "core"),
        ("show notes about {canonical}", "core"),
        ("find {canonical} in my notes", "core"),
        ("search my notes for {canonical}", "core"),
        ("any mention of {canonical} in the notes", "core"),
        ("any info on {canonical} in my notes", "core"),
        ("give me notes about {canonical}", "core"),
        ("show saved notes about {canonical}", "core"),
        ("{typo} notes", "stretch"),
        ("find {typo} in my notes", "stretch"),
        ("what do my notes say about {canonical}", "stretch"),
        ("do i have any notes about {canonical}", "stretch"),
    ]

    for topic in topics:
        for index, note_text in enumerate(topic.note_texts, start=1):
            builder.add(
                note_text,
                focus_area="note_write",
                severity="core" if index <= 3 else "stretch",
                expected_kind="write",
                target_table="notes",
                expected_tokens=topic.expected_tokens,
                rationale=f"Seed note corpus for {topic.slug}.",
                ignore_hint_if_failed="not_ignorable_candidate",
            )

    for topic in topics:
        typo = topic.typos[0]
        for template, severity in note_query_templates:
            builder.add(
                template.format(canonical=topic.canonical, typo=typo),
                focus_area="note_query",
                severity=severity,
                expected_kind="query",
                expected_tokens=topic.expected_tokens,
                rationale=f"Topic retrieval stress for {topic.slug}.",
                ignore_hint_if_failed="not_ignorable_candidate" if severity == "core" else "scope_decision_needed",
            )
        for query in topic.semantic_queries:
            builder.add(
                query,
                focus_area="note_query",
                severity="stretch",
                expected_kind="query",
                expected_tokens=topic.expected_tokens,
                rationale=f"Semantic note retrieval stress for {topic.slug}.",
                ignore_hint_if_failed="scope_decision_needed",
            )

    global_note_queries = [
        ("show me last 5 notes", "core"),
        ("show me last 8 notes", "core"),
        ("show me the last 12 saved notes", "core"),
        ("show me saved notes", "core"),
        ("show recent notes", "core"),
        ("show all notes", "core"),
        ("show all saved notes", "core"),
        ("list my saved notes", "core"),
        ("list all saved notes", "core"),
        ("what are my latest notes", "core"),
        ("latest note", "core"),
        ("last note", "core"),
        ("latest saved note", "core"),
        ("show latest 3 notes", "core"),
        ("show last 3 notes", "core"),
        ("saved notes", "core"),
        ("all notes", "core"),
        ("what did i save recently in notes", "stretch"),
        ("show every saved note", "stretch"),
        ("show note snippets", "stretch"),
    ]
    for text, severity in global_note_queries:
        builder.add(
            text,
            focus_area="note_query",
            severity=severity,
            expected_kind="query",
            rationale="Global note retrieval and recency stress.",
            ignore_hint_if_failed="not_ignorable_candidate" if severity == "core" else "scope_decision_needed",
        )

    cross_topic_queries = [
        ("what note talks about latency and read-only sql safety", ["latency", "sql"]),
        ("find the note that connects mcp status and Amit", ["mcp", "amit"]),
        ("show the note about vivekananda and meditation myth", ["vivekananda", "meditation"]),
        ("which note mentions fundera park and hesitation", ["fundera park", "good"]),
        ("what did i write about cipla and slow decision making", ["cipla", "decision"]),
        ("find the note about tmb and deeper review", ["tamilnad mercentile bank", "review"]),
        ("show the note about peter lynch and low pe ideas", ["peter lynch", "low pe"]),
        ("what note did i save about nightshade vegetables and caution", ["nightshade", "avoid"]),
        ("find the note about datascience in iit chennai and Maddy", ["datascience", "iit chennai"]),
        ("show the note where second brain latency was called a product pain", ["latency", "second brain"]),
    ]
    for text, tokens in cross_topic_queries:
        builder.add(
            text,
            focus_area="note_query",
            severity="stretch",
            expected_kind="query",
            expected_tokens=tokens,
            rationale="Cross-topic semantic note retrieval stress.",
            ignore_hint_if_failed="scope_decision_needed",
        )

    extra_note_templates = [
        ("did i ever save a note on {canonical}", "stretch"),
        ("show every note that mentions {canonical}", "stretch"),
        ("what note mentioned {canonical} most recently", "adversarial"),
    ]
    for topic in topics:
        typo = topic.typos[-1]
        for template, severity in extra_note_templates:
            builder.add(
                template.format(canonical=topic.canonical),
                focus_area="note_query",
                severity=severity,
                expected_kind="query",
                expected_tokens=topic.expected_tokens,
                rationale=f"Additional note retrieval pressure for {topic.slug}.",
                ignore_hint_if_failed=(
                    "maybe_ignorable_if_scope_excludes_recency_semantics"
                    if severity == "adversarial"
                    else "scope_decision_needed"
                ),
            )
        builder.add(
            f"find {typo} in saved notes",
            focus_area="note_query",
            severity="stretch",
            expected_kind="query",
            expected_tokens=topic.expected_tokens,
            rationale=f"Typo-tolerance stress for {topic.slug}.",
            ignore_hint_if_failed="scope_decision_needed",
        )
        builder.add(
            f"any mention of {typo} in my notes",
            focus_area="note_query",
            severity="stretch",
            expected_kind="query",
            expected_tokens=topic.expected_tokens,
            rationale=f"Additional typo note retrieval stress for {topic.slug}.",
            ignore_hint_if_failed="scope_decision_needed",
        )

    extra_global_note_queries = [
        ("show me every saved note", "stretch"),
        ("show me all of my notes", "stretch"),
        ("what notes do i have saved", "stretch"),
        ("show the most recent saved notes", "stretch"),
        ("show me the newest note", "stretch"),
        ("find my recent notes", "stretch"),
        ("list every saved note snippet", "adversarial"),
        ("what are all the notes i have", "stretch"),
        ("show all notes one by one", "stretch"),
        ("give me my saved notes", "stretch"),
        ("show me notes from recent memory", "adversarial"),
        ("all saved note snippets", "adversarial"),
        ("show the full saved note list", "stretch"),
        ("give me the latest saved notes", "stretch"),
        ("show all note entries", "stretch"),
    ]
    for text, severity in extra_global_note_queries:
        builder.add(
            text,
            focus_area="note_query",
            severity=severity,
            expected_kind="query",
            rationale="Additional global note retrieval pressure.",
            ignore_hint_if_failed=(
                "maybe_ignorable_if_scope_excludes_exact_surface_phrase"
                if severity == "adversarial"
                else "scope_decision_needed"
            ),
        )


def build_expense_specs(builder: ProbeBuilder) -> None:
    expense_writes = [
        "petrol 620",
        "groceries 1450",
        "food 310",
        "tea & snacks 80",
        "ginger 45",
        "milk 70",
        "electricity 900",
        "water bottle 25",
        "pepsi 120",
        "repair 1500",
    ]
    for text in expense_writes:
        category = text.rsplit(" ", 1)[0]
        builder.add(
            text,
            focus_area="expense_write",
            severity="core",
            expected_kind="write",
            expected_tokens=[category],
            target_table="expenses",
            rationale=f"Seed expense rows for {category}.",
            ignore_hint_if_failed="not_ignorable_candidate",
        )

    category_queries = {
        "petrol": ["petrol", "total spend"],
        "groceries": ["groceries", "total spend"],
        "food": ["food", "total spend"],
        "tea": ["tea", "total spend"],
        "ginger": ["ginger", "total spend"],
        "milk": ["milk", "total spend"],
        "electricity": ["electricity", "total spend"],
        "repair": ["repair", "total spend"],
    }
    category_templates = [
        ("{category} expense", "core"),
        ("{category} expense this month", "core"),
        ("show {category} expense list", "stretch"),
        ("list {category} expense one by one", "stretch"),
        ("what did i spend on {category} this month", "stretch"),
    ]
    for category, tokens in category_queries.items():
        for template, severity in category_templates:
            builder.add(
                template.format(category=category),
                focus_area="expense_query",
                severity=severity,
                expected_kind="query",
                expected_tokens=tokens,
                rationale=f"Category expense retrieval stress for {category}.",
                ignore_hint_if_failed="not_ignorable_candidate" if severity == "core" else "scope_decision_needed",
            )

    global_expense_queries = [
        ("this month expense", "core"),
        ("monthly expense", "core"),
        ("this month spending", "core"),
        ("current month expense", "core"),
        ("total expense this month", "core"),
        ("what is my current month expense", "core"),
        ("last month expense", "stretch"),
        ("april month expense", "stretch"),
        ("may month expense", "stretch"),
        ("april expense", "stretch"),
        ("last 3 expense", "stretch"),
        ("last 5 expense", "stretch"),
        ("show last 7 expenses", "stretch"),
        ("show recent expenses", "stretch"),
        ("show last 3 expenses one by one", "stretch"),
        ("expense list for this month", "stretch"),
        ("list the expense one by one", "stretch"),
        ("show me this month expense list", "stretch"),
        ("expense status", "stretch"),
        ("analyse this month expense", "stretch"),
        ("show each expense for this month", "stretch"),
        ("groceries expense for this month", "core"),
        ("petrol expense for this month", "core"),
        ("petrol expense for last month", "stretch"),
        ("groceries expense", "core"),
        ("food expense this month", "core"),
        ("milk expense", "core"),
        ("tea expense", "core"),
        ("last 2 month expense", "adversarial"),
        ("last two month expense", "adversarial"),
        ("current month petrol expense", "core"),
        ("current month groceries expense", "core"),
        ("last 4 expenses", "stretch"),
        ("last 3 bills", "adversarial"),
        ("bills this month", "adversarial"),
        ("all expense", "stretch"),
        ("every expense this month", "stretch"),
        ("expense for april month", "stretch"),
        ("show this month's expenses", "stretch"),
        ("groceries expense list for this month", "stretch"),
    ]
    for text, severity in global_expense_queries:
        builder.add(
            text,
            focus_area="expense_query",
            severity=severity,
            expected_kind="query",
            rationale="Global expense retrieval stress.",
            ignore_hint_if_failed=(
                "not_ignorable_candidate"
                if severity == "core"
                else "maybe_ignorable_if_scope_excludes_range_or_phrase_support"
                if severity == "adversarial"
                else "scope_decision_needed"
            ),
        )


def build_todo_specs(builder: ProbeBuilder) -> None:
    todo_items = [
        "update maddy about datascience in iit chennai",
        "call Amit about MCP status",
        "renew driving license",
        "book briyani festival tickets",
        "complete cipla notes review",
        "check fundera park one more time",
        "send peter lynch note summary",
        "buy milk on the way back",
        "pick up ginger and tea supplies",
        "schedule latency review for second brain",
    ]
    for item in todo_items:
        builder.add(
            f"todo: {item}",
            focus_area="todo_write",
            severity="core",
            expected_kind="write",
            expected_tokens=[item.split()[0]],
            target_table="todos",
            rationale="Explicit todo write stress.",
            ignore_hint_if_failed="not_ignorable_candidate",
        )
        builder.add(
            f"remind me to {item}",
            focus_area="todo_write",
            severity="stretch",
            expected_kind="write",
            expected_tokens=[item.split()[0]],
            target_table="todos",
            rationale="Reminder-style todo write stress.",
            ignore_hint_if_failed="scope_decision_needed",
        )

    for text, severity in [
        ("show todo list", "core"),
        ("show me todo list", "core"),
        ("todo list pls", "core"),
        ("show pending tasks", "core"),
        ("pending todo list", "core"),
        ("what is on my todo list", "stretch"),
        ("list pending reminders", "stretch"),
        ("show done todos", "core"),
        ("done task list", "stretch"),
        ("pending tasks", "stretch"),
        ("done todos", "stretch"),
        ("show all pending todos", "stretch"),
        ("show pending reminders", "stretch"),
        ("todo status", "adversarial"),
        ("tasks pending", "stretch"),
    ]:
        builder.add(
            text,
            focus_area="todo_query",
            severity=severity,
            expected_kind="query",
            rationale="Todo retrieval stress.",
            ignore_hint_if_failed="not_ignorable_candidate" if severity == "core" else "scope_decision_needed",
        )


def build_weight_specs(builder: ProbeBuilder) -> None:
    weight_writes = [
        "jeevi 64.4",
        "jeevi weight 64.8 after lunch",
        "jeevi 65.1 post walk",
        "prani 11.9",
        "prani weight 12.1 after breakfast",
        "prani 12.0 evening",
        "murugan 66.0",
        "murugan weight 66.3 post dinner",
        "murugan 66.1 morning",
        "jeevi weight 64.6 with shoes off",
    ]
    for text in weight_writes:
        person = text.split()[0]
        builder.add(
            text,
            focus_area="weight_write",
            severity="core",
            expected_kind="write",
            expected_tokens=[person],
            target_table="weights",
            rationale=f"Seed weight history for {person}.",
            ignore_hint_if_failed="not_ignorable_candidate",
        )

    weight_queries = [
        ("jeevi weight", "core"),
        ("prani weight", "core"),
        ("murugan weight", "core"),
        ("latest weight of jeevi", "core"),
        ("latest weight of prani", "core"),
        ("latest weight of murugan", "core"),
        ("last 3 jeevi weight", "core"),
        ("last 3 prani weight", "core"),
        ("last 3 murugan weight", "core"),
        ("show last 5 jeevi weight with date", "stretch"),
        ("show last 4 prani weight with date", "stretch"),
        ("show last 4 murugan weight with date", "stretch"),
        ("jeevi last 2 weight", "stretch"),
        ("weight status", "adversarial"),
        ("show recent murugan weight", "stretch"),
        ("show jeevi weight history", "stretch"),
        ("show prani weight history", "stretch"),
        ("show murugan weight history", "stretch"),
        ("jeevi recent weights", "stretch"),
        ("prani recent weights", "stretch"),
        ("murugan recent weights", "stretch"),
        ("weight history for jeevi", "stretch"),
        ("weight history for prani", "stretch"),
        ("weight history for murugan", "stretch"),
        ("show jeevi latest weight entry", "stretch"),
    ]
    for text, severity in weight_queries:
        builder.add(
            text,
            focus_area="weight_query",
            severity=severity,
            expected_kind="query",
            rationale="Weight retrieval stress.",
            ignore_hint_if_failed="not_ignorable_candidate" if severity == "core" else "scope_decision_needed",
        )


def build_ledger_specs(builder: ProbeBuilder) -> None:
    for text in [
        "gave maddy 5k",
        "got 2k from ravi",
        "ravi returned 1k",
        "sent thenna 750",
        "maddy gave me 3k",
    ]:
        builder.add(
            text,
            focus_area="ledger_write",
            severity="core",
            expected_kind="write",
            target_table="ledger",
            rationale="Ledger write stress.",
            ignore_hint_if_failed="not_ignorable_candidate",
        )

    for text, severity in [
        ("maddy balance", "core"),
        ("how much do i owe ravi", "core"),
        ("who owes me money", "core"),
        ("who all owe me money and how much. list individually", "core"),
        ("who do i owe", "core"),
        ("show me maddy balance", "core"),
        ("show ledger for maddy", "stretch"),
        ("show ledger for ravi", "stretch"),
        ("all ledger", "stretch"),
        ("show all ledger entries", "stretch"),
        ("maddy ledger summary", "stretch"),
        ("ravi ledger summary", "stretch"),
        ("ledger history for maddy", "stretch"),
        ("ledger history for ravi", "stretch"),
        ("who currently owes me money", "stretch"),
        ("who owes me right now", "stretch"),
    ]:
        builder.add(
            text,
            focus_area="ledger_query",
            severity=severity,
            expected_kind="query",
            rationale="Ledger retrieval stress.",
            ignore_hint_if_failed="not_ignorable_candidate" if severity == "core" else "scope_decision_needed",
        )

    for text in [
        "clear maddy ledger",
        "settled maddy amount",
        "clear ravi ledger",
        "wrote off thenna",
        "maddy settled amount",
    ]:
        builder.add(
            text,
            focus_area="ledger_clarification",
            severity="core",
            expected_kind="clarification",
            rationale="Settlement clarification stress.",
            ignore_hint_if_failed="not_ignorable_candidate",
        )


def build_generated_specs(existing_inputs: set[str]) -> list[ProbeSpec]:
    builder = ProbeBuilder(existing_inputs)
    build_note_specs(builder)
    build_expense_specs(builder)
    build_todo_specs(builder)
    build_weight_specs(builder)
    build_ledger_specs(builder)
    quotas = {
        "note_write": 40,
        "note_query": 210,
        "expense_write": 10,
        "expense_query": 62,
        "todo_write": 20,
        "todo_query": 13,
        "weight_write": 10,
        "weight_query": 15,
        "ledger_write": 5,
        "ledger_query": 10,
        "ledger_clarification": 5,
    }
    selected: list[ProbeSpec] = []
    for focus_area, quota in quotas.items():
        matches = [spec for spec in builder.specs if spec.focus_area == focus_area]
        if len(matches) < quota:
            raise RuntimeError(f"Needed {quota} specs for {focus_area}, found only {len(matches)}")
        selected.extend(matches[:quota])
    if len(selected) != 400:
        raise RuntimeError(f"Expected exactly 400 generated specs after quota selection, found {len(selected)}")
    return selected


def latest_structured_type(result: ReplayResult) -> str | None:
    notes_change = result.table_changes.get("notes") or {}
    latest = notes_change.get("after_latest_row") or {}
    return latest.get("structured_type")


def table_delta(result: ReplayResult, table_name: str) -> int:
    change = result.table_changes.get(table_name) or {}
    delta = change.get("count_delta")
    return int(delta) if isinstance(delta, int) else 0


def response_has_expected_token(result: ReplayResult, spec: ProbeSpec) -> bool | None:
    if not spec.expected_tokens:
        return None
    response = (result.actual_response_text or "").lower()
    return any(token.lower() in response for token in spec.expected_tokens)


def diagnose_result(result: ReplayResult, spec: ProbeSpec) -> dict[str, Any]:
    kind_ok = result.actual_kind in spec.allowed_kinds
    token_hit = response_has_expected_token(result, spec)
    total_ms = float(result.total_ms or 0.0)
    reasons: list[str] = []

    if not kind_ok:
        if spec.expected_kind == "query" and result.actual_kind == "write":
            reasons.append("query_routed_as_write")
        elif spec.expected_kind == "write" and result.actual_kind == "query":
            reasons.append("write_routed_as_query")
        elif spec.expected_kind == "clarification" and result.actual_kind != "clarification":
            reasons.append("clarification_flow_not_triggered")
        elif result.actual_kind == "clarification":
            reasons.append("query_forced_to_clarify")
        else:
            reasons.append("unexpected_kind")

    if spec.expected_kind == "write" and spec.target_table and table_delta(result, spec.target_table) <= 0:
        reasons.append("write_missing_domain_row")

    if spec.focus_area == "note_query":
        if result.actual_kind == "write":
            reasons.append("note_query_saved_as_note")
        if table_delta(result, "embeddings") > 0:
            reasons.append("note_query_created_embedding_side_effect")
        if latest_structured_type(result) == "note" and result.actual_kind == "write":
            reasons.append("note_query_materialized_as_plain_note")
        if token_hit is False:
            reasons.append("note_query_response_missing_expected_topic")

    if spec.focus_area == "expense_query":
        if result.actual_kind == "write":
            reasons.append("expense_query_logged_as_write")
        if token_hit is False and spec.expected_tokens:
            reasons.append("expense_query_response_missing_expected_token")

    if spec.focus_area == "todo_write" and table_delta(result, "todos") <= 0:
        reasons.append("todo_write_missing_todo_row")

    if spec.focus_area == "weight_write" and table_delta(result, "weights") <= 0:
        reasons.append("weight_write_missing_weight_row")

    if spec.focus_area == "ledger_write" and table_delta(result, "ledger") <= 0:
        reasons.append("ledger_write_missing_ledger_row")

    if spec.focus_area.endswith("_query") and total_ms > 5000:
        reasons.append("latency_over_5s_budget")
    elif spec.focus_area.endswith("_query") and total_ms > 1000:
        reasons.append("latency_over_1s")

    if spec.focus_area == "note_write" and total_ms > 5000:
        reasons.append("note_write_latency_over_5s_budget")

    if not reasons:
        triage_bucket = "ok"
    elif spec.ignore_hint_if_failed == "not_ignorable_candidate":
        triage_bucket = "not_ignorable_candidate"
    elif spec.ignore_hint_if_failed.startswith("maybe_ignorable"):
        triage_bucket = spec.ignore_hint_if_failed
    else:
        triage_bucket = "scope_decision_needed"

    return {
        "case_id": result.case_id,
        "input_text": spec.case.text,
        "focus_area": spec.focus_area,
        "severity": spec.severity,
        "expected_kind": spec.expected_kind,
        "allowed_kinds": spec.allowed_kinds,
        "expected_tokens": spec.expected_tokens,
        "kind_ok": kind_ok,
        "token_hit": token_hit,
        "break_reasons": reasons,
        "triage_bucket": triage_bucket,
        "target_table": spec.target_table,
        "actual_kind": result.actual_kind,
        "actual_tier": result.actual_tier,
        "actual_rule": result.actual_rule,
        "total_ms": result.total_ms,
        "rationale": spec.rationale,
    }


def count_by(items: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def summarize_generated(results: list[ReplayResult], specs: list[ProbeSpec]) -> dict[str, Any]:
    spec_map = {spec.case.case_id: spec for spec in specs}
    diagnostics = [diagnose_result(result, spec_map[result.case_id]) for result in results]
    focus_summary: dict[str, Any] = {}
    for focus_area in sorted({item["focus_area"] for item in diagnostics}):
        subset = [item for item in diagnostics if item["focus_area"] == focus_area]
        subset_results = [result for result in results if spec_map[result.case_id].focus_area == focus_area]
        focus_summary[focus_area] = {
            "count": len(subset),
            "kind_ok_count": sum(1 for item in subset if item["kind_ok"]),
            "token_hit_count": sum(1 for item in subset if item["token_hit"] is True),
            "token_comparable_count": sum(1 for item in subset if item["token_hit"] is not None),
            "triage_counts": count_by([item["triage_bucket"] for item in subset]),
            "reason_counts": count_by([reason for item in subset for reason in item["break_reasons"]]),
            "latency": latency_stats(subset_results),
        }
    return {
        "overall_count": len(diagnostics),
        "kind_ok_count": sum(1 for item in diagnostics if item["kind_ok"]),
        "token_hit_count": sum(1 for item in diagnostics if item["token_hit"] is True),
        "token_comparable_count": sum(1 for item in diagnostics if item["token_hit"] is not None),
        "triage_counts": count_by([item["triage_bucket"] for item in diagnostics]),
        "reason_counts": count_by([reason for item in diagnostics for reason in item["break_reasons"]]),
        "focus_summary": focus_summary,
        "diagnostics": diagnostics,
    }


def build_summary_markdown(
    run_metadata: dict[str, Any],
    historical_results: list[ReplayResult],
    generated_results: list[ReplayResult],
    historical_summary: dict[str, Any],
    generated_summary: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("# Full Throttle Replay Summary")
    lines.append("")
    lines.append("## Run metadata")
    lines.append("")
    lines.append(f"- Generated at: `{run_metadata['generated_at']}`")
    lines.append(f"- Replay DB: `{run_metadata['replay_db']}`")
    lines.append(f"- Logs file: `{run_metadata['logs_file']}`")
    lines.append(f"- Historical cases: `{len(historical_results)}`")
    lines.append(f"- Generated cases: `{len(generated_results)}`")
    lines.append(f"- Total cases: `{len(historical_results) + len(generated_results)}`")
    lines.append(f"- LLM backend: `{run_metadata['runtime']['llm']['backend']}`")
    lines.append("")

    lines.append("## Historical Replay Segment")
    lines.append("")
    lines.append(f"- Kind match: `{historical_summary.get('kind_match_count', 0)}/{historical_summary.get('total_cases', 0)}`")
    lines.append(f"- Parsed metadata available in logs: `{historical_summary.get('parsed_available_count', 0)}/{historical_summary.get('total_cases', 0)}`")
    lines.append(f"- Tier match: `{historical_summary.get('tier_match_count', 0)}/{historical_summary.get('tier_comparable_count', 0)}` comparable cases")
    lines.append(f"- Rule match: `{historical_summary.get('rule_match_count', 0)}/{historical_summary.get('rule_comparable_count', 0)}` comparable cases")
    lines.append(f"- Response exact match: `{historical_summary.get('response_exact_match_count', 0)}/{historical_summary.get('total_cases', 0)}`")
    lines.append("")

    lines.append("## Generated Full-Throttle Segment")
    lines.append("")
    lines.append(f"- Expected-kind pass: `{generated_summary['kind_ok_count']}/{generated_summary['overall_count']}`")
    lines.append(f"- Token-hit pass on comparable cases: `{generated_summary['token_hit_count']}/{generated_summary['token_comparable_count']}`")
    lines.append(f"- Triage buckets: `{json.dumps(generated_summary['triage_counts'], ensure_ascii=False)}`")
    lines.append(f"- Break reasons: `{json.dumps(generated_summary['reason_counts'], ensure_ascii=False)}`")
    lines.append("")

    lines.append("## Focus Breakdown")
    lines.append("")
    for focus_area, summary in generated_summary["focus_summary"].items():
        lines.append(
            f"- `{focus_area}`: count `{summary['count']}`, kind-pass `{summary['kind_ok_count']}/{summary['count']}`, token-pass `{summary['token_hit_count']}/{summary['token_comparable_count']}`, triage `{json.dumps(summary['triage_counts'], ensure_ascii=False)}`, latency `{json.dumps(summary['latency'], ensure_ascii=False)}`"
        )
    lines.append("")

    lines.append("## Worst Non-Ignorable Candidates")
    lines.append("")
    diagnostics = generated_summary["diagnostics"]
    not_ignorable = [item for item in diagnostics if item["triage_bucket"] == "not_ignorable_candidate"][:40]
    if not_ignorable:
        for item in not_ignorable[:25]:
            lines.append(
                f"- `{item['case_id']}` `{item['input_text']}` -> `{item['actual_kind']}/{item['actual_tier']}/{item['actual_rule']}` reasons `{item['break_reasons']}` latency `{item['total_ms']}`"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Scope Decision Cases")
    lines.append("")
    scope_cases = [item for item in diagnostics if item["triage_bucket"] == "scope_decision_needed"][:40]
    if scope_cases:
        for item in scope_cases[:20]:
            lines.append(
                f"- `{item['case_id']}` `{item['input_text']}` -> `{item['actual_kind']}/{item['actual_tier']}/{item['actual_rule']}` reasons `{item['break_reasons']}` latency `{item['total_ms']}`"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Slowest Cases")
    lines.append("")
    for row in top_slowest(historical_results + generated_results, limit=25):
        lines.append(
            f"- `{row['case_id']}` `{row['input_text']}` -> `{row['kind']}/{row['tier']}/{row['rule']}` in `{row['total_ms']}` ms"
        )
    lines.append("")
    return "\n".join(lines)


def write_csv(
    path: Path,
    historical_results: list[ReplayResult],
    generated_results: list[ReplayResult],
    generated_summary: dict[str, Any],
) -> None:
    diagnostic_map = {item["case_id"]: item for item in generated_summary["diagnostics"]}
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "segment",
                "case_id",
                "input_text",
                "focus_area",
                "severity",
                "expected_kind",
                "actual_kind",
                "actual_tier",
                "actual_rule",
                "triage_bucket",
                "break_reasons",
                "total_ms",
            ],
        )
        writer.writeheader()
        for row in historical_results:
            writer.writerow(
                {
                    "segment": "historical",
                    "case_id": row.case_id,
                    "input_text": row.input_text,
                    "focus_area": "historical_replay",
                    "severity": "historical",
                    "expected_kind": "",
                    "actual_kind": row.actual_kind,
                    "actual_tier": row.actual_tier,
                    "actual_rule": row.actual_rule,
                    "triage_bucket": "",
                    "break_reasons": "",
                    "total_ms": row.total_ms,
                }
            )
        for row in generated_results:
            diag = diagnostic_map[row.case_id]
            writer.writerow(
                {
                    "segment": "generated",
                    "case_id": row.case_id,
                    "input_text": row.input_text,
                    "focus_area": diag["focus_area"],
                    "severity": diag["severity"],
                    "expected_kind": diag["expected_kind"],
                    "actual_kind": row.actual_kind,
                    "actual_tier": row.actual_tier,
                    "actual_rule": row.actual_rule,
                    "triage_bucket": diag["triage_bucket"],
                    "break_reasons": " | ".join(diag["break_reasons"]),
                    "total_ms": row.total_ms,
                }
            )


def main() -> int:
    if not SOURCE_DB_PATH.exists():
        print(f"FAIL: source DB not found at {SOURCE_DB_PATH}")
        return 1
    if not LOGS_PATH.exists():
        print(f"FAIL: logs file not found at {LOGS_PATH}")
        return 1

    ensure_clean_dir(ARTIFACT_DIR)
    historical_entries = parse_logs(LOGS_PATH)
    historical_cases = build_historical_cases(historical_entries)
    generated_specs = build_generated_specs({normalize_text(entry.input_text) for entry in historical_entries})
    all_cases = historical_cases + [spec.case for spec in generated_specs]

    copy_db(SOURCE_DB_PATH, REPLAY_DB_PATH)
    runner = FlaskReplayRunner(REPLAY_DB_PATH)
    all_results = run_replay_batch(runner, all_cases)
    runtime = runner.runtime_status()

    historical_results = all_results[: len(historical_cases)]
    generated_results = all_results[len(historical_cases) :]
    historical_summary = summarize_historical(historical_results)
    generated_summary = summarize_generated(generated_results, generated_specs)
    run_metadata = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "replay_db": str(REPLAY_DB_PATH),
        "logs_file": str(LOGS_PATH),
        "runtime": runtime,
        "historical_case_count": len(historical_cases),
        "generated_case_count": len(generated_specs),
    }

    payload = {
        "run_metadata": run_metadata,
        "historical_summary": historical_summary,
        "historical_latency": latency_stats(historical_results),
        "generated_latency": latency_stats(generated_results),
        "all_latency": latency_stats(all_results),
        "historical_results": results_to_jsonable(historical_results),
        "generated_results": results_to_jsonable(generated_results),
        "generated_specs": [asdict(spec) for spec in generated_specs],
        "generated_summary": generated_summary,
    }
    summary_md = build_summary_markdown(
        run_metadata,
        historical_results,
        generated_results,
        historical_summary,
        generated_summary,
    )

    (ARTIFACT_DIR / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (ARTIFACT_DIR / "summary.md").write_text(summary_md, encoding="utf-8")
    (ARTIFACT_DIR / "diagnostics.json").write_text(
        json.dumps(generated_summary["diagnostics"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(
        ARTIFACT_DIR / "results.csv",
        historical_results,
        generated_results,
        generated_summary,
    )
    (ARTIFACT_DIR / "case_manifest.json").write_text(
        json.dumps(
            {
                "historical_cases": [asdict(case) for case in historical_cases],
                "generated_specs": [asdict(spec) for spec in generated_specs],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "historical_cases": len(historical_cases),
                "generated_cases": len(generated_specs),
                "total_cases": len(all_cases),
                "artifact_dir": str(ARTIFACT_DIR),
                "historical_latency": latency_stats(historical_results),
                "generated_latency": latency_stats(generated_results),
                "generated_triage": generated_summary["triage_counts"],
                "generated_reason_counts": generated_summary["reason_counts"],
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
