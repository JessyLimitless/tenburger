// StockChart — lightweight-charts 기반 실시간 차트
import { useEffect, useRef } from 'react'
import { createChart, ColorType } from 'lightweight-charts'

export default function StockChart({ data = [], color = '#DC2626', height = 200 }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)

  useEffect(() => {
    if (!containerRef.current) return

    const isDark = document.documentElement.dataset.theme === 'dark'

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: isDark ? '#71717A' : '#A1A1AA',
        fontFamily: "'Pretendard Variable', sans-serif",
        fontSize: 11,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: isDark ? '#1E1E22' : '#F0F0F0', style: 2 },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: isDark ? '#3F3F46' : '#EBEBEB', width: 1, style: 2 },
        horzLine: { color: isDark ? '#3F3F46' : '#EBEBEB', width: 1, style: 2 },
      },
      rightPriceScale: {
        borderVisible: false,
        textColor: isDark ? '#52525B' : '#AAAAAA',
      },
      timeScale: {
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: { vertTouchDrag: false },
    })

    const series = chart.addAreaSeries({
      lineColor: color,
      topColor: color + '30',
      bottomColor: color + '05',
      lineWidth: 2,
      crosshairMarkerRadius: 4,
      crosshairMarkerBorderWidth: 2,
      crosshairMarkerBorderColor: '#fff',
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
    })

    chartRef.current = chart
    seriesRef.current = series

    if (data.length > 0) {
      series.setData(data)
      chart.timeScale().fitContent()
    }

    const resizeObserver = new ResizeObserver(() => {
      chart.applyOptions({ width: containerRef.current.clientWidth })
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      resizeObserver.disconnect()
      chart.remove()
    }
  }, [color, height])

  // 데이터 업데이트
  useEffect(() => {
    if (seriesRef.current && data.length > 0) {
      seriesRef.current.setData(data)
      chartRef.current?.timeScale().fitContent()
    }
  }, [data])

  return (
    <div
      ref={containerRef}
      style={{
        margin: '0 24px',
        borderRadius: 16,
        overflow: 'hidden',
        background: 'var(--bg-secondary)',
      }}
    />
  )
}
