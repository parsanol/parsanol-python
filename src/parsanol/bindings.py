"""Bindings application — a faithful port of `parsanol::parg::bindings`.

Pipeline: capture collection (BFS over the shaped tree, identical order)
→ preprocessing (table_lookup over embedded table rows) → casting
(Ruby-semantics integer/float/string/boolean casts).
"""

from __future__ import annotations

from typing import Any

from .canonical import ruby_json_float


class BindingsError(Exception):
    pass


def is_leaf(value: Any) -> bool:
    """Capture leaves arrive as {value, line, column, offset, length}."""
    return isinstance(value, dict) and "value" in value


def leaf_scalar(value: Any) -> Any:
    return value["value"] if is_leaf(value) else value


def collect_captures(shape: Any) -> dict[str, list[Any]]:
    """BFS capture collection, identical traversal order to Ruby's queue."""
    found: dict[str, list[Any]] = {}
    queue: list[Any] = [shape]
    while queue:
        node = queue.pop(0)
        if isinstance(node, dict):
            for key, value in node.items():
                found.setdefault(key, []).append(value)
                if not is_leaf(value):
                    queue.append(value)
        elif isinstance(node, list):
            queue.extend(node)
    return found


def to_ruby_string(value: Any) -> str:
    """Ruby `value.to_s` for the JSON values bindings see."""
    value = leaf_scalar(value)
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and math_finite(value):
            return f"{value:.1f}"
        return repr(value)
    if value is None:
        return ""
    return ""


def math_finite(value: float) -> bool:
    import math

    return math.isfinite(value)


def _to_int(text: str) -> int:
    negative = text.startswith("-")
    body = text[1:] if negative else text
    if body.startswith("0x"):
        radix, digits = 16, body[2:]
    elif body.startswith("0b"):
        radix, digits = 2, body[2:]
    elif body.startswith("0o"):
        radix, digits = 8, body[2:]
    else:
        radix, digits = 10, body
    try:
        magnitude = int(digits.replace("_", ""), radix)
    except ValueError as error:
        raise BindingsError(f"cannot cast {text!r} to integer") from error
    return -magnitude if negative else magnitude


