# web/server.py
"""
FastAPI 기반 트레이딩 대시보드 서버.
- REST API: 설정 변경, 자동매매 시작/중지, 종목 추가
- WebSocket: 실시간 시세/로그/상태/포지션 Push
"""

import asyncio
import csv
import io
import json
import threading
from pathlib import Path
from typing import List

import requests as req_lib
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.trader_logic import TraderLogic
from core.events import RepeatingTimer

app = FastAPI(title="Vanilla Trading", docs_url="/docs")

# React 빌드 결과물 (web/dashboard/dist)
DASHBOARD_DIR = Path(__file__).parent / "dashboard" / "dist"
# 레거시 (바닐라 JS 폴백)
STATIC_DIR = Path(__file__).parent / "static"

# assets 먼저 마운트 (React 빌드의 JS/CSS)
if DASHBOARD_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(DASHBOARD_DIR / "assets")), name="assets")

# ── 전역 상태 ──
logic: TraderLogic | None = None
ws_clients: List[WebSocket] = []
ws_lock = threading.Lock()
_ws_loop: asyncio.AbstractEventLoop | None = None
_log_history: list = []
_position_push_timer: RepeatingTimer | None = None

# ── 종목 마스터 (종목코드 → 종목명) ──
_stock_master: List[dict] = []  # [{"code":"005930","name":"삼성전자","market":"KOSPI"}, ...]


def _load_stock_master():
    """네이버 증권에서 전체 상장 종목 리스트를 가져와 _stock_master에 저장"""
    global _stock_master
    try:
        print("[종목 마스터] 네이버 증권에서 종목 리스트 로딩 중...")
        kospi = _fetch_naver_stocks("KOSPI")
        kosdaq = _fetch_naver_stocks("KOSDAQ")
        _stock_master = kospi + kosdaq
        print(f"[종목 마스터] 로딩 완료: KOSPI {len(kospi)}개 + KOSDAQ {len(kosdaq)}개 = 총 {len(_stock_master)}개")
    except Exception as e:
        print(f"[종목 마스터] 로딩 실패: {e}")
        _stock_master = []


def _fetch_naver_stocks(market: str) -> list:
    """네이버 증권 모바일 API로 종목 리스트 가져오기 (페이지네이션)"""
    headers = {"User-Agent": "Mozilla/5.0"}
    result = []
    page = 1
    page_size = 100
    while True:
        try:
            url = f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize={page_size}"
            resp = req_lib.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                break
            data = resp.json()
            stocks = data.get("stocks") or []
            if not stocks:
                break
            for item in stocks:
                code = item.get("itemCode", "").strip()
                name = item.get("stockName", "").strip()
                if code and name and len(code) == 6 and code.isdigit():
                    result.append({"code": code, "name": name, "market": market})
            if len(stocks) < page_size:
                break
            page += 1
        except Exception as e:
            print(f"[네이버 {market} p{page}] 오류: {e}")
            break
    return result


# ══════════════════════════════════════
# WebSocket 브로드캐스트
# ══════════════════════════════════════
def broadcast(event_type: str, data):
    msg = json.dumps({"type": event_type, "data": data}, ensure_ascii=False, default=str)
    with ws_lock:
        clients = list(ws_clients)
    for client in clients:
        try:
            asyncio.run_coroutine_threadsafe(client.send_text(msg), _ws_loop)
        except Exception:
            pass


# ── TraderLogic 이벤트 → 브라우저 Push ──
def _on_account_update(data: dict):
    broadcast("account", data)


def _on_log_update(data: dict):
    broadcast("log", data)
    _log_history.append(data)
    if len(_log_history) > 300:
        _log_history.pop(0)
    # 체결확인 이벤트는 별도 타입으로도 Push
    action = (data.get("action") or "").lower()
    if "체결" in action or "confirm" in action:
        broadcast("execution", data)


def _on_condition_list(data: dict):
    broadcast("condition_list", data)


def _on_signal_detected(data: dict):
    broadcast("signal_new", data)


def _on_signal_realtime(data: dict):
    broadcast("signal_update", data)


