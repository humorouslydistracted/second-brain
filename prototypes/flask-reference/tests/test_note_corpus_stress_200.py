from __future__ import annotations

import csv
import importlib
import json
import os
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from test_replay_matrix import (
    APP_DIR,
    SOURCE_DB_PATH,
    copy_db,
    diff_snapshots,
    ensure_clean_dir,
    latency_stats,
    normalize_text,
    snapshot_tables,
)


ARTIFACT_DIR = APP_DIR / "artifacts" / "note_corpus_stress_200"
REPLAY_DB_PATH = ARTIFACT_DIR / "note_corpus_stress.db"


@dataclass
class DomainSpec:
    key: str
    label: str
    alias: str
    typo: str
    frame: str
    caution: str
    anchors: list[str]


@dataclass
class WriteSpec:
    write_id: str
    domain_key: str
    note_index: int
    method: str
    burst_tag: str
    content: str
    expected_tokens: list[str]


@dataclass
class QuerySpec:
    query_id: str
    domain_key: str | None
    phase: str
    category: str
    prompt: str
    expected_tokens: list[str]
    expected_domain_terms: list[str]
    notes: str | None = None


@dataclass
class RouteResult:
    op_id: str
    op_type: str
    route: str
    input_text: str
    domain_key: str | None
    method: str
    category: str
    burst_tag: str | None
    http_status: int
    wall_ms: float
    activity_log_id: int | None
    actual_kind: str | None
    actual_response_text: str | None
    actual_tier: str | None
    actual_rule: str | None
    activity_metadata: dict[str, Any]
    table_changes: dict[str, Any]
    latest_note_row: dict[str, Any] | None
    latest_embedding_row: dict[str, Any] | None


