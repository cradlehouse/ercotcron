// The Shadowprice mark — concept C: the bid stack and its cast shadow.
// Blocks are the market; the detached amber shadow is the value it hides.
export function LogoMark({ size = 22, fg = '#f2f6f6' }: { size?: number; fg?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 96 96" aria-hidden="true">
      <g transform="translate(4,82) skewX(30) scale(1,-0.30) translate(0,-76)" fill="#eda63a" opacity="0.85">
        <rect x="14" y="60" width="20" height="16" rx="1.5" />
        <rect x="38" y="46" width="20" height="30" rx="1.5" />
        <rect x="62" y="32" width="20" height="44" rx="1.5" />
      </g>
      <g fill={fg}>
        <rect x="14" y="60" width="20" height="16" rx="1.5" />
        <rect x="38" y="46" width="20" height="30" rx="1.5" />
        <rect x="62" y="32" width="20" height="44" rx="1.5" />
      </g>
    </svg>
  )
}
