# MCP_INTEGRATION.md

## 1. 接入方式

| 项目 | 值 |
|---|---|
| MCP Server | `mcd-mcp`（麦当劳中国官方 MCP Server） |
| 传输 | Streamable HTTP，JSON-RPC 2.0（兼容 SSE） |
| Endpoint | `https://mcp.mcd.cn` |
| 鉴权 | `Authorization: Bearer ${MCD_MCP_TOKEN}` |
| 客户端 | `src/mcp_client.py`（纯标准库，节流 300 次/分钟 + 429 退避） |

## 2. Tool 清单

| Tool | 命令 | 关键字段 |
|---|---|---|
| `order-list` | `stats` / `build` | `list[].{orderId, createTime, storeCode, storeName, orderStatus, realTotalAmount, orderProductList[].{productName, quantity, comboItemList[]}}` |
| `query-my-account` | `selfcheck` | 连通性校验 |
| `campaign-calendar` | 扩展点 | 可把"当年新品"并入年报时间轴 |

> **只读**。本项目不调用任何写入型工具。

## 3. 调用流程

```
tools/call order-list
        │
        ▼
Order.from_raw()
   ├─ createTime → datetime（兼容 4 种常见格式）
   ├─ realTotalAmount → 实付金额（float）
   └─ orderProductList → 展开 comboItemList，套餐子项一并计入偏好统计
        │
        ▼
analyze(orders)
   ├─ 金额：总额 / 均值 / 最大单笔
   ├─ 时间：时段分布 / 星期分布 / 跨度天数 / 最早最晚
   ├─ 偏好：单品 TOP N / 去重单品数 / 门店 TOP3
   └─ 人格：规则化标签（每条注明触发口径）
        │
        ▼
html_report.render()  →  单文件 HTML（内联 CSS + 手写 SVG 图表）
```

## 4. 套餐为什么要展开子项

`orderProductList` 里的套餐项带有 `comboItemList`。只统计套餐名的话，"最常点"永远是套餐名，
看不到用户**真实的口味偏好**（比如每次都顺手点了鲜萃冰咖）。因此 `Order.from_raw` 会同时展开子项。

## 5. 为什么坚持"零 CDN、零 JS"

- 生成的 HTML 可以直接双击打开、可以邮件附件发送、可以挂 GitHub Pages；
- 不引入第三方脚本 = 不产生外部请求，符合对隐私敏感的订单数据的处理原则；
- 有单测守住：报告中不得出现 `<script` 与外部资源 URL。

## 6. 业务价值

1. 把沉淀在 App 里的历史订单，变成用户愿意主动分享的内容；
2. 所有统计确定性计算，不依赖模型，结果可复现、可测试；
3. 人格标签带口径说明，避免"AI 给我贴标签"的不可解释感；
4. 为后续扩展留出接口：热量维度（配合 `list-nutrition-foods`）、活动维度（配合 `campaign-calendar`）。

## 7. 配置示例

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": { "Authorization": "Bearer ${MCD_MCP_TOKEN}" }
    }
  }
}
```

仓库内不含任何真实 Token，样例订单数据已脱敏。

## 附：接口实测留痕

本项目在 2026-10-25 对麦当劳 MCP 做过真实调用，完整记录（含当时账号状态、原始输出、复现命令）
见 docs/2026-10-25-实测记录.md。

实测确认的两个关键形态（代码已适配）：
1. 响应统一为 {"success":..,"code":..,"data":<业务数据>} 信封，业务数据在 data 内；
2. structuredContent 与 content[0].text 并存，客户端优先取 structuredContent。
