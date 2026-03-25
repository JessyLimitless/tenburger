// TradeLog — 매매내역 (프리미엄)
import { useTrading } from '../../contexts/TradingContext'

const tagStyle = (action) => {
  const a = (action || '').toLowerCase()
  if (a.includes('체결')) return { bg: '#F3E8FF', color: '#7C3AED', label: '체결' }
  if (a.includes('매수') || a.includes('buy')) return { bg: 'var(--accent-soft)', color: 'var(--accent)', label: '매수' }
  if (a.includes('매도') || a.includes('sell')) return { bg: 'var(--blue-soft)', color: 'var(--blue)', label: '매도' }
  if (a.includes('룰') || a.includes('trigger')) return { bg: 'var(--green-soft)', color: 'var(--green)', label: '트리거' }
  if (a.includes('오류') || a.includes('error')) return { bg: '#FEF2F2', color: '#DC2626', label: '오류' }
  if (a.includes('경고')) return { bg: '#FFFBEB', color: '#D97706', label: '경고' }
  return { bg: 'var(--bg-secondary)', color: 'var(--text-muted)', label: '시스템' }
}

export default function TradeLog() {
  const { state } = useTrading()
  const logs = state.logs || []

  if (!logs.length) {
    return (
      <div style={{ textAlign: 'center', padding: '72px 24px', animation: 'fadeIn .3s ease' }}>
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-caption)" strokeWidth="1.2">
          <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/>
          <rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 12h6m-6 4h4"/>
        </svg>
        <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-secondary)', margin: '16px 0 4px' }}>
          매매 내역이 없어요
        </div>
      </div>
    )
  }

  return (
    <div style={{ paddingBottom: 'calc(80px + env(safe-area-inset-bottom, 0px))', animation: 'pageEnter .4s cubic-bezier(.32,.72,0,1)' }}>
      <div style={{ padding: '16px 24px 8px' }}>
        <div style={{ fontSize: 17, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-.3px' }}>
          오늘의 매매
        </div>
      </div>
      {logs.map((log, i) => {
        const tag = tagStyle(log.action)
        return (
          <div
            key={i}
            style={{
              padding: '14px 24px',
              borderBottom: '1px solid var(--border)',
              animation: 'fadeIn .25s ease both',
              animationDelay: `${Math.min(i, 8) * 30}ms`,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 4,
                background: tag.bg, color: tag.color, letterSpacing: '.02em',
              }}>
                {tag.label}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-caption)' }}>{log.time}</span>
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              {log.details}
            </div>
          </div>
        )
      })}
    </div>
  )
}
