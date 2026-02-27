#!/usr/bin/env python3
"""
route.py — Intelligent Prompt Router for OpenClaw
Classifies incoming prompts and routes to the optimal model tier.

Architecture:
  Tier 0: Regex pattern matching (0ms)
  Tier 1: Heuristic scoring across 5 dimensions (<1ms)
  Tier 2: LLM classification via qwen3:8b (~1.5s, ambiguous cases only)

Usage:
  python3 route.py --prompt "What is 2+2?"
  python3 route.py --prompt "Summarize this" --file /path/to/doc.txt
  python3 route.py --prompt "Fix the auth bug" --exec --agent main
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error

# ═══════════════════════════════════════════════════════════════
# MODEL REGISTRY
# ═══════════════════════════════════════════════════════════════

MODELS = {
    "local_fast":    "ollama/qwen3:8b",
    "local_primary": "ollama/qwen3.5:35b",
    "local_coder":   "ollama/qwen3-coder:30b",
    "cloud_cheap":   "anthropic/claude-haiku",
    "cloud_smart":   "anthropic/claude-sonnet-4-20250514",
    "cloud_flash":   "google/gemini-2.5-flash",
    "cloud_pro":     "google/gemini-2.5-pro",
}

LOCAL_CONTEXT_LIMIT = 8192  # Hard ceiling — 32GB M4 constraint
CHARS_PER_TOKEN = 4  # Conservative estimate

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OPENCLAW_BIN = os.environ.get(
    "OPENCLAW_BIN",
    os.path.expanduser("~/.npm-global/bin/openclaw"),
)

# ═══════════════════════════════════════════════════════════════
# TIER 0: REGEX PATTERN MATCHING (instant)
# ═══════════════════════════════════════════════════════════════

PRIVACY_PATTERNS = re.compile(
    r"\b(private\s*key|seed\s*phrase|mnemonic|wallet\s*secret|ssn|"
    r"social\s*security|medical\s*record|password|credential|"
    r"api[_\s]?key\s+is|secret\s+token)\b",
    re.IGNORECASE,
)

CODE_PATTERNS = re.compile(
    r"\b(write|fix|debug|refactor|implement|create)\b.*"
    r"\b(code|script|function|class|module|endpoint|api|bug|error|test)\b",
    re.IGNORECASE,
)

WEB_PATTERNS = re.compile(
    r"\b(latest|current|today|right\s+now|live|real[- ]?time|"
    r"price\s+of|what\s+is\s+the\s+price|trending|news|"
    r"search\s+for|look\s+up|find\s+online)\b",
    re.IGNORECASE,
)

SIMPLE_QUESTION = re.compile(
    r"^.{1,50}\?$",
    re.DOTALL,
)


def tier0_route(prompt: str, token_estimate: int) -> str | None:
    """Instant pattern-match routing. Returns model ID or None."""

    # Privacy: ALWAYS local, no exceptions
    if PRIVACY_PATTERNS.search(prompt):
        return MODELS["local_primary"]

    # Long context: must go to cloud (local capped at 8K)
    if token_estimate > LOCAL_CONTEXT_LIMIT:
        return MODELS["cloud_flash"]

    # Code tasks
    if CODE_PATTERNS.search(prompt):
        return MODELS["local_coder"]

    # Web/live data: local models can't browse
    if WEB_PATTERNS.search(prompt):
        return MODELS["cloud_cheap"]

    # Trivial short questions
    stripped = prompt.strip()
    if SIMPLE_QUESTION.match(stripped) and token_estimate < 100:
        return MODELS["local_fast"]

    return None


# ═══════════════════════════════════════════════════════════════
# TIER 1: HEURISTIC SCORING (<1ms)
# ═══════════════════════════════════════════════════════════════

def score_dimensions(prompt: str, token_estimate: int) -> dict:
    """Score prompt across 5 dimensions (0-10 each)."""

    scores = {
        "complexity": 0,
        "token_volume": 0,
        "privacy": 0,
        "web_needed": 0,
        "code_task": 0,
    }

    lower = prompt.lower()
    word_count = len(prompt.split())

    # --- Complexity ---
    complexity_markers = [
        "analyze", "compare", "evaluate", "architect", "design",
        "optimize", "trade-off", "pros and cons", "strategy",
        "plan", "review", "assess", "synthesize", "reasoning",
    ]
    hits = sum(1 for m in complexity_markers if m in lower)
    scores["complexity"] = min(10, hits * 3 + (1 if word_count > 100 else 0) * 2)

    # Sentence count as complexity proxy
    sentences = len(re.findall(r"[.!?]+", prompt))
    if sentences > 5:
        scores["complexity"] = min(10, scores["complexity"] + 2)

    # --- Token Volume ---
    if token_estimate > 100000:
        scores["token_volume"] = 10
    elif token_estimate > 50000:
        scores["token_volume"] = 9
    elif token_estimate > 16000:
        scores["token_volume"] = 8
    elif token_estimate > 8000:
        scores["token_volume"] = 7
    elif token_estimate > 4000:
        scores["token_volume"] = 5
    elif token_estimate > 1000:
        scores["token_volume"] = 3
    else:
        scores["token_volume"] = 1

    # --- Privacy ---
    privacy_terms = [
        "private", "secret", "wallet", "seed", "password",
        "credential", "medical", "health", "ssn", "personal",
        "confidential", "sensitive", "financial", "bank",
    ]
    p_hits = sum(1 for t in privacy_terms if t in lower)
    scores["privacy"] = min(10, p_hits * 3)

    # --- Web Needed ---
    web_terms = [
        "latest", "current", "today", "price", "news",
        "trending", "live", "real-time", "search",
        "look up", "find online", "what happened",
    ]
    w_hits = sum(1 for t in web_terms if t in lower)
    scores["web_needed"] = min(10, w_hits * 3)

    # --- Code Task ---
    code_terms = [
        "code", "script", "function", "class", "bug",
        "error", "debug", "refactor", "implement", "test",
        "compile", "syntax", "runtime", "exception", "api",
        "endpoint", "database", "query", "migration",
    ]
    c_hits = sum(1 for t in code_terms if t in lower)
    scores["code_task"] = min(10, c_hits * 2)

    return scores


def tier1_route(scores: dict) -> tuple[str, float]:
    """Heuristic decision matrix. Returns (model_id, confidence 0-1)."""

    # Privacy override — never leaves the machine
    if scores["privacy"] >= 7:
        return MODELS["local_primary"], 0.95

    # Long context — must go cloud
    if scores["token_volume"] >= 8:
        if scores["token_volume"] >= 9:
            return MODELS["cloud_flash"], 0.90
        return MODELS["cloud_flash"], 0.80

    # Web/live data — local can't browse
    if scores["web_needed"] >= 5:
        return MODELS["cloud_cheap"], 0.85

    # Code-heavy tasks
    if scores["code_task"] >= 5:
        return MODELS["local_coder"], 0.80

    # Complex analysis, fits in local context
    if scores["complexity"] >= 7 and scores["token_volume"] <= 5:
        return MODELS["local_primary"], 0.75

    # Simple tasks
    if scores["complexity"] <= 3 and scores["token_volume"] <= 3:
        return MODELS["local_fast"], 0.70

    # Default: primary local model
    return MODELS["local_primary"], 0.55


# ═══════════════════════════════════════════════════════════════
# TIER 2: LLM CLASSIFIER (ambiguous cases only, ~1.5s)
# ═══════════════════════════════════════════════════════════════

CLASSIFY_PROMPT = """Classify this prompt into exactly ONE category. Reply with ONLY the category name.

