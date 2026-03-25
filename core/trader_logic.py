# core/trader_logic.py
from __future__ import annotations

import asyncio
import queue
import threading
import time
import traceback
import datetime
import json
import configparser

from .events import EventEmitter, RepeatingTimer

from .kiwoom_api import KiwoomApi
from .kiwoom_ws import KiwoomWs


class TraderLogic:
    """
    Vanilla Trading Basic - TraderLogic (핵심 두뇌 최소 버전)

    ✅ 이 버전이 하는 일 (핵심 5개)
      1) 초기화:
         - REST 로그인
         - WebSocket 이벤트 루프/스레드 생성
         - 조건식 목록 요청 (REST 우선, 실패 시 WS 폴백)
         - 선택된 조건식 실시간 구독 시작

      2) 예수금(매수 가능 금액) 조회 → UI에 전달

      3) 조건식 실시간 신호 수신 → 자동매매 ON 상태면: 자동 '시장가 매수'
         - 현재 버전: 신호당 "무조건 1주" 매수
         - 1주 가격이 BUY_AMOUNT를 넘으면 매수 스킵

      4) 보유 포지션에 대해 **WebSocket REAL 시세 기준으로** TP/SL 조건 만족 시 자동 '시장가 매도'
         - REST 스냅샷은 WS 장애 시에만 폴백으로 사용

      5) 신호 포착 탭:
         - 조건식에 편입된 종목 리스트를 유지
         - WebSocket 실시간 시세로 가격/등락률/거래량 갱신 (REST는 폴백용)

    ⭐ 주요 개선사항 (v2.3 - 종목명 캐싱 강화)
      - 계좌 잔고 조회 시 종목명 자동 캐싱
      - 시세 스냅샷 조회 시 캐시 우선 → API 응답 → ka10100 순서로 종목명 확보
      - 디버깅 로그 강화 (종목명 조회 과정 추적)
    """

    # --- 이벤트 (EventEmitter) ---
    # 인스턴스별로 __init__에서 생성

    # --------------------------------------------------
    # 생성자
    # --------------------------------------------------
    def __init__(self):
        # 이벤트 (pyqtSignal 대체)
        self.account_update = EventEmitter()
        self.log_update = EventEmitter()
        self.condition_list_update = EventEmitter()
        self.signal_detected = EventEmitter()
        self.signal_realtime_update = EventEmitter()

        # 1) 설정 로드
        config = configparser.ConfigParser()
        config.read("config.ini", encoding="utf-8")
        self.config = config

        # 2) API 키 로드
        if "KIWOOM_API" not in config:
            print("[치명적 오류] config.ini에 [KIWOOM_API] 섹션이 없습니다.")
            kiwoom_section = {}
        else:
            kiwoom_section = config["KIWOOM_API"]

        APP_KEY = (
            kiwoom_section.get("APP_KEY")
            or kiwoom_section.get("app_key", "")
        )
        APP_SECRET = (
            kiwoom_section.get("APP_SECRET")
            or kiwoom_section.get("app_secret", "")
        )

        if not APP_KEY or not APP_SECRET:
            print("[치명적 오류] config.ini의 [KIWOOM_API] 섹션에 APP_KEY와 APP_SECRET을 추가해야 합니다.")

        # API 모드 (real / mock)
        self.api_mode = (
            kiwoom_section.get("MODE")
            or kiwoom_section.get("mode", "real")
        )

        # KiwoomApi: 주문 URI(`/api/dostk/ordr`)와 TR 코드(kt10000/kt10001)는 KiwoomApi 쪽에 매핑되어 있다고 가정
        self.api = KiwoomApi(app_key=APP_KEY, app_secret=APP_SECRET, mode=self.api_mode)

        # 3) WebSocket 관련
        self.ws: KiwoomWs | None = None
        self.ws_thread: threading.Thread | None = None
        self.ws_loop: asyncio.AbstractEventLoop | None = None

        # 4) 매매/설정 파라미터
        self.condition_seq = "0"        # 기본 조건식 번호 (UI에서 변경 가능)

        # 1주 매수 시 최대 허용 금액 (config.ini에서 읽음)
        self.buy_amount = 5_000         # 기본값 5,000원

        # 예수금 동기화용 락
        self._cash_lock = threading.Lock()
        self.current_cash = 0           # 예수금(매수 가능 금액)

        # 공유 자원 동기화용 락
        self._positions_lock = threading.Lock()
        self._signals_lock = threading.Lock()

        # 최대 보유 종목 수
        self.max_stock_limit = 10       # 기본값
        self.max_positions = self.max_stock_limit  # 구버전 코드 호환용 alias

        self.start_time = datetime.time(9, 0)
        self.end_time = datetime.time(15, 30)

        # SELL_STRATEGY 섹션에서 TP/SL 퍼센트 읽기
        # config.ini에서 섹션명이 "SELL_STRATEGY:전략이름" 형태이므로 prefix 매칭
        sell_sections = [s for s in config.sections() if s.startswith("SELL_STRATEGY:")]
        if sell_sections:
            sell_section = sell_sections[0]  # 첫 번째 매도 전략 사용
            self.stop_loss_rate = config.getfloat(
                sell_section,
                "STOP_LOSS_RATE",
                fallback=-2.0,  # -2% 손절
            )
            self.profit_cut_rate = config.getfloat(
                sell_section,
                "PROFIT_CUT_RATE",
                fallback=3.0,   # +3% 익절
            )
            print(f"[설정] 매도 전략 로드: {sell_section} (SL={self.stop_loss_rate}%, TP={self.profit_cut_rate}%)")
        else:
            self.stop_loss_rate = -2.0
            self.profit_cut_rate = 3.0
            print("[설정] 매도 전략 섹션 없음 → 기본값 사용 (SL=-2.0%, TP=3.0%)")

        # GLOBAL_SETTINGS 섹션에서 일부 기본값 덮어쓰기
        if "GLOBAL_SETTINGS" in config:
            g = config["GLOBAL_SETTINGS"]
            try:
                self.condition_seq = g.get("CONDITION_SEQ", self.condition_seq)
            except Exception:
                pass
            try:
                self.buy_amount = g.getint("BUY_AMOUNT", fallback=self.buy_amount)
            except Exception:
                pass
            # MAX_STOCKS(신규 키) 우선, MAX_POSITIONS(구 키)는 호환용 폴백
            try:
                # 구 키 먼저 읽고, 신규 키가 있으면 덮어씀
                self.max_stock_limit = g.getint("MAX_POSITIONS", fallback=self.max_stock_limit)
            except Exception:
                pass
            try:
                self.max_stock_limit = g.getint("MAX_STOCKS", fallback=self.max_stock_limit)
            except Exception:
                pass
            try:
                start_str = g.get("START_TIME", "09:00")
                self.start_time = datetime.datetime.strptime(start_str, "%H:%M").time()
            except Exception:
                self.start_time = datetime.time(9, 0)
            try:
                end_str = g.get("END_TIME", "15:30")
                self.end_time = datetime.datetime.strptime(end_str, "%H:%M").time()
            except Exception:
                self.end_time = datetime.time(15, 30)

        # 설정 값 검증
        if self.max_stock_limit < 1 or self.max_stock_limit > 50:
            self._emit_log("경고", f"비정상적인 최대 종목 수({self.max_stock_limit}). 기본값(10)으로 설정")
            self.max_stock_limit = 10

        # buy_amount는 1주 가격 상한선
        if self.buy_amount < 1000:
            self._emit_log("경고", f"매수 금액이 너무 낮음({self.buy_amount}원). 최소값(1,000원) 미만은 불가")
            self.buy_amount = 1000

        # alias 동기화
        self.max_positions = self.max_stock_limit

        # 5) 상태 관리
        self.is_trading = False      # 자동매매 ON/OFF (매수/매도 동작 여부)
        self.is_running = False      # 전체 시스템 러닝 플래그
        self._initializing = False   # 초기화 중 여부

        # 종목코드 → 종목명 캐시
        self._stock_names: dict[str, str] = {}

        # 보유 포지션: code -> {name, qty, entry_price}
        self.open_positions: dict[str, dict] = {}

        # 매수 거부(스킵) 리스트
        self.rejected_codes: set[str] = set()

        # 조건 편입 / 신호 대기 버퍼 (신호 탭 + 최근 가격 상태)
        # key: 종목코드, value: 스냅샷/REAL 정보
        self.pending_signals: dict[str, dict] = {}

        # 당일 재진입 차단용: { '종목코드': date 객체 }
        self.reentry_block: dict[str, datetime.date] = {}

        # 10) 커스텀 워치리스트 룰
        #  key: 종목코드
        #  value: {
        #    "stock_code": str,
        #    "stock_name": str,        # 시세 조회 후 채워짐
        #    "condition": "price_below" | "price_above" | "change_above" | "change_below" | "immediate",
        #    "threshold": float,        # 조건 기준값 (immediate이면 무시)
        #    "tp": float | None,        # 개별 TP (None이면 글로벌)
        #    "sl": float | None,        # 개별 SL (None이면 글로벌)
        #    "enabled": bool,
        #    "triggered": bool,         # 이미 매수 트리거됨
        #  }
        self._rules_lock = threading.Lock()
        self.watch_rules: dict[str, dict] = {}

        # 6) 포지션 감시용 타이머 (TP/SL 체크 - WS 장애 시 폴백용)
        self.position_timer = RepeatingTimer(5.0, self._check_positions)

        # 7) 신호 포착 리스트 실시간 갱신용 타이머 (WebSocket 폴백용)
        self.signal_timer = RepeatingTimer(5.0, self._refresh_signals)
        self.signal_timer.start()

        # 8) WS 신호 처리 큐 + 워커 스레드
        #    WS 콜백은 큐에 넣기만 → 워커가 REST 호출 포함 처리
        self._signal_queue: queue.Queue = queue.Queue()
        self._worker_running = True
        self._worker_thread: threading.Thread | None = None

        # 9) 미체결 주문 추적
        self._order_lock = threading.Lock()
        self._pending_orders: dict[str, dict] = {}
        # 체결 확인 타이머 (2초마다)
        self._order_confirm_timer = RepeatingTimer(2.0, self._confirm_pending_orders)
        # 예수금 정기 갱신 타이머 (60초마다 서버 조회)
        self._cash_sync_timer = RepeatingTimer(60.0, self._sync_cash)

        print("TraderLogic (v3.0 - 큐 기반 + 체결 확인) 객체가 생성되었습니다.")

    # ======================================================
    # 공용 로그 헬퍼
    # ======================================================
    def _emit_log(self, action: str, details: str, stock_name: str | None = None):
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        payload = {
            "time": now_str,
            "action": action,
            "details": details,
        }
        if stock_name:
            payload["stock_name"] = stock_name

        print(f"[TraderLogic LOG][{action}] {details}")
        try:
            self.log_update.emit(payload)
        except Exception:
            pass

    # ======================================================
    # 유틸 함수들
    # ======================================================
    @staticmethod
    def _safe_int(val) -> int:
        try:
            if val is None:
                return 0
            s = str(val).replace(",", "").replace("+", "").strip()
            return int(s)
        except Exception:
            return 0

    @staticmethod
    def _safe_price(val) -> int:
        """가격 문자열을 절대값 양수 정수로 변환"""
        try:
            if val is None:
                return 0
            s = str(val).replace(",", "").strip()
            if s.startswith("+") or s.startswith("-"):
                s = s[1:]
            if not s:
                return 0
            return int(s)
        except Exception:
            return 0

    @staticmethod
    def _safe_float(val) -> float:
        try:
            if val is None:
                return 0.0
            s = str(val).replace(",", "").replace("%", "").strip()
            if not s:
                return 0.0
            return float(s)
        except Exception:
            return 0.0

    @staticmethod
    def _normalize_code(code) -> str:
        if code is None:
            return ""
        s = str(code).strip()
        if s.startswith("A"):
            s = s[1:]
        return s

    def _has_ws(self) -> bool:
        return bool(self.ws and self.ws_loop and self.ws_loop.is_running())

    # 예수금 업데이트 헬퍼 (스레드 안전)
    def _update_cash(self, amount: int):
        with self._cash_lock:
            self.current_cash = max(self.current_cash + amount, 0)

    def _set_cash(self, amount: int):
        with self._cash_lock:
            self.current_cash = max(amount, 0)

    def _get_cash(self) -> int:
        with self._cash_lock:
            return self.current_cash

    # 당일 재진입 차단 관련 유틸
    def _today(self) -> datetime.date:
        return datetime.datetime.now().date()

    def _block_reentry_today(self, code: str):
        code = self._normalize_code(code)
        if not code:
            return
        self.reentry_block[code] = self._today()
        self._emit_log("시스템", f"{code}는 오늘 매도 완료 → 당일 재진입 금지")

    def _can_reenter_today(self, code: str) -> bool:
        code = self._normalize_code(code)
        if not code:
            return False
        last_date = self.reentry_block.get(code)
        if last_date is None:
            return True
        return last_date != self._today()

    # 매수 거부 리스트 전체 초기화
    def clear_all_rejected_codes(self):
        count = len(self.rejected_codes)
        self.rejected_codes.clear()
        self._emit_log("시스템", f"매수 거부 설정 {count}개가 모두 해제되었습니다.")
        return count

    # ------------------------------------------------------
    # 시세 스냅샷 조회 (REST 폴백용) + ⭐ 종목명 캐싱 강화
    # ------------------------------------------------------
    def _fetch_price_snapshot(self, stock_code: str) -> dict | None:
        """
        REST(ka10006 등)로 최소한의 시세 정보를 1회 가져온다.
        
        ⭐ 종목명 조회 우선순위:
          1) 캐시에서 먼저 확인 (계좌 잔고에서 이미 캐싱됨)
          2) 시세 API 응답에서 확인
          3) ka10100 API로 별도 조회 (디버깅 로그 포함)

        반환 형식:
        {
          "stock_code": ...,
          "stock_name": ...,
          "current_price": int,
          "change_rate": float,
          "volume": int,
        }
        """
        stock_code = self._normalize_code(stock_code)
        if not stock_code:
            return None

        try:
            # 1) 시세 조회 (ka10006)
            price_data = self.api.get_stock_price(stock_code)
            if not price_data:
                self._emit_log("오류", f"{stock_code} 시세 조회 실패 (응답 없음)")
                return None

            rc = price_data.get("return_code")
            if rc not in (None, 0, "0"):
                self._emit_log("오류", f"{stock_code} 시세 조회 실패 (return_code={rc})")
                return None

            out = price_data
            parsed = out.get("_parsed") or {}
            
            # 현재가 파싱
            current_price = parsed.get("current_price")
            if current_price is None:
                current_price = out.get("current_price")
            if current_price is not None:
                current_price = self._safe_price(current_price)
            else:
                current_price = self._safe_price(
                    out.get("stck_prpr")
                    or out.get("close_pric")
                    or out.get("lastPrice")
                    or out.get("last_price")
                )

            # 등락률 파싱
            change_rate = self._safe_float(
                out.get("flu_rt")
                or out.get("prdy_ctrt")
                or out.get("stck_prdy_ctrt")
                or parsed.get("change_rate")
            )
            
            # 거래량 파싱
            volume = self._safe_int(
                out.get("trde_qty")
                or out.get("acml_vol")
                or out.get("stck_vol")
                or parsed.get("volume")
            )

            # 2) ⭐⭐⭐ 종목명: 캐시 우선 → API 응답 → ka10100 순서
            stock_name = None
            
            # 2-1) 캐시에서 먼저 확인 (계좌 잔고에서 이미 캐싱됨)
            stock_name = self._stock_names.get(stock_code)
            if stock_name:
                print(f"[종목명 캐시 HIT ✅] {stock_code} → {stock_name}")
            
            # 2-2) 캐시에 없으면 시세 API 응답에서 확인
            if not stock_name:
                stock_name = (
                    out.get("stk_nm")
                    or out.get("name")
                    or out.get("hts_kor_isnm")
                    or out.get("itm_nm")
                    or parsed.get("stock_name")
                )
                if stock_name:
                    stock_name = str(stock_name).strip()
                    self._stock_names[stock_code] = stock_name
                    print(f"[종목명 시세 API ✅] {stock_code} → {stock_name}")
            
            # 2-3) ka10100 API는 키움증권에서 지원하지 않으므로 스킵
            # 종목명이 없으면 일단 종목코드 사용 (계좌 잔고 조회 시 또는 REAL 틱에서 업데이트됨)
            if not stock_name or stock_name == stock_code:
                print(f"[종목명 미확보] {stock_code} - 계좌 잔고 또는 REAL 틱에서 업데이트 예정")
                stock_name = stock_code
            
            # 2-4) 최종 캐시 저장
            if stock_name and stock_name != stock_code:
                self._stock_names[stock_code] = stock_name

            if current_price <= 0:
                self._emit_log("오류", f"{stock_code} 현재가가 0 또는 유효하지 않음.")
                return None

            print(
                f"[시세 스냅샷 ✅] {stock_name}({stock_code}) "
                f"{current_price:,}원 (등락률 {change_rate:.2f}%, 거래량 {volume:,})"
            )

            return {
                "stock_code": stock_code,
                "stock_name": stock_name,  # ← 종목명 포함!
                "current_price": current_price,
                "change_rate": change_rate,
                "volume": volume,
            }

        except Exception as e:
            self._emit_log("오류", f"{stock_code} 시세 조회 예외: {type(e).__name__}: {e}")
            traceback.print_exc()
            return None

    # ======================================================
    # 초기화 / WS 스레드
    # ======================================================
    def initialize_background(self):
        """UI에서 호출하는 비동기 초기화 엔트리포인트"""
        if self._initializing:
            self._emit_log("시스템", "이미 초기화 중입니다. 요청 무시.")
            return

        self._initializing = True
        self.is_running = True
        threading.Thread(target=self._run_initialization, daemon=True).start()

    def _run_initialization(self):
        try:
            print("[초기화] 1단계: 로그인 시도...")
            if not getattr(self.api, "access_token", None):
                if not self.api.login():
                    self._emit_log("오류", "초기화 실패: 로그인 실패")
                    self._initializing = False
                    self.is_running = False
                    return
                print("[초기화] 로그인 성공")

            print("[초기화] 2단계: 신호 처리 워커 + WebSocket 스레드 시작...")
            self._start_signal_worker()
            self.ws_thread = threading.Thread(
                target=self._run_ws_in_thread,
                daemon=True,
            )
            self.ws_thread.start()

            # 루프 생성 대기
            for i in range(30):
                if self.ws_loop:
                    print(f"[초기화] WS 루프 생성 완료 ({i * 0.1:.1f}초)")
                    break
                time.sleep(0.1)
            else:
                self._emit_log("오류", "WS 루프 생성 실패")
                self._initializing = False
                self.is_running = False
                return

            # WS 객체 생성 및 실행
            print("[초기화] 3단계: WebSocket 객체 생성 및 연결...")
            self.ws = KiwoomWs(
                access_token=self.api.access_token,
                signal_callback=self.on_realtime_signal,
                mode=self.api_mode,
            )
            asyncio.run_coroutine_threadsafe(self.ws.run(), self.ws_loop)

            # 연결 대기
            for i in range(100):
                if self.ws and self.ws.connected:
                    print(f"[초기화] WS 연결 성공 ({i * 0.1:.1f}초)")
                    break
                time.sleep(0.1)
            else:
                self._emit_log("오류", "WS 연결 실패")
                self._initializing = False
                self.is_running = False
                return

            # 조건식 목록 요청
            print("[초기화] 4단계: 조건식 목록 요청 (REST 우선)...")
            cond_list_data = self.api.get_condition_list()
            if cond_list_data and cond_list_data.get("return_code") == 0:
                self.condition_list_update.emit(cond_list_data)
                print("[초기화] 조건식 목록 UI 전송 완료 (REST)")
            else:
                print("[초기화] REST 조건식 실패 → WS CNSRLST 폴백 요청")
                asyncio.run_coroutine_threadsafe(
                    self.ws.request_condition_list(),
                    self.ws_loop,
                )

            time.sleep(0.5)

            # ⭐ 순서 변경: 계좌 잔고 조회를 먼저 실행 (종목명 캐싱)
            print("[초기화] 5단계: 초기 예수금 조회 (종목명 캐싱)...")
            self.update_account_info()  # 동기 실행
            time.sleep(1.0)  # 캐싱 완료 대기
            print("[초기화] 5단계 완료: 종목명 캐싱 완료")

            # 5-1) 서버 보유종목 동기화
            print("[초기화] 5-1단계: 서버 보유종목 동기화...")
            self._sync_positions_from_server()

            # 체결 확인 타이머 시작
            self._order_confirm_timer.start()
            self._cash_sync_timer.start()

            # 기본 조건식 실시간 구독
            print(f"[초기화] 6단계: 조건식({self.condition_seq}) 실시간 구독 시도...")
            if self._has_ws():
                asyncio.run_coroutine_threadsafe(
                    self.ws.subscribe_condition(seq=self.condition_seq),
                    self.ws_loop,
                )
                self._emit_log(
                    "시스템",
                    f"조건식({self.condition_seq}) 실시간 구독 시작",
                )

            self._initializing = False
            self._emit_log("시스템", "초기화 완료")

        except Exception as e:
            traceback.print_exc()
            self._emit_log("오류", f"초기화 스레드 예외: {e}")
            self._initializing = False
            self.is_running = False

    def _run_ws_in_thread(self):
        try:
            self.ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.ws_loop)
            print("[WS] 이벤트 루프 시작")
            self.ws_loop.run_forever()
        except Exception as e:
            print(f"[WS] 치명적 오류: {e}")
            traceback.print_exc()
        finally:
            if self.ws_loop:
                self.ws_loop.close()
            print("[WS] 이벤트 루프 종료")

    # ======================================================
    # 서버 보유종목 동기화
    # ======================================================
    def _sync_positions_from_server(self):
        """
        프로그램 시작 시 서버에서 보유종목을 가져와 open_positions에 복원.
        - 이미 로컬에 있는 종목은 서버 데이터로 덮어씀 (서버가 진실)
        - 보유 종목의 실시간 시세도 WS 구독
        """
        try:
            holdings = self.api.get_holdings()
            if not holdings:
                self._emit_log("시스템", "서버 보유종목 없음 (또는 조회 실패)")
                return

            synced_count = 0
            with self._positions_lock:
                for item in holdings:
                    code = item["stock_code"]
                    stock_name = item["stock_name"]
                    qty = item["qty"]
                    avg_price = item["avg_price"]

                    if qty <= 0:
                        continue

                    # 서버 데이터로 덮어씀 (서버가 진실)
                    self.open_positions[code] = {
                        "stock_name": stock_name,
                        "qty": qty,
                        "entry_price": avg_price,  # 실제 평균매입가 사용
                    }

                    # 종목명 캐싱
                    if stock_name and stock_name != code:
                        self._stock_names[code] = stock_name

                    synced_count += 1

            self._emit_log(
                "시스템",
                f"서버 보유종목 동기화 완료: {synced_count}개 종목 복원",
            )

            # 보유 종목에 대해 WS 실시간 시세 구독
            if synced_count > 0 and self._has_ws():
                codes = [item["stock_code"] for item in holdings if item["qty"] > 0]
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.ws.subscribe_multiple_prices(codes),
                        self.ws_loop,
                    )
                    self._emit_log("시스템", f"보유 {len(codes)}개 종목 실시간 시세 구독")
                except Exception as e:
                    print(f"[보유종목 WS 구독 오류] {e}")

            self._emit_account_status()

        except Exception as e:
            self._emit_log("경고", f"서버 보유종목 동기화 실패: {e}")
            traceback.print_exc()

    # ======================================================
    # 계좌(예수금) 조회 / UI 전송 + ⭐ 종목명 캐싱
    # ======================================================
    def _emit_account_status(self):
        cash = self._get_cash()
        payload = {
            "cash": cash,
            "can_order_amt": cash,
            "position_count": len(self.open_positions),
        }
        try:
            self.account_update.emit(payload)
        except Exception:
            pass

    def _sync_cash(self):
        """예수금 정기 갱신 (60초마다 서버 조회)"""
        if not getattr(self.api, "access_token", None):
            return
        try:
            self.update_account_info()
        except Exception as e:
            print(f"[예수금 동기화] 오류: {e}")

    def update_account_info(self):
        """
        ka01690으로 예수금(매수 가능 금액) 조회.
        d2_pymn_alow_amt, ord_psbl_cash_amt 등을 우선 사용.
        
        ⭐ 계좌 잔고 조회 시 종목명도 함께 캐싱!
        ⭐ 캐싱 후 이미 표시된 신호 포착 테이블의 종목명도 업데이트!
        """
        if not getattr(self.api, "access_token", None):
            self._emit_log("경고", "예수금 조회 실패: 로그인 필요 → 매수 차단 (예수금 0원)")
            self._set_cash(0)
            self._emit_account_status()
            return

        try:
            print("[계좌조회] 예수금(매수 가능 금액) 조회 시도...")
            balance_data = self.api.get_current_balance()

            if balance_data and balance_data.get("return_code") == 0:
                try:
                    print("[DEBUG][ka01690 RAW 응답]")
                    print(json.dumps(balance_data, ensure_ascii=False, indent=2))
                except Exception:
                    pass

                # ⭐ 계좌 잔고에서 종목명 캐싱
                day_bal_rt = balance_data.get("day_bal_rt", [])
                if not isinstance(day_bal_rt, list):
                    day_bal_rt = [day_bal_rt]
                
                for item in day_bal_rt:
                    if not isinstance(item, dict):
                        continue
                    
                    code = item.get("stk_cd")
                    if not code:
                        continue
                    
                    code = self._normalize_code(code)
                    if not code:
                        continue
                    
                    # 종목명 파싱 및 캐싱
                    stock_name = item.get("stk_nm")
                    if stock_name:
                        stock_name = str(stock_name).strip()
                        self._stock_names[code] = stock_name
                        print(f"[계좌 잔고 → 종목명 캐싱] {code} → {stock_name}")

                # ⭐⭐⭐ 종목명 캐싱 후 이미 표시된 신호들의 UI 업데이트
                with self._signals_lock:
                    pending_count = len(self.pending_signals)
                    pending_snapshot = dict(self.pending_signals)
                print(f"[계좌 잔고 후 UI 업데이트] pending_signals 종목 {pending_count}개 종목명 갱신 시도")
                for code in list(self._stock_names.keys()):
                    if code in pending_snapshot:
                        sig = pending_snapshot[code]
                        stock_name = self._stock_names[code]
                        
                        # pending_signals 업데이트
                        with self._signals_lock:
                            if code in self.pending_signals:
                                self.pending_signals[code]["stock_name"] = stock_name
                        
                        # UI 업데이트 데이터 구성
                        sig_time = sig.get("time")
                        if isinstance(sig_time, datetime.datetime):
                            time_str = sig_time.strftime("%H:%M:%S")
                        else:
                            time_str = sig_time if sig_time else datetime.datetime.now().strftime("%H:%M:%S")
                        
                        update_data = {
                            "time": time_str,
                            "stock_code": code,
                            "stock_name": stock_name,  # ← 캐싱된 종목명!
                            "current_price": sig.get("current_price", 0),
                            "price": sig.get("current_price", 0),
                            "cur_price": sig.get("current_price", 0),
                            "change_rate": sig.get("change_rate", 0.0),
                            "volume": sig.get("volume", 0),
                        }
                        
                        print(f"[계좌 잔고 후 UI 업데이트] {stock_name}({code}) 종목명 갱신")
                        try:
                            self.signal_realtime_update.emit(update_data)
                        except Exception as e:
                            print(f"[UI 업데이트 오류] {code}: {e}")

                orderable_str = (
                    balance_data.get("d2_pymn_alow_amt")
                    or balance_data.get("ord_psbl_cash_amt")
                    or balance_data.get("can_order_amt")
                    or balance_data.get("dbst_bal")
                    or "0"
                )

                cash_amount = self._safe_int(orderable_str)
                self._set_cash(cash_amount)
                print(f"[계좌조회 ✅] 매수 가능 금액: {cash_amount:,}원")
                self._emit_log("시스템", f"매수 가능 금액 갱신: {cash_amount:,}원")
            else:
                msg = (
                    balance_data.get("return_msg", "알 수 없는 오류")
                    if balance_data else "API 응답 없음"
                )
                self._emit_log("경고", f"예수금 조회 실패: {msg} → 매수 차단 (예수금 0원)")
                print("[계좌조회] ⚠️ 예수금 API 실패 → 안전 모드 (예수금 0원, 매수 차단)")
                self._set_cash(0)

            self._emit_account_status()

        except Exception as e:
            traceback.print_exc()
            self._emit_log("오류", f"예수금 조회 예외: {e} → 매수 차단 (예수금 0원)")
            print("[계좌조회] ⚠️ 예수금 조회 예외 → 안전 모드 (예수금 0원, 매수 차단)")
            self._set_cash(0)
            self._emit_account_status()

    # ======================================================
    # 자동매매 시작/중지
    # ======================================================
    def start_trading(self):
        """
        자동매매 시작 (매수/매도 동작 ON)
        - 매수 거부 리스트는 유지
        """
        if not getattr(self.api, "access_token", None):
            self._emit_log("오류", "자동매매 시작 실패: 로그인 필요")
            self.is_trading = False
            return

        threading.Thread(target=self.update_account_info, daemon=True).start()

        self.is_trading = True

        # position_timer는 WS 장애 시 REST 폴백용
        if not self.position_timer.is_active():
            self.position_timer.start()

        rejected_count = len(self.rejected_codes)
        if rejected_count > 0:
            self._emit_log(
                "시스템",
                f"자동매매 시작 (매수 거부 종목: {rejected_count}개 유지)",
            )

        self._emit_log(
            "시스템",
            (
                f"자동매매 시작: 조건식={self.condition_seq}, "
                f"신호당 매수수량=1주, "
                f"최대 보유 종목 수={self.max_stock_limit}개, "
                f"TP={self.profit_cut_rate}%, SL={self.stop_loss_rate}%"
            ),
        )

    def stop_trading(self):
        """자동매매 중지 (TP/SL 체크만 OFF, WS/조건식은 유지)"""
        self.is_trading = False
        if self.position_timer.is_active():
            self.position_timer.stop()
        self._emit_log("시스템", "자동매매 중지 (조건식 신호/WS는 그대로 유지, TP/SL 체크만 OFF)")

    # UI용 래퍼
    def start_auto_trading(self):
        if self.is_trading:
            self._emit_log("시스템", "자동매매가 이미 실행 중입니다.")
            return

        now = datetime.datetime.now().time()
        if not (self.start_time <= now <= self.end_time):
            self._emit_log(
                "경고",
                f"현재 시간은 {self.start_time.strftime('%H:%M')}~"
                f"{self.end_time.strftime('%H:%M')} 자동매매 시간 밖입니다. (그래도 시작은 합니다)",
            )

        self.start_trading()

        # ON 되는 순간, 이미 조건에 편입되어 있던 종목들 한 번씩 매수 시도
        with self._signals_lock:
            signals = list(self.pending_signals.values())

        if signals:
            self._emit_log(
                "시스템",
                f"자동매매 ON - 현재 조건 편입 {len(signals)}개 종목에 대해 즉시 매수 시도"
            )

            now_time = datetime.datetime.now().time()

            for sig in signals:
                code = sig["stock_code"]

                if code in self.rejected_codes:
                    self._emit_log("알림", f"{code}는 매수 거부 리스트에 있어 초기 일괄매수 스킵")
                    continue

                with self._positions_lock:
                    already_held = code in self.open_positions
                    position_count = len(self.open_positions)

                if already_held:
                    self._emit_log("알림", f"{code} 이미 보유 중. 초기 일괄매수 스킵")
                    continue

                if not self._can_reenter_today(code):
                    self._emit_log("알림", f"{code}는 오늘 이미 매도 완료 → 초기 일괄매수 스킵")
                    continue

                if position_count >= self.max_stock_limit:
                    self._emit_log(
                        "알림",
                        f"최대 보유 종목 수({self.max_stock_limit}개)에 도달하여 "
                        "나머지 초기 편입 종목 매수는 스킵합니다.",
                    )
                    break

                if not (self.start_time <= now_time <= self.end_time):
                    self._emit_log("경고", "거래시간이 아니어서 초기 일괄매수는 실행하지 않음")
                    break

                snapshot = {
                    "stock_code": sig["stock_code"],
                    "stock_name": sig["stock_name"],
                    "current_price": sig["current_price"],
                    "change_rate": sig["change_rate"],
                    "volume": sig["volume"],
                }

                self._auto_buy(code, snapshot)

    def stop_auto_trading(self, user_stop: bool = True):
        if not self.is_trading:
            self._emit_log("시스템", "자동매매가 이미 OFF 상태입니다.")
            return
        self.stop_trading()

    # 전체 종료용
    def shutdown_all(self):
        print("[TraderLogic] 시스템 종료(shutdown_all) 시작...")
        self.stop_trading()
        self.is_running = False

        # 체결 확인 타이머 정지
        if self._order_confirm_timer.is_active():
            self._order_confirm_timer.stop()
        if self._cash_sync_timer.is_active():
            self._cash_sync_timer.stop()

        # 워커 스레드 정지
        self._stop_signal_worker()

        if self.ws and self.ws_loop:
            try:
                if self.ws.connected:
                    asyncio.run_coroutine_threadsafe(self.ws.disconnect(), self.ws_loop)
                self.ws_loop.call_later(1.0, self.ws_loop.stop)
            except Exception:
                pass

        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=2.0)

        self._emit_log("시스템", "시스템 종료(shutdown_all) 완료.")

    # ======================================================
    # 조건식 변경
    # ======================================================
    def change_condition(self, new_seq: str):
        old_seq = self.condition_seq
        new_seq_str = str(new_seq).strip()
        if not new_seq_str:
            self._emit_log("경고", "조건식 번호가 비어 있습니다.")
            return

        self.condition_seq = new_seq_str
        self._emit_log("시스템", f"조건식 변경: {old_seq} → {self.condition_seq}")

        if not self._has_ws():
            self._emit_log("경고", "WS 미실행 상태. 다음 초기화 시점에 적용됩니다.")
            return

        async def _do_change():
            try:
                if hasattr(self.ws, "unsubscribe_condition") and old_seq:
                    await self.ws.unsubscribe_condition(seq=old_seq)
                await self.ws.subscribe_condition(seq=self.condition_seq)
            except Exception as e:
                traceback.print_exc()
                self._emit_log("오류", f"조건식 변경 중 오류: {e}")

        asyncio.run_coroutine_threadsafe(_do_change(), self.ws_loop)

    # ======================================================
    # WS 신호 큐 워커 (별도 스레드에서 실행)
    # ======================================================
    def _start_signal_worker(self):
        """신호 처리 워커 스레드 시작"""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._worker_running = True
        self._worker_thread = threading.Thread(
            target=self._signal_worker_loop,
            daemon=True,
            name="SignalWorker",
        )
        self._worker_thread.start()
        print("[워커] 신호 처리 워커 스레드 시작")

    def _stop_signal_worker(self):
        """신호 처리 워커 스레드 정지"""
        self._worker_running = False
        # 큐에 None sentinel 넣어서 블로킹 get() 해제
        self._signal_queue.put(None)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=3.0)
        print("[워커] 신호 처리 워커 스레드 정지")

    def _signal_worker_loop(self):
        """
        워커 스레드 메인 루프.
        큐에서 메시지를 꺼내 처리. REST 호출이 여기서 일어나므로
        WS 이벤트 루프를 블로킹하지 않음.
        """
        print("[워커] 루프 시작")
        while self._worker_running:
            try:
                msg = self._signal_queue.get(timeout=1.0)
                if msg is None:  # shutdown sentinel
                    break
                self._process_signal(msg)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[워커 오류] {e}")
                traceback.print_exc()
        print("[워커] 루프 종료")

    # ======================================================
    # WebSocket 실시간 신호 처리 (큐 기반)
    # ======================================================
    def on_realtime_signal(self, response_data: dict):
        """
        WS 콜백 — 절대 블로킹하지 않음.
        UI 시그널 emit (가벼운 것)만 직접 하고,
        REST 호출이 필요한 처리는 큐에 넣어 워커에게 위임.
        """
        trnm = response_data.get("trnm")

        # 1) 조건식 목록 (WS 폴백) — emit만, 블로킹 없음
        if trnm == "CNSRLST":
            self.condition_list_update.emit(response_data)
            return

        # 2) REAL 시세 — 파싱은 가벼움, TP/SL 매도 주문은 큐로
        if trnm == "REAL":
            self._signal_queue.put(response_data)
            return

        # 3) 조건식 신호 (CNSRREQ/CNSR) — REST 스냅샷 필요 → 큐로
        if trnm in ("CNSRREQ", "CNSR"):
            self._signal_queue.put(response_data)
            return

        # 4) 기타 (LOGIN 응답 등) — emit만
        self._signal_queue.put(response_data)

    def _process_signal(self, response_data: dict):
        """
        워커 스레드에서 실행되는 실제 신호 처리.
        여기서는 REST 호출을 해도 WS를 블로킹하지 않음.
        """
        trnm = response_data.get("trnm")

        # 조건식 스냅샷(CNSRREQ, 여러 종목) — REST 스냅샷 호출 포함
        if trnm == "CNSRREQ":
            rc = response_data.get("return_code")
            if rc and rc != 0:
                msg = response_data.get("return_msg", "")
                self._emit_log("경고", f"조건식 응답 에러(code={rc}): {msg}")
                return
            print("[워커] CNSRREQ 스냅샷 처리")
            data_list = response_data.get("data") or []
            if not isinstance(data_list, list):
                data_list = []
            for item in data_list:
                jmcode = item.get("jmcode") or item.get("stk_cd")
                stock_code = self._normalize_code(jmcode)
                if not stock_code:
                    continue
                self._handle_condition_signal(stock_code)
            return

        # 조건식 실시간(CNSR, 단건 ADD/DEL) — REST 스냅샷 호출 포함
        if trnm == "CNSR":
            evt_type = response_data.get("type")
            jmcode = (
                response_data.get("stck_shrn_iscd")
                or response_data.get("stk_cd")
                or response_data.get("jmcode")
            )
            stock_code = self._normalize_code(jmcode)
            if not stock_code:
                return

            print(f"[워커 CNSR] type={evt_type}, code={stock_code}")
            if evt_type == "ADD":
                self._handle_condition_signal(stock_code)
            return

        # 실시간 시세 (REAL) — TP/SL + 신호 테이블 갱신
        if trnm == "REAL":
            self._process_real_tick(response_data)
            return

    def _process_real_tick(self, response_data: dict):
        """REAL 틱 처리 (워커 스레드에서 실행)"""
        try:
            parsed = self.ws.parse_realtime_price(response_data)
            if not parsed:
                return

            stock_code = self._normalize_code(parsed.get("stock_code"))
            if not stock_code:
                return

            now_dt = datetime.datetime.now()
            now_time = now_dt.time()
            now_str = now_dt.strftime("%H:%M:%S")

            current_price = parsed.get("current_price", 0)
            if current_price is None:
                current_price = 0
            try:
                current_price = int(current_price)
            except Exception:
                current_price = self._safe_price(current_price)

            if current_price <= 0:
                return

            # 1) 보유 포지션 TP/SL 체크
            with self._positions_lock:
                has_position = (
                    self.is_trading
                    and (self.start_time <= now_time <= self.end_time)
                    and stock_code in self.open_positions
                )
                if has_position:
                    pos = self.open_positions.get(stock_code, {})
                    entry_price = pos.get("entry_price", current_price)
                    qty = pos.get("qty", 0)
                else:
                    entry_price = 0
                    qty = 0

            if has_position and qty > 0 and entry_price > 0:
                profit_rate = (current_price - entry_price) / entry_price * 100.0

                # 개별 룰 TP/SL 우선, 없으면 글로벌
                with self._rules_lock:
                    rule = self.watch_rules.get(stock_code)
                tp = (rule.get("tp") if rule and rule.get("tp") is not None else None) or self.profit_cut_rate
                sl = (rule.get("sl") if rule and rule.get("sl") is not None else None) or self.stop_loss_rate

                if profit_rate >= tp:
                    self._emit_log(
                        "매도주문",
                        f"{stock_code} TP({tp}%) 도달(REAL) → 시장가 전량 매도",
                    )
                    self._auto_sell(stock_code, qty, current_price)
                elif profit_rate <= sl:
                    self._emit_log(
                        "매도주문",
                        f"{stock_code} SL({sl}%) 도달(REAL) → 시장가 전량 매도",
                    )
                    self._auto_sell(stock_code, qty, current_price)

            # 2) 커스텀 룰 체크 (워치리스트 매수 조건)
            change_rate_for_rule = parsed.get("change_rate", 0.0)
            if change_rate_for_rule is None:
                change_rate_for_rule = 0.0
            self._check_watch_rules(stock_code, current_price, change_rate_for_rule)

            # 3) 신호 포착 테이블 실시간 갱신
            if self.ws and stock_code not in self.ws.subscribed_stocks:
                return

            stock_name = self._stock_names.get(stock_code)
            if not stock_name:
                stock_name = parsed.get("stock_name", stock_code)
                if stock_name and stock_name != stock_code:
                    self._stock_names[stock_code] = stock_name

            with self._signals_lock:
                prev_data = self.pending_signals.get(stock_code, {})
            prev_price = prev_data.get("current_price", current_price)

            change_rate = parsed.get("change_rate")
            if change_rate is None:
                if prev_price > 0:
                    change_rate = ((current_price - prev_price) / prev_price) * 100.0
                else:
                    change_rate = 0.0

            volume = parsed.get("volume", 0)
            if not volume:
                volume = prev_data.get("volume", 0)

            signal_data = {
                "time": now_str,
                "stock_code": stock_code,
                "stock_name": stock_name,
                "current_price": current_price,
                "price": current_price,
                "cur_price": current_price,
                "change_rate": change_rate,
                    "volume": volume,
            }

            try:
                self.signal_realtime_update.emit(signal_data)
            except Exception as e:
                print(f"[REAL emit 실패] {e}")

            with self._signals_lock:
                if stock_code not in self.pending_signals:
                    self.pending_signals[stock_code] = {
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                        "current_price": current_price,
                        "change_rate": change_rate,
                        "volume": volume,
                        "time": now_dt,
                    }
                else:
                    self.pending_signals[stock_code].update({
                        "current_price": current_price,
                        "change_rate": change_rate,
                        "volume": volume,
                        "time": now_dt,
                    })

        except Exception as e:
            print(f"[REAL 처리 오류] {e}")
            traceback.print_exc()

    # ------------------------------------------------------
    # 조건식 신호 처리 → UI + WebSocket 실시간 구독 + 자동매수
    # ------------------------------------------------------
    def _handle_condition_signal(self, stock_code: str):
        """
        조건식 신호 포착 시 실행되는 핵심 메서드
        - 최초 1회 REST 스냅샷
        - 신호 포착 탭에 신규 행 추가
        - WebSocket 실시간 시세 구독
        - 자동매매 ON이면 1주 자동 매수
        """
        stock_code = self._normalize_code(stock_code)
        if not stock_code:
            return

        print("\n" + "=" * 50)
        print(f"[조건검색 신호 포착] 종목코드: {stock_code}")
        print("=" * 50)

        snapshot = self._fetch_price_snapshot(stock_code)
        if snapshot is None:
            return

        stock_name = snapshot["stock_name"]
        current_price = snapshot["current_price"]
        change_rate = snapshot["change_rate"]
        volume = snapshot["volume"]

        # 신호 포착 탭에는 항상 표시 (매수 거부/재진입 차단 종목도 표시)
        signal_data = {
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "stock_code": stock_code,
            "stock_name": stock_name,
            "current_price": current_price,
            "price": current_price,
            "cur_price": current_price,
            "change_rate": change_rate,
            "volume": volume,
        }
        self.signal_detected.emit(signal_data)
        print("[UI 전송] 신호 포착 탭으로 데이터 전송")

        with self._signals_lock:
            self.pending_signals[stock_code] = {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "current_price": current_price,
                "change_rate": change_rate,
                "volume": volume,
                "time": datetime.datetime.now(),
            }

        # WebSocket 실시간 시세 구독 (거부 상태와 무관하게 항상 구독)
        if self._has_ws():
            try:
                asyncio.run_coroutine_threadsafe(
                    self.ws.subscribe_price(stock_code),
                    self.ws_loop
                )
                print(f"[실시간 시세 구독] {stock_code} WebSocket 등록 완료")
            except Exception as e:
                print(f"[실시간 시세 구독 오류] {stock_code}: {e}")
                traceback.print_exc()

        # 자동매수 조건 검증 (거부/재진입/시간/보유 등)
        if stock_code in self.rejected_codes:
            self._emit_log("알림", f"{stock_code}는 매수 거부 리스트에 있어 자동매수 스킵 (신호는 표시)")
            return

        if not self._can_reenter_today(stock_code):
            self._emit_log("알림", f"{stock_code}는 오늘 이미 매도 완료 → 자동매수 스킵 (신호는 표시)")
            return

        now_time = datetime.datetime.now().time()
        if not self.is_trading or not (self.start_time <= now_time <= self.end_time):
            print("[자동매매] OFF 상태이므로 자동매수는 실행하지 않음")
            return

        with self._positions_lock:
            if len(self.open_positions) >= self.max_stock_limit:
                self._emit_log(
                    "알림",
                    f"최대 보유 종목 수({self.max_stock_limit}개)에 도달하여 {stock_code} 매수 스킵",
                )
                return

            if stock_code in self.open_positions:
                self._emit_log("알림", f"{stock_code} 이미 보유 중. 매수 스킵")
                return

        self._auto_buy(stock_code, snapshot)

    # ------------------------------------------------------
    # 신호 포착 리스트 갱신 (WebSocket 폴백용)
    # ------------------------------------------------------
    def _refresh_signals(self):
        """
        신호 포착 리스트 갱신 타이머

        - WebSocket 정상 작동 시: REAL 데이터만 사용 (REST 호출 없음)
        - WebSocket 장애 시에만: REST 스냅샷 폴백
        - 오래된 신호(1시간 경과)는 자동 제거 + WS 구독 해제
        """
        with self._signals_lock:
            if not self.pending_signals:
                return
            signals_snapshot = dict(self.pending_signals)

        now = datetime.datetime.now()

        # 오래된 신호 정리
        old_signals = []
        for code, sig in signals_snapshot.items():
            signal_time = sig.get("time", now)
            if (now - signal_time).total_seconds() > 3600:
                old_signals.append(code)

        for code in old_signals:
            with self._signals_lock:
                self.pending_signals.pop(code, None)
            if self._has_ws():
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.ws.unsubscribe_price(code),
                        self.ws_loop
                    )
                except Exception:
                    pass
            self._emit_log("시스템", f"{code} 오래된 신호 제거 (1시간 경과)")

        # WebSocket 정상 → 폴백 불필요
        if self._has_ws() and self.ws and self.ws.connected:
            return

        # WebSocket 장애 → REST 폴백
        print("[신호 갱신 폴백] WebSocket 장애 - REST로 조회")
        with self._signals_lock:
            codes_to_refresh = list(self.pending_signals.keys())
        for code in codes_to_refresh:
            snapshot = self._fetch_price_snapshot(code)
            if snapshot is None:
                continue

            stock_code = snapshot["stock_code"]
            stock_name = snapshot["stock_name"]
            current_price = snapshot["current_price"]
            change_rate = snapshot["change_rate"]
            volume = snapshot["volume"]

            signal_data = {
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "stock_code": stock_code,
                "stock_name": stock_name,
                "current_price": current_price,
                "price": current_price,
                "cur_price": current_price,
                "change_rate": change_rate,
                "volume": volume,
            }

            try:
                self.signal_realtime_update.emit(signal_data)
            except Exception:
                pass

            with self._signals_lock:
                self.pending_signals[stock_code] = {
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "current_price": current_price,
                    "change_rate": change_rate,
                    "volume": volume,
                    "time": datetime.datetime.now(),
                }

    # ------------------------------------------------------
    # 자동 매수 (시장가) - 체결 확인 기반
    # ------------------------------------------------------
    def _auto_buy(self, stock_code: str, snapshot: dict | None = None):
        """
        자동 매수 로직
        - 항상 1주만 매수
        - 1주 가격이 BUY_AMOUNT를 초과하면 매수 안 함
        - 주문 접수 성공 시 _pending_orders에 등록 (체결 확인 후 open_positions로 이동)
        """
        stock_code = self._normalize_code(stock_code)
        if not stock_code:
            return

        # 이미 대기 중인 주문이 있으면 중복 주문 방지
        with self._order_lock:
            for order in self._pending_orders.values():
                if order.get("stock_code") == stock_code and order.get("side") == "BUY":
                    self._emit_log("알림", f"{stock_code} 이미 매수 주문 대기 중 → 중복 주문 방지")
                    return

        if snapshot is None:
            snapshot = self._fetch_price_snapshot(stock_code)
            if snapshot is None:
                return

        stock_name = snapshot["stock_name"]
        current_price = snapshot["current_price"]

        max_buy_amount = self.buy_amount

        if current_price > max_buy_amount:
            self._emit_log(
                "알림",
                f"{stock_name}({stock_code}) 1주 가격 {current_price:,}원 > 설정값 {max_buy_amount:,}원 → 매수 스킵",
            )
            return

        cash = self._get_cash()
        if cash <= 0:
            self._emit_log("경고", "예수금이 0원 또는 부족하여 매수 불가")
            return

        qty = 1
        order_amount = current_price * qty

        if cash < order_amount:
            self._emit_log(
                "알림",
                f"{stock_name} 현재가({current_price:,}원) 기준으로 1주도 살 수 없어 매수 스킵",
            )
            return

        self._emit_log(
            "매수주문",
            f"{stock_name}({stock_code}) 시장가 매수 요청: {qty}주 (약 {order_amount:,}원)",
        )

        result = self.api.buy_market_order(stock_code, qty, current_price=current_price)

        success = False
        if isinstance(result, dict):
            success = (str(result.get("return_code")) == "0")
        elif result:
            success = True

        if success:
            ord_no = str(result.get("ord_no", "")).strip() if isinstance(result, dict) else ""

            # 예수금 선차감 (체결 확인 시 보정)
            self._update_cash(-order_amount)
            self._emit_account_status()

            if ord_no:
                # 체결 확인 대기 큐에 등록
                with self._order_lock:
                    self._pending_orders[ord_no] = {
                        "side": "BUY",
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                        "qty": qty,
                        "expected_price": current_price,
                        "ord_no": ord_no,
                        "submitted_at": datetime.datetime.now(),
                        "confirm_attempts": 0,
                    }
                self._emit_log(
                    "매수주문",
                    f"{stock_name}({stock_code}) 주문 접수 성공 (주문번호: {ord_no}, 체결 대기 중)",
                )
            else:
                # 주문번호 없음 → 기존 방식으로 즉시 등록 (폴백)
                self._emit_log(
                    "매수주문",
                    f"{stock_name}({stock_code}) 주문 접수 성공 (주문번호 미수신 → 즉시 포지션 등록)",
                )
                with self._positions_lock:
                    self.open_positions[stock_code] = {
                        "stock_name": stock_name,
                        "qty": qty,
                        "entry_price": current_price,
                    }
        else:
            if isinstance(result, dict):
                msg = (result.get("return_msg") or "").strip()
                if "1504" in msg or "API ID not supported by that URI" in msg:
                    self._emit_log(
                        "오류",
                        "[Kiwoom REST 설정 오류] 매수 API에서 1504 응답. TR 코드/URI 매핑 점검 필요.",
                    )
            self._emit_log("오류", f"{stock_name}({stock_code}) 매수 주문 실패: {result}")

    # ------------------------------------------------------
    # TP/SL 자동 매도 (타이머 기반) - WebSocket 장애 시 REST 폴백용
    # ------------------------------------------------------
    def _check_positions(self):
        """
        WebSocket REAL이 정상일 때는 아무 것도 하지 않음.
        - TP/SL은 REAL 틱에서 처리
        - 여기서는 WebSocket 장애 시 REST 스냅샷을 사용해 TP/SL을 체크
        """
        if not self.is_trading:
            return

        with self._positions_lock:
            if not self.open_positions:
                return
            positions_snapshot = list(self.open_positions.items())

        if self._has_ws() and self.ws and self.ws.connected:
            return

        now_time = datetime.datetime.now().time()
        if not (self.start_time <= now_time <= self.end_time):
            return

        for code, pos in positions_snapshot:
            snapshot = self._fetch_price_snapshot(code)
            if snapshot is None:
                continue

            current_price = snapshot["current_price"]
            change_rate = snapshot["change_rate"]
            volume = snapshot["volume"]
            stock_name = snapshot["stock_name"]

            try:
                self.signal_realtime_update.emit({
                    "time": datetime.datetime.now().strftime("%H:%M:%S"),
                    "stock_code": code,
                    "stock_name": stock_name,
                    "current_price": current_price,
                    "price": current_price,
                    "cur_price": current_price,
                    "change_rate": change_rate,
                    "volume": volume,
                })
            except Exception:
                pass

            entry_price = pos.get("entry_price", current_price)
            qty = pos.get("qty", 0)
            if qty <= 0 or entry_price <= 0:
                continue

            profit_rate = (current_price - entry_price) / entry_price * 100
            print(
                f"[TP/SL 체크(REST 폴백)] {code} | 진입가:{entry_price:,} | "
                f"현재가:{current_price:,} | 수익률:{profit_rate:.2f}%"
            )

            if profit_rate >= self.profit_cut_rate:
                self._emit_log(
                    "매도주문",
                    f"{code} TP({self.profit_cut_rate}%) 도달(REST 폴백) → 시장가 전량 매도",
                )
                self._auto_sell(code, qty, current_price)
                continue

            if profit_rate <= self.stop_loss_rate:
                self._emit_log(
                    "매도주문",
                    f"{code} SL({self.stop_loss_rate}%) 도달(REST 폴백) → 시장가 전량 매도",
                )
                self._auto_sell(code, qty, current_price)
                continue

    def _auto_sell(self, stock_code: str, qty: int, current_price: int):
        """
        시장가 자동 매도
        - 주문 접수 성공 시 _pending_orders에 등록 (체결 확인 후 포지션 제거)
        - 중복 매도 방지
        """
        stock_code = self._normalize_code(stock_code)
        if not stock_code or qty <= 0:
            return

        # 이미 매도 주문 대기 중이면 중복 방지
        with self._order_lock:
            for order in self._pending_orders.values():
                if order.get("stock_code") == stock_code and order.get("side") == "SELL":
                    self._emit_log("알림", f"{stock_code} 이미 매도 주문 대기 중 → 중복 주문 방지")
                    return

        result = self.api.sell_market_order(stock_code, qty)

        success = False
        if isinstance(result, dict):
            success = (str(result.get("return_code")) == "0")
        elif result:
            success = True

        if success:
            ord_no = str(result.get("ord_no", "")).strip() if isinstance(result, dict) else ""

            if ord_no:
                with self._order_lock:
                    self._pending_orders[ord_no] = {
                        "side": "SELL",
                        "stock_code": stock_code,
                        "stock_name": self._stock_names.get(stock_code, stock_code),
                        "qty": qty,
                        "expected_price": current_price,
                        "ord_no": ord_no,
                        "submitted_at": datetime.datetime.now(),
                        "confirm_attempts": 0,
                    }
                self._emit_log(
                    "매도주문",
                    f"{stock_code} 주문 접수 성공 (주문번호: {ord_no}, 체결 대기 중)",
                )
            else:
                # 주문번호 없음 → 즉시 처리 (폴백)
                self._emit_log(
                    "매도주문",
                    f"{stock_code} 주문 접수 성공 (주문번호 미수신 → 즉시 포지션 제거)",
                )
                with self._positions_lock:
                    self.open_positions.pop(stock_code, None)
                sell_amount = current_price * qty
                self._update_cash(sell_amount)
                self._emit_account_status()
                self._block_reentry_today(stock_code)
        else:
            if isinstance(result, dict):
                msg = (result.get("return_msg") or "").strip()
                if "1504" in msg or "API ID not supported by that URI" in msg:
                    self._emit_log(
                        "오류",
                        "[Kiwoom REST 설정 오류] 매도 API에서 1504 응답. TR 코드/URI 매핑 점검 필요.",
                    )
            self._emit_log("오류", f"{stock_code} 시장가 매도 실패: {result}")

    # ------------------------------------------------------
    # 주문 체결 확인 (QTimer에서 2초마다 호출)
    # ------------------------------------------------------
    def _confirm_pending_orders(self):
        """
        _pending_orders에 있는 미체결 주문을 서버에 조회하여
        체결 확인 시 open_positions에 반영.

        - 매수 체결 → open_positions에 실제 체결가로 등록
        - 매도 체결 → open_positions에서 제거 + 예수금 가산
        - 최대 15회 시도 (약 30초) 후에도 미체결이면 주문 경과 경고
        """
        with self._order_lock:
            if not self._pending_orders:
                return
            orders_snapshot = dict(self._pending_orders)

        completed_ord_nos = []

        for ord_no, order in orders_snapshot.items():
            side = order["side"]
            stock_code = order["stock_code"]
            stock_name = order.get("stock_name", stock_code)
            expected_qty = order["qty"]
            expected_price = order["expected_price"]
            attempts = order.get("confirm_attempts", 0)

            # 체결 조회
            try:
                exec_result = self.api.get_order_execution(ord_no)
            except Exception as e:
                print(f"[체결확인 오류] {ord_no}: {e}")
                continue

            if exec_result.get("filled"):
                filled_qty = exec_result["filled_qty"]
                filled_price = exec_result["filled_price"]

                if side == "BUY":
                    with self._positions_lock:
                        self.open_positions[stock_code] = {
                            "stock_name": stock_name,
                            "qty": filled_qty,
                            "entry_price": filled_price,  # 실제 체결가!
                        }

                    # 예수금 보정: 선차감된 금액과 실제 체결 금액의 차이
                    price_diff = (expected_price * expected_qty) - (filled_price * filled_qty)
                    if price_diff != 0:
                        self._update_cash(price_diff)

                    # 체결가 차이가 크면 경고 (5% 이상)
                    if expected_price > 0:
                        diff_rate = abs(filled_price - expected_price) / expected_price * 100
                        if diff_rate >= 5:
                            self._emit_log(
                                "경고",
                                f"{stock_name}({stock_code}) 체결가 차이 주의: "
                                f"예상 {expected_price:,}원 → 실제 {filled_price:,}원 ({diff_rate:.1f}% 차이)",
                            )

                    self._emit_log(
                        "체결확인",
                        f"{stock_name}({stock_code}) 매수 체결: {filled_qty}주 @ {filled_price:,}원 (주문번호: {ord_no})",
                    )

                elif side == "SELL":
                    with self._positions_lock:
                        self.open_positions.pop(stock_code, None)

                    sell_amount = filled_price * filled_qty
                    self._update_cash(sell_amount)

                    self._block_reentry_today(stock_code)

                    self._emit_log(
                        "체결확인",
                        f"{stock_name}({stock_code}) 매도 체결: {filled_qty}주 @ {filled_price:,}원 (주문번호: {ord_no})",
                    )

                self._emit_account_status()
                completed_ord_nos.append(ord_no)

            else:
                # 미체결 — 재시도 횟수 증가
                with self._order_lock:
                    if ord_no in self._pending_orders:
                        self._pending_orders[ord_no]["confirm_attempts"] = attempts + 1

                if attempts >= 60:
                    # 약 120초간 미체결 → 경고 후 서버 동기화
                    self._emit_log(
                        "경고",
                        f"{stock_name}({stock_code}) 주문번호 {ord_no} ({side}) "
                        f"120초간 체결 미확인 → 서버 보유종목 동기화로 전환",
                    )
                    self._sync_positions_from_server()
                    # 예수금도 서버에서 다시 조회
                    self.update_account_info()
                    completed_ord_nos.append(ord_no)
                elif attempts == 30:
                    # 60초 경과 경고
                    self._emit_log(
                        "경고",
                        f"{stock_name}({stock_code}) 주문번호 {ord_no} ({side}) "
                        f"60초간 체결 미확인 — 계속 확인 중...",
                    )

        # 처리 완료된 주문 제거
        if completed_ord_nos:
            with self._order_lock:
                for ord_no in completed_ord_nos:
                    self._pending_orders.pop(ord_no, None)

    # ------------------------------------------------------
    # 수동 종목 추가 (기존 — 즉시 매수 경로)
    # ------------------------------------------------------
    def add_stock_manually(self, stock_code: str):
        """기존 방식: 종목 추가 + 조건식 경로로 즉시 매수 시도"""
        code = self._normalize_code(stock_code)
        if not code or len(code) != 6:
            self._emit_log("경고", f"잘못된 종목코드: {stock_code}")
            return

        with self._signals_lock:
            if code in self.pending_signals:
                self._emit_log("알림", f"{code}는 이미 신호 목록에 있습니다.")
                return

        self._emit_log("시스템", f"수동 종목 추가: {code}")
        self._signal_queue.put({
            "trnm": "CNSR", "type": "ADD", "stk_cd": code, "_manual": True,
        })

    # ------------------------------------------------------
    # 커스텀 워치리스트 룰 관리
    # ------------------------------------------------------
    def add_watch_rule(self, stock_code: str, condition: str = "immediate",
                       threshold: float = 0, tp: float = None, sl: float = None):
        """
        워치리스트에 종목 + 매수 조건 추가.

        condition:
            "immediate"    → 즉시 매수 (감시 없이)
            "price_below"  → 현재가 ≤ threshold 이면 매수
            "price_above"  → 현재가 ≥ threshold 이면 매수
            "change_above" → 등락률 ≥ threshold% 이면 매수
            "change_below" → 등락률 ≤ threshold% 이면 매수
        tp/sl:
            None이면 글로벌 설정 적용, 값이 있으면 개별 적용
        """
        code = self._normalize_code(stock_code)
        if not code or len(code) != 6:
            self._emit_log("경고", f"잘못된 종목코드: {stock_code}")
            return

        valid_conditions = ("immediate", "price_below", "price_above", "change_above", "change_below")
        if condition not in valid_conditions:
            self._emit_log("경고", f"잘못된 조건 유형: {condition}")
            return

        rule = {
            "stock_code": code,
            "stock_name": self._stock_names.get(code, code),
            "condition": condition,
            "threshold": threshold,
            "tp": tp,
            "sl": sl,
            "enabled": True,
            "triggered": False,
        }

        with self._rules_lock:
            self.watch_rules[code] = rule

        cond_text = {
            "immediate": "즉시 매수",
            "price_below": f"현재가 ≤ {threshold:,.0f}원",
            "price_above": f"현재가 ≥ {threshold:,.0f}원",
            "change_above": f"등락률 ≥ {threshold}%",
            "change_below": f"등락률 ≤ {threshold}%",
        }
        self._emit_log("시스템", f"룰 추가: {code} → {cond_text.get(condition, condition)}")

        # 시세 구독 + 신호 테이블 표시 (워커 경로)
        self._signal_queue.put({
            "trnm": "CNSR", "type": "ADD", "stk_cd": code,
            "_manual": True, "_rule": True,
        })

        # 즉시 매수인 경우 바로 트리거
        if condition == "immediate" and self.is_trading:
            self._emit_log("시스템", f"{code} 즉시 매수 룰 → 매수 시도")
            with self._rules_lock:
                self.watch_rules[code]["triggered"] = True

    def remove_watch_rule(self, stock_code: str):
        """워치리스트에서 종목 룰 삭제"""
        code = self._normalize_code(stock_code)
        with self._rules_lock:
            removed = self.watch_rules.pop(code, None)
        if removed:
            self._emit_log("시스템", f"룰 삭제: {code}")
        return removed is not None

    def update_watch_rule(self, stock_code: str, **kwargs):
        """워치리스트 룰 수정 (condition, threshold, tp, sl, enabled)"""
        code = self._normalize_code(stock_code)
        with self._rules_lock:
            rule = self.watch_rules.get(code)
            if not rule:
                return False
            for key in ("condition", "threshold", "tp", "sl", "enabled"):
                if key in kwargs and kwargs[key] is not None:
                    rule[key] = kwargs[key]
            # 조건 변경 시 triggered 초기화
            if "condition" in kwargs or "threshold" in kwargs:
                rule["triggered"] = False
        self._emit_log("시스템", f"룰 수정: {code}")
        return True

    def get_watch_rules(self) -> list:
        """현재 워치리스트 룰 목록 반환"""
        with self._rules_lock:
            return list(self.watch_rules.values())

    def _check_watch_rules(self, stock_code: str, current_price: int, change_rate: float):
        """
        REAL 틱에서 호출 — 해당 종목에 룰이 있으면 조건 체크 후 매수 트리거.
        """
        with self._rules_lock:
            rule = self.watch_rules.get(stock_code)
            if not rule or not rule["enabled"] or rule["triggered"]:
                return

        if not self.is_trading:
            return

        now_time = datetime.datetime.now().time()
        if not (self.start_time <= now_time <= self.end_time):
            return

        # 이미 보유 중이면 스킵
        with self._positions_lock:
            if stock_code in self.open_positions:
                return
            if len(self.open_positions) >= self.max_stock_limit:
                return

        if stock_code in self.rejected_codes:
            return
        if not self._can_reenter_today(stock_code):
            return

        # 조건 평가
        cond = rule["condition"]
        threshold = rule["threshold"]
        matched = False

        if cond == "immediate":
            matched = True
        elif cond == "price_below" and current_price <= threshold:
            matched = True
        elif cond == "price_above" and current_price >= threshold:
            matched = True
        elif cond == "change_above" and change_rate >= threshold:
            matched = True
        elif cond == "change_below" and change_rate <= threshold:
            matched = True

        if not matched:
            return

        # 트리거!
        with self._rules_lock:
            self.watch_rules[stock_code]["triggered"] = True

        cond_text = {
            "immediate": "즉시 매수",
            "price_below": f"현재가({current_price:,}) ≤ {threshold:,.0f}",
            "price_above": f"현재가({current_price:,}) ≥ {threshold:,.0f}",
            "change_above": f"등락률({change_rate:.2f}%) ≥ {threshold}%",
            "change_below": f"등락률({change_rate:.2f}%) ≤ {threshold}%",
        }
        self._emit_log(
            "룰트리거",
            f"{stock_code} 조건 충족: {cond_text.get(cond, cond)} → 매수 시도",
        )

        # 개별 TP/SL 적용
        original_tp = self.profit_cut_rate
        original_sl = self.stop_loss_rate
        if rule.get("tp") is not None:
            self.profit_cut_rate = rule["tp"]
        if rule.get("sl") is not None:
            self.stop_loss_rate = rule["sl"]

        stock_name = self._stock_names.get(stock_code, stock_code)
        snapshot = {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "current_price": current_price,
            "change_rate": change_rate,
            "volume": 0,
        }
        self._auto_buy(stock_code, snapshot)

        # TP/SL 복원
        self.profit_cut_rate = original_tp
        self.stop_loss_rate = original_sl

    # ------------------------------------------------------
    # 매수 거부(스킵) 관련  ⭐토글 동작
    # ------------------------------------------------------
    def reject_signal(self, stock_code: str):
        """
        UI의 '매수 거부' 버튼에서 호출되는 메서드.

        ▶ 토글 동작:
          - 처음 누르면: 해당 종목을 매수 거부 리스트에 추가
          - 한 번 더 누르면: 매수 거부 리스트에서 제거 (다시 매수 허용)
        """
        code = self._normalize_code(stock_code)
        if not code:
            self._emit_log("경고", f"매수 거부/해제 실패: 잘못된 종목코드 ({stock_code})")
            return

        if code in self.rejected_codes:
            self.rejected_codes.remove(code)
            self._emit_log(
                "시스템",
                f"{code} 매수 거부 해제 → 다시 자동매매 대상에 포함"
            )
        else:
            self.rejected_codes.add(code)
            self._emit_log(
                "시스템",
                f"{code}는 오늘 매수 대상에서 제외 (매수 거부 설정)"
            )

    # 구버전 이름 호환용
    def skip_stock(self, stock_code: str):
        """이전 버전에서 사용하던 이름 – reject_signal 래핑 (동일 토글 동작)"""
        self.reject_signal(stock_code)