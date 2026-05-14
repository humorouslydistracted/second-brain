from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import re
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent

# DEFAULT_ADAPTER = (
#     APP_DIR
#     / "unsloth_qwen3_parser_run-20260506T070456Z-3-002"
#     / "unsloth_qwen3_parser_run"
#     / "lora_adapter"
# )
DEFAULT_ADAPTER = (
    APP_DIR
    / "unsloth_qwen3_parser_run-20260507T152809Z-3-002"
    / "unsloth_qwen3_parser_run"
    / "lora_adapter"
)
DEFAULT_BASE_MODEL = "unsloth/Qwen3-1.7B-bnb-4bit"
DEFAULT_MAX_SEQ_LENGTH = 1024
DEFAULT_MAX_NEW_TOKENS = 256
DEFAULT_BACKEND = "auto"

SYSTEM_PROMPT = """You are a parser for a tag-first personal data app.
Return JSON only.
Do not add markdown.
Do not add explanations.
Do not add extra keys.
Use null for missing values.
Follow the schema shown by the examples exactly."""


def build_system_prompt(today_iso: str | None) -> str:
    """Return the system prompt, optionally with a `Today: <YYYY-MM-DD>` line.

    v2 training (per docs/model-training.md Section 7) appends a `Today:` line to
    the system prompt and trains the model to use that date as the relative-
    date anchor. At runtime we inject the live current date instead. When
    `today_iso` is None the framing stays byte-identical to the v1 training
    prompt so the current v1 adapter still works without behavioral
    regression.
    """
    if today_iso:
        return f"{SYSTEM_PROMPT}\n\nToday: {today_iso}"
    return SYSTEM_PROMPT

