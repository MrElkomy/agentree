import Link from "next/link";

/** Agentree mark: one root, three branches — a business and the agents that work for it. */
export function Mark({ className = "size-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
      <rect width="32" height="32" rx="8" fill="currentColor" />
      <path
        d="M16 25V15M16 15C16 11 10 11 9 7.5M16 15c0-4 6-4 7-7.5M16 15V7"
        stroke="#fff"
        strokeWidth="2.2"
        strokeLinecap="round"
        fill="none"
      />
      <circle cx="9" cy="7.5" r="2.4" fill="#e9b949" />
      <circle cx="23" cy="7.5" r="2.4" fill="#e9b949" />
      <circle cx="16" cy="6.5" r="2.4" fill="#e9b949" />
      <rect x="12.5" y="23" width="7" height="5" rx="1.5" fill="#fff" />
    </svg>
  );
}

export function Wordmark({ href = "/dashboard", inverted = false }: { href?: string; inverted?: boolean }) {
  return (
    <Link
      href={href}
      className={`inline-flex items-center gap-2.5 rounded-md font-display text-lg font-bold tracking-tight ${
        inverted ? "text-white" : "text-ink"
      }`}
    >
      <Mark className={`size-8 ${inverted ? "text-white/15" : "text-canopy"}`} />
      Agentree
    </Link>
  );
}

const BRANCHES = [
  { d: "M200 238 C200 190 90 196 78 128", x: 78, y: 128, label: "Customer support", anchor: "middle" },
  { d: "M200 238 C200 170 160 140 158 70", x: 158, y: 70, label: "Sales", anchor: "middle" },
  { d: "M200 238 C200 170 250 150 254 84", x: 254, y: 84, label: "Bookings", anchor: "middle" },
  { d: "M200 238 C200 196 318 200 330 140", x: 330, y: 140, label: "Follow-ups", anchor: "middle" },
] as const;

/**
 * The single orchestrated moment: the business root grows its agent branches on load.
 * Purely decorative; respects prefers-reduced-motion via globals.css.
 */
export function BrandTree() {
  return (
    <svg viewBox="0 0 400 340" aria-hidden="true" className="w-full max-w-md">
      <path
        className="branch"
        style={{ ["--len" as string]: 1 }}
        pathLength={1}
        d="M200 300 V238"
        stroke="rgb(255 255 255 / 0.55)"
        strokeWidth="3"
        strokeLinecap="round"
        fill="none"
      />
      {BRANCHES.map((b, i) => (
        <g key={b.label}>
          <path
            className="branch"
            style={{ ["--len" as string]: 1, ["--delay" as string]: `${250 + i * 120}ms` }}
            pathLength={1}
            d={b.d}
            stroke="rgb(255 255 255 / 0.55)"
            strokeWidth="2.5"
            strokeLinecap="round"
            fill="none"
          />
          <circle
            className="node"
            style={{ ["--delay" as string]: `${900 + i * 120}ms` }}
            cx={b.x}
            cy={b.y}
            r="9"
            fill="#e9b949"
          />
          <text
            className="node"
            style={{ ["--delay" as string]: `${1000 + i * 120}ms` }}
            x={b.x}
            y={b.y - 18}
            textAnchor={b.anchor}
            fill="rgb(255 255 255 / 0.85)"
            fontSize="13"
            fontWeight="600"
          >
            {b.label}
          </text>
        </g>
      ))}
      <rect x="150" y="296" width="100" height="34" rx="8" fill="#fff" />
      <text x="200" y="318" textAnchor="middle" fill="#123829" fontSize="13" fontWeight="700">
        Your business
      </text>
    </svg>
  );
}
