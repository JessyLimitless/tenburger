// 홍보용 데모 데이터 — 실제 가격 기준
export const DEMO_STATE = {
  connected: true,
  is_trading: true,
  ws_connected: true,
  cash: 4_235_600,
  position_count: 3,
  positions: [
    {
      code: '005930', name: '삼성전자', qty: 10,
      entry_price: 195000, cur_price: 200000,
      pnl_rate: 2.56, pnl_amount: 50000,
    },
    {
      code: '000660', name: 'SK하이닉스', qty: 2,
      entry_price: 980000, cur_price: 1000000,
      pnl_rate: 2.04, pnl_amount: 40000,
    },
    {
      code: '005380', name: '현대자동차', qty: 4,
      entry_price: 510000, cur_price: 500000,
      pnl_rate: -1.96, pnl_amount: -40000,
    },
  ],
  signals: {
    '005930': { stock_code: '005930', stock_name: '삼성전자', current_price: 200000, change_rate: 2.56, volume: 18_432_100, time: '14:45:32' },
    '000660': { stock_code: '000660', stock_name: 'SK하이닉스', current_price: 1000000, change_rate: 1.28, volume: 2_156_800, time: '14:45:28' },
    '005380': { stock_code: '005380', stock_name: '현대자동차', current_price: 500000, change_rate: -0.42, volume: 1_823_400, time: '14:45:25' },
  },
  rules: [
    { stock_code: '005930', stock_name: '삼성전자', condition: 'price_below', threshold: 196000, tp: 3.0, sl: -2.0, enabled: true, triggered: true },
    { stock_code: '000660', stock_name: 'SK하이닉스', condition: 'price_below', threshold: 990000, tp: 5.0, sl: -3.0, enabled: true, triggered: true },
    { stock_code: '005380', stock_name: '현대자동차', condition: 'price_below', threshold: 520000, tp: 2.5, sl: -2.0, enabled: true, triggered: true },
  ],
  rejected_codes: [],
  settings: {
    buy_amount: 1_500_000,
    max_stocks: 5,
    stop_loss_rate: -2.0,
    profit_cut_rate: 3.0,
  },
  logs: [
    { time: '09:00:15', action: '시스템', details: 'DART Trading 자동매매가 시작되었습니다' },
    { time: '09:03:42', action: '룰트리거', details: '삼성전자(005930) 현재가(195,000) ≤ 196,000원 조건 충족' },
    { time: '09:03:43', action: '매수주문', details: '삼성전자(005930) 시장가 매수 10주 접수' },
    { time: '09:03:44', action: '체결확인', details: '삼성전자(005930) 매수 체결: 10주 @ 195,000원 (주문번호: 0000051)' },
    { time: '09:31:15', action: '룰트리거', details: 'SK하이닉스(000660) 현재가(980,000) ≤ 990,000원 조건 충족' },
    { time: '09:31:16', action: '매수주문', details: 'SK하이닉스(000660) 시장가 매수 2주 접수' },
    { time: '09:31:18', action: '체결확인', details: 'SK하이닉스(000660) 매수 체결: 2주 @ 980,000원 (주문번호: 0000058)' },
    { time: '10:15:33', action: '룰트리거', details: '현대자동차(005380) 현재가(510,000) ≤ 520,000원 조건 충족' },
    { time: '10:15:34', action: '매수주문', details: '현대자동차(005380) 시장가 매수 4주 접수' },
    { time: '10:15:36', action: '체결확인', details: '현대자동차(005380) 매수 체결: 4주 @ 510,000원 (주문번호: 0000072)' },
    { time: '13:22:10', action: '시스템', details: '보유 3종목 실시간 감시 중 (TP/SL 자동 체크)' },
    { time: '14:45:00', action: '시스템', details: '삼성전자 +2.56% | SK하이닉스 +2.04% | 현대자동차 -1.96%' },
  ],
}

// 데모용 시세 변동 시뮬레이션
export function simulatePriceUpdate(state) {
  const newSignals = { ...state.signals }
  const newPositions = [...state.positions]

  Object.keys(newSignals).forEach(code => {
    const sig = { ...newSignals[code] }
    const base = sig.current_price
    // 종목별 변동폭 차등
    const volatility = base > 500000 ? 0.001 : 0.002
    const change = base * (Math.random() - 0.47) * volatility
    sig.current_price = Math.round((base + change) / 100) * 100 // 100원 단위
    sig.change_rate = +((sig.current_price / (base / (1 + sig.change_rate / 100)) - 1) * 100).toFixed(2)
    const now = new Date()
    sig.time = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`
    sig.volume = sig.volume + Math.floor(Math.random() * 5000)
    newSignals[code] = sig

    const posIdx = newPositions.findIndex(p => p.code === code)
    if (posIdx >= 0) {
      const pos = { ...newPositions[posIdx] }
      pos.cur_price = sig.current_price
      pos.pnl_rate = +((sig.current_price - pos.entry_price) / pos.entry_price * 100).toFixed(2)
      pos.pnl_amount = (sig.current_price - pos.entry_price) * pos.qty
      newPositions[posIdx] = pos
    }
  })

  return { signals: newSignals, positions: newPositions }
}

// 자동매매 활동 로그 생성 (가끔씩)
const LIVE_MESSAGES = [
  (s) => `삼성전자 현재가 ${Number(s['005930']?.current_price||0).toLocaleString()}원 감시 중`,
  (s) => `SK하이닉스 수익률 ${s['000660']?.change_rate||0}% 모니터링`,
  (s) => `현대자동차 TP/SL 체크 완료 (현재 ${Number(s['005380']?.current_price||0).toLocaleString()}원)`,
  () => '보유 3종목 실시간 TP/SL 자동 체크 중',
  () => '키움 WebSocket 정상 연결 · REAL 시세 수신 중',
  (s) => `삼성전자 ${Number(s['005930']?.volume||0).toLocaleString()}주 거래됨`,
]

export function generateLiveLog(signals) {
  const now = new Date()
  const time = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`
  const msg = LIVE_MESSAGES[Math.floor(Math.random() * LIVE_MESSAGES.length)]
  return { time, action: '시스템', details: msg(signals) }
}
