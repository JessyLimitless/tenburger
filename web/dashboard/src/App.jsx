// DART Trading — App Root
import { useState, lazy, Suspense } from 'react'
import { Routes, Route, useLocation } from 'react-router-dom'
import Header from './components/common/Header'
import BottomTab from './components/common/BottomTab'
import { SkeletonHome, SkeletonList, SkeletonDetail } from './components/common/Skeleton'
import Drawer from './components/common/Drawer'
import SettingsPanel from './components/common/SettingsPanel'

const Home = lazy(() => import('./components/home/Home'))
const Portfolio = lazy(() => import('./components/portfolio/Portfolio'))
const TradeLog = lazy(() => import('./components/log/TradeLog'))
const StockDetail = lazy(() => import('./components/stock/StockDetail'))

function PageFallback() {
  const location = useLocation()
  if (location.pathname.startsWith('/stock/')) return <SkeletonDetail />
  if (location.pathname === '/') return <SkeletonHome />
  return <SkeletonList count={5} />
}

export default function App() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const location = useLocation()
  const isDetail = location.pathname.startsWith('/stock/')

  return (
    <div className="app-shell">
      {!isDetail && <Header onOpenSettings={() => setSettingsOpen(true)} />}

      <Suspense fallback={<PageFallback />}>
        <Routes key={location.pathname}>
          <Route path="/" element={<Home />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/log" element={<TradeLog />} />
          <Route path="/stock/:code" element={<StockDetail />} />
        </Routes>
      </Suspense>

      {!isDetail && <BottomTab />}

      <Drawer open={settingsOpen} onClose={() => setSettingsOpen(false)} title="설정">
        <SettingsPanel onClose={() => setSettingsOpen(false)} />
      </Drawer>
    </div>
  )
}
