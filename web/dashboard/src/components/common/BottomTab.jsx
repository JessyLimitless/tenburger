// BottomTab — 프리미엄 하단 탭
import { useLocation, useNavigate } from 'react-router-dom'
import './BottomTab.css'

function IconHome({ active }) {
  return active ? (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 3l9 8h-3v9h-5v-5h-2v5H6v-9H3l9-8z"/>
    </svg>
  ) : (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/>
    </svg>
  )
}

function IconPortfolio({ active }) {
  return active ? (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
      <rect x="3" y="12" width="5" height="9" rx="1.5"/>
      <rect x="9.5" y="7" width="5" height="14" rx="1.5"/>
      <rect x="16" y="3" width="5" height="18" rx="1.5"/>
    </svg>
  ) : (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="12" width="5" height="9" rx="1.5"/>
      <rect x="9.5" y="7" width="5" height="14" rx="1.5"/>
      <rect x="16" y="3" width="5" height="18" rx="1.5"/>
    </svg>
  )
}

function IconLog({ active }) {
  return active ? (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
      <path d="M4 4a2 2 0 012-2h8a2 2 0 012 2v1h2a2 2 0 012 2v13a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm4 4a1 1 0 100 2h8a1 1 0 100-2H8zm0 4a1 1 0 100 2h5a1 1 0 100-2H8z"/>
    </svg>
  ) : (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/>
      <rect x="9" y="3" width="6" height="4" rx="1"/>
      <path d="M9 12h6m-6 4h4"/>
    </svg>
  )
}

const tabs = [
  { path: '/', label: '홈', Icon: IconHome },
  { path: '/portfolio', label: '보유종목', Icon: IconPortfolio },
  { path: '/log', label: '매매내역', Icon: IconLog },
]

export default function BottomTab() {
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <nav className="bottom-tab">
      {tabs.map(({ path, label, Icon }) => {
        const active = location.pathname === path
        return (
          <button
            key={path}
            className={`btab ${active ? 'on' : ''}`}
            onClick={() => navigate(path)}
          >
            <Icon active={active} />
            <span>{label}</span>
          </button>
        )
      })}
    </nav>
  )
}