def build_domains() -> list[DomainSpec]:
    return [
        DomainSpec(
            key="astronomy",
            label="astronomy",
            alias="stargazing",
            typo="astronamy",
            frame="observation and prediction",
            caution="precise timing matters more than dramatic telescope imagery",
            anchors=[
                "pulsar timing drift",
                "spectral line broadening",
                "lunar occultation notes",
                "nebula dust scattering",
                "planet transit cadence",
                "red dwarf flare cycles",
                "gravitational lens arcs",
                "radio burst triangulation",
                "comet tail asymmetry",
                "magnetar cooling pattern",
            ],
        ),
        DomainSpec(
            key="nutrition",
            label="nutrition",
            alias="food metabolism",
            typo="nutrishun",
            frame="energy, satiety, and steady blood sugar",
            caution="boring meal structure often beats flashy superfood narratives",
            anchors=[
                "protein leverage effect",
                "post lunch glucose dip",
                "fermented rice breakfast",
                "fiber before starch",
                "late night hunger rebound",
                "electrolyte dilution pattern",
                "slow chewing satiety signal",
                "curd rice calm digestion",
                "ginger tea appetite reset",
                "weekend overeating spillover",
            ],
        ),
        DomainSpec(
            key="climate_policy",
            label="climate policy",
            alias="decarbonization policy",
            typo="climte policy",
            frame="infrastructure, pricing, and transition tradeoffs",
            caution="implementation details matter more than broad net-zero slogans",
            anchors=[
                "carbon floor corridor",
                "grid congestion reform",
                "cement clinker cap",
                "methane leak auditing",
                "industrial heat retrofit",
                "urban bus electrification",
                "coastal adaptation bond",
                "agri residue incentive",
                "transmission siting friction",
                "carbon border adjustment",
            ],
        ),
        DomainSpec(
            key="distributed_systems",
            label="distributed systems",
            alias="backend consistency",
            typo="distribted systems",
            frame="failure handling and coordination under uncertainty",
            caution="tail latency and recovery shape user experience more than elegant diagrams",
            anchors=[
                "leader lease expiry",
                "write ahead fencing",
                "quorum read lag",
                "idempotency token reuse",
                "clock skew budget",
                "retry storm collapse",
                "compaction pause cliff",
                "hot partition drift",
                "causal cache invalidation",
                "snapshot catchup window",
            ],
        ),
        DomainSpec(
            key="language_design",
            label="programming language design",
            alias="language ergonomics",
            typo="langauge design",
            frame="expressiveness, safety, and readability",
            caution="small syntax wins mean little if error messages stay confusing",
            anchors=[
                "effect typing boundary",
                "borrow checker narrative",
                "gradual typing escape hatch",
                "pattern exhaustiveness pain",
                "error locality principle",
                "sum type discoverability",
                "compile time reflection risk",
                "trait coherence wrinkle",
                "macro hygiene pressure",
                "nullability migration path",
            ],
        ),
        DomainSpec(
            key="indian_history",
            label="indian history",
            alias="subcontinental history",
            typo="indan history",
            frame="state formation, exchange, and social memory",
            caution="administrative evidence usually matters more than nationalist mythmaking",
            anchors=[
                "ashokan inscription route",
                "sangam port exchange",
                "chalukya temple grant",
                "maratha revenue circuit",
                "mughal garden logistics",
                "bhakti oral transmission",
                "delhi sultan coin flow",
                "taxila learning corridor",
                "vijayanagara horse trade",
                "colonial canal bargaining",
            ],
        ),
        DomainSpec(
            key="psychology",
            label="behavioral psychology",
            alias="habit formation",
            typo="psychlogy habits",
            frame="attention, habit loops, and motivation",
            caution="identity cues and friction control outperform raw willpower talk",
            anchors=[
                "cue triggered routine",
                "reward prediction error",
                "implementation intention phrasing",
                "variable reward trap",
                "identity rehearsal effect",
                "friction ladder design",
                "stress boredom confusion",
                "habit stack overload",
                "dopamine novelty tax",
                "self narrative reset",
            ],
        ),
        DomainSpec(
            key="urban_design",
            label="urban design",
            alias="city planning",
            typo="urban desgin",
            frame="walkability, shade, and public movement",
            caution="shaded corridors and junction safety matter more than iconic flyovers",
            anchors=[
                "shade corridor network",
                "bus stop spillback",
                "mixed use frontage",
                "junction crossing delay",
                "stormwater curb inlet",
                "street tree root zone",
                "footpath continuity gap",
                "night market edge",
                "cycle lane pinch point",
                "public square dwell time",
            ],
        ),
        DomainSpec(
            key="microbiology",
            label="microbiology",
            alias="microbial systems",
            typo="microbilogy",
            frame="adaptation, signaling, and experimental interpretation",
            caution="context and growth conditions matter more than neat petri-dish stories",
            anchors=[
                "quorum sensing pulse",
                "biofilm shear layer",
                "plasmid copy burden",
                "sporulation trigger drift",
                "phage resistance tradeoff",
                "anaerobic niche pocket",
                "ribosome stalling artifact",
                "culture contamination halo",
                "nutrient gradient bias",
                "cell wall stress reporter",
            ],
        ),
        DomainSpec(
            key="film_theory",
            label="film theory",
            alias="cinema analysis",
            typo="flim theory",
            frame="framing, rhythm, and emotional inference",
            caution="editing rhythm often shapes meaning more than plot summaries do",
            anchors=[
                "negative space framing",
                "jump cut anxiety",
                "color temperature shift",
                "off screen implication",
                "diegetic sound bridge",
                "long take pressure",
                "reaction shot delay",
                "mirror blocking cue",
                "elliptical transition fade",
                "foreground background tension",
            ],
        ),
        DomainSpec(
            key="classical_music",
            label="classical music",
            alias="concert listening",
            typo="clasical music",
            frame="structure, tension, and listening attention",
            caution="repeated motifs and tonal return matter more than surface speed",
            anchors=[
                "ragam alapana patience",
                "tani avartanam pulse",
                "counterpoint inversion turn",
                "cadence suspension release",
                "mridangam gumki weight",
                "violin glide contour",
                "motif recurrence memory",
                "shruti alignment tension",
                "call response echo",
                "tempo rubato restraint",
            ],
        ),
        DomainSpec(
            key="agriculture",
            label="regenerative agriculture",
            alias="soil restoration",
            typo="regerative agriculture",
            frame="soil life, water retention, and resilient yield",
            caution="soil structure and timing matter more than input quantity alone",
            anchors=[
                "compost tea dilution",
                "mulch moisture cap",
                "cover crop root web",
                "worm cast aeration",
                "drip line clogging",
                "monsoon runoff trench",
                "seedling transplant shock",
                "shade net airflow",
                "microbial inoculant timing",
                "salinity crust signal",
            ],
        ),
        DomainSpec(
            key="logistics",
            label="logistics planning",
            alias="route operations",
            typo="logstics planning",
            frame="throughput, buffers, and movement reliability",
            caution="handoff clarity and dock timing beat grand optimization claims",
            anchors=[
                "cross dock window",
                "reverse route deadhead",
                "inventory buffer bleed",
                "dispatch handoff gap",
                "dock door queueing",
                "container scan mismatch",
                "cutoff time slippage",
                "last mile density",
                "return loop consolidation",
                "eta confidence interval",
            ],
        ),
        DomainSpec(
            key="linguistics",
            label="linguistics",
            alias="language change",
            typo="lingustics",
            frame="sound shift, grammar, and meaning drift",
            caution="usage patterns usually reveal more than prescriptive rules",
            anchors=[
                "retroflex spread clue",
                "case marking erosion",
                "loanword stress shift",
                "code switch trigger",
                "pragmatic particle drift",
                "analogy leveling effect",
                "agreement mismatch repair",
                "register switching cue",
                "phonotactic smoothing",
                "semantic bleaching path",
            ],
        ),
        DomainSpec(
            key="renewable_energy",
            label="renewable energy",
            alias="grid storage",
            typo="renewble energy",
            frame="generation variability, storage, and grid balancing",
            caution="battery safety and dispatch behavior matter more than clean-energy slogans",
            anchors=[
                "thermal runaway myth",
                "battery round trip loss",
                "solar curtailment pocket",
                "wind lull reserve",
                "inverter clipping plateau",
                "storage dispatch curve",
                "frequency response burst",
                "peak shaving bias",
                "microgrid islanding drill",
                "transformer loading swing",
            ],
        ),
        DomainSpec(
            key="marine_biology",
            label="marine biology",
            alias="ocean ecosystems",
            typo="marine biolgy",
            frame="ecology, adaptation, and fragile balance",
            caution="temperature, acidity, and food-web changes interact more than single-cause narratives suggest",
            anchors=[
                "coral bleaching pulse",
                "mangrove nursery shelter",
                "upwelling nutrient plume",
                "reef fish cleaning station",
                "jelly bloom signal",
                "salinity wedge shift",
                "seagrass sediment trap",
                "krill migration ladder",
                "deep sea vent colony",
                "plankton bloom collapse",
            ],
        ),
        DomainSpec(
            key="cybersecurity",
            label="cybersecurity",
            alias="security operations",
            typo="cybersecurty",
            frame="defense layers, attacker paths, and operational hygiene",
            caution="basic isolation and credential discipline beat flashy detection dashboards",
            anchors=[
                "privilege escalation breadcrumb",
                "phishing lure context",
                "token replay loophole",
                "lateral movement corridor",
                "patch lag exposure",
                "audit log retention",
                "supply chain signing",
                "sandbox escape clue",
                "credential stuffing burst",
                "incident tabletop rehearsal",
            ],
        ),
        DomainSpec(
            key="public_health",
            label="public health",
            alias="population health",
            typo="publc health",
            frame="prevention, communication, and system capacity",
            caution="trusted local communication matters more than abstract top-down messaging",
            anchors=[
                "vaccination cold chain",
                "mosquito breeding pocket",
                "clinic triage overflow",
                "mask fit behavior",
                "surveillance lag gap",
                "hydration campaign design",
                "contact tracing fatigue",
                "school meal coverage",
                "heatwave rest center",
                "wastewater signal drift",
            ],
        ),
        DomainSpec(
            key="philosophy",
            label="philosophy",
            alias="ethics and meaning",
            typo="phliosophy",
            frame="reasoning, values, and self-examination",
            caution="clear distinctions and lived consequences matter more than clever abstractions",
            anchors=[
                "virtue under pressure",
                "means ends confusion",
                "personal identity puzzle",
                "moral luck tension",
                "embodied knowledge claim",
                "attention as ethics",
                "desire discipline loop",
                "certainty humility balance",
                "language reality gap",
                "public reason threshold",
            ],
        ),
        DomainSpec(
            key="education_research",
            label="education research",
            alias="learning science",
            typo="edcation research",
            frame="memory, feedback, and instructional design",
            caution="retrieval practice and feedback timing matter more than presentation polish",
            anchors=[
                "spacing effect ladder",
                "worked example fade",
                "metacognition illusion",
                "feedback delay window",
                "cognitive load spillover",
                "peer instruction loop",
                "retrieval cue design",
                "transfer task mismatch",
                "interleaving surprise benefit",
                "productive struggle boundary",
            ],
        ),
    ]


