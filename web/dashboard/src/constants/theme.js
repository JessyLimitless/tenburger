// DART Trading — Design Tokens (from DART Insight)

export const COLORS = {
  bgPrimary: '#FAFAFA',
  bgCard: '#FFFFFF',
  bgDark: '#18181B',
  bgDarkHover: '#27272A',
  border: '#E4E4E7',
  borderLight: '#F4F4F5',
  textPrimary: '#18181B',
  textSecondary: '#52525B',
  textMuted: '#A1A1AA',
  accent: '#DC2626',
  positive: '#DC2626',
  negative: '#2563EB',
}

export const COLORS_DARK = {
  bgPrimary: '#09090B',
  bgCard: '#18181B',
  bgDark: '#09090B',
  border: '#27272A',
  borderLight: '#18181B',
  textPrimary: '#FAFAFA',
  textSecondary: '#A1A1AA',
  textMuted: '#71717A',
  accent: '#EF4444',
  positive: '#EF4444',
  negative: '#60A5FA',
}

export const FONTS = {
  body: "'Pretendard Variable', 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  mono: "'Inter', 'Pretendard Variable', -apple-system, sans-serif",
}

export const SPACING = { xs: 4, sm: 8, md: 16, lg: 24, xl: 32, xxl: 48 }
export const RADIUS = { sm: 6, md: 10, lg: 14, xl: 20 }
export const TIMING = { fast: '0.15s', base: '0.2s', slow: '0.3s', slower: '0.5s' }

export const SHADOW = {
  sm: '0 1px 2px rgba(0,0,0,0.04), 0 2px 6px rgba(0,0,0,0.04)',
  md: '0 4px 8px rgba(0,0,0,0.06), 0 12px 24px -4px rgba(0,0,0,0.08)',
  lg: '0 8px 16px rgba(0,0,0,0.08), 0 20px 40px -8px rgba(0,0,0,0.12)',
}

export const BADGE_STYLES = {
  watching: { bg: 'rgba(37,99,235,0.08)', color: '#2563EB' },
  triggered: { bg: 'rgba(5,150,105,0.08)', color: '#059669' },
  holding: { bg: 'rgba(220,38,38,0.06)', color: '#DC2626' },
}

export function formatKoreanNumber(value) {
  if (value == null || isNaN(value)) return '—'
  const abs = Math.abs(value)
  if (abs >= 1e12) return (value / 1e12).toFixed(1) + '조'
  if (abs >= 1e8) return (value / 1e8).toFixed(0) + '억'
  if (abs >= 1e4) return (value / 1e4).toFixed(0) + '만'
  return value.toLocaleString('ko-KR')
}

export function formatPrice(value) {
  if (value == null || isNaN(value)) return '—'
  return Number(value).toLocaleString('ko-KR')
}

export function formatPercent(value) {
  if (value == null || isNaN(value)) return '—'
  const sign = value > 0 ? '+' : ''
  return sign + Number(value).toFixed(2) + '%'
}

export function priceClass(change) {
  if (change > 0) return 'up'
  if (change < 0) return 'down'
  return 'flat'
}
