// Commander legality report (server: deck_legality.check, carried on stats.legality and on
// the import preview). Shared by the deck view and the import preview so the two can't drift.
// `unverified` counts cards whose ban status the stored deck doesn't carry; it is shown as
// exactly that, never folded into "legal".
export default function LegalityBlock({ legality, compact = false }) {
  if (!legality || !Array.isArray(legality.issues)) return null
  const ok = legality.legal
  return (
    <div style={{ marginTop: compact ? 0 : 12 }}>
      {!compact && <div style={{ height: 1, background: '#292524', margin: '0 0 12px' }} />}
      <div style={{ fontSize: 12 }}>
        <span style={{ color: '#a8a29e' }}>Commander legal: </span>
        <span style={{ fontWeight: 700, color: ok ? '#86efac' : '#f87171' }}>
          {ok ? 'yes' : `no (${legality.issues.length} issue${legality.issues.length === 1 ? '' : 's'})`}
        </span>
        <span style={{ color: '#78716c' }}> · {legality.total} cards</span>
      </div>
      {legality.issues.map((issue, i) => (
        <div key={i} style={{ fontSize: 11, color: '#fca5a5', marginTop: 3, lineHeight: 1.45 }}>
          {issue.message}
        </div>
      ))}
      {legality.unverified > 0 && (
        <div style={{ fontSize: 11, color: '#78716c', marginTop: 3 }}>
          Ban status not stored for {legality.unverified} card{legality.unverified === 1 ? '' : 's'} (saved before this check existed), so the ban list is unchecked for those.
        </div>
      )}
    </div>
  )
}
