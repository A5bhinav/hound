"""Shared contracts: schema validation + example fixtures (BRIEF.md 8).

Every module that produces a Case or Trace should call validate_case / validate_trace
before returning, so a contract break fails loudly at the source.
"""
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"
EXAMPLES = ROOT / "examples"

_validators = {}


def _validator(name):
    if name not in _validators:
        schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
        _validators[name] = Draft202012Validator(schema, format_checker=FormatChecker())
    return _validators[name]


def _validate(name, obj):
    errors = sorted(_validator(name).iter_errors(obj), key=lambda e: list(e.path))
    if errors:
        lines = [f"  {'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors[:10]]
        raise ValueError(f"{name} does not match schemas/{name}.schema.json:\n" + "\n".join(lines))
    return obj


def validate_case(obj):
    return _validate("case", obj)


def validate_trace(obj):
    return _validate("trace", obj)


def example(name):
    """Load examples/<name>.json. Use these as stubs until the real module is merged."""
    path = EXAMPLES / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"missing example fixture: {path}")
    return json.loads(path.read_text())
