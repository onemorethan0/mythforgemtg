// variant: neutral | ghost | primary | danger | ok | info     size: xs | sm | md
export default function Button({ variant = 'neutral', size = 'md', className = '', type = 'button', ...rest }) {
  return <button type={type} className={`ui-btn ui-btn--${variant} ui-btn--${size} ${className}`.trim()} {...rest} />
}
