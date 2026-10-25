"""单元测试：全部离线，不需要 Token。"""

import datetime
import json
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from html_report import render  # noqa: E402
from moments_engine import (Order, OrderItem, analyze, parse_time,  # noqa: E402
                            persona_tags, slot_of)


def mk_order(time_str, items, amount=20.0, store="示例门店"):
    return Order(order_id="T" + time_str, create_time=parse_time(time_str),
                 store_name=store, amount=amount,
                 items=[OrderItem(name=n, quantity=q) for n, q in items])


class ParseTest(unittest.TestCase):
    def test_parse_time_formats(self):
        self.assertEqual(parse_time("2026-07-13 10:28:40").hour, 10)
        self.assertEqual(parse_time("2026-07-13 10:28").minute, 28)
        self.assertIsNone(parse_time(""))
        self.assertIsNone(parse_time("not a date"))

    def test_slot_boundaries(self):
        self.assertEqual(slot_of(datetime.datetime(2026, 1, 1, 7, 0)), "早餐")
        self.assertEqual(slot_of(datetime.datetime(2026, 1, 1, 12, 30)), "午市")
        self.assertEqual(slot_of(datetime.datetime(2026, 1, 1, 15, 0)), "下午茶")
        self.assertEqual(slot_of(datetime.datetime(2026, 1, 1, 19, 0)), "晚餐")
        self.assertEqual(slot_of(datetime.datetime(2026, 1, 1, 23, 30)), "夜宵")
        self.assertEqual(slot_of(datetime.datetime(2026, 1, 1, 2, 0)), "夜宵")

    def test_from_raw_expands_combo(self):
        raw = {"orderProductList": [{
            "productName": "鲜萃有堡两件套", "quantity": 1,
            "comboItemList": [{"name": "芝芝火腿扒堡", "quantity": 1},
                              {"name": "鲜萃冰咖", "quantity": 1}]}]}
        o = Order.from_raw(raw)
        self.assertEqual(len(o.items), 3)
        self.assertEqual([i.name for i in o.items][1], "芝芝火腿扒堡")


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.orders = [
            mk_order("2026-08-01 07:30:00", [("吉士蛋麦满分", 1), ("热豆浆", 1)], 18.9),
            mk_order("2026-08-02 12:15:00", [("板烧鸡腿堡", 1)], 26.0, "示例午市店"),
            mk_order("2026-08-05 23:40:00", [("麦辣鸡腿堡", 2)], 45.0, "夜宵店"),
            mk_order("2026-08-06 23:10:00", [("麦乐鸡", 1)], 15.0, "夜宵店"),
        ]

    def test_basic_stats(self):
        r = analyze(self.orders)
        self.assertEqual(r["orderCount"], 4)
        self.assertAlmostEqual(r["totalAmount"], 104.9, places=1)
        self.assertAlmostEqual(r["avgAmount"], 26.2, places=1)
        # 1+1 + 1 + 2 + 1 = 6（套餐与其子项分别计数）
        self.assertEqual(r["totalItems"], 6)

    def test_slot_distribution(self):
        r = analyze(self.orders)
        self.assertEqual(r["slots"]["夜宵"], 2)
        self.assertEqual(r["slots"]["早餐"], 1)
        self.assertEqual(r["slots"]["午市"], 1)
        self.assertEqual(sum(r["slots"].values()), 4)

    def test_top_items(self):
        r = analyze(self.orders)
        self.assertEqual(r["topItems"][0]["name"], "麦辣鸡腿堡")
        self.assertEqual(r["topItems"][0]["count"], 2)

    def test_store_ranking(self):
        r = analyze(self.orders)
        self.assertEqual(r["topStores"][0]["name"], "夜宵店")
        self.assertEqual(r["topStores"][0]["count"], 2)

    def test_extremes(self):
        r = analyze(self.orders)
        self.assertIn("23:40", r["latest"]["time"])
        self.assertIn("07:30", r["earliest"]["time"])
        self.assertAlmostEqual(r["biggest"]["amount"], 45.0, places=1)

    def test_span_days(self):
        self.assertEqual(analyze(self.orders)["spanDays"], 6)

    def test_empty_orders_safe(self):
        r = analyze([])
        self.assertEqual(r["orderCount"], 0)
        self.assertEqual(r["totalAmount"], 0)
        self.assertEqual(r["persona"][0]["name"], "待解锁")


class PersonaTest(unittest.TestCase):
    def test_night_owl(self):
        slots = {"早餐": 0, "午市": 0, "下午茶": 0, "晚餐": 1, "夜宵": 3}
        tags = persona_tags(slots, {"周六": 0, "周日": 0}, 4, [("A", 3)], 3, 25.0)
        self.assertIn("夜宵常客", [t["name"] for t in tags])

    def test_big_spender(self):
        slots = {"早餐": 1, "午市": 1, "下午茶": 0, "晚餐": 0, "夜宵": 0}
        tags = persona_tags(slots, {"周六": 0, "周日": 0}, 2, [("A", 1)], 3, 50.0)
        self.assertIn("大手笔", [t["name"] for t in tags])

    def test_every_tag_has_reason(self):
        slots = {"早餐": 5, "午市": 5, "下午茶": 1, "晚餐": 3, "夜宵": 2}
        tags = persona_tags(slots, {"周六": 4, "周日": 4}, 16, [("A", 9), ("B", 4)], 14, 32.0)
        self.assertTrue(tags)
        for t in tags:
            self.assertTrue(t.get("reason"))


class ReportTest(unittest.TestCase):
    def test_render_produces_standalone_page(self):
        page = render(analyze([mk_order("2026-08-01 12:00:00", [("板烧鸡腿堡", 1)], 26.0)]))
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertNotIn("http://", page.replace("http://www.w3.org", ""))
        self.assertNotIn("<script", page)

    def test_render_empty_report(self):
        page = render(analyze([]))
        self.assertIn("<!DOCTYPE html>", page)

    def test_escapes_user_text(self):
        orders = [Order(order_id="x", create_time=parse_time("2026-08-01 12:00:00"),
                        store_name="<script>alert(1)</script>", amount=1.0,
                        items=[OrderItem(name="<b>x</b>", quantity=1)])]
        page = render(analyze(orders))
        self.assertNotIn("<script>alert", page)


class SampleDataTest(unittest.TestCase):
    def test_sample_has_no_real_identifiers(self):
        path = os.path.join(BASE, "samples", "orders_sample.json")
        with open(path, "r", encoding="utf-8") as fh:
            blob = fh.read()
        self.assertIn("脱敏", blob)
        for o in json.loads(blob)["list"]:
            self.assertTrue(o["orderId"].startswith("OMASK"))
            self.assertIn("示例", o["storeName"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
