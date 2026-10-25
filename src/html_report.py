"""单文件 HTML 报告渲染。

约束：
  * 零外部依赖 —— 不引 CDN、不加载外部字体、不联网；
  * 图表用手写 SVG（条形图 / 环形图 / 时间轴）；
  * 生成的 .html 可直接托管到 GitHub Pages，或发给朋友直接双击打开。

配色取用麦当劳品牌常见的红黄组合（仅作视觉呼应，不涉及任何商标使用声明之外的含义）。
"""

from __future__ import annotations

import html
from typing import Dict, List

RED = "#DA291C"
GOLD = "#FFC72C"
INK = "#241f21"
MUTED = "#8a8587"


def _e(text) -> str:
    return html.escape(str(text if text is not None else ""))


def _bars(data: List[Dict], unit: str = "") -> str:
    if not data:
        return "<div class='empty'>暂无数据</div>"
    peak = max((d["value"] for d in data), default=1) or 1
    rows = []
    for d in data:
        pct = d["value"] / peak * 100
        rows.append(
            "<div class='bar-row'>"
            "<span class='bar-label'>%s</span>"
            "<span class='bar-track'><i style='width:%.1f%%'></i></span>"
            "<span class='bar-value'>%s%s</span>"
            "</div>" % (_e(d["label"]), pct, _e(d["value"]), _e(unit)))
    return "".join(rows)


def _donut(data: List[Dict]) -> str:
    total = sum(d["value"] for d in data) or 1
    colors = [RED, GOLD, "#f4795b", "#6fbf73", "#5c8ad4", "#a06cd5", "#e0a83c"]
    circumference = 2 * 3.14159 * 42
    offset = 0.0
    segs = []
    for i, d in enumerate(data):
        if d["value"] <= 0:
            continue
        length = d["value"] / total * circumference
        segs.append(
            "<circle cx='70' cy='70' r='42' fill='none' stroke='%s' stroke-width='18' "
            "stroke-dasharray='%.2f %.2f' stroke-dashoffset='%.2f' "
            "transform='rotate(-90 70 70)'/>"
            % (colors[i % len(colors)], length, circumference - length, -offset))
        offset += length
    return "<svg viewBox='0 0 140 140' width='140' height='140'>%s" \
           "<circle cx='70' cy='70' r='30' fill='#fff'/>" \
           "<text x='70' y='66' text-anchor='middle' font-size='20' font-weight='700' fill='%s'>%d</text>" \
           "<text x='70' y='84' text-anchor='middle' font-size='11' fill='%s'>单</text></svg>" % (
               "".join(segs), INK, int(total), MUTED)


def _tags(tags: List[Dict[str, str]]) -> str:
    return "".join(
        "<span class='tag' title='%s'>%s</span>" % (_e(t.get("reason", "")), _e(t.get("name", "")))
        for t in tags)


