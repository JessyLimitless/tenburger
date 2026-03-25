// Skeleton — DART Insight shimmer 로딩 (강화)
import './Skeleton.css'

export function SkeletonLine({ width = '100%', height = 14, radius = 6 }) {
  return <div className="sk-line" style={{ width, height, borderRadius: radius }} />
}

export function SkeletonCircle({ size = 40, radius = 12 }) {
  return <div className="sk-circle" style={{ width: size, height: size, borderRadius: radius }} />
}

export function SkeletonCard() {
  return (
    <div className="sk-card">
      <SkeletonCircle />
      <div style={{ flex: 1 }}>
        <SkeletonLine width="55%" height={15} />
        <SkeletonLine width="35%" height={11} />
      </div>
      <div style={{ textAlign: 'right' }}>
        <SkeletonLine width={72} height={15} />
        <SkeletonLine width={48} height={11} />
      </div>
    </div>
  )
}

// 홈 전체 스켈레톤
export function SkeletonHome() {
  return (
    <div className="sk-home">
      {/* 계좌 요약 */}
      <div style={{ padding: '20px 20px 16px' }}>
        <SkeletonLine width={60} height={13} />
        <div style={{ marginTop: 10 }}><SkeletonLine width={180} height={30} radius={8} /></div>
        <div style={{ marginTop: 8 }}><SkeletonLine width={120} height={14} /></div>
        <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
          <div className="sk-chip"><SkeletonLine width={50} height={12} /><div style={{ marginTop: 6 }}><SkeletonLine width={80} height={17} /></div></div>
          <div className="sk-chip"><SkeletonLine width={50} height={12} /><div style={{ marginTop: 6 }}><SkeletonLine width={40} height={17} /></div></div>
        </div>
      </div>
      {/* 버튼 */}
      <div style={{ padding: '0 20px 8px' }}><SkeletonLine width="100%" height={50} radius={14} /></div>
      {/* 리스트 */}
      <div style={{ padding: '16px 20px 8px' }}><SkeletonLine width={80} height={13} /></div>
      {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
    </div>
  )
}

// 종목 상세 스켈레톤
export function SkeletonDetail() {
  return (
    <div style={{ padding: 20 }}>
      <SkeletonLine width={40} height={14} />
      <div style={{ marginTop: 8 }}><SkeletonLine width={100} height={14} /></div>
      <div style={{ marginTop: 8 }}><SkeletonLine width={200} height={34} radius={8} /></div>
      <div style={{ marginTop: 8 }}><SkeletonLine width={140} height={14} /></div>
      <div style={{ marginTop: 24 }}><SkeletonLine width="100%" height={220} radius={16} /></div>
    </div>
  )
}

// 기본 리스트 스켈레톤
export function SkeletonList({ count = 5 }) {
  return (
    <div>{Array.from({ length: count }).map((_, i) => <SkeletonCard key={i} />)}</div>
  )
}
