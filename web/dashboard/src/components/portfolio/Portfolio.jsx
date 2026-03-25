// Portfolio — 보유종목 (토스 스타일)
import { useNavigate } from 'react-router-dom'
import { useTrading } from '../../contexts/TradingContext'
import { formatPrice, formatPercent, priceClass } from '../../constants/theme'
import StockAvatar from '../common/StockAvatar'

export default function Portfolio() {
  const { state } = useTrading()
  const navigate = useNavigate()
  const positions = Array.isArray(state.positions) ? state.positions : []

  if (!positions.length) {
    return (
      <div style={{ textAlign: 'center', padding: '72px 24px', animation: 'fadeIn .3s ease' }}>
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-caption)" strokeWidth="1.2">
          <rect x="3" y="12" width="5" height="9" rx="1.5"/><rect x="9.5" y="7" width="5" height="14" rx="1.5"/><rect x="16" y="3" width="5" height="18" rx="1.5"/>
        </svg>
        <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-secondary)', margin: '16px 0 4px' }}>
          보유 종목이 없어요
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5 }}>
          자동매매를 시작하면 여기에 표시돼요
        </div>
      </div>
    )
  }

  const totalValue = positions.reduce((s, p) => s + (p.cur_price || 0) * (p.qty || 0), 0)
  const totalPnl = positions.reduce((s, p) => s + (p.pnl_amount || 0), 0)
  const totalInvested = positions.reduce((s, p) => s + (p.entry_price || 0) * (p.qty || 0), 0)
  const totalPnlRate = totalInvested > 0 ? (totalPnl / totalInvested * 100) : 0

  return (
    <div style={{ paddingBottom: 'calc(80px + env(safe-area-inset-bottom, 0px))', animation: 'pageEnter .4s cubic-bezier(.32,.72,0,1)' }}>
      {/* 요약 */}
      <div style={{ padding: '20px 24px 16px' }}>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 500 }}>총 평가금액</div>
        <div className="num" style={{ fontSize: 28, fontWeight: 800, color: 'var(--text-primary)', margin: '6px 0 3px', letterSpacing: '-1px' }}>
          {formatPrice(totalValue)}<span style={{ fontSize: 16, fontWeight: 600, marginLeft: 1 }}>원</span>
        </div>
        <div className={`num ${priceClass(totalPnl)}`} style={{ fontSize: 14, fontWeight: 600 }}>
          {totalPnl > 0 ? '+' : ''}{formatPrice(totalPnl)}원 ({totalPnlRate > 0 ? '+' : ''}{totalPnlRate.toFixed(2)}%)
        </div>
      </div>

      <div style={{ height: 8, background: 'var(--bg-secondary)' }} />

      <div style={{ padding: '16px 24px 8px' }}>
        <div style={{ fontSize: 17, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-.3px' }}>
          보유 {positions.length}종목
        </div>
      </div>

      {positions.map((p, i) => {
        const r = p.pnl_rate || 0
        const a = p.pnl_amount || 0
        return (
          <div
            key={p.code}
            className="stock-item"
            style={{ animationDelay: `${i * 50}ms`, cursor: 'pointer' }}
            onClick={() => navigate(`/stock/${p.code}`)}
          >
            <StockAvatar code={p.code} name={p.name} />
            <div className="stock-item-body">
              <div className="stock-item-name">
                {p.name || p.code}
                <span className="badge badge-holding">{p.qty}주</span>
              </div>
              <div className="stock-item-sub">매입 {formatPrice(p.entry_price)}원</div>
            </div>
            <div className="stock-item-right">
              <div className="stock-item-price num">{formatPrice(p.cur_price)}</div>
              <div className={`stock-item-change num ${priceClass(r)}`}>
                {r > 0 ? '+' : ''}{formatPrice(a)}원 ({formatPercent(r)})
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
