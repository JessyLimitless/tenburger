// Home — Premium Trading Dashboard
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTrading } from '../../contexts/TradingContext'
import { formatPrice, formatPercent, priceClass } from '../../constants/theme'
import { startTrading, stopTrading, deleteRule } from '../../lib/api'
import { useToast } from '../common/Toast'
import AddStockDrawer from './AddStockDrawer'
import StockAvatar from '../common/StockAvatar'
import './Home.css'

export default function Home() {
  const { state } = useTrading()
  const toast = useToast()
  const navigate = useNavigate()
  const [addOpen, setAddOpen] = useState(false)

  const handleToggle = async () => {
    if (state.is_trading) {
      await stopTrading()
      toast('자동매매가 중지되었어요')
    } else {
      await startTrading({
        buy_amount: state.settings.buy_amount,
        max_stocks: state.settings.max_stocks,
        stop_loss: state.settings.stop_loss_rate,
        take_profit: state.settings.profit_cut_rate,
      })
      toast('자동매매가 시작되었어요')
    }
  }

  const handleDelete = (e, code) => {
    e.stopPropagation()
    deleteRule(code)
    toast('종목이 제거되었어요')
  }

  const positions = Array.isArray(state.positions) ? state.positions : []
  const posValue = positions.reduce((sum, p) => sum + (p.cur_price || 0) * (p.qty || 0), 0)
  const totalPnl = positions.reduce((sum, p) => sum + (p.pnl_amount || 0), 0)
  const totalValue = posValue + (state.cash || 0)

  const rules = state.rules || []
  const logs = state.logs || []
  const condLabels = {
    immediate: '즉시 매수',
    price_below: (t) => `${formatPrice(t)}원 이하`,
    price_above: (t) => `${formatPrice(t)}원 이상`,
    change_above: (t) => `등락률 ${t}% 이상`,
    change_below: (t) => `등락률 ${t}% 이하`,
  }

  return (
    <div className="home" style={{ animation: 'pageEnter .4s cubic-bezier(.32,.72,0,1)' }}>

      {/* ── Hero ── */}
      <div className="home-hero">
        <div className="home-hero-top">
          <div>
            <div className="home-hero-label">내 투자</div>
            <div className="home-hero-amount num">{formatPrice(totalValue)}<span>원</span></div>
            {totalPnl !== 0 ? (
              <div className={`home-hero-pnl num ${priceClass(totalPnl)}`}>
                {totalPnl > 0 ? '+' : ''}{formatPrice(totalPnl)}원
              </div>
            ) : (
              <div className="home-hero-pnl" style={{color:'var(--text-muted)'}}>—</div>
            )}
          </div>
          <div className="home-hero-right">
            <div className="home-hero-chip">
              <span className="home-hero-chip-label">매수가능</span>
              <span className="home-hero-chip-value num">{formatPrice(state.cash || 0)}</span>
            </div>
            <div className="home-hero-chip">
              <span className="home-hero-chip-label">보유</span>
              <span className="home-hero-chip-value">{state.position_count || 0}종목</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── CTA ── */}
      <div className="home-cta">
        <button
          className={`home-cta-btn touch-press ${state.is_trading ? 'stop' : 'go'}`}
          onClick={handleToggle}
        >
          {state.is_trading ? (
            <>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>
              자동매매 중지
            </>
          ) : (
            <>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21"/></svg>
              자동매매 시작
            </>
          )}
        </button>
      </div>

      <div className="home-divider" />

      {/* ── 감시목록 ── */}
      <div className="home-section-header">
        <h3>감시목록</h3>
        <span className="home-section-count">{rules.length}</span>
      </div>

      {rules.length === 0 ? (
        <div className="home-empty">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-caption)" strokeWidth="1.2">
            <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
          </svg>
          <div className="home-empty-title">감시 중인 종목이 없어요</div>
          <div className="home-empty-desc">종목을 추가하고 자동매매를 시작해보세요</div>
          <div className="home-suggest">
            {[
              { code: '005930', name: '삼성전자' },
              { code: '000660', name: 'SK하이닉스' },
              { code: '035720', name: '카카오' },
            ].map(s => (
              <button key={s.code} className="home-suggest-btn touch-press" onClick={() => setAddOpen(true)}>
                {s.name}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div>
          {rules.map((rule, i) => {
            const sig = state.signals[rule.stock_code] || {}
            const price = Number(sig.current_price || 0)
            const chg = Number(sig.change_rate || 0)
            const cond = condLabels[rule.condition]
            const condText = typeof cond === 'function' ? cond(rule.threshold) : cond

            return (
              <div
                key={rule.stock_code}
                className="stock-item"
                style={{ animationDelay: `${i * 50}ms` }}
                onClick={() => navigate(`/stock/${rule.stock_code}`)}
              >
                <StockAvatar code={rule.stock_code} name={rule.stock_name} />
                <div className="stock-item-body">
                  <div className="stock-item-name">
                    {rule.stock_name || rule.stock_code}
                    {rule.triggered
                      ? <span className="badge badge-triggered">체결</span>
                      : rule.enabled
                        ? <span className="badge badge-watching">감시</span>
                        : null}
                  </div>
                  <div className="stock-item-sub">{condText}</div>
                </div>
                <div className="stock-item-right">
                  {price ? (
                    <>
                      <div className="stock-item-price num">{formatPrice(price)}원</div>
                      <div className={`stock-item-change num ${priceClass(chg)}`}>{formatPercent(chg)}</div>
                    </>
                  ) : (
                    <div style={{color:'var(--text-caption)',fontSize:13}}>—</div>
                  )}
                </div>
                <button className="stock-item-delete touch-press" onClick={(e) => handleDelete(e, rule.stock_code)}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                  </svg>
                </button>
              </div>
            )
          })}
        </div>
      )}

      {/* ── 최근 매매 ── */}
      {logs.length > 0 && (
        <>
          <div className="home-divider" />
          <div className="home-section-header">
            <h3>최근 매매</h3>
          </div>
          <div className="home-recent">
            {logs.slice(0, 5).map((log, i) => {
              const a = (log.action || '').toLowerCase()
              const isExec = a.includes('체결')
              const isBuy = a.includes('매수')
              const isSell = a.includes('매도')
              const isTrigger = a.includes('룰') || a.includes('trigger')
              const dotColor = isExec ? '#7C3AED' : isBuy ? 'var(--accent)' : isSell ? 'var(--blue)' : isTrigger ? 'var(--green)' : 'var(--text-caption)'
              return (
                <div key={i} className="home-recent-item" style={{ animationDelay: `${i * 40}ms` }}>
                  <div className="home-recent-dot" style={{ background: dotColor }} />
                  <div className="home-recent-body">
                    <div className="home-recent-text">{log.details}</div>
                    <div className="home-recent-time">{log.time}</div>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}

      <button className="fab touch-press" onClick={() => setAddOpen(true)}>+</button>
      <AddStockDrawer open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  )
}
