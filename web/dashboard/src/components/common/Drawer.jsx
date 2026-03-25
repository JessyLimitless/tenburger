// Drawer — DART Insight 바텀시트 드로어
import './Drawer.css'

export default function Drawer({ open, onClose, title, children }) {
  return (
    <>
      <div className={`drawer-overlay ${open ? 'show' : ''}`} onClick={onClose} />
      <div className={`drawer ${open ? 'show' : ''}`}>
        <div className="drawer-bar" />
        {title && <div className="drawer-title">{title}</div>}
        {children}
      </div>
    </>
  )
}
