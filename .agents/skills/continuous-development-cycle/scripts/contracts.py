"""Small strict YAML/type helpers shared by policy and checkpoint validation."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

try:
    import yaml
except ImportError as exc:
    raise SystemExit("FAIL: PyYAML is required; install scripts/requirements.txt") from exc


class ContractError(ValueError):
    pass


class StrictLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ContractError("YAML aliases are not supported; write explicit settings")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ContractError("mapping keys must be strings")
            if key in result:
                raise ContractError(f"duplicate YAML key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


StrictLoader.yaml_implicit_resolvers = {
    key: [(tag, regex) for tag, regex in entries if tag != "tag:yaml.org,2002:timestamp"]
    for key, entries in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(path, frontmatter=False):
    text = Path(path).read_text(encoding="utf-8")
    if len(text) > 262144:
        raise ContractError("configuration exceeds 256 KiB")
    if frontmatter:
        match = re.match(r"\A---\n(.*?)\n---(?:\n|\Z)", text, re.S)
        if not match:
            raise ContractError("checkpoint requires YAML frontmatter")
        text = match.group(1)
    try:
        return yaml.load(text, Loader=StrictLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ContractError(f"invalid YAML: {exc}") from exc


def check(value, spec, path="adapter"):
    """Validate strict dictionaries, homogeneous lists, enums and scalar predicates."""
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            raise ContractError(f"{path}: expected mapping")
        missing, unknown = spec.keys() - value.keys(), value.keys() - spec.keys()
        if missing:
            raise ContractError(f"{path}: missing fields: {', '.join(sorted(missing))}")
        if unknown:
            raise ContractError(f"{path}: unknown fields: {', '.join(sorted(unknown))}")
        for name, item in spec.items():
            check(value[name], item, f"{path}.{name}")
    elif isinstance(spec, list):
        if not isinstance(value, list):
            raise ContractError(f"{path}: expected list")
        for index, item in enumerate(value):
            check(item, spec[0], f"{path}[{index}]")
    elif isinstance(spec, tuple):
        if not any(type(value) is type(item) and value == item for item in spec):
            raise ContractError(f"{path}: expected one of {spec}")
    elif isinstance(spec, type):
        if type(value) is not spec:
            raise ContractError(f"{path}: expected {spec.__name__}")
    elif not spec(value):
        raise ContractError(f"{path}: invalid value {value!r}")


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def nullable_text(value):
    return value is None or nonempty(value)


def positive(value):
    return type(value) is int and value > 0


def utc(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
        return "T" in value
    except ValueError:
        return False


def sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is not None


def semver(value):
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ContractError("skill versions must be stable major.minor.patch values")
    return tuple(int(part) for part in value.split("."))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()
