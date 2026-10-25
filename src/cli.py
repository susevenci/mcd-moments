"""mcd-moments 命令行入口。"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_client import McpError, McdMcpClient  # noqa: E402
from moments_engine import Order, analyze  # noqa: E402
from html_report import render  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_ORDERS = os.path.join(BASE, "samples", "orders_sample.json")


def load_orders(offline: bool, snapshot: str = ""):
    if not offline:
        try:
            raw = McdMcpClient.from_env().call_tool("order-list")
            if isinstance(raw, dict) and isinstance(raw.get("list"), list):
                items = raw["list"]
            elif isinstance(raw, list):
                items = raw
            else:
                items = []
            orders = [Order.from_raw(o) for o in (items or []) if isinstance(o, dict)]
            if orders:
                return orders, "麦当劳 MCP order-list 实时返回"
            print("[warn] 订单列表为空，回落本地样例", file=sys.stderr)
        except McpError as exc:
            print("[warn] MCP 调用失败，回落本地样例：%s" % exc, file=sys.stderr)
    path = snapshot or SAMPLE_ORDERS
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    raw_list = data.get("list") or data.get("data", {}).get("list") or data
    return [Order.from_raw(o) for o in raw_list if isinstance(o, dict)], \
        "本地脱敏样例 %s" % os.path.basename(path)


def cmd_selfcheck(_a):
    st = McdMcpClient.token_status()
    print("=== 环境自检 ===")
    print("MCD_MCP_TOKEN: %s" % ("已配置" if st["configured"] else "未配置"))
    print("tokenLength  : %d" % st["tokenLength"])
    print("结论：%s" % ("Token 已就绪" if st["configured"] else "未配置 Token，可用 --offline 体验"))
    return 0


def _build(args):
    orders, note = load_orders(args.offline, getattr(args, "snapshot", ""))
    return analyze(orders, top_n=args.top), note


def cmd_stats(args):
    report, note = _build(args)
    if args.json:
        export = report.copy()
        for k in ("firstDate", "lastDate"):
            if export.get(k):
                export[k] = export[k].isoformat()
        print(json.dumps(export, ensure_ascii=False, indent=2, default=str))
        return 0
    print("【麦门周报 · 数据概览】")
    print("订单数：%d 单｜累计 ¥%.1f｜平均单笔 ¥%.1f｜共 %d 件单品" % (
        report["orderCount"], report["totalAmount"], report["avgAmount"], report["totalItems"]))
    print("时间段：%s ~ %s（跨 %d 天）" % (
        report["firstDate"].strftime("%Y-%m-%d") if report["firstDate"] else "-",
        report["lastDate"].strftime("%Y-%m-%d") if report["lastDate"] else "-",
        report["spanDays"]))
    print("时段分布：" + "、".join("%s %d 单" % (k, v) for k, v in report["slots"].items() if v))
    print("常点 TOP：" + "、".join("%s(%d)" % (i["name"], i["count"]) for i in report["topItems"]))
    print("人格标签：" + "、".join(t["name"] for t in report["persona"]))
    print("数据来源：%s" % note)
    return 0


def cmd_build(args):
    report, note = _build(args)
    page = render(report, title=args.title, source_note=note)
    out = args.out
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("已生成：%s（%.1f KB）" % (out, len(page.encode("utf-8")) / 1024))
    print("提示：把这个文件推到 GitHub 并开启 Pages，就是你的在线年报。")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="mcd-moments",
                                description="麦门周报：把吃麦当劳的数据编译成能晒的单文件 HTML 年报")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("selfcheck", help="Token 自检").set_defaults(func=cmd_selfcheck)

    sp = sub.add_parser("stats", help="终端看数据概览")
    sp.add_argument("--offline", action="store_true")
    sp.add_argument("--snapshot", default="")
    sp.add_argument("--top", type=int, default=5)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("build", help="生成单文件 HTML 年报")
    sp.add_argument("--out", default=os.path.join("output", "mcd-moments.html"))
    sp.add_argument("--title", default="我的麦门周报")
    sp.add_argument("--offline", action="store_true")
    sp.add_argument("--snapshot", default="")
    sp.add_argument("--top", type=int, default=5)
    sp.set_defaults(func=cmd_build)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
