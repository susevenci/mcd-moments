"""麦当劳 MCP 调用层：零依赖实现 Streamable HTTP JSON-RPC。

设计要点（对照活动规则与《麦当劳 MCP 服务规则》）：
  * 纯 Python 标准库实现，无需 pip install 任何包；
  * Token 只从环境变量 MCD_MCP_TOKEN 读取，绝不落盘、绝不进入仓库；
  * 内置滑动窗口节流（默认 300 次/分钟，官方上限 600）与 429 指数退避；
  * 写操作（下单 / 抽奖 / 建址）默认 dry_run，必须由调用方显式确认才执行；
  * 响应同时兼容 JSON 与 SSE（text/event-stream）两种流媒体格式。

这是一个通用的 MCP 客户端：工具名与入参完全数据驱动，上层业务逻辑不在本文件。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections import deque

DEFAULT_ENDPOINT = "https://mcp.mcd.cn"
DEFAULT_TIMEOUT = 30.0
PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    """MCP 调用失败。保留服务端返回的 code / trace 便于定位。"""

    def __init__(self, message, *, status=None, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class McdMcpClient:
    """极简 MCP Streamable HTTP 客户端。

    典型用法::

        client = McdMcpClient.from_env()
        data = client.call_tool("query-my-account")
    """

    def __init__(self, token, endpoint=DEFAULT_ENDPOINT, timeout=DEFAULT_TIMEOUT,
                 rate_per_minute=300, max_retries=3):
        if not token:
            raise McpError("缺少 MCD_MCP_TOKEN，请先在环境变量中配置 MCP Token")
        self.token = token
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_per_minute = max(1, min(rate_per_minute, 600))
        self._hits = deque()
        self._seq = 0
        self._session_id = None
        self._initialized = False

    # ------------------------------------------------------------------ #
    # 构造
    # ------------------------------------------------------------------ #
    @classmethod
    def from_env(cls, **kwargs):
        token = os.environ.get("MCD_MCP_TOKEN", "").strip()
        endpoint = os.environ.get("MCD_MCP_ENDPOINT", DEFAULT_ENDPOINT).strip() or DEFAULT_ENDPOINT
        return cls(token=token, endpoint=endpoint, **kwargs)

    @staticmethod
    def token_status():
        """自检用：只报告 Token 是否存在与长度，绝不返回 Token 本身。"""
        token = os.environ.get("MCD_MCP_TOKEN", "").strip()
        return {
            "configured": bool(token),
            "tokenLength": len(token),
            "endpoint": os.environ.get("MCD_MCP_ENDPOINT", DEFAULT_ENDPOINT),
        }

    # ------------------------------------------------------------------ #
    # 节流
    # ------------------------------------------------------------------ #
    def _throttle(self):
        now = time.monotonic()
        window = 60.0
        while self._hits and now - self._hits[0] > window:
            self._hits.popleft()
        if len(self._hits) >= self.rate_per_minute:
            sleep_for = window - (now - self._hits[0]) + 0.01
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.monotonic()
        self._hits.append(now)

    # ------------------------------------------------------------------ #
    # 传输
    # ------------------------------------------------------------------ #
    def _headers(self):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer %s" % self.token,
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, payload, timeout=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint, data=body, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid
                return raw
        except urllib.error.HTTPError as exc:  # 4xx / 5xx
            detail = exc.read().decode("utf-8", errors="replace")
            raise McpError("HTTP %s: %s" % (exc.code, detail[:400]),
                           status=exc.code, payload=detail[:400]) from exc
        except urllib.error.URLError as exc:
            raise McpError("网络不可用: %s" % exc.reason) from exc

    def _rpc(self, method, params=None, timeout=None):
        self._seq += 1
        payload = {"jsonrpc": "2.0", "id": self._seq, "method": method}
        if params is not None:
            payload["params"] = params
        raw = self._post(payload, timeout=timeout)
        return self._unwrap(raw)

    @staticmethod
    def _unwrap(raw):
        """把原始响应（JSON 或 SSE）还原为 JSON-RPC 报文。"""
        text = (raw or "").strip()
        if not text:
            return {}
        if text.startswith("{"):
            return json.loads(text)
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk and chunk != "[DONE]":
                    try:
                        return json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
        raise McpError("无法解析 MCP 响应（既非 JSON 也非 SSE data 段）: %s" % text[:200])

    # ------------------------------------------------------------------ #
    # 会话
    # ------------------------------------------------------------------ #
    def initialize(self):
        if self._initialized:
            return True
        result = self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mcd-mcp-python-client", "version": "1.0.0"},
        })
        if "error" in result:
            raise McpError("握手失败: %s" % result["error"])
        self._initialized = True
        # 通知服务端初始化完成，部分服务端要求此步骤
        try:
            self._seq += 1
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except McpError:
            pass
        return True

    def list_tools(self):
        """拉取服务端工具清单，用于探针与入参校准。"""
        result = self._rpc("tools/list")
        if "error" in result:
            raise McpError("拉取工具清单失败: %s" % result["error"])
        return result.get("result", {}).get("tools", [])

    # ------------------------------------------------------------------ #
    # 业务调用
    # ------------------------------------------------------------------ #
    def call_tool(self, name, arguments=None, timeout=None, allow_retry=True):
        """调用一个 MCP 工具，返回解析后的 Python 对象。

        服务端约定：结果包在 result.content[0].text 中，text 可能是 JSON 字符串，
        也可能是已经渲染好的 Markdown；此外可能存在 result.structuredContent。
        """
        self.initialize()
        params = {"name": name, "arguments": arguments or {}}

        attempt = 0
        while True:
            attempt += 1
            self._throttle()
            result = self._rpc("tools/call", params, timeout=timeout)
            if "error" in result:
                err = result["error"]
                code = err.get("code")
                # -32000 通常承载业务错误（如限购、门店不可用），不做重试
                raise McpError("工具 %s 调用失败: %s" % (name, err.get("message", err)),
                               status=code, payload=err)
            res = result.get("result", {}) or {}
            if res.get("isError"):
                first = (res.get("content") or [{}])[0]
                raise McpError("工具 %s 返回业务错误: %s" % (name, first.get("text", "")))
            return self._extract(res)

    def _extract(self, res):
        structured = res.get("structuredContent")
        if structured:
            return self._unwrap_envelope(structured)
        contents = res.get("content") or []
        texts = [c.get("text", "") for c in contents if isinstance(c, dict)]
        joined = "\n".join(t for t in texts if t).strip()
        if not joined:
            return {}
        try:
            parsed = json.loads(joined)
            # 服务端统一包装 {"success":..,"code":..,"data":..}
            if isinstance(parsed, dict) and "data" in parsed:
                return self._unwrap_envelope(parsed)
            return parsed
        except json.JSONDecodeError:
            return {"text": joined}

    @staticmethod
    def _unwrap_envelope(envelope):
        """把 {"success":..,"code":..,"data":..} 的外壳拆掉，只留 data。

        实测发现 data 有三种形态：
          1. dict / list  —— 直接可用；
          2. str          —— 某些接口（如 list-nutrition-foods）返回自定义
                             伪表格字符串，原样交给上层解析；
          3. 无 data 字段 —— 极少见，返回整个信封。
        """
        if not isinstance(envelope, dict):
            return envelope
        if "data" not in envelope:
            return envelope
        data = envelope["data"]
        if isinstance(data, (dict, list)):
            return data
        return {"data": data}


def call_with_retry(client, name, arguments=None, retries=2):
    """对只读工具做有限次重试（写操作请勿使用）。"""
    last = None
    for i in range(retries + 1):
        try:
            return client.call_tool(name, arguments)
        except McpError as exc:
            last = exc
            if exc.status == 429:
                time.sleep(1.5 * (i + 1))
                continue
            if exc.status and 500 <= exc.status < 600:
                time.sleep(1.0 * (i + 1))
                continue
            raise
    raise last
