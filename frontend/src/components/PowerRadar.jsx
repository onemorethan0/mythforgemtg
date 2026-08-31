// A small SVG radar/spider chart for the Power Profile's 0-100 axes — a companion to
// the bar rows in SimStrengthPanel.jsx, not a replacement: the bars carry the exact
// numbers and the measured "why" detail text, which a radar can't show. What a radar
// adds is the deck's SHAPE at a glance (e.g. a "glass cannon" — high Speed/Ceiling, low
// Resilience/Interaction — jumps out immediately here in a way five separate bars don't).
//
// Dependency-free by design (matches this file's siblings — no charting library in
// package.json), pure presentation: `axes` is `[{key, label, value, term}]`, `value` in
// 0-100 or null. An axis with `value == null` is NOT plotted as 0 — that would present
// "unmeasured" as "measured and weak", the exact confident-fabrication failure this
// project avoids everywhere else. It still gets a spoke and a label, just no vertex, so
// the reader can see an axis exists and is honestly blank rather than the shape silently
// collapsing toward that corner.

// The plot (rings/spokes/polygon) is a circle of radius MAX_R. Labels sit OUTSIDE that
// circle and are edge-anchored ('start'/'end', not just 'middle') for every axis that
// isn't at the very top or bottom, so their text runs sideways away from the circle —
// a "Consistency 82"-length label anchored near the horizontal can extend 70-90px past
// its anchor point. The canvas used to be a tight SIZE x SIZE square sized to the circle
// alone (viewBox == width/height), so those labels ran past the SVG's own bounds — and an
// <svg> defaults to `overflow: hidden`, so the ones that ran off got silently clipped
// mid-word ("Resilience" -> "Resi", "Pod 44" -> "d 44") instead of overflowing visibly.
// WIDTH/HEIGHT now carry real label margin beyond the circle so every anchored label —
// including a full-width horizontal one, the worst case — has room to render complete.
const MAX_R = 74
const LABEL_R = MAX_R + 16
const WIDTH = 380
const HEIGHT = 260
const CENTER_X = WIDTH / 2
const CENTER_Y = HEIGHT / 2
const RINGS = [0.25, 0.5, 0.75, 1.0]

function point(angle, r) {
  return [CENTER_X + r * Math.cos(angle), CENTER_Y + r * Math.sin(angle)]
}

export default function PowerRadar({ axes, accent = '#38bdf8' }) {
  const n = axes.length
  if (n < 3) return null   // fewer than 3 axes has no meaningful polygon shape to show

  const angleFor = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n
  const measured = axes.filter(a => a.value != null)

  const dataPoints = measured.map(a => {
    const i = axes.indexOf(a)
    const [x, y] = point(angleFor(i), MAX_R * Math.max(0, Math.min(100, a.value)) / 100)
    return `${x},${y}`
  })

  return (
    <svg
      width={WIDTH} height={HEIGHT} viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      style={{ display: 'block', margin: '4px auto 8px', maxWidth: '100%', height: 'auto' }}
    >
      {/* background rings, faint */}
      {RINGS.map((frac, ri) => {
        const ringPts = axes.map((_, i) => point(angleFor(i), MAX_R * frac).join(',')).join(' ')
        return (
          <polygon key={ri} points={ringPts} fill="none" stroke="#292524" strokeWidth={1} />
        )
      })}
      {/* spokes */}
      {axes.map((a, i) => {
        const [x, y] = point(angleFor(i), MAX_R)
        return <line key={a.key} x1={CENTER_X} y1={CENTER_Y} x2={x} y2={y} stroke="#292524" strokeWidth={1} />
      })}
      {/* data polygon — only drawn when every axis is measured, so an unmeasured axis
          can't silently pull a straight edge through where its vertex would have been */}
      {measured.length === n && (
        <polygon points={dataPoints.join(' ')} fill={`${accent}33`} stroke={accent} strokeWidth={1.5} />
      )}
      {/* measured vertices as dots, connected pairwise only between ADJACENT measured
          axes so a gap (unmeasured axis) breaks the line rather than skipping over it */}
      {measured.length < n && axes.map((a, i) => {
        const next = axes[(i + 1) % n]
        if (a.value == null || next.value == null) return null
        const [x1, y1] = point(angleFor(i), MAX_R * Math.max(0, Math.min(100, a.value)) / 100)
        const [x2, y2] = point(angleFor((i + 1) % n), MAX_R * Math.max(0, Math.min(100, next.value)) / 100)
        return <line key={`seg-${a.key}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke={accent} strokeWidth={1.5} />
      })}
      {axes.map((a, i) => {
        if (a.value == null) return null
        const [x, y] = point(angleFor(i), MAX_R * Math.max(0, Math.min(100, a.value)) / 100)
        return <circle key={`dot-${a.key}`} cx={x} cy={y} r={2.5} fill={accent} />
      })}
      {/* labels, each with a native tooltip carrying the axis's glossary definition */}
      {axes.map((a, i) => {
        const [lx, ly] = point(angleFor(i), LABEL_R)
        const anchor = Math.abs(lx - CENTER_X) < 4 ? 'middle' : lx > CENTER_X ? 'start' : 'end'
        return (
          <text
            key={`label-${a.key}`}
            x={lx} y={ly}
            textAnchor={anchor}
            dominantBaseline="middle"
            fontSize={10.5}
            fill={a.value == null ? '#57534e' : '#a8a29e'}
          >
            <title>{a.term}</title>
            {a.label}{a.value == null ? ' (—)' : ` ${Math.round(a.value)}`}
          </text>
        )
      })}
    </svg>
  )
}
