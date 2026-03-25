// SettingsPanel — 단순 매매 설정
import { useState } from 'react'
import { useTrading } from '../../contexts/TradingContext'
import { saveSettings } from '../../lib/api'
import { useToast } from './Toast'
import './SettingsPanel.css'

export default function SettingsPanel({ onClose }) {
  const { state } = useTrading()
  const toast = useToast()
  const s = state.settings

  const [form, setForm] = useState({
    buy_amount: s.buy_amount,
    max_stocks: s.max_stocks,
    stop_loss: s.stop_loss_rate,
    take_profit: s.profit_cut_rate,
  })

  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }))

  const handleSave = async () => {
    await saveSettings(form)
    toast('설정이 저장되었어요')
    onClose()
  }

  return (
    <div className="settings-panel">
      <div className="sp-section">
        <div className="sp-section-title">매수</div>
        <div className="sp-row">
          <span className="sp-label">1주 최대 가격</span>
          <div className="sp-input-wrap">
            <input className="sp-input num" type="number" value={form.buy_amount} onChange={e => set('buy_amount', Number(e.target.value))} />
            <span className="sp-unit">원</span>
          </div>
        </div>
        <div className="sp-row">
          <span className="sp-label">최대 보유 종목</span>
          <div className="sp-input-wrap">
            <input className="sp-input num" type="number" min="1" max="50" value={form.max_stocks} onChange={e => set('max_stocks', Number(e.target.value))} />
            <span className="sp-unit">개</span>
          </div>
        </div>
      </div>

      <div className="sp-section">
        <div className="sp-section-title">매도</div>
        <div className="sp-row">
          <span className="sp-label">손절 라인</span>
          <div className="sp-input-wrap">
            <input className="sp-input num" type="number" step="0.1" max="0" value={form.stop_loss} onChange={e => set('stop_loss', Number(e.target.value))} />
            <span className="sp-unit">%</span>
          </div>
        </div>
        <div className="sp-row">
          <span className="sp-label">익절 라인</span>
          <div className="sp-input-wrap">
            <input className="sp-input num" type="number" step="0.1" min="0" value={form.take_profit} onChange={e => set('take_profit', Number(e.target.value))} />
            <span className="sp-unit">%</span>
          </div>
        </div>
      </div>

      <div className="sp-section">
        <div className="sp-section-title">상태</div>
        <div className="sp-row">
          <span className="sp-label">연결</span>
          <span className={`sp-status ${state.ws_connected ? 'on' : ''}`}>
            {state.ws_connected ? '연결됨' : '연결 안됨'}
          </span>
        </div>
        <div className="sp-row">
          <span className="sp-label">자동매매</span>
          <span className={`sp-status ${state.is_trading ? 'on' : ''}`}>
            {state.is_trading ? '실행 중' : '중지'}
          </span>
        </div>
        <div className="sp-row">
          <span className="sp-label">예수금</span>
          <span className="sp-value num">{Number(state.cash || 0).toLocaleString()}원</span>
        </div>
      </div>

      <button className="sp-save touch-press" onClick={handleSave}>저장</button>
    </div>
  )
}