# ── 포지션 주기 Push (2초마다) ──
def _push_positions():
    if not logic:
        return
    with logic._positions_lock:
        positions = dict(logic.open_positions)
    if not positions and not ws_clients:
        return
    # 각 포지션에 실시간 수익률 계산 추가
    pos_list = []
    for code, pos in positions.items():
        entry = pos.get("entry_price", 0)
        # pending_signals에서 최신 가격 가져오기
        with logic._signals_lock:
            sig = logic.pending_signals.get(code, {})
        cur_price = sig.get("current_price", entry)
        pnl_rate = ((cur_price - entry) / entry * 100) if entry > 0 else 0.0
        pnl_amount = (cur_price - entry) * pos.get("qty", 0) if entry > 0 else 0
        pos_list.append({
            "code": code,
            "name": pos.get("stock_name", code),
            "qty": pos.get("qty", 0),
            "entry_price": entry,
            "cur_price": cur_price,
            "pnl_rate": round(pnl_rate, 2),
            "pnl_amount": pnl_amount,
        })
    broadcast("positions", {
        "list": pos_list,
        "count": len(pos_list),
        "cash": logic._get_cash(),
    })


# ══════════════════════════════════════
# 라이프사이클
# ══════════════════════════════════════
@app.on_event("startup")
async def startup():
    global logic, _ws_loop, _position_push_timer
    _ws_loop = asyncio.get_event_loop()

    try:
        logic = TraderLogic()
        logic.account_update.connect(_on_account_update)
        logic.log_update.connect(_on_log_update)
        logic.condition_list_update.connect(_on_condition_list)
        logic.signal_detected.connect(_on_signal_detected)
        logic.signal_realtime_update.connect(_on_signal_realtime)

        logic.initialize_background()
    except Exception as e:
        print(f"[Web] TraderLogic 초기화 실패 (서버는 계속 실행): {e}")
        logic = None

    # 포지션 Push 타이머
    _position_push_timer = RepeatingTimer(2.0, _push_positions)
    _position_push_timer.start()

    # 종목 마스터 로딩 (백그라운드)
    threading.Thread(target=_load_stock_master, daemon=True).start()

    print("[Web] Vanilla Trading 서버 시작")


@app.on_event("shutdown")
async def shutdown():
    global _position_push_timer
    if _position_push_timer:
        _position_push_timer.stop()
    if logic:
        logic.shutdown_all()
    print("[Web] 서버 종료")


# ══════════════════════════════════════
# 페이지
# ══════════════════════════════════════
@app.get("/")
async def index():
    react_index = DASHBOARD_DIR / "index.html"
    if react_index.exists():
        return FileResponse(str(react_index))
    return FileResponse(str(STATIC_DIR / "index.html"))


# ══════════════════════════════════════
# WebSocket
# ══════════════════════════════════════
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    with ws_lock:
        ws_clients.append(ws)

    if logic:
        await ws.send_text(json.dumps({
            "type": "init",
            "data": _get_full_state(),
        }, ensure_ascii=False, default=str))

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        with ws_lock:
            if ws in ws_clients:
                ws_clients.remove(ws)


def _get_full_state() -> dict:
    if not logic:
        return {}

    with logic._positions_lock:
        positions = dict(logic.open_positions)
    with logic._signals_lock:
        signals = dict(logic.pending_signals)

    return {
        "is_trading": logic.is_trading,
        "is_running": logic.is_running,
        "ws_connected": bool(logic.ws and logic.ws.connected),
        "ws_logged_in": bool(logic.ws and logic.ws.logged_in),
        "cash": logic._get_cash(),
        "condition_seq": logic.condition_seq,
        "buy_amount": logic.buy_amount,
        "max_stocks": logic.max_stock_limit,
        "stop_loss_rate": logic.stop_loss_rate,
        "profit_cut_rate": logic.profit_cut_rate,
        "start_time": str(logic.start_time),
        "end_time": str(logic.end_time),
        "positions": positions,
        "position_count": len(positions),
        "signals": {k: {kk: vv for kk, vv in v.items() if kk != "time"} for k, v in signals.items()},
        "signal_count": len(signals),
        "rejected_codes": list(logic.rejected_codes),
        "rules": logic.get_watch_rules(),
        "logs": _log_history[-50:],
    }


# ══════════════════════════════════════
# REST API
# ══════════════════════════════════════
@app.get("/api/state")
async def get_state():
    return _get_full_state()


class StartRequest(BaseModel):
    buy_amount: int | None = None
    max_stocks: int | None = None
    stop_loss: float | None = None
    take_profit: float | None = None