def note_lines(domain: DomainSpec, anchor: str, index: int) -> list[str]:
    variant = index % 4
    if variant == 0:
        return [
            f"Long note on {domain.label}: I want to remember how {anchor} changed the way I think about {domain.frame}.",
            f"The subtle point is that {domain.caution}, so I should distrust the simplified headline version.",
            f"Another layer is that {anchor} keeps surfacing whenever the conversation becomes too generic or too abstract.",
            f"If I search later, the anchors should be {domain.alias}, {anchor}, and the broader theme of {domain.frame}.",
        ]
    if variant == 1:
        return [
            f"Working note for {domain.label}. The phrase I do not want to lose is {anchor}, because it keeps grounding the topic in something concrete.",
            f"My current takeaway is that {domain.caution}, even when people sound very confident about the opposite.",
            f"I also want to remember that {anchor} sits inside the larger frame of {domain.frame}, not as an isolated fact.",
            f"If I come back later, the search trail should include {domain.label}, {domain.alias}, and {anchor}.",
        ]
    if variant == 2:
        return [
            f"Memory note about {domain.label}: the anchor phrase here is {anchor}, and it keeps correcting my first impression.",
            f"The important nuance is that {domain.caution}, which is easy to miss when the discussion becomes dramatic.",
            f"I should connect {anchor} to the broader issue of {domain.frame}, because that is where the real meaning sits.",
            f"When I retrieve this later, I expect to remember {domain.alias}, {anchor}, and the caution about oversimplification.",
        ]
    return [
        f"Field note for {domain.label}. I keep returning to {anchor} whenever I try to make this topic practical instead of vague.",
        f"The strongest lesson so far is that {domain.caution}, which makes the flashy version much less useful.",
        f"I want to tie {anchor} back to {domain.frame}, because otherwise the idea becomes shallow and forgettable.",
        f"If I search again, the retrieval anchors should include {domain.label}, {anchor}, and {domain.alias}.",
    ]


def compose_note_text(domain: DomainSpec, note_index: int) -> str:
    anchor = domain.anchors[note_index]
    return "\n".join(note_lines(domain, anchor, note_index))


def build_write_specs(domains: list[DomainSpec]) -> list[WriteSpec]:
    specs: list[WriteSpec] = []
    counter = 1
    for domain in domains:
        for idx in range(10):
            content = compose_note_text(domain, idx)
            if idx <= 3:
                method = "notes_page_burst4"
                burst_tag = f"{domain.key}-burst-notes-page"
            elif idx <= 6:
                method = "home_explicit_burst3"
                burst_tag = f"{domain.key}-burst-home-explicit"
            elif idx <= 8:
                method = "home_freeform_single"
                burst_tag = f"{domain.key}-single-freeform-{idx}"
            else:
                method = "notes_page_single"
                burst_tag = f"{domain.key}-single-notes-page"
            specs.append(
                WriteSpec(
                    write_id=f"W{counter:03d}",
                    domain_key=domain.key,
                    note_index=idx,
                    method=method,
                    burst_tag=burst_tag,
                    content=content,
                    expected_tokens=[domain.label, domain.alias, domain.anchors[idx]],
                )
            )
            counter += 1
    return specs


