// StockDetail — 종목 상세 (토스증권 스타일 + DART 톤앤매너)
import { useParams, useNavigate } from 'react-router-dom'
import { useState, useEffect, useMemo } from 'react'
import { useTrading } from '../../contexts/TradingContext'
import { formatPrice, formatPercent, priceClass } from '../../constants/theme'
import { getPrice, getChartData, deleteRule } from '../../lib/api'
import { useToast } from '../common/Toast'
import StockChart from './StockChart'
import OrderDrawer from './OrderDrawer'
import './StockDetail.css'

// 가짜 차트 데이터 생성 (실제 API 연동 전 placeholder)
function generateChartData(basePrice, count = 78) {
  const data = []
  const now = Math.floor(Date.now() / 1000)
  let price = basePrice
  for (let i = count; i >= 0; i--) {
    price = price + (Math.random() - 0.48) * (basePrice * 0.003)
    price = Math.max(price * 0.95, Math.min(price, basePrice * 1.05))
    data.push({ time: now - i * 60, value: Math.round(price) })
  }
  return data
}

export default function StockDetail() {
  const { code } = useParams()
  const navigate = useNavigate()
  const { state } = useTrading()
  const toast = useToast()

  const sig = state.signals[code] || {}
  const [priceData, setPriceData] = useState(null)
  const [activeTab, setActiveTab] = useState('차트')
  const [orderSide, setOrderSide] = useState(null) // 'buy' | 'sell' | null

  const price = Number(priceData?.current_price || sig.current_price || 0)
  const chg = Number(priceData?.change_rate || sig.change_rate || 0)
  const name = priceData?.stock_name || sig.stock_name || sig.name || code

  const [chartData, setChartData] = useState([])

  // 시세 + 차트 데이터 조회
  useEffect(() => {
    getPrice(code).then(d => setPriceData(d)).catch(() => {})
    getChartData(code).then(data => {
      if (data && data.length > 0) {
        setChartData(data)
      } else if (price > 0) {
        // 체결 데이터 없으면 placeholder
        setChartData(generateChartData(price))
      }
    }).catch(() => {
      if (price > 0) setChartData(generateChartData(price))
    })
  }, [code])

  const chartColor = chg >= 0 ? 'var(--positive)' : 'var(--negative)'
  const cssChartColor = chg >= 0 ? '#DC2626' : '#2563EB'

  // 룰 정보
  const rule = state.rules.find(r => r.stock_code === code)

  // 보유 정보
  const position = state.positions.find(p => p.code === code)

  const handleRemove = async () => {
    await deleteRule(code)
    toast('감시목록에서 제거되었어요')
    navigate(-1)
  }

  const tabs = ['차트', '내 주식', '종목정보']

  return (
    <div className="detail" style={{ animation: 'pageEnter 0.45s cubic-bezier(0.32,0.72,0,1)' }}>
      {/* 헤더 */}
      <div className="detail-header">
        <button className="detail-back touch-press" onClick={() => navigate(-1)}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <div style={{ flex: 1 }} />
        {rule && (
          <button className="detail-action touch-press" onClick={handleRemove}>
            감시 해제
          </button>
        )}
      </div>

      {/* 가격 히어로 — 토스 스타일 */}
      <div className="detail-hero">
        <div className="detail-name">{name}</div>
        <div className="detail-price num">
          {price ? formatPrice(price) + '원' : '—'}
        </div>
        <div className={`detail-change num ${priceClass(chg)}`}>
          {price ? `어제보다 ${chg > 0 ? '+' : ''}${formatPrice(Math.abs(Math.round(price * chg / 100)))}원 (${formatPercent(chg)})` : ''}
        </div>
      </div>

      {/* 탭 */}
      <div className="detail-tabs">
        {tabs.map(t => (
          <div
            key={t}
            className={`detail-tab ${activeTab === t ? 'on' : ''}`}
            onClick={() => setActiveTab(t)}
          >
            {t}
          </div>
        ))}
      </div>

      {/* 차트 */}
      {activeTab === '차트' && (
        <div style={{ padding: '16px 0' }}>
          {chartData.length > 0 ? (
            <StockChart data={chartData} color={cssChartColor} height={220} />
          ) : (
            <div className="detail-chart-empty">시세 데이터를 불러오는 중...</div>
          )}
        </div>
      )}

      {/* 내 주식 탭 */}
      {activeTab === '내 주식' && (
        <div className="detail-section" style={{ animation: 'fadeIn 0.25s ease' }}>
          {position ? (
            <div className="detail-info-grid">
              <div className="detail-info-item">
                <span className="detail-info-label">보유수량</span>
                <span className="detail-info-value">{position.qty}주</span>
              </div>
              <div className="detail-info-item">
                <span className="detail-info-label">매입가</span>
                <span className="detail-info-value num">{formatPrice(position.entry_price)}원</span>
              </div>
              <div className="detail-info-item">
                <span className="detail-info-label">현재가</span>
                <span className={`detail-info-value num ${priceClass(position.pnl_rate)}`}>{formatPrice(position.cur_price)}원</span>
              </div>
              <div className="detail-info-item">
                <span className="detail-info-label">수익률</span>
                <span className={`detail-info-value num ${priceClass(position.pnl_rate)}`}>{formatPercent(position.pnl_rate)}</span>
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)', fontSize: 14 }}>
              보유하고 있지 않은 종목이에요
            </div>
          )}
          {rule && (
            <div className="detail-rule-card">
              <div className="detail-rule-title">감시 룰</div>
              <div className="detail-rule-text">
                {rule.condition === 'immediate' ? '즉시 매수' :
                 rule.condition === 'price_below' ? `현재가 ≤ ${formatPrice(rule.threshold)}원` :
                 rule.condition === 'price_above' ? `현재가 ≥ ${formatPrice(rule.threshold)}원` :
                 rule.condition === 'change_above' ? `등락률 ≥ ${rule.threshold}%` :
                 `등락률 ≤ ${rule.threshold}%`}
              </div>
              {(rule.tp != null || rule.sl != null) && (
                <div className="detail-rule-sub">
                  {rule.tp != null ? `TP ${rule.tp}%` : ''} {rule.sl != null ? `SL ${rule.sl}%` : ''}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 종목정보 탭 */}
      {activeTab === '종목정보' && (
        <div className="detail-section" style={{ animation: 'fadeIn 0.25s ease' }}>
          <div className="detail-info-grid">
            <div className="detail-info-item">
              <span className="detail-info-label">종목코드</span>
              <span className="detail-info-value">{code}</span>
            </div>
            <div className="detail-info-item">
              <span className="detail-info-label">현재가</span>
              <span className="detail-info-value num">{formatPrice(price)}원</span>
            </div>
            <div className="detail-info-item">
              <span className="detail-info-label">등락률</span>
              <span className={`detail-info-value num ${priceClass(chg)}`}>{formatPercent(chg)}</span>
            </div>
            <div className="detail-info-item">
              <span className="detail-info-label">거래량</span>
              <span className="detail-info-value num">{formatPrice(sig.volume || 0)}</span>
            </div>
          </div>
        </div>
      )}

      {/* 하단 매수/매도 버튼 — 토스 스타일 */}
      <div className="detail-bottom">
        <button className="detail-btn detail-btn-sell touch-press" onClick={() => setOrderSide('sell')}>판매하기</button>
        <button className="detail-btn detail-btn-buy touch-press" onClick={() => setOrderSide('buy')}>구매하기</button>
      </div>

      {/* 주문 드로어 */}
      <OrderDrawer
        open={orderSide !== null}
        onClose={() => setOrderSide(null)}
        code={code}
        name={name}
        price={price}
        side={orderSide || 'buy'}
      />
    </div>
  )
}
