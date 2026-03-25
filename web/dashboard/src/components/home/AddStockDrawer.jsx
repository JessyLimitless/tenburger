// AddStockDrawer — 종목 검색 + 시세 미리보기 + 룰 추가
import { useState, useRef, useEffect, useCallback } from 'react'
import Drawer from '../common/Drawer'
import { searchStocks, getPrice, addRule } from '../../lib/api'
import { useToast } from '../common/Toast'
import { formatPrice, formatPercent, priceClass } from '../../constants/theme'
import './AddStockDrawer.css'

export default function AddStockDrawer({ open, onClose }) {
  const toast = useToast()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [selected, setSelected] = useState(null)
  const [preview, setPreview] = useState(null)
  const [condition, setCondition] = useState('immediate')
  const [threshold, setThreshold] = useState('')
  const [tp, setTp] = useState('')
  const [sl, setSl] = useState('')
  const [loading, setLoading] = useState(false)
  const searchTimer = useRef(null)
  const inputRef = useRef(null)

  // 드로어 열릴 때 초기화
  useEffect(() => {
    if (open) {
      setQuery(''); setResults([]); setSelected(null); setPreview(null)
      setCondition('immediate'); setThreshold(''); setTp(''); setSl('')
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 400)
    }
  }, [open])

  // 검색
  const handleSearch = useCallback((q) => {
    setQuery(q)
    setSelected(null)
    setPreview(null)
    clearTimeout(searchTimer.current)
    if (!q || q.length < 1) { setResults([]); return }
    setLoading(true)
    searchTimer.current = setTimeout(async () => {
      try {
        const items = await searchStocks(q)
        setResults(items)
      } catch { setResults([]) }
      setLoading(false)
    }, 250)
  }, [])

  // 종목 선택
  const handleSelect = useCallback(async (item) => {
    setSelected(item)
    setQuery(item.name)
    setResults([])  // 결과 닫기
    setPreview(null)
    try {
      const data = await getPrice(item.code)
      setPreview(data)
    } catch {
      setPreview({ current_price: 0 })
    }
  }, [])

  // 제출
  const handleSubmit = async () => {
    if (!selected) return
    await addRule({
      code: selected.code,
      condition,
      threshold: parseFloat(threshold) || 0,
      tp: tp ? parseFloat(tp) : null,
      sl: sl ? parseFloat(sl) : null,
    })
    toast(`${selected.name} 감시 종목이 추가되었어요`)
    onClose()
  }

  const price = preview ? Number(preview.current_price || 0) : 0
  const chg = preview ? Number(preview.change_rate || 0) : 0
  const showResults = !selected && results.length > 0

  return (
    <Drawer open={open} onClose={onClose} title="종목 추가">
      {/* 검색 */}
      <div className="add-field">
        <label className="add-label">종목 검색</label>
        <div className="add-search-wrap">
          <input
            ref={inputRef}
            className="add-input"
            value={query}
            onChange={(e) => handleSearch(e.target.value)}
            placeholder="종목명 또는 코드를 입력하세요"
            autoComplete="off"
          />
          {selected && (
            <button className="add-clear" onClick={() => { setSelected(null); setQuery(''); setPreview(null); setResults([]); inputRef.current?.focus() }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* 검색 결과 — 인라인 리스트 */}
      {showResults && (
        <div className="add-results">
          {results.map(item => (
            <div
              key={item.code}
              className="add-result-item touch-press"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => handleSelect(item)}
            >
              <div className="add-result-name">{item.name}</div>
              <div className="add-result-code">{item.code} · {item.market}</div>
            </div>
          ))}
        </div>
      )}

      {/* 로딩 */}
      {loading && !showResults && query && (
        <div className="add-loading">검색 중...</div>
      )}

      {/* 시세 미리보기 */}
      {selected && preview && (
        <div className="add-preview" style={{ animation: 'fadeIn 0.2s ease' }}>
          <div>
            <div className="add-preview-name">{selected.name}</div>
            <div className="add-preview-code">{selected.code} · {selected.market}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className={`add-preview-price num ${priceClass(chg)}`}>
              {price ? formatPrice(price) + '원' : '시세 없음'}
            </div>
            <div className={`add-preview-change num ${priceClass(chg)}`}>
              {price ? `${chg > 0 ? '+' : ''}${formatPercent(chg)}` : ''}
            </div>
          </div>
        </div>
      )}

      {/* 매수 조건 */}
      {selected && (
        <>
          <div className="add-field" style={{ animation: 'fadeIn 0.2s ease' }}>
            <label className="add-label">매수 조건</label>
            <select className="add-input add-select" value={condition} onChange={e => setCondition(e.target.value)}>
              <option value="immediate">즉시 매수</option>
              <option value="price_below">현재가 이하이면 매수</option>
              <option value="price_above">현재가 이상이면 매수</option>
              <option value="change_above">등락률 이상이면 매수</option>
              <option value="change_below">등락률 이하이면 매수</option>
            </select>
          </div>

          {condition !== 'immediate' && (
            <div className="add-field" style={{ animation: 'fadeIn 0.15s ease' }}>
              <label className="add-label">기준값</label>
              <input
                className="add-input num"
                type="number"
                step="any"
                value={threshold}
                onChange={e => setThreshold(e.target.value)}
                placeholder={condition.includes('price') ? '가격 (원)' : '등락률 (%)'}
              />
            </div>
          )}

          <div className="add-row">
            <div className="add-field" style={{ flex: 1 }}>
              <label className="add-label">익절 % (선택)</label>
              <input className="add-input num" type="number" step="0.1" value={tp} onChange={e => setTp(e.target.value)} placeholder="글로벌" />
            </div>
            <div className="add-field" style={{ flex: 1 }}>
              <label className="add-label">손절 % (선택)</label>
              <input className="add-input num" type="number" step="0.1" value={sl} onChange={e => setSl(e.target.value)} placeholder="글로벌" />
            </div>
          </div>
        </>
      )}

      <button
        className={`add-submit touch-press ${selected ? 'active' : ''}`}
        onClick={handleSubmit}
        disabled={!selected}
      >
        {selected ? `${selected.name} 추가하기` : '종목을 먼저 선택하세요'}
      </button>
    </Drawer>
  )
}
