// DART Trading — API client

const BASE = ''  // same origin

export async function post(path, body = {}) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return res.json()
}

export async function del(path, body = {}) {
  const res = await fetch(BASE + path, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return res.json()
}

export async function get(path) {
  const res = await fetch(BASE + path)
  return res.json()
}

// 종목 검색
export async function searchStocks(query) {
  if (!query || query.length < 1) return []
  const data = await get(`/api/search?q=${encodeURIComponent(query)}`)
  return data.results || []
}

// 시세 조회
export async function getPrice(code) {
  return get(`/api/price/${code}`)
}

// 차트 데이터
export async function getChartData(code) {
  const data = await get(`/api/chart/${code}`)
  return data.data || []
}

// 자동매매
export const startTrading = (params) => post('/api/start', params)
export const stopTrading = () => post('/api/stop')

// 룰
export const addRule = (rule) => post('/api/rules', rule)
export const deleteRule = (code) => del('/api/rules', { code })

// 설정
export const saveSettings = (s) => post('/api/settings', s)

// 종목 거부
export const rejectStock = (code) => post('/api/reject', { code })

// 수동 주문
export const buyStock = (code, qty = 1) => post('/api/order', { code, qty, side: 'buy' })
export const sellStock = (code, qty = 1) => post('/api/order', { code, qty, side: 'sell' })