Categories:
- SIMPLE: trivial questions, greetings, math, definitions
- CODE: programming, debugging, scripting, DevOps
- ANALYSIS: research, comparison, strategy, deep thinking
- SEARCH: requires current/live data from the internet
- VISION: image analysis or generation
- LONGCTX: requires processing large documents
- PRIVATE: contains sensitive personal/financial data

Prompt: {prompt}

Category:"""

CATEGORY_TO_MODEL = {
    "SIMPLE":  MODELS["local_fast"],
    "CODE":    MODELS["local_coder"],
    "ANALYSIS": MODELS["local_primary"],
    "SEARCH":  MODELS["cloud_cheap"],
    "VISION":  MODELS["cloud_flash"],
    "LONGCTX": MODELS["cloud_flash"],
    "PRIVATE": MODELS["local_primary"],
}


def tier2_classify(prompt: str) -> str | None:
    """Use qwen3:8b to classify ambiguous prompts."""
    payload = {
        "model": "qwen3:8b",
        "prompt": CLASSIFY_PROMPT.format(prompt=prompt[:500]),
        "stream": False,
        "options": {
            "num_ctx": 2048,
            "temperature": 0.1,
            "num_predict": 20,
        },
    }

    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            raw = result.get("response", "").strip().upper()
            # Extract first valid category from response
            for cat in CATEGORY_TO_MODEL:
                if cat in raw:
                    return CATEGORY_TO_MODEL[cat]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        pass

    return None


# ═══════════════════════════════════════════════════════════════
# SATURATION DETECTION
# ═══════════════════════════════════════════════════════════════

def ollama_is_busy() -> bool:
    """Check if Ollama is currently processing a request."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/ps", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            models = data.get("models", [])
            return len(models) > 0
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False


