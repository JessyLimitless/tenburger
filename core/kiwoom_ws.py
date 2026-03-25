# core/kiwoom_ws.py
import asyncio
import json
import traceback
from typing import Callable, List, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed


class KiwoomWs:
    """
    키움증권 WebSocket 클라이언트 (완전판 + 디버깅 강화)

    ✅ 기능:
    1) LOGIN 메시지로 인증
    2) 조건식 목록 조회 (CNSRLST)
    3) 조건식 실시간 구독 / 해제 (CNSRREQ / CNSRCLR)
    4) 실시간 시세 구독 (REG, type=0A)
    5) PING/PONG 자동 처리
    6) 지수 백오프 재연결 로직
    7) HEARTBEAT 로그로 WebSocket 상태 주기 출력  ← ★ 추가

    ⭐ v2.3: type='0A' (주식기세) 실시간 시세 적용
    ⭐ v2.4: trnm 이 애매한 실시간 틱도 강제로 REAL 로 래핑해서 전달
    """

    SOCKET_URLS = {
        "real": "wss://api.kiwoom.com:10000/api/dostk/websocket",
        "mock": "wss://mockapi.kiwoom.com:10000/api/dostk/websocket",
    }

    def __init__(
        self,
        access_token: str,
        signal_callback: Optional[Callable] = None,
        mode: str = "real",
    ):
        self.access_token = access_token
        self.signal_callback = signal_callback
        self.mode = mode if mode in self.SOCKET_URLS else "real"
        self.SOCKET_URL = self.SOCKET_URLS[self.mode]
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        self.logged_in = False
        self._running = True
        self._reconnect_attempt = 0
        self._max_reconnect_attempts = 3
        self._backoff_time = 2.0

        # 실시간 구독 관리
        self.subscribed_conditions: Set[str] = set()
        self.subscribed_stocks: Set[str] = set()

        # HEARTBEAT 관련 상태
        self._heartbeat_interval = 10.0  # 초 단위: 10초마다 상태 출력
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._last_message_ts: Optional[float] = None

    # ======================================================
    # 메인 루프
    # ======================================================
    async def run(self):
        """WebSocket 메인 루프"""
        # HEARTBEAT 태스크는 run() 시작 시 한 번만 생성
        if self._heartbeat_task is None:
            loop = asyncio.get_running_loop()
            self._heartbeat_task = loop.create_task(self._heartbeat_loop())

        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                print(f"[KiwoomWs] 오류 발생: {e}")
                traceback.print_exc()
                if self._running:
                    await self._handle_reconnect()

        # run() 루프 완전히 끝날 때 HEARTBEAT 정리
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = None

    async def _connect_and_listen(self):
        """연결 및 메시지 수신"""
        try:
            print(f"[KiwoomWs] 연결 시도: {self.SOCKET_URL}")

            # 공식 예제처럼 헤더 없이 연결
            async with websockets.connect(
                self.SOCKET_URL,
                ping_interval=20,
                ping_timeout=10,
            ) as ws:
                self.ws = ws
                self.connected = True
                self.logged_in = False
                self._reconnect_attempt = 0
                self._backoff_time = 2.0
                # 연결되면 마지막 메시지 시간도 초기화
                self._last_message_ts = asyncio.get_running_loop().time()

                print("[KiwoomWs] 연결 성공!")

                # 연결 후 즉시 LOGIN 메시지 전송
                await self._send_login()
                print("[KiwoomWs] LOGIN 메시지 전송 완료, 서버 응답 대기...")

                print("[KiwoomWs] 메시지 수신 대기 중...")
                async for message in ws:
                    try:
                        # 메시지를 받을 때마다 타임스탬프 갱신
                        self._last_message_ts = asyncio.get_running_loop().time()
                        await self._handle_message(message)
                    except Exception as e:
                        print(f"[KiwoomWs] 메시지 처리 오류: {e}")
                        traceback.print_exc()

        except ConnectionClosed as e:
            print(f"[KiwoomWs] 연결 종료: {e}")
            self.connected = False
            self.logged_in = False
        except Exception as e:
            print(f"[KiwoomWs] 연결 오류: {e}")
            traceback.print_exc()
            self.connected = False
            self.logged_in = False

    async def _send_login(self):
        """LOGIN 메시지 전송 (키움 공식 방식)"""
        login_msg = {
            "trnm": "LOGIN",
            "token": self.access_token,
        }
        await self._send_message_raw(login_msg)

    async def _handle_reconnect(self):
        """지수 백오프 재연결"""
        if self._reconnect_attempt >= self._max_reconnect_attempts:
            print(
                f"[KiwoomWs] 최대 재연결 시도 횟수({self._max_reconnect_attempts}) 초과 - 60초 대기"
            )
            await asyncio.sleep(60)
            self._reconnect_attempt = 0
            self._backoff_time = 2.0
            return

        wait_time = min(self._backoff_time, 60.0)
        print(
            f"[KiwoomWs] {wait_time:.1f}초 후 재연결 시도 "
            f"({self._reconnect_attempt + 1}/{self._max_reconnect_attempts})"
        )
        await asyncio.sleep(wait_time)
        self._reconnect_attempt += 1
        self._backoff_time *= 2

    async def _restore_subscriptions(self):
        """재연결 후 기존 구독 복원"""
        for seq in list(self.subscribed_conditions):
            print(f"[KiwoomWs] 조건식({seq}) 재구독 중...")
            await self.subscribe_condition(seq)

        if self.subscribed_stocks:
            print(
                f"[KiwoomWs] {len(self.subscribed_stocks)}개 종목 실시간 시세 재구독 중..."
            )
            await self.subscribe_multiple_prices(list(self.subscribed_stocks))

    # ======================================================
    # HEARTBEAT 루프 (터미널에 WS 상태 계속 표시)
    # ======================================================
    async def _heartbeat_loop(self):
        """
        일정 주기마다 WebSocket / 구독 상태를 터미널에 출력하는 HEARTBEAT.
        - run()이 돌아가는 동안 계속 실행됨.
        """
        while self._running:
            await asyncio.sleep(self._heartbeat_interval)

            now = asyncio.get_running_loop().time()
            last_ts = self._last_message_ts
            if last_ts is not None:
                gap = now - last_ts
                gap_str = f"{gap:.1f}초 전"
            else:
                gap_str = "수신 기록 없음"

            print(
                "[KiwoomWs HEARTBEAT] "
                f"running={self._running}, "
                f"connected={self.connected}, "
                f"logged_in={self.logged_in}, "
                f"조건식구독={len(self.subscribed_conditions)}개, "
                f"종목구독={len(self.subscribed_stocks)}개, "
                f"마지막_메시지_이후={gap_str}"
            )

            if not self.connected:
                print("[KiwoomWs HEARTBEAT] ⚠️ 현재 WebSocket이 연결되어 있지 않습니다.")

    # ======================================================
    # 실시간 틱 형태 감지 💡(새로 추가)
    # ======================================================
    @staticmethod
    def _looks_like_realtime_tick(msg: dict) -> bool:
        """
        trnm 값이 애매해도,
        data: [ { "item": "...", "values": { "10": "...", ... } } ]
        이런 형태면 '실시간 시세 틱'으로 본다.
        """
        try:
            data_list = msg.get("data")
            if not isinstance(data_list, list) or not data_list:
                return False
            first = data_list[0]
            if not isinstance(first, dict):
                return False
            item = first.get("item")
            values = first.get("values")
            if not item or not isinstance(values, dict):
                return False
            # 현재가 필드 '10' 이 있으면 거의 확실히 틱
            if "10" in values:
                return True
        except Exception:
            return False
        return False

    # ======================================================
    # 메시지 처리 (디버깅 강화 버전)
    # ======================================================
    async def _handle_message(self, message: str):
        """
        수신 메시지 처리 (디버깅 강화)

        ⭐ v2.3 개선사항:
        - type='0A' (주식기세) 실시간 시세 수신
        - 모든 메시지 원본 로깅
        - REAL 메시지 강조 로깅

        ⭐ v2.4 개선사항:
        - trnm 이 'REAL' 이 아니어도, 틱 형태면 강제로 REAL 로 래핑해서 콜백
        """
        try:
            # ⭐ 디버깅: 원본 메시지 로깅 (PING 제외, 첫 500자)
            if '"trnm":"PING"' not in message and '"trnm": "PING"' not in message:
                print(f"\n[KiwoomWs 원본 수신] {message[:500]}...")
            data = json.loads(message)
        except Exception as e:
            print(f"[KiwoomWs] JSON 파싱 실패: {message[:100]}")
            print(f"[KiwoomWs] 파싱 오류: {e}")
            return

        trnm = data.get("trnm")

        # ⭐ 디버깅: 메시지 타입 로깅 (PING 제외)
        if trnm != "PING":
            print(f"[KiwoomWs] 📥 메시지 타입: trnm={trnm}")

        # 1) LOGIN 응답
        if trnm == "LOGIN":
            return_code = data.get("return_code")
            if return_code != 0:
                print(f"[KiwoomWs] ❌ 로그인 실패: {data.get('return_msg')}")
                self.logged_in = False
                self._running = False
            else:
                print("[KiwoomWs] ✅ 로그인 성공!")
                self.logged_in = True
                # 로그인 성공 후 구독 복원
                await self._restore_subscriptions()

            # LOGIN도 콜백으로 전달
            if self.signal_callback:
                try:
                    self.signal_callback(data)
                except Exception as e:
                    print(f"[KiwoomWs] LOGIN 콜백 오류: {e}")
                    traceback.print_exc()
            return

        # 2) PING/PONG 처리
        if trnm == "PING":
            await self._send_message_raw(data)
            return

        # 3) REG (실시간 등록) 응답
        if trnm == "REG":
            rc = data.get("return_code")
            msg = data.get("return_msg", "")
            if rc == 0:
                print(f"[KiwoomWs] ✅ 실시간 등록 성공")
            else:
                print(f"[KiwoomWs] ❌ 실시간 등록 실패: {msg}")

            # REG 응답도 콜백 전달 (필요시)
            if self.signal_callback:
                try:
                    self.signal_callback(data)
                except Exception as e:
                    print(f"[KiwoomWs] REG 콜백 오류: {e}")
            return

        # ⭐⭐⭐ 4) REAL (실시간 시세) - trnm=REAL 인 경우 ⭐⭐⭐
        if trnm == "REAL":
            print(f"\n{'='*60}")
            print(f"[KiwoomWs] ⭐⭐⭐ REAL 메시지 수신! (trnm=REAL) ⭐⭐⭐")
            print(f"{'='*60}")
            print(f"[KiwoomWs REAL 원본] {json.dumps(data, ensure_ascii=False)[:500]}")

            # 종목코드 확인
            data_list = data.get("data", [])
            if data_list:
                item_data = data_list[0]
                stock_code = item_data.get("item", "알 수 없음")
                values = item_data.get("values", {})
                current_price = values.get("10", "N/A")
                change_rate = values.get("12", "N/A")
                volume = values.get("13", "N/A")
                print(
                    f"[KiwoomWs REAL] 종목코드={stock_code}, 현재가={current_price}, "
                    f"등락률={change_rate}%, 거래량={volume}"
                )

            # 콜백 전달
            if self.signal_callback:
                try:
                    print(f"[KiwoomWs REAL] signal_callback 호출 중...")
                    self.signal_callback(data)
                    print(f"[KiwoomWs REAL] signal_callback 호출 완료 ✓")
                except Exception as e:
                    print(f"[KiwoomWs REAL 콜백 오류] {e}")
                    traceback.print_exc()
            else:
                print(f"[KiwoomWs REAL 경고] signal_callback이 None입니다!")

            print(f"{'='*60}\n")
            return

        # 5) 조건검색 관련 응답/신호
        if trnm in ("CNSRREQ", "CNSRCLR", "CNSR", "CNSRLST"):
            if trnm == "CNSR":
                print("[KiwoomWs] 📡 조건검색 실시간 신호 수신 (CNSR)")
                print(f"[KiwoomWs CNSR] {json.dumps(data, ensure_ascii=False)[:300]}")

            if self.signal_callback:
                try:
                    self.signal_callback(data)
                except Exception as e:
                    print(f"[KiwoomWs] {trnm} 콜백 오류: {e}")
                    traceback.print_exc()
            return

        # 💡 6) trnm 이 애매하지만 '실시간 틱 형태'인 경우 → 강제 REAL 래핑
        if self._looks_like_realtime_tick(data):
            print(f"\n{'='*60}")
            print("[KiwoomWs] 🔍 trnm이 REAL은 아니지만, 틱 형태 감지 → REAL로 래핑")
            print(f"[KiwoomWs] 원본 trnm={trnm}")
            print(f"{'='*60}")
            real_wrapper = {
                "trnm": "REAL",
                "data": data.get("data", []),
            }

            if self.signal_callback:
                try:
                    print("[KiwoomWs] REAL 래핑 → signal_callback 호출 중...")
                    self.signal_callback(real_wrapper)
                    print("[KiwoomWs] REAL 래핑 → signal_callback 호출 완료 ✓")
                except Exception as e:
                    print(f"[KiwoomWs REAL-Wrapper 콜백 오류] {e}")
                    traceback.print_exc()
            else:
                print("[KiwoomWs REAL-Wrapper 경고] signal_callback이 None입니다!")
            print(f"{'='*60}\n")
            return

        # 7) 기타 알 수 없는 메시지
        print(f"[KiwoomWs] ⚠️ 처리되지 않은 메시지 타입: {trnm}")
        print(f"[KiwoomWs] 원본 데이터: {json.dumps(data, ensure_ascii=False)[:300]}")

        # 그래도 콜백은 전달
        if self.signal_callback:
            try:
                self.signal_callback(data)
            except Exception as e:
                print(f"[KiwoomWs] 알 수 없는 메시지 콜백 오류: {e}")
                traceback.print_exc()

    async def _send_message_raw(self, message: dict):
        """메시지 전송 (raw)"""
        if not self.ws:
            print("[KiwoomWs] WebSocket 미연결")
            return

        try:
            await self.ws.send(json.dumps(message, ensure_ascii=False))
            if message.get("trnm") != "PING":
                print(f"[KiwoomWs] 전송: {message}")
        except Exception as e:
            print(f"[KiwoomWs] 메시지 전송 실패: {e}")
            traceback.print_exc()

    # ======================================================
    # 조건식 관련
    # ======================================================
    async def request_condition_list(self):
        """조건식 목록 요청 (CNSRLST)"""
        msg = {
            "trnm": "CNSRLST",
        }
        await self._send_message_raw(msg)

    async def subscribe_condition(self, seq: str):
        """조건식 실시간 구독 (CNSRREQ)"""
        seq = str(seq).strip()
        if not seq:
            print("[KiwoomWs] 잘못된 조건식 번호")
            return

        if not self.logged_in:
            print(f"[KiwoomWs] ⚠️ 로그인 전 - 조건식({seq}) 구독 보류(자동 복원 예정)")
            self.subscribed_conditions.add(seq)
            return

        print(f"[KiwoomWs] 조건식({seq}) 실시간 구독 요청 중...")

        msg = {
            "trnm": "CNSRREQ",
            "seq": seq,
            "search_type": "1",  # 0: 일반조회, 1: 조건검색+실시간
            "stex_tp": "K",      # K: KRX
        }

        await self._send_message_raw(msg)
        self.subscribed_conditions.add(seq)
        print(f"[KiwoomWs] ✅ 조건식({seq}) 실시간 구독 요청 전송 완료")

    async def unsubscribe_condition(self, seq: str):
        """조건식 실시간 구독 해제 (CNSRCLR)"""
        seq = str(seq).strip()
        if not seq:
            return

        if not self.logged_in:
            self.subscribed_conditions.discard(seq)
            return

        msg = {
            "trnm": "CNSRCLR",
            "seq": seq,
        }
        await self._send_message_raw(msg)
        self.subscribed_conditions.discard(seq)
        print(f"[KiwoomWs] 조건식({seq}) 실시간 구독 해제 요청 전송")

    # ======================================================
    # 실시간 시세 REG (type=0A)
    # ======================================================
    async def subscribe_price(self, stock_code: str):
        """단일 종목 실시간 시세 구독 (REG, type=0A)"""
        if stock_code.startswith("A"):
            stock_code = stock_code[1:]
        stock_code = stock_code.strip()

        if not stock_code or len(stock_code) != 6:
            print(f"[KiwoomWs] 잘못된 종목코드: {stock_code}")
            return

        if not self.logged_in:
            print(f"[KiwoomWs] 로그인 전 - {stock_code} 구독 보류(자동 복원 예정)")
            self.subscribed_stocks.add(stock_code)
            return

        print(f"\n[KiwoomWs 실시간 구독] {stock_code} 구독 요청 시작 (type=0A)")
        print(f"[KiwoomWs 실시간 구독] 현재 구독 종목 수: {len(self.subscribed_stocks)}")

        msg = {
            "trnm": "REG",
            "grp_no": "1",
            "refresh": "0",
            "data": [
                {
                    "item": [stock_code],
                    "type": ["0A"],  # 주식기세
                }
            ],
        }

        await self._send_message_raw(msg)
        self.subscribed_stocks.add(stock_code)
        print(f"[KiwoomWs 실시간 구독] {stock_code} 구독 완료 ✓")
        print(f"[KiwoomWs 실시간 구독] 업데이트된 구독 종목: {list(self.subscribed_stocks)[:10]}...\n")

    async def unsubscribe_price(self, stock_code: str):
        """단일 종목 실시간 시세 구독 해제"""
        if stock_code.startswith("A"):
            stock_code = stock_code[1:]
        stock_code = stock_code.strip()
        if not stock_code:
            return

        if not self.logged_in:
            self.subscribed_stocks.discard(stock_code)
            return

        remaining = [s for s in self.subscribed_stocks if s != stock_code]

        if remaining:
            msg = {
                "trnm": "REG",
                "grp_no": "1",
                "refresh": "1",
                "data": [
                    {
                        "item": remaining,
                        "type": ["0A"],
                    }
                ],
            }
        else:
            msg = {
                "trnm": "REG",
                "grp_no": "1",
                "refresh": "1",
                "data": [],
            }

        await self._send_message_raw(msg)
        self.subscribed_stocks.discard(stock_code)
        print(f"[KiwoomWs] {stock_code} 실시간 시세 구독 해제")

    async def subscribe_multiple_prices(self, stock_codes: List[str]):
        """여러 종목 일괄 시세 구독"""
        normalized = []
        for code in stock_codes:
            if code.startswith("A"):
                code = code[1:]
            code = code.strip()
            if code and len(code) == 6:
                normalized.append(code)

        if not normalized:
            print("[KiwoomWs] 유효한 종목코드가 없음")
            return

        if not self.logged_in:
            print("[KiwoomWs] 로그인 전 - 일괄 구독 보류(자동 복원 예정)")
            self.subscribed_stocks.update(normalized)
            return

        print(f"\n[KiwoomWs 일괄 구독] {len(normalized)}개 종목 구독 요청 시작 (type=0A)")
        print(f"[KiwoomWs 일괄 구독] 종목 리스트: {normalized[:10]}...")

        msg = {
            "trnm": "REG",
            "grp_no": "1",
            "refresh": "0",
            "data": [
                {
                    "item": normalized,
                    "type": ["0A"],
                }
            ],
        }

        await self._send_message_raw(msg)
        self.subscribed_stocks.update(normalized)
        print(f"[KiwoomWs 일괄 구독] {len(normalized)}개 종목 구독 완료 ✓\n")

    # ======================================================
    # REAL 파서 (type='0A' 주식기세 기준)
    # ======================================================
    def parse_realtime_price(self, real_data: dict) -> dict:
        """
        REAL 메시지에서 실시간 시세 파싱 (type='0A' 기준)
        """
        if real_data.get("trnm") != "REAL":
            print(f"[parse_realtime_price] 경고: REAL이 아닌 메시지 ({real_data.get('trnm')})")
            return {}

        data_list = real_data.get("data", [])
        if not data_list:
            print(f"[parse_realtime_price] 경고: data 리스트 비어있음")
            return {}

        item_data = data_list[0]
        values = item_data.get("values", {})

        # 종목코드 파싱
        stock_code = item_data.get("item", "")
        if not stock_code:
            print(f"[parse_realtime_price] 경고: 종목코드 없음. item_data keys: {item_data.keys()}")
            return {}

        result = {
            "stock_code": stock_code,
            "stock_name": values.get("302", ""),  # 종목명
            "time": values.get("908", ""),        # 시간
            "raw_values": values,
        }

        # 현재가 ('10')
        cur_str = values.get("10", "0")
        try:
            result["current_price"] = int(cur_str.replace("+", "").replace("-", "").replace(",", ""))
        except Exception as e:
            print(f"[parse_realtime_price] 현재가 파싱 실패: {cur_str}, 오류: {e}")
            result["current_price"] = 0

        # 전일대비 ('11')
        diff_str = values.get("11", "0")
        try:
            result["price_diff"] = int(diff_str.replace("+", "").replace("-", "").replace(",", ""))
        except Exception:
            result["price_diff"] = 0

        # 등락률 ('12')
        rate_str = values.get("12", "0")
        try:
            result["change_rate"] = float(rate_str.replace("+", "").replace("%", ""))
        except Exception:
            result["change_rate"] = 0.0

        # 누적거래량 ('13')
        vol_str = values.get("13", "0")
        try:
            result["volume"] = int(vol_str.replace(",", ""))
        except Exception:
            result["volume"] = 0

        # 매도호가 ('27')
        ask_str = values.get("27", "0")
        try:
            result["sell_price"] = int(ask_str.replace("+", "").replace("-", "").replace(",", ""))
        except Exception:
            result["sell_price"] = 0

        # 매수호가 ('28')
        bid_str = values.get("28", "0")
        try:
            result["buy_price"] = int(bid_str.replace("+", "").replace("-", "").replace(",", ""))
        except Exception:
            result["buy_price"] = 0

        print(
            f"[parse_realtime_price 성공] {stock_code}: "
            f"현재가={result['current_price']:,}원, "
            f"등락률={result['change_rate']:.2f}%, "
            f"거래량={result['volume']:,}"
        )

        return result

    # ======================================================
    # 연결 종료
    # ======================================================
    async def disconnect(self):
        print("[KiwoomWs] 연결 종료 요청")
        self._running = False
        self.connected = False
        self.logged_in = False

        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass

        self.subscribed_conditions.clear()
        self.subscribed_stocks.clear()
        print("[KiwoomWs] 연결 종료 완료")