def build_query_specs(domains: list[DomainSpec]) -> list[QuerySpec]:
    specs: list[QuerySpec] = []
    counter = 1

    def add(
        *,
        domain_key: str | None,
        phase: str,
        category: str,
        prompt: str,
        expected_tokens: list[str],
        expected_domain_terms: list[str],
        notes: str | None = None,
    ) -> None:
        nonlocal counter
        specs.append(
            QuerySpec(
                query_id=f"Q{counter:03d}",
                domain_key=domain_key,
                phase=phase,
                category=category,
                prompt=prompt,
                expected_tokens=expected_tokens,
                expected_domain_terms=expected_domain_terms,
                notes=notes,
            )
        )
        counter += 1

    for domain in domains:
        add(
            domain_key=domain.key,
            phase="immediate_after_domain_seed",
            category="domain_smoke",
            prompt=f"show notes about {domain.label}",
            expected_tokens=[domain.label, domain.alias],
            expected_domain_terms=[domain.label, domain.alias],
            notes="Immediate retrieval after the domain's 10 notes are seeded.",
        )

    for domain in domains:
        terms = [domain.label, domain.alias]
        add(
            domain_key=domain.key,
            phase="full_corpus",
            category="domain_direct",
            prompt=f"{domain.label} notes",
            expected_tokens=terms + [domain.anchors[0]],
            expected_domain_terms=terms,
        )
        add(
            domain_key=domain.key,
            phase="full_corpus",
            category="domain_direct",
            prompt=f"show notes about {domain.label}",
            expected_tokens=terms + [domain.anchors[1]],
            expected_domain_terms=terms,
        )
        add(
            domain_key=domain.key,
            phase="full_corpus",
            category="anchor_exact",
            prompt=f"find {domain.anchors[0]} in my notes",
            expected_tokens=[domain.anchors[0], domain.label, domain.alias],
            expected_domain_terms=terms,
        )
        add(
            domain_key=domain.key,
            phase="full_corpus",
            category="anchor_exact",
            prompt=f"search my notes for {domain.anchors[5]}",
            expected_tokens=[domain.anchors[5], domain.label, domain.alias],
            expected_domain_terms=terms,
        )
        add(
            domain_key=domain.key,
            phase="full_corpus",
            category="alias_query",
            prompt=f"what do my notes say about {domain.alias}",
            expected_tokens=terms + [domain.anchors[2]],
            expected_domain_terms=terms,
        )
        add(
            domain_key=domain.key,
            phase="full_corpus",
            category="typo_query",
            prompt=f"any mention of {domain.typo} in the notes",
            expected_tokens=terms + [domain.anchors[3]],
            expected_domain_terms=terms,
        )
        add(
            domain_key=domain.key,
            phase="full_corpus",
            category="complex_paraphrase",
            prompt=f"which note said that {domain.caution} in the context of {domain.frame}",
            expected_tokens=terms + [domain.anchors[4]],
            expected_domain_terms=terms,
        )
        add(
            domain_key=domain.key,
            phase="full_corpus",
            category="complex_anchor",
            prompt=f"find the {domain.label} note where {domain.anchors[7]} mattered more than headlines",
            expected_tokens=terms + [domain.anchors[7]],
            expected_domain_terms=terms,
        )

    global_queries = [
        "show me last 5 notes",
        "show me last 10 notes",
        "show me last 20 notes",
        "show me saved notes",
        "show recent notes",
        "show all notes",
        "show all saved notes",
        "list my saved notes",
        "latest note",
        "last note",
        "what are my latest notes",
        "show me last 15 saved notes",
        "show me the most recent notes",
        "show the latest saved note",
        "list all saved notes",
        "show all note snippets",
        "find astronomy in my notes",
        "find cybersecurity in my notes",
        "find marine biology in my notes",
        "find education research in my notes",
    ]
    for prompt in global_queries:
        add(
            domain_key=None,
            phase="full_corpus",
            category="global_recency",
            prompt=prompt,
            expected_tokens=[],
            expected_domain_terms=[],
        )
    return specs


