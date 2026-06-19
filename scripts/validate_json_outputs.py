"""Validate repository JSON artifacts against local schemas.

Uses jsonschema when installed. A small fallback validator covers the schema
features used by this repository so smoke tests can run before the Conda
environment is created.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover
    jsonschema = None

_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
    "null": type(None),
}


def _check_type(value: Any, expected: Any, path: str) -> None:
    if expected is None:
        return
    expected_values = expected if isinstance(expected, list) else [expected]
    ok = False
    for item in expected_values:
        if item == "number" and isinstance(value, bool):
            continue
        if item == "integer" and isinstance(value, bool):
            continue
        if isinstance(value, _TYPE_MAP[item]):
            ok = True
            break
    if not ok:
        raise ValueError(f"{path} expected type {expected_values}, got {type(value).__name__}")


def _fallback_validate(instance: Any, schema: dict[str, Any], path: str = "$") -> None:
    _check_type(instance, schema.get("type"), path)
    if "const" in schema and instance != schema["const"]:
        raise ValueError(f"{path} expected constant {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise ValueError(f"{path} expected one of {schema['enum']}, got {instance!r}")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                raise ValueError(f"{path} missing required key {key}")
        for key, child_schema in schema.get("properties", {}).items():
            if key in instance:
                _fallback_validate(instance[key], child_schema, f"{path}.{key}")
    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            _fallback_validate(item, schema["items"], f"{path}[{index}]")


def validate_file(json_path: str | Path, schema_path: str | Path) -> dict[str, Any]:
    json_path = Path(json_path)
    schema_path = Path(schema_path)
    instance = json.loads(json_path.read_text())
    schema = json.loads(schema_path.read_text())
    if jsonschema is not None:
        jsonschema.validate(instance=instance, schema=schema)
    else:
        _fallback_validate(instance, schema)
    return instance


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a JSON file against a local schema")
    parser.add_argument("json_path")
    parser.add_argument("schema_path")
    args = parser.parse_args()
    validate_file(args.json_path, args.schema_path)
    print(json.dumps({"status": "valid", "json_path": args.json_path, "schema_path": args.schema_path}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
