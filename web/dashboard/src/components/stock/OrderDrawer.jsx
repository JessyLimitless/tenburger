// OrderDrawer — 매수/매도 수량 입력 + 주문 실행
import { useState } from 'react'
import Drawer from '../common/Drawer'
import { buyStock, sellStock } from '../../lib/api'
import { useToast } from '../common/Toast'
import { formatPrice } from '../../constants/theme'
import './OrderDrawer.css'

export default function OrderDrawer({ open, onClose, code, name, price, side = 'buy' }) {
  const toast = useToast()
  const [qty, setQty] = useState(1)
  const [loading, setLoading] = useState(false)

  const isBuy = side === 'buy'
  const totalAmount = (price || 0) * qty

  const handleOrder = async () => {
    if (qty <= 0) return
    setLoading(true)
    try {
      const result = isBuy ? await buyStock(code, qty) : await sellStock(code, qty)
      if (result.ok) {
        toast(`${name} ${qty}주 ${isBuy ? '매수' : '매도'} 주문이 접수되었어요`)
        onClose()
      } else {
        toast(`주문 실패: ${result.result?.return_msg || '알 수 없는 오류'}`)
      }
    } catch (e) {
      toast('주문 중 오류가 발생했어요')
    } finally {
      setLoading(false)
    }
  }

  const qtyButtons = [1, 5, 10, 50]

  return (
    <Drawer open={open} onClose={onClose} title={isBuy ? '구매하기' : '판매하기'}>
      {/* 종목 정보 */}
      <div className="order-stock">
        <div className="order-stock-name">{name}</div>
        <div className="order-stock-price num">{formatPrice(price)}원</div>
      </div>

      {/* 수량 입력 */}
      <div className="order-field">
        <label className="order-label">수량</label>
        <div className="order-qty-row">
          <button className="order-qty-btn touch-press" onClick={() => setQty(Math.max(1, qty - 1))}>-</button>
          <input
            className="order-qty-input num"
            type="number"
            min="1"
            value={qty}
            onChange={e => setQty(Math.max(1, parseInt(e.target.value) || 1))}
          />
          <button className="order-qty-btn touch-press" onClick={() => setQty(qty + 1)}>+</button>
        </div>
        <div className="order-qty-presets">
          {qtyButtons.map(q => (
            <button key={q} className="order-preset touch-press" onClick={() => setQty(q)}>{q}주</button>
          ))}
        </div>
      </div>

      {/* 예상 금액 */}
      <div className="order-summary">
        <span className="order-summary-label">예상 주문금액</span>
        <span className="order-summary-value num">{formatPrice(totalAmount)}원</span>
      </div>

      {/* 주문 버튼 */}
      <button
        className={`order-submit touch-press ${isBuy ? 'buy' : 'sell'}`}
        onClick={handleOrder}
        disabled={loading || qty <= 0}
      >
        {loading ? '주문 중...' : `시장가 ${isBuy ? '구매' : '판매'}하기`}
      </button>
    </Drawer>
  )
}