class AppRouteRunner:
    def __init__(self, db_path: Path) -> None:
        os.environ["SECOND_BRAIN_DB_PATH"] = str(db_path)
        os.environ["SECOND_BRAIN_PREWARM"] = "0"
        for module_name in ("second_brain_core", "second_brain_orchestrator", "app"):
            sys.modules.pop(module_name, None)
        self.core_module = importlib.import_module("second_brain_core")
        self.orchestrator_module = importlib.import_module("second_brain_orchestrator")
        self.app_module = importlib.import_module("app")
        self.client = self.app_module.app.test_client()
        self.db_path = db_path
        self.app_module.DB_PATH = str(db_path)
        self.core_module.ensure_activity_log_schema(str(db_path))

        def _orchestrate(text: str, *, _db_path=str(db_path)):
            return self.orchestrator_module.handle(text, db_path=_db_path)

        self.app_module.orchestrate = _orchestrate

    def runtime_status(self) -> dict[str, Any]:
        llm_service, embedding_service = self.orchestrator_module.get_runtime_services()
        return {
            "llm": llm_service.status(),
            "embedding": embedding_service.status(),
        }

    def post(
        self,
        *,
        route: str,
        form_data: dict[str, str],
        op_id: str,
        op_type: str,
        input_text: str,
        domain_key: str | None,
        method: str,
        category: str,
        burst_tag: str | None = None,
    ) -> RouteResult:
        before = snapshot_tables(self.db_path)
        started = time.perf_counter()
        response = self.client.post(route, data=form_data, follow_redirects=False)
        wall_ms = round((time.perf_counter() - started) * 1000.0, 3)
        after = snapshot_tables(self.db_path)
        table_changes = diff_snapshots(before, after)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            activity_log_id = after["activity_log"]["max_id"]
            activity_row = None
            if activity_log_id is not None:
                activity_row = conn.execute(
                    "SELECT id, input_text, response_text, kind, metadata_json FROM activity_log WHERE id = ?",
                    (activity_log_id,),
                ).fetchone()
            latest_note_row = None
            note_id = after["notes"]["max_id"]
            if note_id is not None:
                latest_note_row = conn.execute(
                    "SELECT id, content, structured_type, note_domain, metadata_json, created_at FROM notes WHERE id = ?",
                    (note_id,),
                ).fetchone()
            latest_embedding_row = None
            embed_id = after["embeddings"]["max_id"]
            if embed_id is not None:
                latest_embedding_row = conn.execute(
                    "SELECT id, domain, content, source, source_note_id, created_at FROM embeddings WHERE id = ?",
                    (embed_id,),
                ).fetchone()
        finally:
            conn.close()

        metadata: dict[str, Any] = {}
        if activity_row and activity_row["metadata_json"]:
            try:
                metadata = json.loads(activity_row["metadata_json"])
            except json.JSONDecodeError:
                metadata = {"metadata_decode_error": activity_row["metadata_json"]}

        return RouteResult(
            op_id=op_id,
            op_type=op_type,
            route=route,
            input_text=input_text,
            domain_key=domain_key,
            method=method,
            category=category,
            burst_tag=burst_tag,
            http_status=response.status_code,
            wall_ms=wall_ms,
            activity_log_id=activity_row["id"] if activity_row else None,
            actual_kind=activity_row["kind"] if activity_row else None,
            actual_response_text=activity_row["response_text"] if activity_row else None,
            actual_tier=metadata.get("tier"),
            actual_rule=metadata.get("rule"),
            activity_metadata=metadata,
            table_changes=table_changes,
            latest_note_row=dict(latest_note_row) if latest_note_row else None,
            latest_embedding_row=dict(latest_embedding_row) if latest_embedding_row else None,
        )


def write_payload(write_spec: WriteSpec) -> tuple[str, dict[str, str]]:
    if write_spec.method == "notes_page_burst4":
        return "/notes/add", {"content": write_spec.content}
    if write_spec.method == "notes_page_single":
        return "/notes/add", {"content": write_spec.content}
    if write_spec.method == "home_explicit_burst3":
        return "/note", {"text": f"note:\n{write_spec.content}"}
    if write_spec.method == "home_freeform_single":
        return "/note", {"text": write_spec.content}
    raise ValueError(f"Unknown write method: {write_spec.method}")


def expected_query_terms(query_spec: QuerySpec) -> list[str]:
    return [term.lower() for term in query_spec.expected_tokens if term]


def response_text(result: RouteResult) -> str:
    return (result.actual_response_text or "").lower()


def query_diagnostic(
    result: RouteResult,
    query_spec: QuerySpec,
    domains: dict[str, DomainSpec],
) -> dict[str, Any]:
    text = response_text(result)
    expected_terms = expected_query_terms(query_spec)
    kind_ok = result.actual_kind == "query"
    token_hit = any(term in text for term in expected_terms) if expected_terms else None

    all_domain_terms: dict[str, list[str]] = {}
    for domain in domains.values():
        all_domain_terms[domain.key] = [domain.label.lower(), domain.alias.lower()]

    other_domain_hits = []
    for key, terms in all_domain_terms.items():
        if query_spec.domain_key and key == query_spec.domain_key:
            continue
        if any(term in text for term in terms):
            other_domain_hits.append(key)

    reasons: list[str] = []
    if not kind_ok:
        reasons.append("query_routed_as_write" if result.actual_kind == "write" else "unexpected_kind")
    if query_spec.domain_key and token_hit is False:
        reasons.append("response_missing_expected_domain")
    if query_spec.domain_key and token_hit is False and other_domain_hits:
        reasons.append("cross_domain_contamination")
    if result.actual_kind == "write" and result.latest_note_row and result.latest_note_row.get("structured_type") == "note":
        reasons.append("query_saved_as_plain_note")
    if result.actual_kind == "write" and table_delta(result, "embeddings") > 0:
        reasons.append("query_created_embedding_side_effect")
    if result.wall_ms > 5000:
        reasons.append("latency_over_5s")
    elif result.wall_ms > 1000:
        reasons.append("latency_over_1s")

    return {
        "query_id": query_spec.query_id,
        "domain_key": query_spec.domain_key,
        "phase": query_spec.phase,
        "category": query_spec.category,
        "prompt": query_spec.prompt,
        "expected_terms": query_spec.expected_tokens,
        "expected_domain_terms": query_spec.expected_domain_terms,
        "kind_ok": kind_ok,
        "token_hit": token_hit,
        "other_domain_hits": other_domain_hits,
        "reasons": reasons,
        "actual_kind": result.actual_kind,
        "actual_tier": result.actual_tier,
        "actual_rule": result.actual_rule,
        "wall_ms": result.wall_ms,
        "response_first_line": (result.actual_response_text or "").splitlines()[:1],
    }


def table_delta(result: RouteResult, table_name: str) -> int:
    change = result.table_changes.get(table_name) or {}
    delta = change.get("count_delta")
    return int(delta) if isinstance(delta, int) else 0


