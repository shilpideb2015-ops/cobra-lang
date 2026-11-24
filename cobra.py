#!/usr/bin/env python3
"""Cobra v2.0 Runtime Engine (cobra.py)."""

import csv
import json
import math as py_math
import os
import random
import re
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


class CobraError(Exception):
    def __init__(self, message: str, kind: str = "RuntimeError"):
        super().__init__(message)
        self.kind = kind
        self.message = message


class LoopBreak(Exception):
    pass


class LoopContinue(Exception):
    pass


class ReturnSignal(Exception):
    def __init__(self, value: Any = None):
        self.value = value


ALL_LIBS = {
    "code", "math", "language", "list", "task",
    "file", "sys", "time", "net", "error", "ai", "ui", "data",
}


class CobraList:
    def __init__(self, elem_type: str, items: Optional[List[Any]] = None):
        self.elem_type = elem_type
        self.items: List[Any] = list(items) if items else []

    def _idx(self, one_based: int) -> int:
        if not isinstance(one_based, int) or one_based < 1 or one_based > len(self.items):
            raise CobraError(
                f"1-based index out of range: .num({one_based}) for length {len(self.items)}",
                "IndexError",
            )
        return one_based - 1

    def num(self, i: int) -> Any:
        return self.items[self._idx(i)]

    def list_add(self, val: Any) -> None:
        self.items.append(val)

    def list_insert(self, i: int, val: Any) -> None:
        pos = 0 if i <= 1 else min(len(self.items), i - 1)
        self.items.insert(pos, val)

    def list_remove(self, i: int) -> Any:
        return self.items.pop(self._idx(i))

    def list_sort(self, reverse: bool = False) -> None:
        self.items.sort(reverse=reverse)

    def list_reverse(self) -> None:
        self.items.reverse()

    def list_count(self) -> int:
        return len(self.items)

    def list_find(self, target: Any) -> int:
        for idx, item in enumerate(self.items, start=1):
            if item == target:
                return idx
        return -1

    def math_sum(self) -> float | int:
        return sum(self.items)

    def math_avg(self) -> float:
        if not self.items:
            raise CobraError("Cannot compute average of empty list", "MathError")
        return sum(self.items) / len(self.items)

    def math_min(self) -> Any:
        if not self.items:
            raise CobraError("Cannot compute min of empty list", "MathError")
        return min(self.items)

    def math_max(self) -> Any:
        if not self.items:
            raise CobraError("Cannot compute max of empty list", "MathError")
        return max(self.items)


class CobraMap:
    def __init__(self, data: Optional[Dict[str, Any]] = None):
        self.data: Dict[str, Any] = dict(data) if data else {}

    def map_set(self, key: str, value: Any) -> "CobraMap":
        self.data[str(key)] = value
        return self

    def map_get(self, key: str, default: Any = None) -> Any:
        return self.data.get(str(key), default)


class CobraCounter:
    def __init__(self, initial: int = 0):
        self._val = int(initial)
        self._lock = threading.Lock()

    def task_add(self, delta: int = 1) -> int:
        with self._lock:
            self._val += int(delta)
            return self._val

    def task_get(self) -> int:
        with self._lock:
            return self._val


class CobraChannel:
    def __init__(self, elem_type: str, capacity: int = 100):
        self.elem_type = elem_type
        self.capacity = max(1, int(capacity))
        self._queue: List[Any] = []
        self._cond = threading.Condition()

    def task_send(self, val: Any) -> None:
        with self._cond:
            while len(self._queue) >= self.capacity:
                self._cond.wait()
            self._queue.append(val)
            self._cond.notify_all()

    def task_receive(self) -> Any:
        with self._cond:
            while not self._queue:
                self._cond.wait()
            val = self._queue.pop(0)
            self._cond.notify_all()
            return val


class CobraTaskHandle:
    def __init__(self, fn: Callable[[], Any], name: str = "task"):
        self.name = name
        self.result: Any = None
        self.error: Optional[BaseException] = None
        self._fn = fn

        def _runner():
            try:
                self.result = self._fn()
            except BaseException as exc:
                self.error = exc

        self._thread = threading.Thread(target=_runner, daemon=True)
        self._thread.start()

    def join(self) -> Any:
        self._thread.join()
        if self.error:
            raise CobraError(f"Task '{self.name}' failed: {self.error}", "TaskError")
        return self.result

    def is_done(self) -> bool:
        return not self._thread.is_alive()


class CobraFile:
    def __init__(self, path: str, mode: str = "r"):
        self.path = path
        self.mode = mode
        py_mode = {"r": "r", "w": "w", "a": "a", "rb": "rb", "wb": "wb"}.get(mode, mode)
        self._fp = open(path, py_mode, encoding="utf-8" if "b" not in py_mode else None)

    def file_read_sentence(self) -> str:
        return self._fp.read()

    def file_read_list(self) -> CobraList:
        return CobraList("sentence", [line.rstrip("\r\n") for line in self._fp.readlines()])

    def file_write_sentence(self, text: str, newline: bool = False) -> None:
        self._fp.write(str(text) + ("\n" if newline else ""))

    def file_close(self) -> None:
        if not self._fp.closed:
            self._fp.close()


class CobraStopwatch:
    def __init__(self):
        self._start = time.perf_counter()

    def time_elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000.0


class CobraNetResponse:
    def __init__(self, body: str, status: int = 200):
        self.body = body
        self.status = status

    def net_parse_json(self) -> Any:
        parsed = json.loads(self.body)
        if isinstance(parsed, dict):
            return CobraMap(parsed)
        if isinstance(parsed, list):
            return CobraList("sentence", parsed)
        return parsed


