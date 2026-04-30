"""
Lazy-loading inference wrapper for the GRPO attacker/defender checkpoints.

Models are loaded from Hugging Face on first use and cached in-process.
A status_callback(msg) is fired at each stage so the UI can show live
"Loading attacker model…" / "Loading defender model…" messages.
"""

from __future__ import annotations

import re
import threading
from typing import Callable, Optional

ATTACKER_REPO = "RapidOrc121/Incident-Response-attacker"
DEFENDER_REPO = "RapidOrc121/Incident-response-defender"

ATTACKS  = ["PHISH", "BRUTEFORCE", "DRIVEBY", "RANSOM", "SQLI", "RCE", "LPE", "SUPPLYCHAIN"]
DEFENSES = ["MFA", "PATCH", "EDR", "BACKUP", "WAF", "LEASTPRIV", "SBOM", "ROTATEKEYS"]

_ATK_RE = re.compile(r"ATTACK:\s*(PHISH|BRUTEFORCE|DRIVEBY|RANSOM|SQLI|RCE|LPE|SUPPLYCHAIN)\b", re.IGNORECASE)
_DEF_RE = re.compile(r"DEFEND:\s*(MFA|PATCH|EDR|BACKUP|WAF|LEASTPRIV|SBOM|ROTATEKEYS)\b",       re.IGNORECASE)

_lock = threading.Lock()
_cache: dict = {}          # keys: "attacker", "defender"
_hf_available: Optional[bool] = None


def _check_hf() -> bool:
    """Return True if transformers+torch are available for inference."""
    global _hf_available
    if _hf_available is not None:
        return _hf_available
    try:
        import torch                        # noqa: F401
        from transformers import pipeline   # noqa: F401
        _hf_available = True
    except ImportError:
        _hf_available = False
    return _hf_available


BASE_MODEL = "unsloth/qwen2.5-0.5b-instruct-unsloth-bnb-4bit"


def _load_model(adapter_repo: str, role: str, cb: Callable[[str], None]):
    """
    Load the base Qwen2.5-0.5B (4-bit) model then apply the LoRA adapter.
    Both repos are PEFT adapter checkpoints — no standalone config.json.
    """
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, pipeline
    from peft import PeftModel
    import torch

    cb(f"Loading base model ({BASE_MODEL})…")
    use_gpu = torch.cuda.is_available()
    bnb_cfg = BitsAndBytesConfig(load_in_4bit=True) if use_gpu else None
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    base = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_cfg,
        device_map="auto" if use_gpu else None,
        torch_dtype=torch.float16 if use_gpu else torch.float32,
        low_cpu_mem_usage=True,
    )
    cb(f"Base model loaded. Applying {role} LoRA adapter from {adapter_repo}…")
    model = PeftModel.from_pretrained(base, adapter_repo)
    model.eval()
    cb(f"{role.capitalize()} adapter merged. Building pipeline…")
    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tok,
        max_new_tokens=48,
        do_sample=True,
        temperature=0.4,
    )
    cb(f"{role.capitalize()} model ready.")
    return pipe


def get_model(role: str, cb: Callable[[str], None]):
    """Return cached pipeline for role ('attacker'|'defender'), loading if needed."""
    with _lock:
        if role not in _cache:
            repo = ATTACKER_REPO if role == "attacker" else DEFENDER_REPO
            _cache[role] = _load_model(repo, role, cb)
        else:
            cb(f"{role.capitalize()} model already loaded.")
    return _cache[role]


def _parse(text: str, role: str) -> str:
    pat = _ATK_RE if role == "attacker" else _DEF_RE
    m = pat.search(text or "")
    return m.group(1).upper() if m else ""


def generate_action(role: str, prompt: str, cb: Callable[[str], None]) -> str:
    """
    Run inference for one role using the GRPO checkpoint.

    Returns the raw action string e.g. "ATTACK: PHISH" or "DEFEND: MFA",
    or "" if the model output could not be parsed.
    """
    if not _check_hf():
        cb("transformers/torch not installed — cannot run model inference.")
        return ""

    pipe = get_model(role, cb)
    cb(f"Running {role} inference…")

    output = pipe(prompt, return_full_text=False)
    raw = output[0]["generated_text"] if output else ""
    action = _parse(raw, role)

    if not action:
        cb(f"Could not parse {role} output: {raw!r:.80}")
    else:
        prefix = "ATTACK" if role == "attacker" else "DEFEND"
        cb(f"Model chose: {prefix}: {action}")
    return f"{'ATTACK' if role == 'attacker' else 'DEFEND'}: {action}" if action else ""
