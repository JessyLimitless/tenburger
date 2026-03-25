# core/kiwoom_api.py

import requests
import json
import time
import traceback


class KiwoomApi:
    """
    키움증권 REST API 클라이언트

    주요 기능:
    - OAuth 토큰 발급 (login)
    - 조건식 목록 조회
    - 현재가/호가 조회 (통합)
    - 계좌 잔고 조회
    - 매수/매도 주문
    """

    BASE_URLS = {
        "real": "https://api.kiwoom.com",
        "mock": "https://mockapi.kiwoom.com",
    }

    def __init__(self, app_key: str, app_secret: str, mode: str = "real"):
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = None
        self.last_token_time = 0
        self.mode = mode if mode in self.BASE_URLS else "real"
        self.BASE = self.BASE_URLS[self.mode]

    # ------------------------------------------------------
    # 내부 헬퍼: 종목코드 정규화 / output 평탄화
    # ------------------------------------------------------
    def _normalize_code(self, code: str) -> str:
        """
        'A005930' -> '005930' 같이 앞의 'A' 제거
        """
        if code is None:
            return ""
        c = str(code).strip()
        if c.startswith("A"):
            c = c[1:]
        return c

    def _flatten_output(self, body: dict) -> dict:
        """
        키움 REST 응답에서 output1[0] 등의 내용을 최상위로 풀어주는 헬퍼.
        - 기존 구조(output1 등)는 건드리지 않고,
        - 필요한 필드(stck_prpr, stck_prdy_ctrt, acml_vol 등)를
          get_stock_price 최종 결과에 올리기 위해 사용.
        """
        if not isinstance(body, dict):
            return {}

        flat = {}

        # 1) output1, output2 내의 첫 번째 레코드를 평탄화
        for key in ("output1", "output2"):
            v = body.get(key)
            if isinstance(v, list) and v:
                first = v[0]
                if isinstance(first, dict):
                    flat.update(first)

        # 2) top-level 에 직접 들어있는 stck_* / acml_* 류가 있다면 그것도 포함
        for k, v in body.items():
            if k.startswith("stck_") or k.startswith("acml_") or k in (
                "stck_prpr",
                "stck_prdy_ctrt",
                "acml_vol",
                "flu_rt",
                "trde_qty",
            ):
                flat.setdefault(k, v)

        return flat

    # ======================================================
    # 로그인 (OAuth 토큰 발급)
    # ======================================================
    def login(self):
        """
        OAuth 토큰 발급 (키움증권 공식 스펙)

        요청:
        {
            "grant_type": "client_credentials",
            "appkey": "...",
            "secretkey": "..."
        }

        응답:
        {
            "expires_dt": "20241107083713",
            "token_type": "bearer",
            "token": "WQJCwyqInphKnR3bSRtB9NE1lv...",  ← access_token 아님!
            "return_code": 0,
            "return_msg": "정상적으로 처리되었습니다"
        }

        Returns:
            bool: 성공 시 True, 실패 시 False
        """
        url = f"{self.BASE}/oauth2/token"
        headers = {"Content-Type": "application/json;charset=UTF-8"}

        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,        # appkey (소문자)
            "secretkey": self.app_secret,  # secretkey (소문자)
        }

        try:
            print(f"[로그인] 토큰 발급 요청: {url}")
            print(f"[로그인] appkey: ***masked***")
            print(f"[로그인] mode: {self.mode}")

            response = requests.post(url, headers=headers, json=data, timeout=10)

            print(f"[로그인] HTTP {response.status_code}")

            if response.status_code != 200:
                try:
                    result = response.json()
                    print(f"[로그인 실패] {result.get('return_msg', response.text[:200])}")
                except Exception:
                    print(f"[로그인 실패] 응답: {response.text[:500]}")
                return False

            result = response.json()

            # 디버그용 전체 응답 출력
            try:
                print(f"[로그인] 응답: {json.dumps(result, indent=2, ensure_ascii=False)}")
            except Exception:
                print(f"[로그인] 응답: {result}")

            # ⭐ 키움 API는 "token" 필드 사용
            self.access_token = result.get("token")

            if not self.access_token:
                print("[로그인 실패] token 필드 없음")
                print(f"[로그인 실패] return_code: {result.get('return_code')}")
                print(f"[로그인 실패] return_msg: {result.get('return_msg')}")
                return False

            return_code = result.get("return_code")
            if return_code != 0:
                print(f"[로그인 실패] return_code={return_code}")
                print(f"[로그인 실패] return_msg: {result.get('return_msg')}")
                return False

            self.last_token_time = time.time()
            expires_dt = result.get("expires_dt", "N/A")

            print(f"[로그인 성공] 토큰 발급 완료!")
            print(f"[로그인 성공] token_type: {result.get('token_type')}")
            print(f"[로그인 성공] expires_dt: {expires_dt}")
            return True

        except Exception as e:
            print(f"[로그인 오류] {type(e).__name__}: {e}")
            traceback.print_exc()
            return False

    # ======================================================
    # 토큰 유효성 확인 및 갱신
    # ======================================================
    def ensure_token(self):
        """
        토큰 유효성 확인 및 필요 시 재발급
        - 토큰이 없거나 1시간 이상 경과 시 재발급
        """
        if self.access_token and (time.time() - self.last_token_time) < 3600:
            return  # 토큰 유효

        print("[토큰] 토큰 갱신 필요")
        if not self.login():
            raise RuntimeError("KiwoomApi 로그인 실패")

    # ======================================================
    # 공용: /api/dostk/mrkcond 호출 헬퍼
    # ======================================================
    def _call_mrkcond(self, api_id: str, params: dict) -> dict:
        """
        ka10006 / ka10004 등 /api/dostk/mrkcond 공통 호출
        """
        self.ensure_token()

        url = self.BASE + "/api/dostk/mrkcond"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.access_token}",
            "cont-yn": "N",
            "next-key": "",
            "api-id": api_id,
        }

        try:
            resp = requests.post(url, headers=headers, json=params, timeout=10.0)
        except requests.Timeout:
            print(f"[{api_id}] 타임아웃")
            return {"return_code": -1, "return_msg": "Timeout"}
        except Exception as e:
            print(f"[{api_id}] 요청 오류: {e}")
            return {"return_code": -1, "return_msg": str(e)}

        print(f"[DEBUG][{api_id}] HTTP {resp.status_code}")

        body = {}
        try:
            body = resp.json()
        except Exception:
            print(f"[DEBUG][{api_id}] JSON 디코딩 실패, text=", resp.text[:200])

        if resp.status_code != 200:
            return {
                "return_code": -1,
                "return_msg": f"HTTP {resp.status_code}",
                "raw": body,
            }

        if "return_code" not in body:
            body["return_code"] = 0

        return body

    # ======================================================
    # 조건식 목록 조회
    # ======================================================
    def get_condition_list(self) -> dict:
        """
        조건식 목록 조회 (ka03001)
        """
        self.ensure_token()

        url = self.BASE + "/api/dostk/mrkcond"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.access_token}",
            "api-id": "ka03001",
        }

        try:
            print("[조건식 목록] 요청 중...")
            resp = requests.post(url, headers=headers, json={}, timeout=10.0)

            if resp.status_code != 200:
                print(f"[조건식 목록] HTTP {resp.status_code} 실패")
                return {"return_code": -1, "return_msg": f"HTTP {resp.status_code}"}

            result = resp.json()

            if "return_code" not in result:
                result["return_code"] = 0

            print(f"[조건식 목록] 성공: {len(result.get('output1', []))}개")
            return result

        except Exception as e:
            print(f"[조건식 목록] 오류: {e}")
            traceback.print_exc()
            return {"return_code": -1, "return_msg": str(e)}

    # ======================================================
    # 현재가 + 호가 통합 조회
    # ======================================================
    def get_stock_price(self, stock_code: str) -> dict:
        """
        종목 시세 통합 조회
        - ka10006: 현재가 / 등락률 / 거래량
        - ka10004: 매수/매도 1호가
        """
        code = self._normalize_code(stock_code)
        params = {"stk_cd": code}

        # 1) ka10006 – 가격/등락률/거래량
        price_data = self._call_mrkcond("ka10006", params)
        if not price_data or price_data.get("return_code") != 0:
            return price_data or {"return_code": -1, "return_msg": "ka10006 호출 실패"}

        # 2) ka10004 – 1호가 정보
        hoga_data = self._call_mrkcond("ka10004", params)
        if not hoga_data or hoga_data.get("return_code") != 0:
            hoga_data = {}  # 호가 실패해도 계속 진행

        # 2-1) 평탄화
        flat_price = self._flatten_output(price_data)
        flat_hoga = self._flatten_output(hoga_data)

        # 3) 두 응답 merge
        merged = {}

        # (1) 원본 그대로
        merged.update(price_data)
        for k, v in hoga_data.items():
            if k in ("return_code", "return_msg"):
                continue
            merged[k] = v

        # (2) 평탄화된 필드 최상위에 추가
        for k, v in flat_price.items():
            merged[k] = v
        for k, v in flat_hoga.items():
            if k not in ("return_code", "return_msg"):
                merged.setdefault(k, v)

        merged["return_code"] = 0
        merged.setdefault("return_msg", "OK")

        return merged

    # ======================================================
    # 계좌 잔고 조회
    # ======================================================
    def get_current_balance(self, qry_dt: str = None) -> dict:
        """
        계좌 잔고 조회 (ka01690 - 일별잔고수익률)
        """
        self.ensure_token()

        url = self.BASE + "/api/dostk/acnt"

        if qry_dt is None:
            from datetime import datetime
            qry_dt = datetime.now().strftime("%Y%m%d")

        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.access_token}",
            "api-id": "ka01690",
        }

        params = {"qry_dt": qry_dt}

        try:
            print(f"[계좌 잔고] 조회 중... (qry_dt={qry_dt})")
            resp = requests.post(url, headers=headers, json=params, timeout=10.0)

            if resp.status_code != 200:
                print(f"[계좌 잔고] HTTP {resp.status_code} 실패")
                return {"return_code": -1, "return_msg": f"HTTP {resp.status_code}"}

            result = resp.json()

            if "return_code" not in result:
                result["return_code"] = 0

            if result.get("return_code") == 0:
                dbst_bal_str = result.get("dbst_bal", "0")
                try:
                    dbst_bal = int(str(dbst_bal_str).replace(",", ""))
                except Exception:
                    dbst_bal = 0

                result["ord_psbl_cash_amt"] = str(dbst_bal)
                result["can_order_amt"] = str(dbst_bal)
                result["d2_pymn_alow_amt"] = str(dbst_bal)

                print(f"[계좌 잔고] 성공: 매수가능금액 = {dbst_bal:,}원")
            else:
                print(f"[계좌 잔고] 실패: {result.get('return_msg', 'N/A')}")

            return result

        except Exception as e:
            print(f"[계좌 잔고] 오류: {e}")
            traceback.print_exc()
            return {"return_code": -1, "return_msg": str(e)}

    # ======================================================
    # 보유종목 목록 조회 (잔고 응답에서 파싱)
    # ======================================================
    def get_holdings(self) -> list:
        """
        서버에서 보유종목 목록을 조회하여 정규화된 리스트로 반환.
        ka01690 응답의 day_bal_rt 배열에서 보유 수량이 1 이상인 종목만 추출.

        Returns:
            list of dict: [
                {
                    "stock_code": "005930",
                    "stock_name": "삼성전자",
                    "qty": 10,
                    "avg_price": 72000,
                },
                ...
            ]
            빈 리스트면 보유종목 없음 또는 조회 실패.
        """
        balance_data = self.get_current_balance()
        if not balance_data or balance_data.get("return_code") != 0:
            print("[보유종목] 잔고 조회 실패")
            return []

        day_bal_rt = balance_data.get("day_bal_rt", [])
        if not isinstance(day_bal_rt, list):
            day_bal_rt = [day_bal_rt] if day_bal_rt else []

        holdings = []
        for item in day_bal_rt:
            if not isinstance(item, dict):
                continue

            code = self._normalize_code(item.get("stk_cd"))
            if not code:
                continue

            # 보유수량: ka01690 → rmnd_qty (잔여수량)
            qty_str = item.get("rmnd_qty") or "0"
            try:
                qty = int(str(qty_str).replace(",", "").strip())
            except Exception:
                qty = 0

            if qty <= 0:
                continue

            # 평균매입가: ka01690 → buy_uv (매입단가)
            avg_str = item.get("buy_uv") or "0"
            try:
                avg_price = int(float(str(avg_str).replace(",", "").strip()))
            except Exception:
                avg_price = 0

            stock_name = str(item.get("stk_nm") or code).strip()

            holdings.append({
                "stock_code": code,
                "stock_name": stock_name,
                "qty": qty,
                "avg_price": avg_price,
            })

            print(f"[보유종목] {stock_name}({code}) {qty}주, 평균가 {avg_price:,}원")

        print(f"[보유종목] 총 {len(holdings)}개 종목 보유 중")
        return holdings

    # ======================================================
    # 주문 체결 조회
    # ======================================================
    def get_order_execution(self, ord_no: str) -> dict:
        """
        주문번호로 체결 상태 조회 (kt00007 - 당일주문체결내역상세).

        API 스펙:
            URL: /api/dostk/acnt
            api-id: kt00007
            Request: qry_tp="3"(전체), stk_bond_tp="0"(전체), sell_tp="0"(전체),
                     dmst_stex_tp="%"(전체)
            Response: acnt_ord_cntr_prps_dtl[].ord_no, cntr_qty, cntr_uv, stk_cd, stk_nm

        Returns:
            dict: {
                "return_code": 0,
                "filled": True/False,
                "filled_qty": int,
                "filled_price": int,
                "ord_no": str,
                "raw": dict,
            }
        """
        self.ensure_token()

        url = self.BASE + "/api/dostk/acnt"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.access_token}",
            "api-id": "kt00007",
        }
        params = {
            "ord_dt": "",           # 당일
            "qry_tp": "3",         # 전체 (1:주문순, 2:역순, 3:전체순, 4:체결내역순)
            "stk_bond_tp": "0",    # 전체
            "sell_tp": "0",        # 전체
            "stk_cd": "",          # 전체 종목
            "fr_ord_no": "",       # 전체 주문
            "dmst_stex_tp": "%",   # 전체 거래소
        }

        try:
            print(f"[체결조회] 주문번호={ord_no} 조회 중... (kt00007)")
            resp = requests.post(url, headers=headers, json=params, timeout=10.0)

            if resp.status_code != 200:
                print(f"[체결조회] HTTP {resp.status_code} 실패")
                return {"return_code": -1, "filled": False, "raw": {}}

            body = resp.json()

            if "return_code" not in body:
                body["return_code"] = 0 if resp.status_code == 200 else -1

            if body.get("return_code") != 0:
                print(f"[체결조회] 실패: {body.get('return_msg', 'N/A')}")
                return {"return_code": body["return_code"], "filled": False, "raw": body}

            # kt00007 응답: acnt_ord_cntr_prps_dtl 리스트
            exec_list = body.get("acnt_ord_cntr_prps_dtl", [])

            # 디버그: 응답 구조 확인
            if exec_list:
                print(f"[체결조회 DEBUG] {len(exec_list)}건 조회됨. 첫 건: {exec_list[0]}")
            else:
                print(f"[체결조회 DEBUG] acnt_ord_cntr_prps_dtl 비어있음. 응답 키: {list(body.keys())}")

            # ord_no에 해당하는 체결 건 찾기
            target_ord_no = str(ord_no).strip().lstrip('0')  # 앞자리 0 제거하여 매칭
            filled_qty = 0
            total_amount = 0

            for item in exec_list:
                if not isinstance(item, dict):
                    continue

                item_ord_no = str(item.get("ord_no", "")).strip().lstrip('0')
                raw_ord_no = str(item.get("ord_no", "")).strip()
                if item_ord_no != target_ord_no and raw_ord_no != str(ord_no).strip():
                    continue

                # cntr_qty: 체결수량, cntr_uv: 체결단가
                qty_str = item.get("cntr_qty") or "0"
                try:
                    q = int(str(qty_str).strip())
                except Exception:
                    q = 0

                price_str = item.get("cntr_uv") or "0"
                try:
                    p = int(str(price_str).strip())
                except Exception:
                    p = 0

                if q > 0:
                    filled_qty += q
                    total_amount += q * p

            filled_price = (total_amount // filled_qty) if filled_qty > 0 else 0

            result = {
                "return_code": 0,
                "filled": filled_qty > 0,
                "filled_qty": filled_qty,
                "filled_price": filled_price,
                "ord_no": target_ord_no,
                "raw": body,
            }

            if filled_qty > 0:
                print(f"[체결조회] 체결 확인: {filled_qty}주 @ {filled_price:,}원")
            else:
                print(f"[체결조회] 미체결 (주문번호={ord_no})")

            return result

        except Exception as e:
            print(f"[체결조회] 오류: {e}")
            traceback.print_exc()
            return {"return_code": -1, "filled": False, "raw": {}}

    # ======================================================
    # 종목 기본 정보 조회
    # ======================================================
    def get_stock_basic_info(self, stock_code: str) -> dict:
        """
        종목 기본 정보 조회 (ka10100)
        """
        code = self._normalize_code(stock_code)
        params = {"stk_cd": code}
        return self._call_mrkcond("ka10100", params)

    # ======================================================
    # 매수 주문 (시장가) - kt10000, /api/dostk/ordr
    # ======================================================
    def buy_market_order(self, stock_code: str, qty: int, current_price: int = None) -> dict:
        """
        시장가 매수 주문 (키움 공식 예제: kt10000)

        Request 예시:
        {
            "dmst_stex_tp" : "KRX",
            "stk_cd" : "005930",
            "ord_qty" : "1",
            "ord_uv" : "",
            "trde_tp" : "3",
            "cond_uv" : ""
        }
        """
        self.ensure_token()

        code = self._normalize_code(stock_code)

        url = self.BASE + "/api/dostk/ordr"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.access_token}",
            "cont-yn": "N",
            "next-key": "",
            "api-id": "kt10000",  # ⭐ 주식 매수주문
        }

        params = {
            "dmst_stex_tp": "KRX",   # 국내거래소구분
            "stk_cd": code,
            "ord_qty": str(qty),
            "ord_uv": "",            # 시장가이므로 공백
            "trde_tp": "3",          # 3: 시장가
            "cond_uv": "",           # 조건단가 없음
        }

        try:
            print(f"[매수 주문] {code} {qty}주 시장가 매수 (kt10000)")
            resp = requests.post(url, headers=headers, json=params, timeout=10.0)

            print(f"[매수 주문 HTTP] {resp.status_code}")
            result = {}
            try:
                result = resp.json()
            except Exception:
                print("[매수 주문] JSON 파싱 실패, text=", resp.text[:200])
                return {"return_code": -1, "return_msg": f"HTTP {resp.status_code}"}

            if "return_code" not in result:
                # 성공 시 예제: {"ord_no": "00024", "return_code":0, "return_msg":"정상적으로 처리되었습니다"}
                result["return_code"] = 0 if resp.status_code == 200 else -1

            if result.get("return_code") == 0:
                print(f"[매수 주문] 성공: {result}")
            else:
                print(f"[매수 주문] 실패: {result}")

            return result

        except Exception as e:
            print(f"[매수 주문] 오류: {e}")
            traceback.print_exc()
            return {"return_code": -1, "return_msg": str(e)}

    # ======================================================
    # 매도 주문 (시장가) - kt10001, /api/dostk/ordr
    # ======================================================
    def sell_market_order(self, stock_code: str, qty: int) -> dict:
        """
        시장가 매도 주문

        ※ 공식 예시 문서는 매수(kt10000)만 나와 있지만,
           일반적으로 매도는 같은 URI(/api/dostk/ordr)에
           매도용 TR ID(예: kt10001)를 사용하는 패턴이므로
           그 구조에 맞춰 구현.

        실제 TR ID가 다르면 여기 api-id만 바꿔주면 됨.
        """
        self.ensure_token()

        code = self._normalize_code(stock_code)

        url = self.BASE + "/api/dostk/ordr"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.access_token}",
            "cont-yn": "N",
            "next-key": "",
            "api-id": "kt10001",  # ⭐ 주식 매도주문 (필요 시 문서 보고 변경)
        }

        params = {
            "dmst_stex_tp": "KRX",
            "stk_cd": code,
            "ord_qty": str(qty),
            "ord_uv": "",
            "trde_tp": "3",   # 시장가
            "cond_uv": "",
        }

        try:
            print(f"[매도 주문] {code} {qty}주 시장가 매도 (kt10001)")
            resp = requests.post(url, headers=headers, json=params, timeout=10.0)

            print(f"[매도 주문 HTTP] {resp.status_code}")
            result = {}
            try:
                result = resp.json()
            except Exception:
                print("[매도 주문] JSON 파싱 실패, text=", resp.text[:200])
                return {"return_code": -1, "return_msg": f"HTTP {resp.status_code}"}

            if "return_code" not in result:
                result["return_code"] = 0 if resp.status_code == 200 else -1

            if result.get("return_code") == 0:
                print(f"[매도 주문] 성공: {result}")
            else:
                print(f"[매도 주문] 실패: {result}")

            return result

        except Exception as e:
            print(f"[매도 주문] 오류: {e}")
            traceback.print_exc()
            return {"return_code": -1, "return_msg": str(e)}