@app.post("/api/start")
async def start_trading(req: StartRequest = None):
    if not logic:
        return {"error": "Not initialized"}
    if req:
        if req.buy_amount is not None:
            logic.buy_amount = req.buy_amount
        if req.max_stocks is not None:
            logic.max_stock_limit = req.max_stocks
        if req.stop_loss is not None:
            logic.stop_loss_rate = req.stop_loss
        if req.take_profit is not None:
            logic.profit_cut_rate = req.take_profit
    logic.start_auto_trading()
    broadcast("status", {"is_trading": logic.is_trading})
    return {"ok": True, "is_trading": logic.is_trading}


@app.post("/api/stop")
async def stop_trading():
    if not logic:
        return {"error": "Not initialized"}
    logic.stop_auto_trading()
    broadcast("status", {"is_trading": logic.is_trading})
    return {"ok": True, "is_trading": logic.is_trading}


class AddStockRequest(BaseModel):
    code: str


@app.post("/api/add_stock")
async def add_stock(req: AddStockRequest):
    if not logic:
        return {"error": "Not initialized"}
    logic.add_stock_manually(req.code)
    return {"ok": True, "code": req.code}


class RejectRequest(BaseModel):
    code: str


@app.post("/api/reject")
async def reject_stock(req: RejectRequest):
    if not logic:
        return {"error": "Not initialized"}
    logic.reject_signal(req.code)
    is_rejected = req.code in logic.rejected_codes
    broadcast("reject", {"code": req.code, "rejected": is_rejected})
    return {"ok": True, "code": req.code, "rejected": is_rejected}


class SettingsRequest(BaseModel):
    buy_amount: int | None = None
    max_stocks: int | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    condition_seq: str | None = None


@app.post("/api/settings")
async def update_settings(req: SettingsRequest):
    if not logic:
        return {"error": "Not initialized"}
    if req.buy_amount is not None:
        logic.buy_amount = req.buy_amount
    if req.max_stocks is not None:
        logic.max_stock_limit = req.max_stocks
    if req.stop_loss is not None:
        logic.stop_loss_rate = req.stop_loss
    if req.take_profit is not None:
        logic.profit_cut_rate = req.take_profit
    if req.condition_seq is not None:
        logic.change_condition(req.condition_seq)
    broadcast("settings", _get_full_state())
    return {"ok": True}


# ── 워치리스트 룰 API ──

class RuleRequest(BaseModel):
    code: str
    condition: str = "immediate"  # immediate, price_below, price_above, change_above, change_below
    threshold: float = 0
    tp: float | None = None
    sl: float | None = None


@app.get("/api/rules")
async def get_rules():
    if not logic:
        return {"rules": []}
    return {"rules": logic.get_watch_rules()}


@app.post("/api/rules")
async def add_rule(req: RuleRequest):
    if not logic:
        return {"error": "Not initialized"}
    logic.add_watch_rule(
        stock_code=req.code,
        condition=req.condition,
        threshold=req.threshold,
        tp=req.tp,
        sl=req.sl,
    )
    broadcast("rules", {"rules": logic.get_watch_rules()})
    return {"ok": True}


@app.put("/api/rules")
async def update_rule(req: RuleRequest):
    if not logic:
        return {"error": "Not initialized"}
    logic.update_watch_rule(
        stock_code=req.code,
        condition=req.condition,
        threshold=req.threshold,
        tp=req.tp,
        sl=req.sl,
    )
    broadcast("rules", {"rules": logic.get_watch_rules()})
    return {"ok": True}


class RuleDeleteRequest(BaseModel):
    code: str


@app.delete("/api/rules")
async def delete_rule(req: RuleDeleteRequest):
    if not logic:
        return {"error": "Not initialized"}
    logic.remove_watch_rule(req.code)
    broadcast("rules", {"rules": logic.get_watch_rules()})
    return {"ok": True}


# ── 종목 검색 + 시세 조회 API ──

@app.get("/api/search")
async def search_stocks(q: str = Query("", min_length=1)):
    """종목명 또는 코드로 검색 (최대 15건)"""
    q = q.strip().lower()
    if not q:
        return {"results": []}
    results = []
    for item in _stock_master:
        if q in item["name"].lower() or q in item["code"]:
            results.append(item)
            if len(results) >= 15:
                break
    return {"results": results}


