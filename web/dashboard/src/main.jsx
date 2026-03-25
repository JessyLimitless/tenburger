import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { TradingProvider } from './contexts/TradingContext'
import { ToastProvider } from './components/common/Toast'
import App from './App'
import './styles/theme-vars.css'
import './styles/global.css'

// 테마 초기화
const savedTheme = localStorage.getItem('dart-theme') || 'light'
document.documentElement.dataset.theme = savedTheme

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <TradingProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </TradingProvider>
    </BrowserRouter>
  </StrictMode>
)
