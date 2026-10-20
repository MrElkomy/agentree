import Link from "next/link";

// Final logo artwork (docs/brand/BRAND_IDENTITY.md): files in public/brand. "agen" is Midnight
// Ink (white when reversed) and "tree" is Cobalt Blue. Plain <img>: the SVGs are static assets.

/** The "a" monogram. Decorative by default; the wordmark next to it carries the name. */
export function Mark({ className = "size-8", inverted = false }: { className?: string; inverted?: boolean }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={inverted ? "/brand/agentree-mark-reversed.svg" : "/brand/agentree-mark.svg"}
      alt=""
      className={`object-contain ${className}`}
    />
  );
}

/** The logo with the slogan, the PO's chosen lockup for the app chrome. Keep it at h-10 or taller
 * so the slogan stays legible; the bare wordmark files remain for tiny placements. */
export function Wordmark({
  href = "/dashboard",
  inverted = false,
  className = "h-11",
}: {
  href?: string;
  inverted?: boolean;
  className?: string;
}) {
  return (
    <Link href={href} className="inline-flex items-center rounded-md">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={inverted ? "/brand/agentree-logo-slogan-reversed.svg" : "/brand/agentree-logo-slogan.svg"}
        alt="Agentree — Your AI Team. Always On."
        className={`w-auto ${className}`}
      />
    </Link>
  );
}

const BRANCHES = [
  { d: "M200 238 C200 190 90 196 78 128", x: 78, y: 128, label: "Customer Service", anchor: "middle" },
  { d: "M200 238 C200 170 160 140 158 70", x: 158, y: 70, label: "Sales", anchor: "middle" },
  { d: "M200 238 C200 170 250 150 254 84", x: 254, y: 84, label: "Technical Support", anchor: "middle" },
  { d: "M200 238 C200 196 318 200 330 140", x: 330, y: 140, label: "Data Analyst", anchor: "middle" },
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
            fill="#16b8a6"
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
      <text x="200" y="318" textAnchor="middle" fill="#101b2b" fontSize="13" fontWeight="700">
        Your business
      </text>
    </svg>
  );
}
