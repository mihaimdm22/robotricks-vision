import type { SVGProps } from "react";

export type IconName =
  | "gear"
  | "ruler"
  | "route"
  | "robot"
  | "target"
  | "fingerprint"
  | "camera"
  | "chip"
  | "wave";

type Props = SVGProps<SVGSVGElement>;

const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function Gear(props: Props) {
  return (
    <svg {...base} {...props} aria-hidden>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 2.5v2.4M12 19.1v2.4M21.5 12h-2.4M4.9 12H2.5M18.7 5.3l-1.7 1.7M7 17l-1.7 1.7M18.7 18.7 17 17M7 7 5.3 5.3" />
    </svg>
  );
}

export function Ruler(props: Props) {
  return (
    <svg {...base} {...props} aria-hidden>
      <rect x="2.5" y="7" width="19" height="10" rx="2" />
      <path d="M7 7v3M11 7v4.5M15 7v3M19 7v4.5" />
    </svg>
  );
}

export function Route(props: Props) {
  return (
    <svg {...base} {...props} aria-hidden>
      <circle cx="5" cy="18.5" r="2.3" />
      <circle cx="19" cy="5.5" r="2.3" />
      <path d="M7 17.4C9.5 15 9 11 12 9.5s5-1 6.4-2.6" strokeDasharray="1.6 2.4" />
    </svg>
  );
}

export function Robot(props: Props) {
  return (
    <svg {...base} {...props} aria-hidden>
      <rect x="4" y="8" width="16" height="11" rx="2.5" />
      <path d="M12 4.5V8M9 13h.01M15 13h.01M9 16.5h6M2.5 12v3M21.5 12v3" />
      <circle cx="12" cy="4" r="1.1" />
    </svg>
  );
}

export function Target(props: Props) {
  return (
    <svg {...base} {...props} aria-hidden>
      <circle cx="12" cy="12" r="8.2" />
      <circle cx="12" cy="12" r="3.4" />
      <path d="M12 1.6v3.2M12 19.2v3.2M1.6 12h3.2M19.2 12h3.2" />
    </svg>
  );
}

export function Fingerprint(props: Props) {
  return (
    <svg {...base} {...props} aria-hidden>
      <path d="M5.5 11a6.5 6.5 0 0 1 13 0v2.5" />
      <path d="M8.5 11.5a3.5 3.5 0 0 1 7 0v3a4 4 0 0 0 .5 2" />
      <path d="M11.5 11.5a.5.5 0 0 1 1 0V15a7 7 0 0 0 1.2 4" />
      <path d="M6 16.5a8 8 0 0 0 1 3.5M8.7 19.6c0-.01.3.4.3.4" />
    </svg>
  );
}

export function Camera(props: Props) {
  return (
    <svg {...base} {...props} aria-hidden>
      <path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.2l1-1.6a1.5 1.5 0 0 1 1.3-.7h4a1.5 1.5 0 0 1 1.3.7l1 1.6h1.2A2.5 2.5 0 0 1 21 8.5v8A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z" />
      <circle cx="12" cy="12.5" r="3.4" />
    </svg>
  );
}

export function Chip(props: Props) {
  return (
    <svg {...base} {...props} aria-hidden>
      <rect x="6.5" y="6.5" width="11" height="11" rx="2" />
      <rect x="9.75" y="9.75" width="4.5" height="4.5" rx="0.8" />
      <path d="M9.5 3.5v2M14.5 3.5v2M9.5 18.5v2M14.5 18.5v2M3.5 9.5h2M3.5 14.5h2M18.5 9.5h2M18.5 14.5h2" />
    </svg>
  );
}

export function Wave(props: Props) {
  return (
    <svg {...base} {...props} aria-hidden>
      <path d="M5 12a4 4 0 0 1 4-4M5 12a4 4 0 0 0 4 4" />
      <path d="M5 12a7.5 7.5 0 0 1 7.5-7.5M5 12a7.5 7.5 0 0 0 7.5 7.5" opacity="0.7" />
      <path d="M5 12a11 11 0 0 1 11-11M5 12a11 11 0 0 0 11 11" opacity="0.4" />
    </svg>
  );
}

const REGISTRY: Record<IconName, (p: Props) => React.ReactElement> = {
  gear: Gear,
  ruler: Ruler,
  route: Route,
  robot: Robot,
  target: Target,
  fingerprint: Fingerprint,
  camera: Camera,
  chip: Chip,
  wave: Wave,
};

export function Icon({ name, ...props }: { name: IconName } & Props) {
  const Cmp = REGISTRY[name];
  return <Cmp {...props} />;
}
