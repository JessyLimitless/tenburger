// StockDetail — 종목 상세 (버그 수정: 캐시/시세)
import { useParams, useNavigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { useTrading } from '../../contexts/TradingContext'
import { formatPrice, formatPercent, priceClass } from '../../constants/theme'
import { getPrice, getChartData, deleteRule } from '../../lib/api'
import { useToast } from '../common/Toast'
import StockChart from './StockChart'
import OrderDrawer from './OrderDrawer'
import './StockDetail.css'

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

  // 종목 변경 시 모든 상태 초기화
  const [priceData, setPriceData] = useState(null)
  const [chartData, setChartData] = useState([])
  const [activeTab, setActiveTab] = useState('차트')
  const [orderSide, setOrderSide] = useState(null)
  const [loading, setLoading] = useState(true)

  // 종목 변경 시 초기화 + 데이터 새로 로드
  useEffect(() => {
    setPriceData(null)
    setChartData([])
    setActiveTab('차트')
    setOrderSide(null)
    setLoading(true)

    // 시세 조회
    getPrice(code).then(d => {
      setPriceData(d)
      const p = Number(d?.current_price || 0)

      // 차트 데이터
      getChartData(code).then(cdata => {
        if (cdata && cdata.length > 0) {
          setChartData(cdata)
        } else if (p > 0) {
          setChartData(generateChartData(p))
        }
        setLoading(false)
      }).catch(() => {
        if (p > 0) setChartData(generateChartData(p))
        setLoading(false)
      })
    }).catch(() => setLoading(false))
  }, [code])

  // 실시간 시세 (WebSocket에서 업데이트)
  const sig = state.signals[code] || {}
  const livePrice = Number(sig.current_price || 0)
  const price = livePrice || Number(priceData?.current_price || 0)
  const chg = Number(sig.change_rate || priceData?.change_rate || 0)
  const name = sig.stock_name || priceData?.stock_name || sig.name || code
  const volume = Number(sig.volume || priceData?.volume || 0)

  // 실시간 틱 → 차트에 포인트 추가
  useEffect(() => {
    if (livePrice > 0 && chartData.length > 0) {
      const now = Math.floor(Date.now() / 1000)
      const last = chartData[chartData.length - 1]
      if (now > last.time) {
        setChartData(prev => [...prev, { time: now, value: livePrice }])
      }
    }
  }, [livePrice])

  const cssChartColor = chg >= 0 ? '#E8363C' : '#3478F6'

  // 룰 정보
  const rule = state.rules.find(r => r.stock_code === code)

  // 보유 정보 — code 키 다양한 형태 매칭
  const positions = Array.isArray(state.positions) ? state.positions : []
  const position = positions.find(p => p.code === code || p.stock_code === code)

  const handleRemove = async () => {
    await deleteRule(code)
    toast('감시목록에서 제거되었어요')
    navigate(-1)
  }

  const tabs = ['차트', '내 주식', '종목정보']

  return (
    <div className="detail" style={{ animation: 'pageEnter .4s cubic-bezier(.32,.72,0,1)' }}>
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

      {/* 가격 히어로 */}
      <div className="detail-hero">
        <div className="detail-name">{name}</div>
        {loading ? (
          <div className="detail-price num" style={{ color: 'var(--text-muted)' }}>불러오는 중...</div>
        ) : (
          <>
            <div className="detail-price num">
              {price ? formatPrice(price) + '원' : '—'}
            </div>
            <div className={`detail-change num ${priceClass(chg)}`}>
              {price ? `어제보다 ${chg > 0 ? '+' : ''}${formatPrice(Math.abs(Math.round(price * chg / 100)))}원 (${formatPercent(chg)})` : ''}
            </div>
          </>
        )}
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
            <div className="detail-chart-empty">
              {loading ? '차트 데이터 로드 중...' : '차트 데이터 없음'}
            </div>
          )}
        </div>
      )}

      {/* 내 주식 탭 */}
      {activeTab === '내 주식' && (
        <div className="detail-section" style={{ animation: 'fadeIn 0.2s ease' }}>
          {position ? (
            <div className="detail-info-grid">
              <div className="detail-info-item">
                <span className="detail-info-label">보유수량</span>
                <span className="detail-info-value">{position.qty}주</span>
              </div>
              <div className="detail-info-item">
                <span className="detail-info-label">매입가</span>
                <span className="detail-info-value num">{formatPrice(position.entry_price || position.avg_price)}원</span>
              </div>
              <div className="detail-info-item">
                <span className="detail-info-label">현재가</span>
                <span className={`detail-info-value num ${priceClass(position.pnl_rate)}`}>{formatPrice(position.cur_price || price)}원</span>
              </div>
              <div className="detail-info-item">
                <span className="detail-info-label">수익률</span>
                <span className={`detail-info-value num ${priceClass(position.pnl_rate)}`}>{formatPercent(position.pnl_rate)}</span>
              </div>
              <div className="detail-info-item">
                <span className="detail-info-label">평가금액</span>
                <span className="detail-info-value num">{formatPrice((position.cur_price || price) * position.qty)}원</span>
              </div>
              <div className="detail-info-item">
                <span className="detail-info-label">평가손익</span>
                <span className={`detail-info-value num ${priceClass(position.pnl_amount)}`}>
                  {position.pnl_amount > 0 ? '+' : ''}{formatPrice(position.pnl_amount)}원
                </span>
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
                  {rule.tp != null ? `익절 ${rule.tp}%` : ''} {rule.sl != null ? `손절 ${rule.sl}%` : ''}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 종목정보 탭 */}
      {activeTab === '종목정보' && (
        <div className="detail-section" style={{ animation: 'fadeIn 0.2s ease' }}>
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
              <span className="detail-info-value num">{formatPrice(volume)}</span>
            </div>
          </div>
        </div>
      )}

      {/* 하단 매수/매도 버튼 */}
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
