/**
 * The hero centerpiece: a stylized live camera frame showing exactly what
 * CatRanger produces — a tracked cat with its metric distance, plus the
 * predicted "ghost" box (where the cat will be) connected by a motion
 * trajectory. Pure SVG so it's crisp, self-contained, and animated.
 */
export function AnnotatedFrame() {
  return (
    <svg
      viewBox="0 0 480 360"
      role="img"
      aria-label="Live camera frame: a tracked cat at 1.84 meters, with a predicted ghost box at 1.74 meters half a second ahead."
      className="h-auto w-full"
    >
      <defs>
        <linearGradient id="traj" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="var(--color-orange)" />
          <stop offset="1" stopColor="var(--color-purple-bright)" />
        </linearGradient>
        <linearGradient id="cat" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#2a2336" />
          <stop offset="1" stopColor="#171120" />
        </linearGradient>
        <radialGradient id="floor" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="var(--color-purple)" stopOpacity="0.28" />
          <stop offset="1" stopColor="var(--color-purple)" stopOpacity="0" />
        </radialGradient>
        <clipPath id="frameClip">
          <rect x="0" y="0" width="480" height="360" rx="18" />
        </clipPath>
      </defs>

      {/* frame body */}
      <rect x="0" y="0" width="480" height="360" rx="18" fill="#0a0712" />
      <rect
        x="0.75"
        y="0.75"
        width="478.5"
        height="358.5"
        rx="17.5"
        fill="none"
        stroke="var(--color-line-strong)"
      />

      <g clipPath="url(#frameClip)">
        {/* inner grid */}
        <g stroke="rgba(255,255,255,0.05)" strokeWidth="1">
          {Array.from({ length: 9 }, (_, i) => (
            <line key={`v${i}`} x1={(i + 1) * 48} y1="0" x2={(i + 1) * 48} y2="360" />
          ))}
          {Array.from({ length: 7 }, (_, i) => (
            <line key={`h${i}`} x1="0" y1={(i + 1) * 45} x2="480" y2={(i + 1) * 45} />
          ))}
        </g>

        {/* floor glow + contact shadow under the cat */}
        <ellipse cx="205" cy="300" rx="150" ry="34" fill="url(#floor)" />
        <ellipse cx="205" cy="302" rx="64" ry="13" fill="#000" opacity="0.5" />

        {/* ---- the cat (stylized sitting silhouette, facing right) ---- */}
        <g fill="url(#cat)" stroke="rgba(255,255,255,0.08)" strokeWidth="1">
          {/* tail */}
          <path d="M243 296 C 285 304 300 262 284 232 C 277 218 261 222 264 238 C 266 250 276 252 276 262 C 276 280 258 286 240 282 Z" />
          {/* body / haunch */}
          <path d="M150 300 C 148 248 166 210 205 208 C 244 210 262 248 260 300 Z" />
          {/* chest */}
          <path d="M178 300 C 176 262 188 236 205 236 C 222 236 234 262 232 300 Z" fill="#221b2e" />
          {/* head */}
          <circle cx="200" cy="190" r="30" />
          {/* ears */}
          <path d="M176 172 L182 142 L200 166 Z" />
          <path d="M224 172 L218 142 L200 166 Z" />
        </g>
        {/* eyes */}
        <circle cx="190" cy="188" r="2.6" fill="var(--color-orange-bright)" />
        <circle cx="210" cy="188" r="2.6" fill="var(--color-orange-bright)" />

        {/* ---- predicted ghost box (where it will be) ---- */}
        <g opacity="0.95">
          <rect
            x="250"
            y="120"
            width="150"
            height="176"
            rx="4"
            fill="var(--color-purple)"
            fillOpacity="0.06"
            stroke="var(--color-purple-bright)"
            strokeWidth="1.6"
            strokeDasharray="7 6"
          />
          <g
            transform="translate(250 110)"
            fontFamily="var(--font-mono)"
            fontSize="12"
          >
            <rect x="0" y="-14" width="150" height="18" rx="4" fill="var(--color-purple)" />
            <text x="8" y="-1" fill="#fff" letterSpacing="0.5">
              +0.5s → 1.74 m
            </text>
          </g>
        </g>

        {/* ---- trajectory from current center to predicted center ---- */}
        <path
          d="M205 214 C 250 206 268 200 322 196"
          fill="none"
          stroke="url(#traj)"
          strokeWidth="2.4"
          strokeDasharray="2 7"
          strokeLinecap="round"
          style={{ animation: "dash 1.1s linear infinite" }}
        />
        <circle cx="205" cy="214" r="3.5" fill="var(--color-orange-bright)" />
        <path d="M316 191 L326 196 L316 201 Z" fill="var(--color-purple-bright)" />

        {/* ---- current solid distance box ---- */}
        <rect
          x="128"
          y="132"
          width="150"
          height="176"
          rx="4"
          fill="none"
          stroke="var(--color-orange)"
          strokeWidth="2.2"
        />
        {/* corner ticks */}
        <g stroke="var(--color-orange-bright)" strokeWidth="2.6" fill="none">
          <path d="M128 150 V132 H146" />
          <path d="M260 132 H278 V150" />
          <path d="M128 290 V308 H146" />
          <path d="M260 308 H278 V290" />
        </g>
        {/* label chip */}
        <g transform="translate(128 110)" fontFamily="var(--font-mono)">
          <rect x="0" y="-16" width="150" height="20" rx="4" fill="var(--color-orange)" />
          <text x="8" y="-2" fontSize="12" fill="#1a0f06" letterSpacing="0.4">
            CAT #7 · 1.84 m
          </text>
        </g>
        <g transform="translate(132 322)" fontFamily="var(--font-mono)" fontSize="11">
          <text fill="var(--color-orange-bright)">±0.04 m</text>
          <text x="56" fill="var(--color-muted)">closing 0.21 m/s</text>
        </g>

        {/* center crosshair */}
        <g stroke="rgba(255,255,255,0.35)" strokeWidth="1">
          <line x1="240" y1="174" x2="240" y2="186" />
          <line x1="234" y1="180" x2="246" y2="180" />
        </g>

        {/* HUD corner brackets */}
        <g stroke="var(--color-line-strong)" strokeWidth="1.5" fill="none">
          <path d="M16 34 V16 H34" />
          <path d="M446 16 H464 V34" />
          <path d="M16 326 V344 H34" />
          <path d="M446 344 H464 V326" />
        </g>

        {/* top status row */}
        <g fontFamily="var(--font-mono)" fontSize="11">
          <circle cx="28" cy="30" r="4" fill="#ff3b3b">
            <animate attributeName="opacity" values="1;0.3;1" dur="1.4s" repeatCount="indefinite" />
          </circle>
          <text x="38" y="34" fill="var(--color-fg)" letterSpacing="1">
            LIVE
          </text>
          <text x="240" y="34" fill="var(--color-muted)" textAnchor="middle">
            RT-DETR · BoT-SORT
          </text>
          <text x="452" y="34" fill="var(--color-fg)" textAnchor="end">
            28 FPS
          </text>
        </g>

        {/* animated scanline */}
        <rect
          x="0"
          y="0"
          width="480"
          height="2"
          fill="var(--color-orange-bright)"
          opacity="0.25"
          style={{ animation: "scan 5s ease-in-out infinite" }}
        />
      </g>
    </svg>
  );
}