def apply_saturation_check(model: str, scores: dict) -> str:
    """If local model selected but Ollama is busy and task isn't private,
    escalate to cloud to avoid queueing."""
    if not model.startswith("ollama/"):
        return model

    if scores.get("privacy", 0) >= 7:
        return model  # Privacy tasks NEVER leave the machine

    if ollama_is_busy():
        # Escalate to cheapest cloud option
        return MODELS["cloud_cheap"]

    return model


# ═══════════════════════════════════════════════════════════════
# TOKEN ESTIMATION
# ═══════════════════════════════════════════════════════════════

def estimate_tokens(text: str, file_path: str | None = None) -> int:
    """Estimate total token count from prompt + optional file."""
    total = len(text) // CHARS_PER_TOKEN

    if file_path and os.path.isfile(file_path):
        file_size = os.path.getsize(file_path)
        total += file_size // CHARS_PER_TOKEN

    return total


# ═══════════════════════════════════════════════════════════════
# MAIN ROUTER
# ═══════════════════════════════════════════════════════════════

def route(prompt: str, file_path: str | None = None, verbose: bool = False) -> str:
    """Full 3-tier routing pipeline. Returns model ID."""

    token_estimate = estimate_tokens(prompt, file_path)

    # Tier 0: instant pattern match
    t0 = tier0_route(prompt, token_estimate)
    if t0:
        if verbose:
            print(f"[tier0] pattern match → {t0}", file=sys.stderr)
        scores = score_dimensions(prompt, token_estimate)
        return apply_saturation_check(t0, scores)

    # Tier 1: heuristic scoring
    scores = score_dimensions(prompt, token_estimate)
    model, confidence = tier1_route(scores)

    if verbose:
        print(f"[tier1] scores={scores} → {model} (confidence={confidence:.0%})", file=sys.stderr)

    # Tier 2: LLM classifier for low-confidence cases
    if confidence < 0.60:
        t2 = tier2_classify(prompt)
        if t2:
            if verbose:
                print(f"[tier2] llm classify → {t2}", file=sys.stderr)
            model = t2

    return apply_saturation_check(model, scores)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Route prompts to the optimal model tier.",
    )
    parser.add_argument("--prompt", required=True, help="The prompt to classify and route")
    parser.add_argument("--file", default=None, help="Optional file to include (affects token estimate)")
    parser.add_argument("--exec", dest="execute", action="store_true", help="Execute via openclaw CLI after routing")
    parser.add_argument("--agent", default="main", help="Agent ID for --exec mode (default: main)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show routing decision details on stderr")
    parser.add_argument("--json", dest="json_out", action="store_true", help="Output full routing decision as JSON")

    args = parser.parse_args()

    model = route(args.prompt, args.file, verbose=args.verbose)

    if args.json_out:
        token_est = estimate_tokens(args.prompt, args.file)
        scores = score_dimensions(args.prompt, token_est)
        output = {
            "model": model,
            "token_estimate": token_est,
            "scores": scores,
            "is_local": model.startswith("ollama/"),
        }
        print(json.dumps(output, indent=2))
    elif args.execute:
        cmd = [
            OPENCLAW_BIN, "agent",
            "--agent", args.agent,
            "--message", args.prompt,
            "--model", model,
            "--thinking", "off",
        ]
        if args.verbose:
            print(f"[exec] {' '.join(cmd)}", file=sys.stderr)
        os.execvp(cmd[0], cmd)
    else:
        print(model)


if __name__ == "__main__":
    main()
