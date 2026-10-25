"""把吃麦当劳这件事，编译成一份能晒的报告。

数据来源全部走 MCP 只读接口（`order-list` 等）。
**隐私底线**：导出到仓库的样例一律脱敏 —— 订单号、门店编码替换为示意值。

分析口径全部确定性计算，不依赖大模型。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# 时段口径
SLOTS: List[Tuple[str, int, int]] = [
    ("早餐", 5, 10),      # 05:00 - 10:00
    ("午市", 10, 14),     # 10:00 - 14:00
    ("下午茶", 14, 17),   # 14:00 - 17:00
    ("晚餐", 17, 21),     # 17:00 - 21:00
    ("夜宵", 21, 29),     # 21:00 - 次日 05:00（用 29 表示跨零点）
]
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def parse_time(text: str) -> Optional[datetime.datetime]:
    if not text:
        return None
    text = str(text).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


@dataclass
class OrderItem:
    name: str
    quantity: int = 1

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "OrderItem":
        return cls(
            name=str(raw.get("productName") or raw.get("name") or "未知单品"),
            quantity=int(_num(raw.get("quantity") or 1)) or 1,
        )


@dataclass
class Order:
    order_id: str
    create_time: Optional[datetime.datetime]
    store_name: str = ""
    store_code: str = ""
    order_status: str = ""
    amount: float = 0.0
    items: List[OrderItem] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "Order":
        # 套餐要拆子项，否则"最常点"里永远只有套餐名看不到真实偏好
        items: List[OrderItem] = []
        for p in (raw.get("orderProductList") or []):
            items.append(OrderItem.from_raw(p))
            for sub in (p.get("comboItemList") or []):
                items.append(OrderItem.from_raw(sub))
        return cls(
            order_id=str(raw.get("orderId") or ""),
            create_time=parse_time(raw.get("createTime", "")),
            store_name=str(raw.get("storeName") or ""),
            store_code=str(raw.get("storeCode") or ""),
            order_status=str(raw.get("orderStatus") or ""),
            amount=_num(raw.get("realTotalAmount")),
            items=items,
            raw=raw,
        )

    @property
    def item_count(self) -> int:
        return sum(i.quantity for i in self.items)


def slot_of(dt: datetime.datetime) -> str:
    hour = dt.hour
    for name, start, end in SLOTS:
        if name == "夜宵":
            if hour >= 21 or hour < 5:
                return name
            continue
        if start <= hour < end:
            return name
    return "其他"


def analyze(orders: List[Order], top_n: int = 5) -> Dict[str, Any]:
    timed = [o for o in orders if o.create_time]
    completed = [o for o in orders if "完成" in o.order_status or not o.order_status]

    total_amount = round(sum(o.amount for o in orders), 2)
    avg_amount = round(total_amount / len(orders), 2) if orders else 0.0

    # 单品排行（含套餐内容）
    item_counter: Dict[str, int] = {}
    for o in orders:
        for it in o.items:
            item_counter[it.name] = item_counter.get(it.name, 0) + it.quantity
    top_items = sorted(item_counter.items(), key=lambda kv: -kv[1])[:top_n]

    # 门店排行
    store_counter: Dict[str, int] = {}
    for o in orders:
        if o.store_name:
            store_counter[o.store_name] = store_counter.get(o.store_name, 0) + 1
    top_stores = sorted(store_counter.items(), key=lambda kv: -kv[1])[:3]

    # 时段分布
    slot_counter: Dict[str, int] = {name: 0 for name, _, _ in SLOTS}
    for o in timed:
        slot_counter[slot_of(o.create_time)] = slot_counter.get(slot_of(o.create_time), 0) + 1

    # 星期分布
    weekday_counter = {w: 0 for w in WEEKDAYS}
    for o in timed:
        weekday_counter[WEEKDAYS[o.create_time.weekday()]] += 1

    # 极值
    earliest = latest = None
    biggest = None
    if timed:
        earliest = min(timed, key=lambda o: o.create_time.hour * 60 + o.create_time.minute)
        latest = max(timed, key=lambda o: o.create_time.hour * 60 + o.create_time.minute)
    if orders:
        biggest = max(orders, key=lambda o: o.amount)

    span_days = 0
    if timed:
        span_days = (max(o.create_time for o in timed).date()
                     - min(o.create_time for o in timed).date()).days + 1

    total_items = sum(o.item_count for o in orders)
    return {
        "orderCount": len(orders),
        "completedCount": len(completed),
        "totalAmount": total_amount,
        "avgAmount": avg_amount,
        "totalItems": total_items,
        "spanDays": span_days,
        "firstDate": min((o.create_time for o in timed), default=None),
        "lastDate": max((o.create_time for o in timed), default=None),
        "topItems": [{"name": k, "count": v} for k, v in top_items],
        "distinctItems": len(item_counter),
        "topStores": [{"name": k, "count": v} for k, v in top_stores],
        "slots": slot_counter,
        "weekdays": weekday_counter,
        "earliest": _order_brief(earliest),
        "latest": _order_brief(latest),
        "biggest": _order_brief(biggest),
        "persona": persona_tags(slot_counter, weekday_counter, len(timed),
                                top_items, len(item_counter), avg_amount),
    }


def _order_brief(o: Optional[Order]) -> Optional[Dict[str, Any]]:
    if not o or not o.create_time:
        return None
    return {
        "time": o.create_time.strftime("%Y-%m-%d %H:%M"),
        "store": o.store_name,
        "amount": o.amount,
        "items": [i.name for i in o.items][:3],
    }


def persona_tags(slots: Dict[str, int], weekdays: Dict[str, int], total: int,
                 top_items: List[Tuple[str, int]], distinct: int, avg: float) -> List[Dict[str, str]]:
    """基于行为打标签。每条标签必须能追溯到具体口径。"""
    tags: List[Dict[str, str]] = []
    if total <= 0:
        return [{"name": "待解锁", "reason": "还没有可分析的订单"}]

    def share(v: int) -> float:
        return v / total

    night = slots.get("夜宵", 0)
    morning = slots.get("早餐", 0)
    weekend = weekdays.get("周六", 0) + weekdays.get("周日", 0)

    if share(night) >= 0.3:
        tags.append({"name": "夜宵常客", "reason": "夜宵时段占 %.0f%%" % (share(night) * 100)})
    if share(morning) >= 0.3:
        tags.append({"name": "早餐党", "reason": "早餐时段占 %.0f%%" % (share(morning) * 100)})
    if share(weekend) >= 0.5:
        tags.append({"name": "周末出动", "reason": "周末下单占 %.0f%%" % (share(weekend) * 100)})
    if top_items:
        lead = top_items[0]
        lead_share = lead[1] / max(1, sum(c for _, c in top_items))
        if lead_share >= 0.4:
            tags.append({"name": "专一星人", "reason": "「%s」在最常点里占 %.0f%%" % (
                lead[0], lead_share * 100)})
    if distinct >= 12:
        tags.append({"name": "菜单探险家", "reason": "尝过 %d 种不同单品" % distinct})
    if avg >= 40:
        tags.append({"name": "大手笔", "reason": "平均单笔 ¥%.1f" % avg})
    elif 0 < avg <= 20:
        tags.append({"name": "精算达人", "reason": "平均单笔仅 ¥%.1f" % avg})
    if total >= 20:
        tags.append({"name": "真正麦门信徒", "reason": "统计期内 %d 单" % total})
    if not tags:
        tags.append({"name": "均衡型选手", "reason": "各时段分布比较均匀"})
    return tags
