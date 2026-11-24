#!/usr/bin/env python3
"""Cobra v2.0 Compiler (cobrac.py) — Phase 5: compiles .cobra to .cobrabc with optional --run."""

import os
import re
import subprocess
import sys
from typing import List


def strip_comments_and_blanks(source: str) -> List[str]:
    no_multi = re.sub(r"##.*?##", "", source, flags=re.DOTALL)
    out_lines: List[str] = []
    for raw_line in no_multi.splitlines():
        in_str = None
        buf: List[str] = []
        i = 0
        while i < len(raw_line):
            ch = raw_line[i]
            if ch in ('"', "'") and (i == 0 or raw_line[i - 1] != "\\"):
                if in_str is None:
                    in_str = ch
                elif in_str == ch:
                    in_str = None
                buf.append(ch)
            elif ch == "#" and in_str is None:
                break
            else:
                buf.append(ch)
            i += 1
        trimmed = "".join(buf).strip()
        if trimmed:
            out_lines.append(trimmed)
    return out_lines


def compile_cobra_file(src_path: str, out_path: str = "program.cobrabc") -> tuple[int, int]:
    with open(src_path, "r", encoding="utf-8") as fp:
        source = fp.read()

    lines = strip_comments_and_blanks(source)
    out_buf: List[str] = [
        "# Cobra v2.0 Compiled Artifact",
        f"# Source: {src_path}",
    ]

    fn_total = 0
    stmt_total = 0

    for line in lines:
        head = line.split(" ", 1)[0]
        if head == "@use":
            stmt_total += 1
            out_buf.append(f"USE {line}")
        elif head == "func":
            fn_total += 1
            out_buf.append(f"FUNC {line}")
        else:
            stmt_total += 1
            out_buf.append(f"STMT {line}")

    with open(out_path, "w", encoding="utf-8") as writer:
        for item in out_buf:
            writer.write(item)
            writer.write("\n")

    return fn_total, stmt_total


def main() -> None:
    args = sys.argv[1:]
    run_after = False
    if "--run" in args:
        run_after = True
        args = [a for a in args if a != "--run"]

    if not args:
        print("Usage: python cobrac.py <source.cobra> [output.cobrabc] [--run]")
        sys.exit(1)

    src_file = args[0]
    if not os.path.exists(src_file):
        print(f"Missing file: {src_file}", file=sys.stderr)
        sys.exit(1)

    out_file = args[1] if len(args) >= 2 else "program.cobrabc"
    fn_total, stmt_total = compile_cobra_file(src_file, out_file)
    print(f"Built {out_file} | Functions: {fn_total} | Statements: {stmt_total}")

    if run_after:
        runtime_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cobra.py")
        completed = subprocess.run([sys.executable, runtime_path, out_file])
        sys.exit(completed.returncode)


if __name__ == "__main__":
    main()