// Dexter "data globe" mark — a blue gradient sphere with scattered nodes,
// echoing the Dexter Capital Advisors logo. Pure SVG, theme-independent.
export default function BrandMark({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" className="shrink-0 drop-shadow-sm" aria-hidden>
      <defs>
        <radialGradient id="dx-sphere" cx="34%" cy="28%" r="85%">
          <stop offset="0%" stopColor="#8FD6F4" />
          <stop offset="48%" stopColor="#3AA0DA" />
          <stop offset="100%" stopColor="#13568F" />
        </radialGradient>
      </defs>
      <circle cx="20" cy="20" r="19" fill="url(#dx-sphere)" />
      <g fill="#FFFFFF">
        <circle cx="12.5" cy="13" r="1.5" opacity=".95" />
        <circle cx="16.5" cy="10.5" r="2.1" opacity=".9" />
        <circle cx="21" cy="11" r="1.4" opacity=".8" />
        <circle cx="11" cy="18" r="2.3" opacity=".95" />
        <circle cx="15.5" cy="16" r="1.2" opacity=".7" />
        <circle cx="10.5" cy="24" r="1.6" opacity=".85" />
        <circle cx="14.5" cy="22.5" r="2.4" opacity=".95" />
        <circle cx="19" cy="20" r="1.1" opacity=".6" />
        <circle cx="13.5" cy="29" r="1.3" opacity=".75" />
        <circle cx="18.5" cy="27.5" r="1.7" opacity=".85" />
        <circle cx="23" cy="25" r="1.1" opacity=".6" />
      </g>
    </svg>
  );
}
