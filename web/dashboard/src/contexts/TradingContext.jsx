// DART Trading — Global State + WebSocket
import { createContext, useContext, useEffect, useReducer, useCallback, useRef } from 'react'

const TradingContext = createContext(null)

const initialState = {
  connected: false,
  is_trading: false,
  ws_connected: false,
  cash: 0,
  position_count: 0,
  positions: [],
  signals: {},
  rules: [],
  rejected_codes: [],
  logs: [],
  settings: {
    condition_seq: '1',
    buy_amount: 5000,
    max_stocks: 1,
    stop_loss_rate: -2.0,
    profit_cut_rate: 2.0,
  },
}

function reducer(state, action) {
  switch (action.type) {
    case 'INIT': {
      // positions는 서버에서 객체({})로 오지만 프론트는 배열([])을 기대
      const d = action.data
      return {
        ...state,
        ...d,
        connected: true,
        positions: Array.isArray(d.positions) ? d.positions : [],
        rules: Array.isArray(d.rules) ? d.rules : [],
        signals: (d.signals && typeof d.signals === 'object') ? d.signals : {},
        settings: {
          condition_seq: d.condition_seq || state.settings.condition_seq,
          buy_amount: d.buy_amount || state.settings.buy_amount,
          max_stocks: d.max_stocks || state.settings.max_stocks,
          stop_loss_rate: d.stop_loss_rate ?? state.settings.stop_loss_rate,
          profit_cut_rate: d.profit_cut_rate ?? state.settings.profit_cut_rate,
        },
        logs: Array.isArray(d.logs) ? d.logs : [],
      }
    }

    case 'ACCOUNT':
      return {
        ...state,
        cash: action.data.cash ?? state.cash,
        position_count: action.data.position_count ?? state.position_count,
      }

    case 'SIGNAL':
      const code = (action.data.stock_code || '').replace(/^A/, '')
      if (!code) return state
      return {
        ...state,
        signals: { ...state.signals, [code]: action.data },
      }

    case 'POSITIONS':
      return {
        ...state,
        positions: action.data.list || [],
        position_count: action.data.count ?? state.position_count,
        cash: action.data.cash ?? state.cash,
      }

    case 'LOG':
      return {
        ...state,
        logs: [action.data, ...state.logs].slice(0, 200),
      }

    case 'STATUS':
      return { ...state, is_trading: action.data.is_trading }

    case 'RULES':
      return { ...state, rules: action.data.rules || [] }

    case 'REJECT': {
      const { code: rc, rejected } = action.data
      const rj = new Set(state.rejected_codes)
      rejected ? rj.add(rc) : rj.delete(rc)
      return { ...state, rejected_codes: [...rj] }
    }

    case 'SETTINGS':
      return {
        ...state,
        ...action.data,
        settings: {
          condition_seq: action.data.condition_seq || state.settings.condition_seq,
          buy_amount: action.data.buy_amount || state.settings.buy_amount,
          max_stocks: action.data.max_stocks || state.settings.max_stocks,
          stop_loss_rate: action.data.stop_loss_rate ?? state.settings.stop_loss_rate,
          profit_cut_rate: action.data.profit_cut_rate ?? state.settings.profit_cut_rate,
        },
      }

    case 'DISCONNECTED':
      return { ...state, connected: false }

    default:
      return state
  }
}

// 데모 모드 감지
function isDemo() {
  return new URLSearchParams(window.location.search).has('demo')
}

export function TradingProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)
  const demoTimerRef = useRef(null)

  // 데모 모드 — 백엔드 없이 가짜 데이터로 실행
  const startDemo = useCallback(async () => {
    const { DEMO_STATE, simulatePriceUpdate, generateLiveLog } = await import('../lib/demoData.js')
    dispatch({ type: 'INIT', data: DEMO_STATE })

    let tick = 0
    // 1.2초마다 시세 변동
    demoTimerRef.current = setInterval(() => {
      const updated = simulatePriceUpdate(stateRef.current)
      dispatch({ type: 'POSITIONS', data: { list: updated.positions, count: updated.positions.length, cash: stateRef.current.cash } })
      Object.values(updated.signals).forEach(sig => {
        dispatch({ type: 'SIGNAL', data: sig })
      })
      // 5틱마다 활동 로그 추가 (자동매매 느낌)
      tick++
      if (tick % 5 === 0) {
        dispatch({ type: 'LOG', data: generateLiveLog(updated.signals) })
      }
    }, 1200)
  }, [])

  // stateRef — 인터벌 콜백에서 최신 state 접근용
  const stateRef = useRef(state)
  stateRef.current = state

  const connect = useCallback(() => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws`)

    ws.onopen = () => console.log('[WS] Connected')

    ws.onmessage = (e) => {
      try {
        const { type, data } = JSON.parse(e.data)

        // 체결 시 브라우저 알림
        if (type === 'execution' && data?.details) {
          try {
            if (Notification.permission === 'granted') {
              new Notification('DART Trading', { body: data.details, icon: '/favicon.svg' })
            } else if (Notification.permission !== 'denied') {
              Notification.requestPermission()
            }
          } catch {}
        }

        const map = {
          init: 'INIT',
          account: 'ACCOUNT',
          signal_new: 'SIGNAL',
          signal_update: 'SIGNAL',
          positions: 'POSITIONS',
          log: 'LOG',
          execution: 'LOG',
          status: 'STATUS',
          rules: 'RULES',
          reject: 'REJECT',
          settings: 'SETTINGS',
        }
        if (map[type]) dispatch({ type: map[type], data })
      } catch (err) {
        console.error('[WS] Parse error', err)
      }
    }

    ws.onclose = () => {
      dispatch({ type: 'DISCONNECTED' })
      reconnectRef.current = setTimeout(connect, 3000)
    }

    ws.onerror = () => ws.close()
    wsRef.current = ws
  }, [])

  useEffect(() => {
    if (isDemo()) {
      startDemo()
    } else {
      connect()
    }
    return () => {
      clearTimeout(reconnectRef.current)
      clearInterval(demoTimerRef.current)
      wsRef.current?.close()
    }
  }, [connect, startDemo])

  return (
    <TradingContext.Provider value={{ state, dispatch }}>
      {children}
    </TradingContext.Provider>
  )
}

export function useTrading() {
  const ctx = useContext(TradingContext)
  if (!ctx) throw new Error('useTrading must be inside TradingProvider')
  return ctx
}

export function useSignal(code) {
  const { state } = useTrading()
  return state.signals[code] || null
}
