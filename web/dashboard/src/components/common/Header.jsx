// Header — DART Insight 스타일 (56px, blur, 로고 + 상태 LED)
import { useTrading } from '../../contexts/TradingContext'
import './Header.css'

export default function Header({ onOpenSettings }) {
  const { state } = useTrading()

  const toggleTheme = () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    localStorage.setItem('dart-theme', next)
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      'content', next === 'dark' ? '#09090B' : '#FAFAFA'
    )
  }

  return (
    <header className="header">
      <div className="header-left">
        <div className="header-logo-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="#fff">
            <path d="M4 4h7c5.5 0 9 3.5 9 8s-3.5 8-9 8H4V4zm4 3.5v9h3c3.3 0 5.5-2.2 5.5-4.5S14.3 7.5 11 7.5H8z"/>
          </svg>
        </div>
        <span className="header-logo-text">DART <em>Trading</em></span>
        <div className="header-dots">
          <span className={`header-dot ${state.ws_connected ? 'on' : ''}`} title="WebSocket" />
          <span className={`header-dot ${state.is_trading ? 'live' : ''}`} title="Trading" />
        </div>
      </div>
      <div className="header-right">
        <button className="header-icon" onClick={toggleTheme} title="테마 전환">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32l1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41m11.32-11.32l1.41-1.41"/>
          </svg>
        </button>
        <button className="header-icon" onClick={onOpenSettings} title="설정">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>
          </svg>
        </button>
      </div>
    </header>
  )
}