def cast_integer(value: Any) -> int:
    value = leaf_scalar(value)
    if isinstance(value, bool):
        raise BindingsError(f"cannot cast {value!r} to integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        result = _to_int(value)
        if not (-(2**63) <= result < 2**63):
            raise BindingsError(f"integer out of i64 range: {text_safe(value)}")
        return result
    raise BindingsError(f"cannot cast {value!r} to integer")


def text_safe(value: str) -> str:
    return value


def cast_float(value: Any) -> float:
    value = leaf_scalar(value)
    if isinstance(value, bool):
        raise BindingsError(f"cannot cast {value!r} to float")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as error:
            raise BindingsError(f"cannot cast {value!r} to float") from error
    raise BindingsError(f"cannot cast {value!r} to float")


def cast(value: Any, kind: str | None) -> Any:
    value = leaf_scalar(value)
    if kind == "integer":
        return cast_integer(value)
    if kind == "float":
        return cast_float(value)
    if kind == "string":
        if isinstance(value, (str, int, float, bool)) or value is None:
            return to_ruby_string(value)
        raise BindingsError(f"cannot cast {value!r} to string")
    if kind == "boolean":
        return value is True or (
            isinstance(value, str) and value.lower() == "true"
        )
    return value


def canonical(value: Any) -> Any:
    """The suite's comparison form: floats render as their B6 text, leaves
    reduce to their scalar."""
    if isinstance(value, float) and not isinstance(value, bool):
        return ruby_json_float(value)
    if isinstance(value, dict):
        if is_leaf(value):
            return canonical(leaf_scalar(value))
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


class Bindings:
    """An entry's binding list with the embedded preprocess tables."""

    def __init__(self, envelope: dict, entry: str):
        self.envelope = envelope
        entry_value = (envelope.get("entries") or {}).get(entry) or {}
        self.list: list[dict] = entry_value.get("bindings") or []

    def _preprocess_steps(self, name: str) -> list[dict]:
        return ((self.envelope.get("preprocess") or {}).get(name)) or []

    def _table_rows(self, name: str) -> list[dict]:
        declared = (self.envelope.get("tables") or {}).get(name)
        if not isinstance(declared, dict):
            raise BindingsError(f"unknown table {name!r}")
        rows = declared.get("rows")
        if not isinstance(rows, list):
            raise BindingsError(f"unknown table {name!r}")
        return rows

    def _preprocess(self, binding: dict, value: Any) -> Any:
        name = binding.get("preprocess")
        if not isinstance(name, str):
            return value
        for step in self._preprocess_steps(name):
            op = step.get("op")
            if op != "table_lookup":
                raise BindingsError(f"unknown preprocess op {op!r}")
            try:
                table = step["table"]
                source = step["from"]
                target = step["to"]
            except KeyError as error:
                raise BindingsError(f"unknown preprocess op {op!r}") from error
            needle = to_ruby_string(value)
            mapped = None
            for row in self._table_rows(table):
                if not isinstance(row, dict):
                    continue
                if to_ruby_string(row.get(source)) == needle:
                    mapped = row.get(target)
                    break
            if mapped is not None:
                value = mapped
        return value

    def _finalize(self, binding: dict, value: Any) -> Any:
        return cast(self._preprocess(binding, value), binding.get("type"))

    @staticmethod
    def _leaf_key(path: str) -> str:
        if "[]" in path:
            return path.rsplit("].", 1)[-1]
        return path

    def _assign_scalar(self, out: dict, binding: dict, captures: dict) -> None:
        capture = binding.get("capture") or ""
        path = binding.get("path") or ""
        if "." in path or "[" in path:
            raise BindingsError(f"nested binding path {path!r} for capture {capture!r}")
        values = captures.get(capture)
        if not values:
            return
        value = values[0]
        if value is None:
            # Ruby `return if value.nil?` (ts#34): the absent-optional
            # wire is null; the key is skipped, never cast to "".
            return
        out[self._leaf_key(path)] = self._finalize(binding, value)

    @staticmethod
    def _group_instances(shape: Any, prefix: str) -> list[Any] | None:
        """The `prefix[]` group's instance subtrees — Ruby's BFS walk."""
        queue: list[Any] = [shape]
        while queue:
            node = queue.pop(0)
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == prefix and isinstance(value, list):
                        return value
                    if isinstance(value, (dict, list)):
                        queue.append(value)
            elif isinstance(node, list):
                queue.extend(node)
        if isinstance(shape, list) and any(isinstance(item, dict) for item in shape):
            return shape
        return None

    def _assign_array(
        self,
        out: dict,
        prefix: str,
        group: list[dict],
        captures: dict,
        shape: Any = None,
    ) -> None:
        # Position-aware pairing (ruby#381): when the shape nests the
        # group's instances under the prefix key (or IS the instance
        # array — a repetition-root entry), each instance's subtree
        # owns its captures. Captures outside any instance keep the
        # legacy occurrence pairing.
        instances = self._group_instances(shape, prefix) if shape is not None else None
        if instances is not None:
            if not instances:
                # rs#370: the occurrence path's `count == 0 → bind
                # nothing` — a zero-iteration repetition (the tree
                # carries `prefix: []`) binds no key.
                return
            list_out: list[dict] = out.setdefault(prefix, [])
            for instance in instances:
                found = collect_captures(instance)
                element: dict = {}
                for binding in group:
                    capture = binding.get("capture") or ""
                    values = found.get(capture)
                    if not values:
                        continue
                    value = values[0]
                    if value is None:
                        continue
                    element[self._leaf_key(binding.get("path") or "")] = self._finalize(
                        binding, value
                    )
                list_out.append(element)
            return
        count = max(
            (len(captures[b.get("capture") or ""]) for b in group if (b.get("capture") or "") in captures),
            default=0,
        )
        if count == 0:
            return
        list_out = []
        for index in range(count):
            element = {}
            for binding in group:
                capture = binding.get("capture") or ""
                values = captures.get(capture)
                if values is None or index >= len(values):
                    continue
                value = values[index]
                if value is None:
                    # Ruby `next if value.nil?`: null slots bind
                    # nothing in their element.
                    continue
                element[self._leaf_key(binding.get("path") or "")] = self._finalize(
                    binding, value
                )
            list_out.append(element)
        out[prefix] = list_out

    def apply(self, shape: Any) -> dict:
        captures = collect_captures(shape)
        scalars: list[dict] = []
        arrays: list[tuple[str, dict]] = []
        for binding in self.list:
            if not isinstance(binding, dict):
                continue
            path = binding.get("path") or ""
            if "[]" in path:
                arrays.append((path.split("[]", 1)[0], binding))
            else:
                scalars.append(binding)

        out: dict = {}
        for binding in scalars:
            self._assign_scalar(out, binding, captures)
        # Ruby groups by prefix while preserving first-seen order.
        order: list[str] = []
        for prefix, _ in arrays:
            if prefix not in order:
                order.append(prefix)
        for prefix in order:
            group = [binding for candidate, binding in arrays if candidate == prefix]
            self._assign_array(out, prefix, group, captures, shape)
        return out
