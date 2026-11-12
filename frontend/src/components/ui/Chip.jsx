// tone: neutral | ok | warn | bad | info
export default function Chip({ tone = 'neutral', children, ...rest }) {
  const cls = tone === 'neutral' ? 'ui-chip' : `ui-chip ui-chip--${tone}`
  return <span className={cls} {...rest}>{children}</span>
}