def write_diagnostic(result: RouteResult, write_spec: WriteSpec) -> dict[str, Any]:
    note_delta = table_delta(result, "notes")
    embed_delta = table_delta(result, "embeddings")
    latest_note = result.latest_note_row or {}
    kind_ok = result.actual_kind == "write"
    note_saved = note_delta > 0 and latest_note.get("structured_type") == "note"
    reasons: list[str] = []
    if not kind_ok:
        reasons.append("write_not_logged_as_write")
    if not note_saved:
        reasons.append("write_missing_plain_note_row")
    if embed_delta <= 0:
        reasons.append("write_missing_embedding")
    if result.wall_ms > 5000:
        reasons.append("write_latency_over_5s")
    elif result.wall_ms > 1000:
        reasons.append("write_latency_over_1s")
    return {
        "write_id": write_spec.write_id,
        "domain_key": write_spec.domain_key,
        "method": write_spec.method,
        "burst_tag": write_spec.burst_tag,
        "kind_ok": kind_ok,
        "note_saved": note_saved,
        "embedding_saved": embed_delta > 0,
        "reasons": reasons,
        "actual_kind": result.actual_kind,
        "actual_tier": result.actual_tier,
        "actual_rule": result.actual_rule,
        "wall_ms": result.wall_ms,
    }