@app.get("/api/chart/{code}")
async def get_chart(code: str):
    """종목 체결 차트 데이터 (ka10003)"""
    if not logic:
        return {"data": []}
    code = code.strip().replace("A", "")
    if not code or len(code) != 6:
        return {"data": []}
    try:
        result = logic.api._call_mrkcond("ka10003", {"stk_cd": code})
        if not result or result.get("return_code") not in (0, None):
            return {"data": []}
        items = result.get("cntr_infr") or []
        chart_data = []
        import datetime as dt
        today = dt.date.today()
        for item in reversed(items):
            tm = item.get("tm", "")
            price_str = item.get("cur_prc", "0")
            try:
                p = abs(int(str(price_str).replace("+", "").replace("-", "").replace(",", "")))
            except Exception:
                p = 0
            if not tm or p <= 0:
                continue
            # HH:MM:SS → unix timestamp
            try:
                t = dt.datetime.combine(today, dt.time(int(tm[:2]), int(tm[2:4]), int(tm[4:6])))
                chart_data.append({"time": int(t.timestamp()), "value": p})
            except Exception:
                continue
        return {"data": chart_data}
    except Exception as e:
        print(f"[차트 데이터] 오류: {e}")
        return {"data": []}


@app.get("/api/price/{code}")
async def get_price(code: str):
    """종목 시세 조회"""
    if not logic:
        return {"error": "Not initialized"}
    code = code.strip().replace("A", "")
    if not code or len(code) != 6:
        return {"error": "Invalid code"}

    snapshot = logic._fetch_price_snapshot(code)
    if snapshot is None:
        # 종목명이라도 넣어주기
        name = code
        for item in _stock_master:
            if item["code"] == code:
                name = item["name"]
                break
        return {"stock_code": code, "stock_name": name, "current_price": 0, "change_rate": 0, "volume": 0}

    return snapshot


# ── 수동 매수/매도 API ──

class OrderRequest(BaseModel):
    code: str
    qty: int = 1
    side: str = "buy"  # buy / sell


@app.post("/api/order")
async def manual_order(req: OrderRequest):
    """수동 매수/매도 주문"""
    if not logic:
        return {"error": "Not initialized"}

    # 수량 검증 — 돈이 오가므로 엄격하게
    if req.qty <= 0:
        return {"error": "수량은 1주 이상이어야 합니다"}
    if req.qty > 1000:
        return {"error": "1회 최대 주문 수량은 1,000주입니다"}
    if req.side not in ("buy", "sell"):
        return {"error": "주문 유형은 buy 또는 sell만 가능합니다"}

    code = req.code.strip().replace("A", "")
    if not code or len(code) != 6:
        return {"error": "Invalid code"}

    if req.side == "buy":
        result = logic.api.buy_market_order(code, req.qty)
        action = "매수"
    elif req.side == "sell":
        result = logic.api.sell_market_order(code, req.qty)
        action = "매도"
    else:
        return {"error": "Invalid side"}

    success = isinstance(result, dict) and str(result.get("return_code")) == "0"

    if success:
        ord_no = result.get("ord_no", "")
        name = logic._stock_names.get(code, code)
        broadcast("log", {
            "time": __import__("datetime").datetime.now().strftime("%H:%M:%S"),
            "action": f"수동{action}",
            "details": f"{name}({code}) {req.qty}주 시장가 {action} 접수 (주문번호: {ord_no})",
        })
        # 체결 확인 대기에 등록
        if ord_no and hasattr(logic, '_order_lock'):
            import datetime as dt
            with logic._order_lock:
                logic._pending_orders[str(ord_no)] = {
                    "side": "BUY" if req.side == "buy" else "SELL",
                    "stock_code": code,
                    "stock_name": name,
                    "qty": req.qty,
                    "expected_price": 0,
                    "ord_no": str(ord_no),
                    "submitted_at": dt.datetime.now(),
                    "confirm_attempts": 0,
                }

    return {"ok": success, "result": result}


# ══════════════════════════════════════
# SPA Fallback — 반드시 모든 API 뒤에 위치
# ══════════════════════════════════════
@app.get("/{path:path}")
async def spa_fallback(path: str):
    """React Router용 — 알 수 없는 경로는 index.html로"""
    react_index = DASHBOARD_DIR / "index.html"
    if react_index.exists():
        return FileResponse(str(react_index))
    return FileResponse(str(STATIC_DIR / "index.html"))
