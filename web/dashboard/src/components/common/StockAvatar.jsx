// StockAvatar — 기업 로고 (네이버 증권) + 이니셜 fallback
import { useState } from 'react'
import './StockAvatar.css'

const LOGO_URL = (code) =>
  `https://file.alphasquare.co.kr/media/images/stock_logo/kr/${code}.png`

const FALLBACK_URL = (code) =>
  `https://ssl.pstatic.net/imgstock/fn/real/logo/stock/${code}.png`

export default function StockAvatar({ code, name, size = 40 }) {
  const [src, setSrc] = useState(LOGO_URL(code))
  const [failed, setFailed] = useState(false)
  const initial = (name || code || '?').charAt(0)

  const handleError = () => {
    if (src === LOGO_URL(code)) {
      // 1차 실패 → 네이버 로고 시도
      setSrc(FALLBACK_URL(code))
    } else {
      // 2차도 실패 → 이니셜 표시
      setFailed(true)
    }
  }

  if (failed) {
    return (
      <div className="stock-avatar-initial" style={{ width: size, height: size, fontSize: size * 0.35 }}>
        {initial}
      </div>
    )
  }

  return (
    <img
      className="stock-avatar-img"
      src={src}
      alt={name || code}
      width={size}
      height={size}
      onError={handleError}
      loading="lazy"
    />
  )
}