class CobraTable:
    def __init__(self, rows: List[Dict[str, Any]], columns: Optional[List[str]] = None):
        self.rows = rows
        self.columns = columns or (list(rows[0].keys()) if rows else [])

    def data_filter(self, expr_str: str) -> "CobraTable":
        m = re.match(r"^\s*([A-Za-z_]\w*)\s*(==|!=|<=|>=|<|>)\s*(.+?)\s*$", expr_str)
        if not m:
            raise CobraError(f"Unsupported data_filter expression: {expr_str}", "DataError")
        col, op, raw_val = m.groups()
        try:
            rhs = float(raw_val) if "." in raw_val else int(raw_val)
        except ValueError:
            rhs = raw_val.strip('"').strip("'")
        ops = {
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
        }
        out = []
        for r in self.rows:
            lhs = r.get(col)
            try:
                lhs_val = float(lhs) if isinstance(rhs, (int, float)) else lhs
            except (TypeError, ValueError):
                lhs_val = lhs
            if ops[op](lhs_val, rhs):
                out.append(dict(r))
        return CobraTable(out, self.columns)

    def data_sort(self, col: str, order: str = "asc") -> "CobraTable":
        rev = order.lower() == "desc"

        def key_fn(row):
            v = row.get(col, "")
            try:
                return (0, float(v))
            except (TypeError, ValueError):
                return (1, str(v))

        return CobraTable(sorted(self.rows, key=key_fn, reverse=rev), self.columns)

    def data_save_excel(self, path: str) -> str:
        out_path = path if path.endswith(".csv") else path + ".csv"
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.columns)
            writer.writeheader()
            writer.writerows(self.rows)
        return out_path


@dataclass
class CobraFunction:
    name: str
    params: List[str]
    body: List[str]
    closure: Dict[str, Any] = field(default_factory=dict)


def strip_comments(source: str) -> str:
    no_multi = re.sub(r"##.*?##", "", source, flags=re.DOTALL)
    lines = []
    for line in no_multi.splitlines():
        in_str = None
        out = []
        i = 0
        while i < len(line):
            ch = line[i]
            if ch in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
                if in_str is None:
                    in_str = ch
                elif in_str == ch:
                    in_str = None
                out.append(ch)
            elif ch == "#" and in_str is None:
                break
            else:
                out.append(ch)
            i += 1
        lines.append("".join(out))
    return "\n".join(lines)


def split_top_level(text: str, sep: str) -> List[str]:
    parts = []
    buf = []
    depth_paren = 0
    depth_brace = 0
    in_str = None
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in ('"', "'") and (i == 0 or text[i - 1] != "\\"):
            if in_str is None:
                in_str = ch
            elif in_str == ch:
                in_str = None
            buf.append(ch)
        elif in_str is None:
            if ch == "(":
                depth_paren += 1
            elif ch == ")":
                depth_paren -= 1
            elif ch == "{":
                depth_brace += 1
            elif ch == "}":
                depth_brace -= 1
            if depth_paren == 0 and depth_brace == 0 and text[i:i + len(sep)] == sep:
                parts.append("".join(buf).strip())
                buf = []
                i += len(sep)
                continue
            buf.append(ch)
        else:
            buf.append(ch)
        i += 1
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p != ""]


def split_dot_chain(expr: str) -> List[str]:
    steps = []
    buf = []
    depth = 0
    in_str = None
    for i, ch in enumerate(expr):
        if ch in ('"', "'") and (i == 0 or expr[i - 1] != "\\"):
            if in_str is None:
                in_str = ch
            elif in_str == ch:
                in_str = None
            buf.append(ch)
        elif in_str is None:
            if ch == "(":
                depth += 1
                buf.append(ch)
            elif ch == ")":
                depth -= 1
                buf.append(ch)
            elif ch == "." and depth == 0:
                steps.append("".join(buf).strip())
                buf = []
            else:
                buf.append(ch)
        else:
            buf.append(ch)
    if buf:
        steps.append("".join(buf).strip())
    return steps


def group_chain_calls(raw_steps: List[str]) -> Optional[List[Tuple[str, str]]]:
    """
    Combine dotted method prefixes like ['file_write', 'sentence(content)']
    into [('file_write.sentence', 'content')]. Returns None if malformed.
    """
    calls: List[Tuple[str, str]] = []
    prefix_parts: List[str] = []
    for step in raw_steps:
        m = re.match(r"^([A-Za-z_]\w*)\((.*)\)$", step, flags=re.DOTALL)
        if m:
            method_name = ".".join(prefix_parts + [m.group(1)]) if prefix_parts else m.group(1)
            calls.append((method_name, m.group(2)))
            prefix_parts = []
        else:
            if not re.fullmatch(r"[A-Za-z_]\w*", step):
                return None
            prefix_parts.append(step)
    if prefix_parts or not calls:
        return None
    return calls


def is_pure_dot_chain(expr: str) -> bool:
    """True when expr is a pure dot-chain starting with an identifier and ending in a call."""
    steps = split_dot_chain(expr)
    if len(steps) < 2 or not re.fullmatch(r"[A-Za-z_]\w*", steps[0]):
        return False
    return group_chain_calls(steps[1:]) is not None