TAGGED_LANES = {"expense", "buy", "todo", "weight", "ledger", "ask"}
WRITE_LANES = {"expense", "buy", "todo", "weight", "ledger"}
WRITE_DISPOSITIONS = {"accept", "confirm", "reject"}
QUERY_DOMAINS = {"note", "expense", "buy", "todo", "weight", "ledger"}
QUERY_INTENTS = {
    # v1 kept for backward compat; v2 adds "list" and "latest"
    "note": {"recent", "search", "latest_bucket", "day_bucket", "list", "latest"},
    "expense": {"total", "list", "compare"},
    "buy": {"list", "search", "latest_day"},
    "todo": {"list", "search", "history"},
    "weight": {"latest", "history", "trend", "change", "latest_all"},
    # v1 kept for backward compat; v2 adds "summary" (replaces open_summary) and "search"
    "ledger": {"balance", "list", "summary", "search", "open_summary", "settled_list", "latest_balance"},
}
# v2 query dispositions (clarify/reject have null intent — validated separately)
QUERY_DISPOSITIONS = {"accept", "clarify", "reject"}
QUERY_FILTER_KEYS = {
    "note": set(),
    "expense": {"group", "description_text", "exclude_group", "exclude_description_text"},
    "buy": {"status", "item_text"},
    "todo": {"status", "text_match"},
    "weight": {"person_text"},
    "ledger": {"person_text", "perspective", "status"},
}
FOLLOWUP_PREFIXES = (
    "of that",
    "of those",
    "of them",
    "only ",
    "just ",
    "apart from",
    "except ",
    "what about",
    "show only",
    "show open",
    "show done",
    "only from",
    "only people",
    "done ones",
    "open ones",
    "andha ",
    "adhula ",
    "mattum",
    "thavira",
    "nethu",
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TAGGED_RE = re.compile(r"^\s*(expense|buy|todo|weight|ledger|ask)\s*:", re.IGNORECASE)


def finetuned_parser_enabled() -> bool:
    return os.environ.get("SECOND_BRAIN_FINETUNED_PARSER_ENABLED", "0").lower() in {"1", "true", "yes"}


def today_injection_enabled() -> bool:
    """Whether `parse()` should inject a live `Today: <YYYY-MM-DD>` line into
    the system prompt.

    Off by default so the current v1 adapter path stays clean. Flip on (set
    SECOND_BRAIN_FINETUNED_PARSER_TODAY_INJECTION=1) once a v2-trained adapter
    is loaded, since v2 training expects the line to be present.
    """
    return os.environ.get("SECOND_BRAIN_FINETUNED_PARSER_TODAY_INJECTION", "0").lower() in {"1", "true", "yes"}


def _resolve_today_iso() -> str:
    return date.today().isoformat()


def detect_tagged_lane(text: str) -> str | None:
    match = TAGGED_RE.match((text or "").strip())
    if not match:
        return None
    return match.group(1).lower()


def should_use_followup_context(text: str) -> bool:
    lane = detect_tagged_lane(text)
    if lane != "ask":
        return False
    _, _, body = (text or "").partition(":")
    body = body.strip().lower()
    if not body:
        return False
    if re.match(r"^(expense|buy|todo|weight|ledger|note)\s*:", body):
        return False
    if len(body.split()) <= 4:
        return True
    return any(body.startswith(prefix) for prefix in FOLLOWUP_PREFIXES)


def build_user_text(prompt: str, context: dict[str, Any] | None) -> str:
    user_text = prompt.strip()
    if context is not None:
        payload = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        user_text = (
            "Previous structured query context:\n"
            f"{payload}\n\n"
            "User input:\n"
            f"{user_text}"
        )
    return user_text


def _record_ms(perf: dict[str, float] | None, key: str, started: float) -> None:
    if perf is None:
        return
    perf[key] = round((time.perf_counter() - started) * 1000.0, 3)


def _resolve_cached_base_model(base_model: str) -> tuple[str, bool]:
    base_path = Path(base_model)
    if base_path.exists():
        return str(base_path), True
    if "/" not in base_model:
        return base_model, False
    repo_dir = (
        Path.home()
        / ".cache"
        / "huggingface"
        / "hub"
        / f"models--{base_model.replace('/', '--')}"
    )
    if not repo_dir.exists():
        return base_model, False
    ref_file = repo_dir / "refs" / "main"
    if ref_file.exists():
        ref_name = ref_file.read_text(encoding="utf-8").strip()
        snapshot_dir = repo_dir / "snapshots" / ref_name
        if snapshot_dir.exists():
            return str(snapshot_dir), True
    snapshot_dirs = sorted(
        (repo_dir / "snapshots").glob("*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for snapshot_dir in snapshot_dirs:
        if snapshot_dir.is_dir():
            return str(snapshot_dir), True
    return base_model, False


@contextlib.contextmanager
def _hide_torchao_for_transformers() -> Any:
    original_find_spec = importlib.util.find_spec
    import_utils = sys.modules.get("transformers.utils.import_utils")
    original_is_package_available = None

    def patched_find_spec(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "torchao" or name.startswith("torchao."):
            return None
        return original_find_spec(name, *args, **kwargs)

    importlib.util.find_spec = patched_find_spec
    try:
        if import_utils is not None:
            original_is_package_available = getattr(import_utils, "_is_package_available", None)
            if original_is_package_available is not None:
                def patched_is_package_available(pkg_name: str, return_version: bool = False) -> tuple[bool, str | None]:
                    if pkg_name == "torchao":
                        return (False, "N/A") if return_version else (False, None)
                    return original_is_package_available(pkg_name, return_version=return_version)

                import_utils._is_package_available = patched_is_package_available
            is_torchao_available = getattr(import_utils, "is_torchao_available", None)
            if is_torchao_available is not None and hasattr(is_torchao_available, "cache_clear"):
                is_torchao_available.cache_clear()
        yield
    finally:
        importlib.util.find_spec = original_find_spec
        if import_utils is not None and original_is_package_available is not None:
            import_utils._is_package_available = original_is_package_available
            is_torchao_available = getattr(import_utils, "is_torchao_available", None)
            if is_torchao_available is not None and hasattr(is_torchao_available, "cache_clear"):
                is_torchao_available.cache_clear()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_date_or_none(value: Any) -> bool:
    return value is None or (isinstance(value, str) and bool(DATE_RE.match(value)))


def _is_text_or_none(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _validate_filters(domain: str, filters: Any) -> str | None:
    if not isinstance(filters, dict):
        return f"{domain} filters must be an object"
    expected = QUERY_FILTER_KEYS[domain]
    actual = set(filters.keys())
    if actual != expected:
        return f"{domain} filters must use keys {sorted(expected)}"
    if domain in {"buy", "todo"}:
        status = filters.get("status")
        if status not in {None, "open", "done"}:
            return f"{domain} status must be open, done, or null"
    if domain == "ledger":
        perspective = filters.get("perspective")
        if perspective not in {None, "i_owe_them", "they_owe_me"}:
            return "ledger perspective must be i_owe_them, they_owe_me, or null"
        status = filters.get("status")
        if status not in {None, "open", "settled"}:
            return "ledger status must be open, settled, or null"
    return None


def _validate_write_payload(payload: dict[str, Any]) -> str | None:
    lane = payload.get("lane")
    disposition = payload.get("disposition")
    records = payload.get("records")
    if lane not in WRITE_LANES:
        return f"unsupported write lane: {lane!r}"
    if disposition not in WRITE_DISPOSITIONS:
        return f"unsupported write disposition: {disposition!r}"
    if payload.get("reason_code") is not None and not isinstance(payload.get("reason_code"), str):
        return "reason_code must be a string or null"
    if not isinstance(records, list):
        return "records must be a list"
    if disposition == "reject":
        if records:
            return "reject outputs must have empty records"
        return None
    if not records:
        return "accept/confirm outputs must contain at least one record"
    for record in records:
        if not isinstance(record, dict):
            return "each record must be an object"
        if lane == "expense":
            if not isinstance(record.get("description"), str) or not record["description"].strip():
                return "expense description must be non-empty"
            if not _is_number(record.get("amount")):
                return "expense amount must be numeric"
            if not _is_date_or_none(record.get("date")):
                return "expense date must be YYYY-MM-DD"
            if not _is_text_or_none(record.get("group")):
                return "expense group must be a string or null"
        elif lane == "buy":
            if not isinstance(record.get("item_text"), str) or not record["item_text"].strip():
                return "buy item_text must be non-empty"
            if not _is_text_or_none(record.get("quantity_text")):
                return "buy quantity_text must be a string or null"
            if not _is_text_or_none(record.get("unit_text")):
                return "buy unit_text must be a string or null"
            if not _is_date_or_none(record.get("date")):
                return "buy date must be YYYY-MM-DD"
        elif lane == "todo":
            if not isinstance(record.get("text"), str) or not record["text"].strip():
                return "todo text must be non-empty"
            if not _is_date_or_none(record.get("date")):
                return "todo date must be YYYY-MM-DD"
        elif lane == "weight":
            if not isinstance(record.get("person_text"), str) or not record["person_text"].strip():
                return "weight person_text must be non-empty"
            if not _is_number(record.get("value")):
                return "weight value must be numeric"
            if record.get("unit") != "kg":
                return "weight unit must be kg"
            if not _is_date_or_none(record.get("date")):
                return "weight date must be YYYY-MM-DD"
            if not _is_text_or_none(record.get("note")):
                return "weight note must be a string or null"
        elif lane == "ledger":
            if not isinstance(record.get("person_text"), str) or not record["person_text"].strip():
                return "ledger person_text must be non-empty"
            if record.get("action") not in {"add_debt", "add_credit", "repay_debt", "collect_credit", "settle"}:
                return f"unsupported ledger action: {record.get('action')!r}"
            amount = record.get("amount")
            if record.get("action") == "settle":
                if amount is not None and not _is_number(amount):
                    return "ledger settle amount must be numeric or null"
            elif not _is_number(amount):
                return "ledger amount must be numeric"
            if not _is_date_or_none(record.get("date")):
                return "ledger date must be YYYY-MM-DD"
            if not _is_text_or_none(record.get("note")):
                return "ledger note must be a string or null"
    return None


def _validate_query_payload(payload: dict[str, Any]) -> str | None:
    task = payload.get("task")
    domain = payload.get("domain")
    intent = payload.get("intent")
    disposition = payload.get("disposition") or "accept"
    if task == "parse_followup_query" and payload.get("inherit_context") is not True:
        return "parse_followup_query must set inherit_context=true"
    if domain not in QUERY_DOMAINS:
        return f"unsupported query domain: {domain!r}"
    # v2: clarify/reject dispositions carry null intent and null filters — validate only their own fields
    if disposition == "reject":
        if payload.get("reason_code") is not None and not isinstance(payload.get("reason_code"), str):
            return "reject reason_code must be a string or null"
        return None
    if disposition == "clarify":
        if payload.get("clarify_reason") is not None and not isinstance(payload.get("clarify_reason"), str):
            return "clarify_reason must be a string or null"
        opts = payload.get("clarify_options")
        if opts is not None and not isinstance(opts, list):
            return "clarify_options must be a list or null"
        return None
    if disposition not in QUERY_DISPOSITIONS:
        return f"unsupported query disposition: {disposition!r}"
    # accept path: validate intent, dates, limit, filters
    if intent not in QUERY_INTENTS[domain]:
        return f"unsupported intent {intent!r} for domain {domain!r}"
    for key in ("date_start", "date_end", "compare_date_start", "compare_date_end"):
        if not _is_date_or_none(payload.get(key)):
            return f"{key} must be YYYY-MM-DD or null"
    if payload.get("limit") is not None:
        if not isinstance(payload.get("limit"), int) or int(payload["limit"]) <= 0:
            return "limit must be a positive integer or null"
    if not _is_text_or_none(payload.get("query_text")):
        return "query_text must be a string or null"
    return _validate_filters(domain, payload.get("filters"))


def validate_parser_payload(payload: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(payload, dict):
        return None, "parser output must be a JSON object"
    task = payload.get("task")
    if task == "parse_write":
        error = _validate_write_payload(payload)
        return (payload if error is None else None), error
    if task in {"parse_query", "parse_followup_query"}:
        error = _validate_query_payload(payload)
        return (payload if error is None else None), error
    return None, f"unsupported parser task: {task!r}"


def summarize_parser_payload(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"task": payload.get("task")}
    if payload.get("task") == "parse_write":
        summary.update(
            {
                "lane": payload.get("lane"),
                "disposition": payload.get("disposition"),
                "reason_code": payload.get("reason_code"),
                "record_count": len(payload.get("records") or []),
            }
        )
        return summary
    summary.update(
        {
            "domain": payload.get("domain"),
            "intent": payload.get("intent"),
            "date_start": payload.get("date_start"),
            "date_end": payload.get("date_end"),
            "limit": payload.get("limit"),
        }
    )
    return summary


class FinetunedParserService:
    def __init__(
        self,
        *,
        adapter_path: str | None = None,
        base_model: str | None = None,
        max_seq_length: int | None = None,
        max_new_tokens: int | None = None,
        backend: str | None = None,
    ) -> None:
        self.adapter_path = Path(adapter_path or os.environ.get("SECOND_BRAIN_FINETUNED_PARSER_ADAPTER") or DEFAULT_ADAPTER)
        self.base_model = base_model or os.environ.get("SECOND_BRAIN_FINETUNED_PARSER_BASE_MODEL") or DEFAULT_BASE_MODEL
        self.max_seq_length = int(
            max_seq_length
            or os.environ.get("SECOND_BRAIN_FINETUNED_PARSER_MAX_SEQ_LENGTH")
            or DEFAULT_MAX_SEQ_LENGTH
        )
        self.max_new_tokens = int(
            max_new_tokens
            or os.environ.get("SECOND_BRAIN_FINETUNED_PARSER_MAX_NEW_TOKENS")
            or DEFAULT_MAX_NEW_TOKENS
        )
        self.backend = str(
            backend
            or os.environ.get("SECOND_BRAIN_FINETUNED_PARSER_BACKEND")
            or DEFAULT_BACKEND
        ).strip().lower()
        self._lock = threading.Lock()
        self._model = None
        self._tokenizer = None
        self._torch = None
        self._load_error: str | None = None
        self._loaded = False
        self._loaded_backend: str | None = None

    def status(self) -> dict[str, Any]:
        return {
            "enabled": finetuned_parser_enabled(),
            "loaded": self._loaded,
            "adapter_path": str(self.adapter_path),
            "base_model": self.base_model,
            "backend": self._loaded_backend or self.backend,
            "load_error": self._load_error,
            "today_injection_enabled": today_injection_enabled(),
        }

    def warm(self, perf: dict[str, float] | None = None) -> dict[str, Any]:
        if not finetuned_parser_enabled():
            return self.status()
        self._load_model(perf=perf)
        return self.status()

    def _load_model(self, perf: dict[str, float] | None = None) -> tuple[Any, Any, Any]:
        if self._loaded and self._model is not None and self._tokenizer is not None and self._torch is not None:
            return self._model, self._tokenizer, self._torch
        started = time.perf_counter()
        with self._lock:
            if self._loaded and self._model is not None and self._tokenizer is not None and self._torch is not None:
                return self._model, self._tokenizer, self._torch
            if not self.adapter_path.exists():
                self._load_error = f"adapter folder not found: {self.adapter_path}"
                raise FileNotFoundError(self._load_error)
            if not (self.adapter_path / "adapter_config.json").exists():
                self._load_error = f"missing adapter_config.json under {self.adapter_path}"
                raise FileNotFoundError(self._load_error)
            errors: list[str] = []
            backends = ["transformers", "unsloth"] if self.backend == "auto" else [self.backend]
            model = None
            tokenizer = None
            torch = None
            loaded_backend = None
            for backend in backends:
                try:
                    if backend == "transformers":
                        model, tokenizer, torch = self._load_transformers_backend()
                    elif backend == "unsloth":
                        model, tokenizer, torch = self._load_unsloth_backend()
                    else:
                        raise ValueError(f"unsupported finetuned parser backend: {backend}")
                    loaded_backend = backend
                    break
                except Exception as exc:
                    errors.append(f"{backend}: {exc}")
            if model is None or tokenizer is None or torch is None or loaded_backend is None:
                self._load_error = "; ".join(errors) if errors else "unknown parser load failure"
                raise RuntimeError(self._load_error)
            self._model = model
            self._tokenizer = tokenizer
            self._torch = torch
            self._load_error = None
            self._loaded = True
            self._loaded_backend = loaded_backend
        _record_ms(perf, "finetuned_parser.load_model_ms", started)
        return self._model, self._tokenizer, self._torch

    def _load_transformers_backend(self) -> tuple[Any, Any, Any]:
        base_model_ref, local_files_only = _resolve_cached_base_model(self.base_model)
        with _hide_torchao_for_transformers():
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

            token = os.environ.get("HF_TOKEN")
            tokenizer = AutoTokenizer.from_pretrained(
                base_model_ref,
                trust_remote_code=True,
                token=token,
                local_files_only=local_files_only,
            )
            model_kwargs: dict[str, Any] = {
                "trust_remote_code": True,
                "token": token,
                "local_files_only": local_files_only,
            }
            if torch.cuda.is_available():
                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_compute_dtype=torch.float16,
                )
                model_kwargs["device_map"] = "auto"
            else:
                model_kwargs["torch_dtype"] = torch.float32
            model = AutoModelForCausalLM.from_pretrained(
                base_model_ref,
                **model_kwargs,
            )
            model = PeftModel.from_pretrained(model, str(self.adapter_path), is_trainable=False)
            model.eval()
            return model, tokenizer, torch

    def _load_unsloth_backend(self) -> tuple[Any, Any, Any]:
        import unsloth  # noqa: F401
        import torch
        from peft import PeftModel
        from unsloth import FastLanguageModel

        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=self.base_model,
            max_seq_length=self.max_seq_length,
            load_in_4bit=True,
            load_in_8bit=False,
            full_finetuning=False,
            token=os.environ.get("HF_TOKEN"),
        )
        model = PeftModel.from_pretrained(model, str(self.adapter_path), is_trainable=False)
        FastLanguageModel.for_inference(model)
        model.eval()
        return model, tokenizer, torch

    def parse(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
        perf: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        model, tokenizer, torch = self._load_model(perf=perf)
        today_iso = _resolve_today_iso() if today_injection_enabled() else None
        messages = [
            {"role": "system", "content": build_system_prompt(today_iso)},
            {"role": "user", "content": build_user_text(prompt, context)},
        ]
        chat_text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        device = "cuda" if torch.cuda.is_available() else "cpu"
        encode_started = time.perf_counter()
        inputs = tokenizer(chat_text, return_tensors="pt").to(device)
        _record_ms(perf, "finetuned_parser.encode_ms", encode_started)
        generate_started = time.perf_counter()
        outputs = model.generate(
            **inputs,
            max_new_tokens=self.max_new_tokens,
            do_sample=False,
        )
        _record_ms(perf, "finetuned_parser.generate_ms", generate_started)
        raw = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True,
        ).strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"finetuned parser returned non-JSON output: {exc}") from exc
        validated, error = validate_parser_payload(parsed)
        if error:
            raise ValueError(f"finetuned parser returned invalid payload: {error}")
        return {
            "raw": raw,
            "parsed": validated,
            "summary": summarize_parser_payload(validated),
            "used_context": bool(context),
        }


_default_service: FinetunedParserService | None = None
_default_lock = threading.Lock()


def get_finetuned_parser_service() -> FinetunedParserService:
    global _default_service
    with _default_lock:
        if _default_service is None:
            _default_service = FinetunedParserService()
        return _default_service


def finetuned_parser_status() -> dict[str, Any]:
    return get_finetuned_parser_service().status()


def warm_finetuned_parser(perf: dict[str, float] | None = None) -> dict[str, Any]:
    return get_finetuned_parser_service().warm(perf=perf)