def count_by(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def summarize_writes(write_results: list[RouteResult], write_specs: list[WriteSpec]) -> dict[str, Any]:
    spec_map = {spec.write_id: spec for spec in write_specs}
    diagnostics = [write_diagnostic(result, spec_map[result.op_id]) for result in write_results]
    methods = {}
    for method in sorted({diag["method"] for diag in diagnostics}):
        subset = [diag for diag in diagnostics if diag["method"] == method]
        subset_results = [result for result in write_results if spec_map[result.op_id].method == method]
        methods[method] = {
            "count": len(subset),
            "kind_ok_count": sum(1 for diag in subset if diag["kind_ok"]),
            "note_saved_count": sum(1 for diag in subset if diag["note_saved"]),
            "embedding_saved_count": sum(1 for diag in subset if diag["embedding_saved"]),
            "reason_counts": count_by([reason for diag in subset for reason in diag["reasons"]]),
            "latency": latency_stats(
                [
                    type("WallStat", (), {"total_ms": result.wall_ms})()  # noqa: SIM901
                    for result in subset_results
                ]
            ),
        }
    return {
        "count": len(diagnostics),
        "kind_ok_count": sum(1 for diag in diagnostics if diag["kind_ok"]),
        "note_saved_count": sum(1 for diag in diagnostics if diag["note_saved"]),
        "embedding_saved_count": sum(1 for diag in diagnostics if diag["embedding_saved"]),
        "reason_counts": count_by([reason for diag in diagnostics for reason in diag["reasons"]]),
        "methods": methods,
        "diagnostics": diagnostics,
    }


def summarize_queries(
    query_results: list[RouteResult],
    query_specs: list[QuerySpec],
    domains: dict[str, DomainSpec],
) -> dict[str, Any]:
    spec_map = {spec.query_id: spec for spec in query_specs}
    diagnostics = [query_diagnostic(result, spec_map[result.op_id], domains) for result in query_results]
    phases = {}
    categories = {}
    for key_name, bucket in [("phase", phases), ("category", categories)]:
        for key_value in sorted({diag[key_name] for diag in diagnostics}):
            subset = [diag for diag in diagnostics if diag[key_name] == key_value]
            subset_results = [result for result in query_results if getattr(spec_map[result.op_id], key_name) == key_value]
            bucket[key_value] = {
                "count": len(subset),
                "kind_ok_count": sum(1 for diag in subset if diag["kind_ok"]),
                "token_hit_count": sum(1 for diag in subset if diag["token_hit"] is True),
                "token_comparable_count": sum(1 for diag in subset if diag["token_hit"] is not None),
                "reason_counts": count_by([reason for diag in subset for reason in diag["reasons"]]),
                "latency": latency_stats(
                    [
                        type("WallStat", (), {"total_ms": result.wall_ms})()  # noqa: SIM901
                        for result in subset_results
                    ]
                ),
            }
    domain_summary = {}
    for domain_key in sorted({diag["domain_key"] for diag in diagnostics if diag["domain_key"]}):
        subset = [diag for diag in diagnostics if diag["domain_key"] == domain_key]
        subset_results = [result for result in query_results if spec_map[result.op_id].domain_key == domain_key]
        domain_summary[domain_key] = {
            "count": len(subset),
            "kind_ok_count": sum(1 for diag in subset if diag["kind_ok"]),
            "token_hit_count": sum(1 for diag in subset if diag["token_hit"] is True),
            "token_comparable_count": sum(1 for diag in subset if diag["token_hit"] is not None),
            "reason_counts": count_by([reason for diag in subset for reason in diag["reasons"]]),
            "latency": latency_stats(
                [
                    type("WallStat", (), {"total_ms": result.wall_ms})()  # noqa: SIM901
                    for result in subset_results
                ]
            ),
        }
    return {
        "count": len(diagnostics),
        "kind_ok_count": sum(1 for diag in diagnostics if diag["kind_ok"]),
        "token_hit_count": sum(1 for diag in diagnostics if diag["token_hit"] is True),
        "token_comparable_count": sum(1 for diag in diagnostics if diag["token_hit"] is not None),
        "reason_counts": count_by([reason for diag in diagnostics for reason in diag["reasons"]]),
        "phases": phases,
        "categories": categories,
        "domains": domain_summary,
        "diagnostics": diagnostics,
    }


def summarize_corpus(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        notes_count = conn.execute("SELECT COUNT(*) c FROM notes WHERE structured_type = 'note'").fetchone()["c"]
        embed_count = conn.execute("SELECT COUNT(*) c FROM embeddings").fetchone()["c"]
        latest_notes = conn.execute(
            "SELECT id, substr(content, 1, 120) AS snippet, created_at FROM notes WHERE structured_type = 'note' ORDER BY id DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()
    return {
        "plain_note_count": int(notes_count),
        "embedding_count": int(embed_count),
        "latest_notes": [dict(row) for row in latest_notes],
    }


def reset_db_for_note_corpus(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        before = {
            "notes": int(conn.execute("SELECT COUNT(*) c FROM notes").fetchone()["c"]),
            "embeddings": int(conn.execute("SELECT COUNT(*) c FROM embeddings").fetchone()["c"]),
            "activity_log": int(conn.execute("SELECT COUNT(*) c FROM activity_log").fetchone()["c"]),
            "pending_actions": int(conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"]),
            "user_routing_memory": int(conn.execute("SELECT COUNT(*) c FROM user_routing_memory").fetchone()["c"]),
        }
        conn.execute("DELETE FROM embeddings")
        conn.execute("DELETE FROM notes")
        conn.execute("DELETE FROM activity_log")
        conn.execute("DELETE FROM pending_actions")
        conn.execute("DELETE FROM user_routing_memory")
        conn.commit()
        return before
    finally:
        conn.close()


def write_csvs(
    write_results: list[RouteResult],
    query_results: list[RouteResult],
    write_summary: dict[str, Any],
    query_summary: dict[str, Any],
) -> None:
    write_diag_map = {diag["write_id"]: diag for diag in write_summary["diagnostics"]}
    query_diag_map = {diag["query_id"]: diag for diag in query_summary["diagnostics"]}

    with (ARTIFACT_DIR / "write_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "write_id",
                "domain_key",
                "method",
                "burst_tag",
                "input_text",
                "actual_kind",
                "actual_tier",
                "actual_rule",
                "wall_ms",
                "kind_ok",
                "note_saved",
                "embedding_saved",
                "reasons",
            ],
        )
        writer.writeheader()
        for result in write_results:
            diag = write_diag_map[result.op_id]
            writer.writerow(
                {
                    "write_id": result.op_id,
                    "domain_key": result.domain_key,
                    "method": result.method,
                    "burst_tag": result.burst_tag,
                    "input_text": result.input_text.replace("\n", " | "),
                    "actual_kind": result.actual_kind,
                    "actual_tier": result.actual_tier,
                    "actual_rule": result.actual_rule,
                    "wall_ms": result.wall_ms,
                    "kind_ok": diag["kind_ok"],
                    "note_saved": diag["note_saved"],
                    "embedding_saved": diag["embedding_saved"],
                    "reasons": " | ".join(diag["reasons"]),
                }
            )

    with (ARTIFACT_DIR / "query_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "query_id",
                "domain_key",
                "phase",
                "category",
                "prompt",
                "actual_kind",
                "actual_tier",
                "actual_rule",
                "wall_ms",
                "kind_ok",
                "token_hit",
                "other_domain_hits",
                "reasons",
                "response_first_line",
            ],
        )
        writer.writeheader()
        for result in query_results:
            diag = query_diag_map[result.op_id]
            writer.writerow(
                {
                    "query_id": result.op_id,
                    "domain_key": result.domain_key,
                    "phase": diag["phase"],
                    "category": diag["category"],
                    "prompt": result.input_text.replace("\n", " | "),
                    "actual_kind": result.actual_kind,
                    "actual_tier": result.actual_tier,
                    "actual_rule": result.actual_rule,
                    "wall_ms": result.wall_ms,
                    "kind_ok": diag["kind_ok"],
                    "token_hit": diag["token_hit"],
                    "other_domain_hits": ",".join(diag["other_domain_hits"]),
                    "reasons": " | ".join(diag["reasons"]),
                    "response_first_line": (result.actual_response_text or "").splitlines()[:1],
                }
            )


def build_summary_md(
    runtime: dict[str, Any],
    reset_summary: dict[str, Any],
    corpus_summary: dict[str, Any],
    write_summary: dict[str, Any],
    query_summary: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("# Note Corpus Stress Summary")
    lines.append("")
    lines.append("## Run metadata")
    lines.append("")
    lines.append(f"- Generated at: `{datetime.now().isoformat(timespec='seconds')}`")
    lines.append(f"- Replay DB: `{REPLAY_DB_PATH}`")
    lines.append(f"- LLM backend: `{runtime['llm']['backend']}`")
    lines.append(f"- Reset baseline before seeding: `{json.dumps(reset_summary, ensure_ascii=False)}`")
    lines.append(f"- Plain notes saved in corpus DB: `{corpus_summary['plain_note_count']}`")
    lines.append(f"- Embeddings present after run: `{corpus_summary['embedding_count']}`")
    lines.append("")
    lines.append("## Write segment")
    lines.append("")
    lines.append(f"- Write ops: `{write_summary['count']}`")
    lines.append(f"- Logged as write: `{write_summary['kind_ok_count']}/{write_summary['count']}`")
    lines.append(f"- Plain-note rows created: `{write_summary['note_saved_count']}/{write_summary['count']}`")
    lines.append(f"- Embeddings created: `{write_summary['embedding_saved_count']}/{write_summary['count']}`")
    lines.append(f"- Write issues: `{json.dumps(write_summary['reason_counts'], ensure_ascii=False)}`")
    lines.append("")
    lines.append("## Query segment")
    lines.append("")
    lines.append(f"- Query ops: `{query_summary['count']}`")
    lines.append(f"- Stayed queries: `{query_summary['kind_ok_count']}/{query_summary['count']}`")
    lines.append(f"- Token hit on comparable queries: `{query_summary['token_hit_count']}/{query_summary['token_comparable_count']}`")
    lines.append(f"- Query issues: `{json.dumps(query_summary['reason_counts'], ensure_ascii=False)}`")
    lines.append("")
    lines.append("## Query phases")
    lines.append("")
    for phase, info in query_summary["phases"].items():
        lines.append(
            f"- `{phase}`: count `{info['count']}`, kind-pass `{info['kind_ok_count']}/{info['count']}`, token-pass `{info['token_hit_count']}/{info['token_comparable_count']}`, reasons `{json.dumps(info['reason_counts'], ensure_ascii=False)}`, latency `{json.dumps(info['latency'], ensure_ascii=False)}`"
        )
    lines.append("")
    lines.append("## Top failing query cases")
    lines.append("")
    failures = [diag for diag in query_summary["diagnostics"] if diag["reasons"]]
    for diag in failures[:25]:
        lines.append(
            f"- `{diag['query_id']}` `{diag['prompt']}` -> `{diag['actual_kind']}/{diag['actual_tier']}/{diag['actual_rule']}` reasons `{diag['reasons']}`"
        )
    if not failures:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if not SOURCE_DB_PATH.exists():
        print(f"FAIL: source DB not found at {SOURCE_DB_PATH}")
        return 1

    ensure_clean_dir(ARTIFACT_DIR)
    copy_db(SOURCE_DB_PATH, REPLAY_DB_PATH)
    reset_summary = reset_db_for_note_corpus(REPLAY_DB_PATH)
    domains = build_domains()
    domain_map = {domain.key: domain for domain in domains}
    write_specs = build_write_specs(domains)
    query_specs = build_query_specs(domains)
    runner = AppRouteRunner(REPLAY_DB_PATH)

    write_results: list[RouteResult] = []
    query_results: list[RouteResult] = []

    domain_writes: dict[str, list[WriteSpec]] = {}
    for spec in write_specs:
        domain_writes.setdefault(spec.domain_key, []).append(spec)
    immediate_queries = [spec for spec in query_specs if spec.phase == "immediate_after_domain_seed"]
    full_queries = [spec for spec in query_specs if spec.phase == "full_corpus"]
    immediate_query_map = {spec.domain_key: spec for spec in immediate_queries if spec.domain_key}

    for domain in domains:
        for write_spec in domain_writes[domain.key]:
            route, form_data = write_payload(write_spec)
            write_results.append(
                runner.post(
                    route=route,
                    form_data=form_data,
                    op_id=write_spec.write_id,
                    op_type="write",
                    input_text=write_spec.content,
                    domain_key=write_spec.domain_key,
                    method=write_spec.method,
                    category="note_write",
                    burst_tag=write_spec.burst_tag,
                )
            )
        immediate_query = immediate_query_map[domain.key]
        query_results.append(
            runner.post(
                route="/note",
                form_data={"text": immediate_query.prompt},
                op_id=immediate_query.query_id,
                op_type="query",
                input_text=immediate_query.prompt,
                domain_key=immediate_query.domain_key,
                method="home_query",
                category=immediate_query.category,
                burst_tag=domain.key,
            )
        )

    for query_spec in full_queries:
        query_results.append(
            runner.post(
                route="/note",
                form_data={"text": query_spec.prompt},
                op_id=query_spec.query_id,
                op_type="query",
                input_text=query_spec.prompt,
                domain_key=query_spec.domain_key,
                method="home_query",
                category=query_spec.category,
                burst_tag=query_spec.phase,
            )
        )

    runtime = runner.runtime_status()
    corpus_summary = summarize_corpus(REPLAY_DB_PATH)
    write_summary = summarize_writes(write_results, write_specs)
    query_summary = summarize_queries(query_results, query_specs, domain_map)

    payload = {
        "runtime": runtime,
        "reset_summary": reset_summary,
        "corpus_summary": corpus_summary,
        "domains": [asdict(domain) for domain in domains],
        "write_specs": [asdict(spec) for spec in write_specs],
        "query_specs": [asdict(spec) for spec in query_specs],
        "write_results": [asdict(result) for result in write_results],
        "query_results": [asdict(result) for result in query_results],
        "write_summary": write_summary,
        "query_summary": query_summary,
    }
    (ARTIFACT_DIR / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (ARTIFACT_DIR / "write_diagnostics.json").write_text(
        json.dumps(write_summary["diagnostics"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ARTIFACT_DIR / "query_diagnostics.json").write_text(
        json.dumps(query_summary["diagnostics"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csvs(write_results, query_results, write_summary, query_summary)
    (ARTIFACT_DIR / "summary.md").write_text(
        build_summary_md(runtime, reset_summary, corpus_summary, write_summary, query_summary),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "write_count": len(write_results),
                "query_count": len(query_results),
                "artifact_dir": str(ARTIFACT_DIR),
                "reset_summary": reset_summary,
                "corpus_summary": corpus_summary,
                "write_issues": write_summary["reason_counts"],
                "query_issues": query_summary["reason_counts"],
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