def is_wrapped_call(expr: str, prefix: str) -> Optional[str]:
    """If expr is `prefix(<inner>)` where the opening `(` closes at len(expr) - 1, return `<inner>`."""
    target = prefix + "("
    if not (expr.startswith(target) and expr.endswith(")")):
        return None
    depth = 0
    in_str = None
    start_paren = len(prefix)
    for i in range(start_paren, len(expr)):
        ch = expr[i]
        if ch in ('"', "'") and (i == 0 or expr[i - 1] != "\\"):
            if in_str is None:
                in_str = ch
            elif in_str == ch:
                in_str = None
        elif in_str is None:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i < len(expr) - 1:
                    return None
    if depth == 0:
        return expr[start_paren + 1:-1]
    return None


def decode_cobra_string(raw_inner: str) -> str:
    escapes = {
        "\\n": "\n",
        "\\r": "\r",
        "\\t": "\t",
        '\\"': '"',
        "\\'": "'",
        "\\\\": "\\",
    }
    out: List[str] = []
    i = 0
    while i < len(raw_inner):
        if raw_inner[i] == "\\" and i + 1 < len(raw_inner):
            pair = raw_inner[i:i + 2]
            if pair in escapes:
                out.append(escapes[pair])
                i += 2
                continue
        out.append(raw_inner[i])
        i += 1
    return "".join(out)


def find_top_level_calls(expr: str) -> List[Tuple[int, int, str]]:
    """Find balanced dotted call spans like 'args.list_count()' or 'lines.num(i).language_trim()'."""
    spans: List[Tuple[int, int, str]] = []
    n = len(expr)
    i = 0
    in_str = None
    while i < n:
        ch = expr[i]
        if ch in ('"', "'") and (i == 0 or expr[i - 1] != "\\"):
            if in_str is None:
                in_str = ch
            elif in_str == ch:
                in_str = None
            i += 1
            continue
        if in_str is None and (ch.isalpha() or ch == "_"):
            start = i
            while i < n and (expr[i].isalnum() or expr[i] == "_"):
                i += 1
            if i < n and expr[i] == ".":
                j = i
                has_call = False
                while j < n:
                    if expr[j] == ".":
                        j += 1
                        while j < n and (expr[j].isalnum() or expr[j] == "_"):
                            j += 1
                        if j < n and expr[j] == "(":
                            depth = 0
                            sub_str = None
                            while j < n:
                                cj = expr[j]
                                if cj in ('"', "'") and (j == 0 or expr[j - 1] != "\\"):
                                    if sub_str is None:
                                        sub_str = cj
                                    elif sub_str == cj:
                                        sub_str = None
                                elif sub_str is None:
                                    if cj == "(":
                                        depth += 1
                                    elif cj == ")":
                                        depth -= 1
                                        if depth == 0:
                                            has_call = True
                                            j += 1
                                            break
                                j += 1
                        else:
                            continue
                    else:
                        break
                if has_call:
                    spans.append((start, j, expr[start:j]))
                    i = j
                    continue
        i += 1
    return spans


def extract_brace_block(lines: List[str], start_idx: int) -> Tuple[List[str], int]:
    brace_depth = 0
    started = False
    block_lines: List[str] = []
    idx = start_idx
    while idx < len(lines):
        line = lines[idx]
        i = 0
        in_str = None
        while i < len(line):
            ch = line[i]
            if ch in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
                if in_str is None:
                    in_str = ch
                elif in_str == ch:
                    in_str = None
            elif in_str is None:
                if ch == "{":
                    brace_depth += 1
                    started = True
                elif ch == "}":
                    brace_depth -= 1
            i += 1
        if not started:
            idx += 1
            continue
        stripped = line.strip()
        if brace_depth == 0 and started:
            if stripped == "}":
                idx += 1
                break
            elif stripped.endswith("}"):
                block_lines.append(stripped[:-1])
                idx += 1
                break
        if stripped == "{":
            idx += 1
            continue
        if stripped.startswith("{") and len(block_lines) == 0:
            stripped = stripped[1:].strip()
        block_lines.append(stripped)
        idx += 1
    return block_lines, idx