def render(report: Dict, title: str = "我的麦门周报", source_note: str = "") -> str:
    first = report.get("firstDate")
    last = report.get("lastDate")
    period = ""
    if first and last:
        period = "%s ~ %s" % (first.strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d"))

    slot_data = [{"label": k, "value": v} for k, v in report.get("slots", {}).items() if v]
    week_data = [{"label": k, "value": v} for k, v in report.get("weekdays", {}).items()]

    top_items = report.get("topItems") or []
    item_rows = "".join(
        "<tr><td>%d</td><td>%s</td><td class='num'>%d 份</td></tr>" % (i + 1, _e(x["name"]), x["count"])
        for i, x in enumerate(top_items)) or "<tr><td colspan='3'>暂无</td></tr>"

    store_rows = "".join(
        "<div class='store'>· %s <em>%d 单</em></div>" % (_e(s["name"]), s["count"])
        for s in (report.get("topStores") or [])) or "<div class='store'>暂无</div>"

    def brief_card(title_text, b):
        if not b:
            return ""
        its = "、".join(b.get("items") or []) or "—"
        return ("<div class='card'><h3>%s</h3><p class='big'>%s</p>"
                "<p class='meta'>%s｜¥%.1f</p><p class='meta'>%s</p></div>"
                % (_e(title_text), _e(b.get("time", "")), _e(b.get("store", "")),
                   b.get("amount", 0), _e(its)))

    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#faf6f1;color:{ink};
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}
.page{{max-width:820px;margin:0 auto;padding:32px 20px 48px}}
.hero{{background:linear-gradient(135deg,{red},#f0503a);color:#fff;border-radius:20px;padding:28px 30px;
box-shadow:0 10px 30px rgba(218,41,28,.18)}}
.hero h1{{margin:0;font-size:26px;letter-spacing:1px}}
.hero p{{margin:8px 0 0;opacity:.9;font-size:13px}}
.gold{{background:{gold};display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;color:{ink};font-weight:700}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}}
.stat{{background:#fff;border-radius:14px;padding:16px 14px;text-align:center;
box-shadow:0 4px 14px rgba(0,0,0,.05)}}
.stat b{{display:block;font-size:22px;color:{red}}}
.stat span{{font-size:12px;color:{muted}}}
.panel{{background:#fff;border-radius:16px;padding:20px 22px;margin-bottom:16px;
box-shadow:0 4px 14px rgba(0,0,0,.05)}}
.panel h2{{margin:0 0 14px;font-size:16px;border-left:4px solid {gold};padding-left:10px}}
.bar-row{{display:flex;align-items:center;gap:10px;margin-bottom:9px;font-size:13px}}
.bar-label{{width:60px;color:{muted}}}
.bar-track{{flex:1;height:12px;background:#f2ece6;border-radius:999px;overflow:hidden}}
.bar-track i{{display:block;height:100%;background:{red};border-radius:999px}}
.bar-value{{width:56px;text-align:right}}
.flex{{display:flex;gap:20px;align-items:center;flex-wrap:wrap}}
.legend{{font-size:13px;line-height:1.9}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
td{{padding:8px 4px;border-bottom:1px dashed #eee}}
.num{{text-align:right;color:{muted}}}
.tag{{display:inline-block;background:#fff4d6;border:1px solid {gold};color:{ink};
border-radius:999px;padding:6px 14px;margin:4px 6px 0 0;font-size:13px}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
.card{{background:#fbf7f2;border:1px dashed #e6d9cc;border-radius:12px;padding:14px}}
.card h3{{margin:0 0 6px;font-size:13px;color:{muted};font-weight:600}}
.card .big{{margin:0;font-size:15px;font-weight:700}}
.card .meta{{margin:4px 0 0;font-size:12px;color:{muted}}}
.store{{font-size:13px;padding:4px 0}}
.store em{{float:right;color:{muted};font-style:normal}}
.empty{{color:{muted};font-size:13px}}
footer{{margin-top:20px;font-size:12px;color:{muted};line-height:1.8}}
@media(max-width:640px){{.grid,.cards{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><div class="page">

<div class="hero">
  <h1>{title}</h1>
  <p>{period}　·　共 {orders} 单　·　{items} 件单品　<span class="gold">{amount} 元</span></p>
</div>

<div class="grid">
  <div class="stat"><b>{orders}</b><span>下单次数</span></div>
  <div class="stat"><b>{amount}</b><span>累计金额(元)</span></div>
  <div class="stat"><b>{avg}</b><span>平均单笔(元)</span></div>
  <div class="stat"><b>{span}</b><span>覆盖天数</span></div>
</div>

<div class="panel"><h2>我属于哪一档</h2>{tags}</div>

<div class="panel"><h2>什么时候在吃</h2>{slot_bars}</div>

<div class="panel"><h2>星期分布</h2><div class="flex">{donut}
  <div class="legend">{legend}</div></div></div>

<div class="panel"><h2>最常点 TOP {topn}</h2><table>{item_rows}</table></div>

<div class="panel"><h2>常去的门店</h2>{store_rows}</div>

<div class="panel"><h2>几个片段</h2><div class="cards">
  {earliest}{latest}{biggest}
</div></div>

<footer>
  数据来源：{source}。本报告由 mcd-moments 自动生成，全部数值来自麦当劳 MCP 只读接口在生成时刻的返回。<br>
  本报告为麦当劳程序员创意开发大赛参赛作品产出，非麦当劳官方产品；内容仅作个人记录与分享用途。
</footer>

</div></body></html>""".format(
        title=_e(title), period=_e(period), orders=report.get("orderCount", 0),
        items=report.get("totalItems", 0), amount=report.get("totalAmount", 0),
        avg=report.get("avgAmount", 0), span=report.get("spanDays", 0),
        tags=_tags(report.get("persona") or []),
        slot_bars=_bars(slot_data, " 单"),
        donut=_donut(week_data),
        legend="".join("%s：%d 单<br>" % (_e(w["label"]), w["value"]) for w in week_data),
        topn=len(top_items), item_rows=item_rows, store_rows=store_rows,
        earliest=brief_card("最早的一单", report.get("earliest")),
        latest=brief_card("最晚的一单", report.get("latest")),
        biggest=brief_card("最大手笔", report.get("biggest")),
        source=_e(source_note or "离线样例数据"),
        ink=INK, red=RED, gold=GOLD, muted=MUTED,
    )
