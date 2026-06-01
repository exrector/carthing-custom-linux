#!/usr/bin/env python3
"""carthing-mcp · smoke-test (без устройства, без MCP-зависимостей).

Прогоняет ВСЕ read-only инструменты из core.TOOLS и печатает структурированный JSON.
Работает на чистом stdlib — НЕ требует пакета `mcp` и НЕ трогает устройство.

    python smoke_test.py            # читает реальные файлы репозитория
    python smoke_test.py --mock     # канонические данные, репозиторий не нужен
    python smoke_test.py --tool get_git_status
"""

from __future__ import annotations

import argparse
import json
import sys

import core


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="carthing-mcp read-only smoke test")
    ap.add_argument("--mock", action="store_true", help="канонические данные без чтения репо")
    ap.add_argument("--tool", help="запустить только один инструмент по имени")
    ap.add_argument("--root", help="путь к корню репозитория (иначе авто/CARTHING_REPO_ROOT)")
    args = ap.parse_args(argv)

    tools = core.TOOLS
    if args.tool:
        if args.tool not in tools:
            print(f"unknown tool: {args.tool}; available: {', '.join(tools)}", file=sys.stderr)
            return 2
        tools = {args.tool: tools[args.tool]}

    report = {"mode": "mock" if args.mock else "read", "results": {}}
    ok_count = 0
    for name, fn in tools.items():
        try:
            res = fn(root=args.root, mock=args.mock)
        except Exception as exc:  # инструмент не должен валить весь прогон
            res = {"ok": False, "tool": name, "error": f"exception: {exc!r}"}
        report["results"][name] = res
        ok_count += 1 if res.get("ok") else 0

    report["summary"] = {"tools_run": len(tools), "ok": ok_count,
                         "failed": len(tools) - ok_count}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # read-режим: ok, даже если часть инструментов не нашла данные — это не падение теста.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