class CobraInterpreter:
    def __init__(self, cli_args: Optional[List[str]] = None):
        self.enabled_libs: set[str] = set()
        self.vars: Dict[str, Any] = {}
        self.funcs: Dict[str, CobraFunction] = {}
        self.cli_args = cli_args or []

    def require(self, lib: str):
        if lib not in ALL_LIBS:
            raise CobraError(f"Unknown Cobra library: @{lib}", "ImportError")
        if lib not in self.enabled_libs:
            raise CobraError(
                f"Zero-Trust violation: add '@use {lib}' at the top of your .cobra file.",
                "SecurityError",
            )

    def run_program(self, source: str):
        clean = strip_comments(source)
        lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
        self.execute_block(lines)

    def execute_block(self, lines: List[str]):
        idx = 0
        while idx < len(lines):
            line = lines[idx]

            if line.startswith("@use "):
                lib = line[5:].strip()
                if lib not in ALL_LIBS:
                    raise CobraError(f"Unknown library '{lib}'", "ImportError")
                self.enabled_libs.add(lib)
                idx += 1
                continue

            fn_match = re.match(r"^func\s+([A-Za-z_]\w*)\.is\.\s*\((.*?)\)\s*\{?\s*$", line)
            if fn_match:
                self.require("code")
                fn_name = fn_match.group(1)
                params = [p.strip() for p in fn_match.group(2).strip().split(",") if p.strip()]
                if line.rstrip().endswith("{"):
                    body, next_idx = extract_brace_block(lines[idx:], 0)
                    idx += next_idx
                else:
                    body, idx = extract_brace_block(lines, idx + 1)
                self.funcs[fn_name] = CobraFunction(fn_name, params, body, dict(self.vars))
                continue

            sl_loop = re.match(r"^loop\.(.+?)\.nextln\.(.+)$", line)
            if sl_loop:
                self.require("code")
                stmt_txt = sl_loop.group(1).strip()
                count = int(self.eval_expr(sl_loop.group(2).strip()))
                for _ in range(count):
                    self.execute_block([stmt_txt])
                    print()
                idx += 1
                continue

            blk_loop = re.match(r"^loop\.times\((.+?)\)\s*\{?\s*$", line)
            if blk_loop:
                self.require("code")
                count = int(self.eval_expr(blk_loop.group(1).strip()))
                if line.rstrip().endswith("{"):
                    body, next_idx = extract_brace_block(lines[idx:], 0)
                    idx += next_idx
                else:
                    body, idx = extract_brace_block(lines, idx + 1)
                for _ in range(count):
                    try:
                        self.execute_block(list(body))
                    except LoopContinue:
                        continue
                    except LoopBreak:
                        break
                continue

            for_match = re.match(r"^for\s+([A-Za-z_]\w*)\s+in\s+(.+?)\s*\{?\s*$", line)
            if for_match:
                self.require("code")
                var_name = for_match.group(1)
                col_val = self.eval_expr(for_match.group(2).strip())
                if line.rstrip().endswith("{"):
                    body, next_idx = extract_brace_block(lines[idx:], 0)
                    idx += next_idx
                else:
                    body, idx = extract_brace_block(lines, idx + 1)
                iterable = col_val.items if isinstance(col_val, CobraList) else list(col_val)
                for item in iterable:
                    self.vars[var_name] = item
                    try:
                        self.execute_block(list(body))
                    except LoopContinue:
                        continue
                    except LoopBreak:
                        break
                continue

            while_match = re.match(r"^while\s*\((.+)\)\s*\{?\s*$", line)
            if while_match:
                self.require("code")
                cond_expr = while_match.group(1).strip()
                if line.rstrip().endswith("{"):
                    body, next_idx = extract_brace_block(lines[idx:], 0)
                    idx += next_idx
                else:
                    body, idx = extract_brace_block(lines, idx + 1)
                while bool(self.eval_expr(cond_expr)):
                    try:
                        self.execute_block(list(body))
                    except LoopContinue:
                        continue
                    except LoopBreak:
                        break
                continue

            if_match = re.match(r"^if\s*\((.+)\)\s*\{?\s*$", line)
            if if_match:
                self.require("code")
                branches: List[Tuple[Optional[str], List[str]]] = []
                cond = if_match.group(1).strip()
                if line.rstrip().endswith("{"):
                    body, cur = extract_brace_block(lines[idx:], 0)
                    cur += idx
                else:
                    body, cur = extract_brace_block(lines, idx + 1)
                branches.append((cond, body))
                while cur < len(lines):
                    nxt = lines[cur]
                    elif_m = re.match(r"^elif\s*\((.+)\)\s*\{?\s*$", nxt)
                    else_m = re.match(r"^else\s*\{?\s*$", nxt)
                    if elif_m:
                        e_cond = elif_m.group(1).strip()
                        if nxt.rstrip().endswith("{"):
                            e_body, next_c = extract_brace_block(lines[cur:], 0)
                            cur += next_c
                        else:
                            e_body, cur = extract_brace_block(lines, cur + 1)
                        branches.append((e_cond, e_body))
                    elif else_m:
                        if nxt.rstrip().endswith("{"):
                            el_body, next_c = extract_brace_block(lines[cur:], 0)
                            cur += next_c
                        else:
                            el_body, cur = extract_brace_block(lines, cur + 1)
                        branches.append((None, el_body))
                        break
                    else:
                        break
                idx = cur
                for b_cond, b_body in branches:
                    if b_cond is None or bool(self.eval_expr(b_cond)):
                        self.execute_block(list(b_body))
                        break
                continue

            try_match = re.match(r"^try\s*\{?\s*$", line)
            if try_match:
                self.require("error")
                if line.rstrip().endswith("{"):
                    try_body, cur = extract_brace_block(lines[idx:], 0)
                    cur += idx
                else:
                    try_body, cur = extract_brace_block(lines, idx + 1)
                catch_var = "err"
                catch_body: List[str] = []
                if cur < len(lines):
                    c_match = re.match(r"^catch(?:\s*\(\s*([A-Za-z_]\w*)\s*\))?\s*\{?\s*$", lines[cur])
                    if c_match:
                        if c_match.group(1):
                            catch_var = c_match.group(1)
                        if lines[cur].rstrip().endswith("{"):
                            catch_body, next_c = extract_brace_block(lines[cur:], 0)
                            cur += next_c
                        else:
                            catch_body, cur = extract_brace_block(lines, cur + 1)
                idx = cur
                try:
                    self.execute_block(list(try_body))
                except CobraError as exc:
                    self.vars[catch_var] = exc.message
                    self.execute_block(list(catch_body))
                continue

            self.execute_simple_stmt(line)
            idx += 1

    def execute_simple_stmt(self, stmt: str):
        stmt = stmt.strip()
        if not stmt or stmt in ("{", "}"):
            return
        if stmt == "loop.stop":
            self.require("code")
            raise LoopBreak()
        if stmt == "loop.skip":
            self.require("code")
            raise LoopContinue()
        if stmt.startswith("return"):
            self.require("code")
            m = re.match(r"^return\s*\((.*)\)\s*$", stmt)
            val = self.eval_expr(m.group(1).strip()) if (m and m.group(1).strip()) else None
            raise ReturnSignal(val)

        print_match = re.match(
            r"^(?:from\s+([A-Za-z0-9_;\s]+)\s+)?(?:sys\s+)?print(?:\.([A-Za-z_]\w*))?\((.*)\)(\.nextln)?$",
            stmt,
        )
        if print_match:
            self.require("code")
            libs_str, p_type, args_str, nextln = print_match.groups()
            if libs_str:
                for raw_lib in re.split(r"[;,]", libs_str):
                    if raw_lib.strip():
                        self.require(raw_lib.strip())
            if p_type in ("sentence", "letter"):
                self.require("language")
            elif p_type in ("int", "float"):
                self.require("math")

            if p_type == "int":
                rendered = str(int(self.eval_expr(args_str)))
            elif p_type == "float":
                rendered = str(float(self.eval_expr(args_str)))
            elif p_type in ("sentence", "letter"):
                rendered = str(self.eval_expr(args_str))
            else:
                rendered = "".join(str(self.eval_expr(it)) for it in self._tokenize_print_items(args_str))

            sys.stdout.write(rendered + ("\n" if nextln else ""))
            sys.stdout.flush()
            return

        input_match = re.match(r"^(?:from\s+([A-Za-z0-9_;\s]+)\s+)?input\s*\((.*)\)(\.nextln)?$", stmt)
        if input_match:
            self.require("code")
            libs_str, specs_str, _ = input_match.groups()
            if libs_str:
                for raw_lib in re.split(r"[;,]", libs_str):
                    if raw_lib.strip():
                        self.require(raw_lib.strip())
            specs = [s.strip() for s in specs_str.split(";") if s.strip()]
            raw_line = input()
            tokens = raw_line.strip().split()
            for i, spec in enumerate(specs):
                tm = re.match(r"^(int|float|sentence|letter)\s*\(\s*([A-Za-z_]\w*)\s*\)$", spec)
                if not tm:
                    raise CobraError(f"Invalid input spec: {spec}", "SyntaxError")
                t_kind, var_name = tm.groups()
                raw_val = raw_line.strip() if len(specs) == 1 else (tokens[i] if i < len(tokens) else "")
                if t_kind == "int":
                    self.require("math")
                    self.vars[var_name] = int(raw_val)
                elif t_kind == "float":
                    self.require("math")
                    self.vars[var_name] = float(raw_val)
                else:
                    self.require("language")
                    self.vars[var_name] = str(raw_val)
            return

        comp_m = re.match(r"^([A-Za-z_]\w*)\s*(\+=|-=|\*=|/=|%=)\s*(.+)$", stmt)
        if comp_m:
            self.require("code")
            self.require("math")
            name, op, rhs_expr = comp_m.groups()
            cur_val = self.vars.get(name, 0)
            rhs_val = self.eval_expr(rhs_expr)
            ops = {
                "+=": lambda a, b: a + b,
                "-=": lambda a, b: a - b,
                "*=": lambda a, b: a * b,
                "/=": lambda a, b: a / b,
                "%=": lambda a, b: a % b,
            }
            self.vars[name] = ops[op](cur_val, rhs_val)
            return

        assign_m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", stmt)
        if assign_m and not re.match(r"^[A-Za-z_]\w*\s*==", stmt):
            self.require("code")
            name, rhs_expr = assign_m.groups()
            self.vars[name] = self.eval_expr(rhs_expr)
            return

        self.eval_expr(stmt)

    def _tokenize_print_items(self, text: str) -> List[str]:
        items = []
        buf = []
        depth = 0
        in_str = None
        for i, ch in enumerate(text):
            if ch in ('"', "'") and (i == 0 or text[i - 1] != "\\"):
                if in_str is None:
                    in_str = ch
                elif in_str == ch:
                    in_str = None
                buf.append(ch)
            elif in_str is None:
                if ch in ("(", "{", "["):
                    depth += 1
                    buf.append(ch)
                elif ch in (")", "}", "]"):
                    depth -= 1
                    buf.append(ch)
                elif ch in (" ", ",") and depth == 0:
                    tok = "".join(buf).strip()
                    if tok:
                        items.append(tok)
                    buf = []
                else:
                    buf.append(ch)
            else:
                buf.append(ch)
        tail = "".join(buf).strip()
        if tail:
            items.append(tail)
        return items

    def eval_expr(self, expr: str) -> Any:
        expr = expr.strip()
        if not expr:
            return None

        # Grouped parenthesized expression
        grouped_inner = is_wrapped_call(expr, "")
        if grouped_inner is not None:
            return self.eval_expr(grouped_inner)

        if (expr.startswith('"') and expr.endswith('"')) or (expr.startswith("'") and expr.endswith("'")):
            self.require("language")
            return decode_cobra_string(expr[1:-1])
        if expr == "true":
            self.require("code")
            return True
        if expr == "false":
            self.require("code")
            return False
        if re.fullmatch(r"-?\d+", expr):
            self.require("math")
            return int(expr)
        if re.fullmatch(r"-?\d+\.\d+", expr):
            self.require("math")
            return float(expr)

        # Adjacent space-separated items like "# Source: " src_file
        if '"' in expr or "'" in expr:
            adj_items = self._tokenize_print_items(expr)
            if len(adj_items) > 1:
                self.require("language")
                return "".join(str(self.eval_expr(tok)) for tok in adj_items)

        task_run_m = re.match(r"^task\.run\s*\{(.*)\}$", expr, flags=re.DOTALL)
        if task_run_m:
            self.require("task")
            inner = [ln.strip() for ln in task_run_m.group(1).splitlines() if ln.strip()]
            child = CobraInterpreter(self.cli_args)
            child.enabled_libs = set(self.enabled_libs)
            child.vars = dict(self.vars)
            child.funcs = dict(self.funcs)
            return CobraTaskHandle(lambda: child.execute_block(inner), "task.run")

        run_all_m = re.match(r"^task\.run_all\.\s*\(\s*([^,]+)\s*,\s*([A-Za-z_]\w*)\s*\)$", expr)
        if run_all_m:
            self.require("task")
            workers = self.eval_expr(run_all_m.group(1))
            fn_name = run_all_m.group(2)
            items = workers.items if isinstance(workers, CobraList) else list(workers)
            handles = [
                CobraTaskHandle(lambda arg=w: self.invoke_cobra_func(fn_name, [arg]), f"{fn_name}({w})")
                for w in items
            ]
            return CobraList("task", handles)

        wait_all_m = re.match(r"^task\.wait_all\.\s*\((.+)\)$", expr)
        if wait_all_m:
            self.require("task")
            target = self.eval_expr(wait_all_m.group(1))
            handles = target.items if isinstance(target, CobraList) else [target]
            return [h.join() for h in handles if isinstance(h, CobraTaskHandle)]

        wait_any_m = re.match(r"^task\.wait_any\.\s*\((.+)\)$", expr)
        if wait_any_m:
            self.require("task")
            raw_handles = [self.eval_expr(p) for p in split_top_level(wait_any_m.group(1), ",")]
            while True:
                for h in raw_handles:
                    if isinstance(h, CobraTaskHandle) and h.is_done():
                        return h.join()
                time.sleep(0.005)

        sleep_m = re.match(r"^task_sleep\.time\.ms\((.+)\)$", expr)
        if sleep_m:
            self.require("task")
            time.sleep(float(self.eval_expr(sleep_m.group(1))) / 1000.0)
            return None

        cnt_m = re.match(r"^task\.counter\.int\((.+)\)$", expr)
        if cnt_m:
            self.require("task")
            return CobraCounter(int(self.eval_expr(cnt_m.group(1))))

        ch_m = re.match(r"^task\.channel\.([A-Za-z_]\w*)\((.+)\)$", expr)
        if ch_m:
            self.require("task")
            return CobraChannel(ch_m.group(1), int(self.eval_expr(ch_m.group(2))))

        list_m = re.match(r"^list\.([A-Za-z_]\w*)\((.*)\)$", expr)
        if list_m:
            self.require("list")
            ltype = list_m.group(1)
            raw_items = split_top_level(list_m.group(2), ",") if list_m.group(2).strip() else []
            return CobraList(ltype, [self.eval_expr(x) for x in raw_items])

        if expr == "map.new()":
            self.require("list")
            return CobraMap()

        for w_name, req_lib, fn_conv in [
            ("int", "math", lambda v: int(float(v))),
            ("float", "math", lambda v: float(v)),
            ("sentence", "language", lambda v: str(v)),
            ("letter", "language", lambda v: str(v)[0] if str(v) else ""),
            ("bool", "code", lambda v: bool(v)),
        ]:
            inner_conv = is_wrapped_call(expr, w_name)
            if inner_conv is not None:
                self.require(req_lib)
                return fn_conv(self.eval_expr(inner_conv))

        is_call_m = re.match(r"^([A-Za-z_]\w*)\.is\.(?:([A-Za-z_]\w*)\s*)?\((.*)\)$", expr)
        if is_call_m:
            self.require("code")
            fn_name, _ret, arg_str = is_call_m.groups()
            args = [self.eval_expr(a) for a in split_top_level(arg_str, ",")] if arg_str.strip() else []
            return self.invoke_cobra_func(fn_name, args)

        if expr.startswith("math.") and is_pure_dot_chain(expr):
            self.require("math")
            m = re.match(r"^math\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\((.*)\)$", expr)
            op, arg_str = m.groups()
            args = [self.eval_expr(a) for a in split_top_level(arg_str, ",")] if arg_str.strip() else []
            if op == "root":
                return py_math.sqrt(args[0])
            if op == "nroot":
                return args[0] ** (1.0 / args[1])
            if op == "power":
                return args[0] ** args[1]
            if op == "abs":
                return abs(args[0])
            if op == "round":
                return round(args[0])
            if op == "random.int":
                return random.randint(int(args[0]), int(args[1]))

        if expr.startswith("file.") and is_pure_dot_chain(expr):
            self.require("file")
            m = re.match(r"^file\.([A-Za-z_]\w*)\((.*)\)$", expr)
            op, arg_str = m.groups()
            args = [self.eval_expr(a) for a in split_top_level(arg_str, ",")] if arg_str.strip() else []
            if op == "open":
                return CobraFile(str(args[0]), str(args[1]) if len(args) > 1 else "r")
            if op == "exists":
                return os.path.exists(str(args[0]))

        if expr.startswith("sys.") and is_pure_dot_chain(expr):
            self.require("sys")
            if expr == "sys.args.list()":
                return CobraList("sentence", list(self.cli_args))
            if expr == "sys.os.sentence()":
                return sys.platform
            m_env = re.match(r"^sys\.env\.sentence\((.+)\)$", expr)
            if m_env:
                return os.environ.get(str(self.eval_expr(m_env.group(1))), "")
            m_exec = re.match(r"^sys\.exec\.int\((.+)\)$", expr)
            if m_exec:
                return os.system(str(self.eval_expr(m_exec.group(1))))
            m_exit = re.match(r"^sys\.exit\.int\((.+)\)$", expr)
            if m_exit:
                sys.exit(int(self.eval_expr(m_exit.group(1))))

        if expr.startswith("time.") and is_pure_dot_chain(expr):
            self.require("time")
            if expr == "time.now.int()":
                return int(time.time())
            m_date = re.match(r"^time\.date\.sentence\((.*)\)$", expr)
            if m_date:
                fmt = str(self.eval_expr(m_date.group(1))) if m_date.group(1).strip() else "%Y-%m-%d"
                fmt = fmt.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
                return time.strftime(fmt)
            if expr == "time.stopwatch.start()":
                return CobraStopwatch()

        if expr.startswith("net.") and is_pure_dot_chain(expr):
            self.require("net")
            m_get = re.match(r"^net\.get\.sentence\((.+)\)$", expr)
            if m_get:
                url = str(self.eval_expr(m_get.group(1)))
                with urllib.request.urlopen(url, timeout=10) as resp:
                    return CobraNetResponse(resp.read().decode("utf-8"), resp.status)
            m_post = re.match(r"^net\.post\.sentence\((.+),(.+)\)$", expr)
            if m_post:
                url = str(self.eval_expr(m_post.group(1)))
                body_obj = self.eval_expr(m_post.group(2))
                payload = json.dumps(body_obj.data if isinstance(body_obj, CobraMap) else body_obj).encode("utf-8")
                req = urllib.request.Request(
                    url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return CobraNetResponse(resp.read().decode("utf-8"), resp.status)
            m_dl = re.match(r"^net\.download\((.+),(.+)\)$", expr)
            if m_dl:
                url = str(self.eval_expr(m_dl.group(1)))
                dest = str(self.eval_expr(m_dl.group(2)))
                urllib.request.urlretrieve(url, dest)
                return dest

        if expr.startswith("error.") and is_pure_dot_chain(expr):
            self.require("error")
            m_throw = re.match(r"^error\.throw\((.+)\)$", expr)
            if m_throw:
                raise CobraError(str(self.eval_expr(m_throw.group(1))), "UserError")
            m_chk = re.match(r"^error\.check\((.+),(.+)\)$", expr)
            if m_chk:
                if not bool(self.eval_expr(m_chk.group(1))):
                    raise CobraError(str(self.eval_expr(m_chk.group(2))), "AssertionError")
                return True

        if expr.startswith("ai.") and is_pure_dot_chain(expr):
            self.require("ai")
            m_ask = re.match(r"^ai\.ask\.sentence\((.+)\)$", expr)
            if m_ask:
                return f"[Cobra AI] {self.eval_expr(m_ask.group(1))}"
            m_sum = re.match(r"^ai\.summarize\.sentence\((.+)\)$", expr)
            if m_sum:
                txt = str(self.eval_expr(m_sum.group(1)))
                return txt[:120] + ("..." if len(txt) > 120 else "")
            m_cls = re.match(r"^ai\.classify\.sentence\((.+),(.+)\)$", expr)
            if m_cls:
                labels = self.eval_expr(m_cls.group(2))
                return labels.items[0] if isinstance(labels, CobraList) and labels.items else "general"

        if expr.startswith("ui.") and is_pure_dot_chain(expr):
            self.require("ui")
            m_win = re.match(r"^ui\.window\.sentence\((.+)\)$", expr)
            if m_win:
                return CobraMap({"title": str(self.eval_expr(m_win.group(1))), "widgets": []})

        if expr.startswith("data.") and is_pure_dot_chain(expr):
            self.require("data")
            m_csv = re.match(r"^data\.load_csv\((.+)\)$", expr)
            if m_csv:
                with open(str(self.eval_expr(m_csv.group(1))), "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    return CobraTable([dict(r) for r in reader], reader.fieldnames or [])

        # Pure dot-chain evaluation (e.g., lines.num(i).language_trim(), reader.file_read.list())
        if is_pure_dot_chain(expr):
            steps = split_dot_chain(expr)
            root_name = steps[0]
            calls = group_chain_calls(steps[1:])
            if root_name in self.vars and calls is not None:
                cur_val = self.vars[root_name]
                for m_name, m_args_str in calls:
                    m_args = (
                        [self.eval_expr(a) for a in split_top_level(m_args_str, ",")]
                        if m_args_str.strip()
                        else []
                    )
                    cur_val = self._apply_method_to_obj(cur_val, m_name, m_args)
                return cur_val

        # Logical / comparison / arithmetic expressions (with nested call resolution)
        if re.search(r"\b(and|or|not)\b|==|!=|<=|>=|<|>|\*\*|\+|-|\*|/|%|<<|>>", expr):
            if any(
                tok in expr for tok in ("+", "-", "*", "/", "%", "**", "<<", ">>", "==", "!=", "<", ">", "<=", ">=")
            ):
                self.require("math")
            if re.search(r"\b(and|or|not)\b", expr):
                self.require("code")

            safe_ns = {
                k: v for k, v in self.vars.items()
                if not isinstance(v, (CobraFile, CobraTaskHandle))
            }

            resolved_expr = expr
            spans = find_top_level_calls(expr)
            for idx_c, (start, end, call_str) in enumerate(reversed(spans)):
                val = self.eval_expr(call_str)
                placeholder = f"__cobra_val_{idx_c}"
                safe_ns[placeholder] = val
                resolved_expr = resolved_expr[:start] + placeholder + resolved_expr[end:]

            return eval(resolved_expr, {"__builtins__": {}}, safe_ns)

        if expr in self.vars:
            return self.vars[expr]

        raise CobraError(f"Unknown symbol or expression: {expr}", "NameError")

    def invoke_cobra_func(self, fn_name: str, args: List[Any]) -> Any:
        if fn_name not in self.funcs:
            raise CobraError(f"Undefined function: {fn_name}", "NameError")
        fn = self.funcs[fn_name]
        saved = dict(self.vars)
        self.vars.update(fn.closure)
        for p_name, p_val in zip(fn.params, args):
            self.vars[p_name] = p_val
        try:
            self.execute_block(list(fn.body))
        except ReturnSignal as ret:
            return ret.value
        finally:
            for k, v in list(self.vars.items()):
                if k not in fn.params and k not in saved:
                    saved[k] = v
            self.vars = saved
        return None

    def _apply_method_to_obj(self, obj: Any, method: str, args: List[Any]) -> Any:
        if isinstance(obj, str):
            self.require("language")
            if method == "language_count":
                return len(obj)
            if method == "num":
                idx = int(args[0])
                if idx < 1 or idx > len(obj):
                    raise CobraError(f"Index .num({idx}) out of bounds", "IndexError")
                return obj[idx - 1]
            if method == "language_upper":
                return obj.upper()
            if method == "language_lower":
                return obj.lower()
            if method == "language_trim":
                return obj.strip()
            if method == "language_split":
                return CobraList("sentence", obj.split(str(args[0])))
            if method == "language_replace":
                return obj.replace(str(args[0]), str(args[1]))
            if method == "math_to_int":
                self.require("math")
                return int(obj)
            if method == "math_to_float":
                self.require("math")
                return float(obj)

        if isinstance(obj, (int, float)):
            if method == "language_to_sentence":
                self.require("language")
                return str(obj)
            if method == "math_round":
                self.require("math")
                return round(obj)

        if isinstance(obj, CobraList):
            self.require("list")
            if method == "num":
                return obj.num(int(args[0]))
            if method.startswith("list_add"):
                obj.list_add(args[0])
                return None
            if method == "list_insert":
                obj.list_insert(int(args[0]), args[1])
                return None
            if method == "list_remove":
                return obj.list_remove(int(args[0]))
            if method == "list_sort":
                obj.list_sort(bool(args[0]) if args else False)
                return None
            if method == "list_reverse":
                obj.list_reverse()
                return None
            if method == "list_count":
                return obj.list_count()
            if method == "list_find":
                return obj.list_find(args[0])
            if method in ("math_sum", "math_avg", "math_min", "math_max"):
                self.require("math")
                return getattr(obj, method)()

        if isinstance(obj, CobraMap):
            if method == "map_set":
                self.require("list")
                return obj.map_set(args[0], args[1])
            if method == "map_get":
                self.require("list")
                return obj.map_get(args[0], args[1] if len(args) > 1 else None)
            if method == "ui_input.sentence":
                self.require("ui")
                obj.data["widgets"].append(("input", args[0]))
                return obj
            if method == "ui_button.sentence":
                self.require("ui")
                obj.data["widgets"].append(("button", args[0], args[1] if len(args) > 1 else None))
                return obj
            if method == "ui_show":
                self.require("ui")
                print(f"[UI Window '{obj.data.get('title')}'] {obj.data.get('widgets')}")
                return None

        if isinstance(obj, CobraCounter):
            self.require("task")
            if method.startswith("task_add"):
                return obj.task_add(int(args[0]) if args else 1)
            if method.startswith("task_get"):
                return obj.task_get()

        if isinstance(obj, CobraChannel):
            self.require("task")
            if method.startswith("task_send"):
                obj.task_send(args[0])
                return None
            if method.startswith("task_receive"):
                return obj.task_receive()

        if isinstance(obj, CobraFile):
            self.require("file")
            if method == "file_read.sentence":
                return obj.file_read_sentence()
            if method == "file_read.list":
                return obj.file_read_list()
            if method == "file_write.sentence":
                obj.file_write_sentence(args[0], newline=False)
                return None
            if method == "file_close":
                obj.file_close()
                return None

        if isinstance(obj, CobraStopwatch):
            self.require("time")
            if method == "time_elapsed.ms":
                return obj.time_elapsed_ms()

        if isinstance(obj, CobraNetResponse):
            self.require("net")
            if method == "net_parse_json":
                return obj.net_parse_json()

        if isinstance(obj, CobraTable):
            self.require("data")
            if method == "data_filter":
                return obj.data_filter(str(args[0]))
            if method == "data_sort":
                return obj.data_sort(str(args[0]), str(args[1]) if len(args) > 1 else "asc")
            if method == "data_save_excel":
                return obj.data_save_excel(str(args[0]))

        raise CobraError(f"Unknown method '{method}'", "AttributeError")


def load_cobrabc_source(cobrabc_path: str) -> str:
    extracted: List[str] = []
    with open(cobrabc_path, "r", encoding="utf-8") as fp:
        for raw in fp:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            for prefix in ("USE ", "FUNC ", "STMT "):
                if line.startswith(prefix):
                    extracted.append(line[len(prefix):].strip())
                    break
    return "\n".join(extracted)


def main():
    if len(sys.argv) < 2:
        print("Cobra v2.0 Runtime — Usage: python cobra.py <file.cobra | file.cobrabc> [args...]")
        sys.exit(1)
    target = sys.argv[1]
    if not os.path.exists(target):
        print(f"File not found: {target}")
        sys.exit(1)
    if target.endswith(".cobrabc"):
        code_text = load_cobrabc_source(target)
    else:
        with open(target, "r", encoding="utf-8") as f:
            code_text = f.read()
    interp = CobraInterpreter(cli_args=sys.argv[2:])
    try:
        interp.run_program(code_text)
    except CobraError as e:
        print(f"[{e.kind}] {e.message}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()