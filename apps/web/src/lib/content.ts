/**
 * Static landing-page content + mock telemetry.
 * When the realtime API exists, the `liveDistance` mock is swapped for the
 * WebSocket-fed store; everything else stays as marketing copy.
 */
import type { IconName } from "@/components/icons";

export const nav = {
  links: [
    { label: "Features", href: "#features" },
    { label: "How it works", href: "#how" },
    { label: "Hardware", href: "#hardware" },
    { label: "Docs", href: "#" },
  ],
  cta: { label: "Open Console", href: "/console" },
};

export const hero = {
  eyebrow: "Monsson 2026 · CatRanger",
  // The headline is split so "MOVE" gets the gradient + trajectory swoosh.
  headingTop: "TRACK EVERY",
  headingAccent: "MOVE",
  body:
    "Detect a cat, hold its identity, and say exactly how far it is — in meters, " +
    "with an honest confidence interval — from one ordinary camera. Then see where " +
    "it will be, so you frame the shot before it lands.",
  primary: { label: "Open Console", href: "/console" },
  secondary: { label: "Watch the pipeline", href: "#how" },
  chips: [
    "±1 cm ground truth",
    "Real-time",
    "Monocular",
    "BoT-SORT · ReID",
  ],
  stats: [
    { value: "2", label: "detector approaches" },
    { value: "± CI", label: "every estimate" },
    { value: "120°", label: "FOV undistort" },
  ],
};

export type LiveDistance = {
  meters: number;
  lo: number;
  hi: number;
  truthMeters: number;
  /** closing speed in m/s, positive = approaching */
  closingMps: number;
  trackId: number;
  catName: string;
};

export const liveDistance: LiveDistance = {
  meters: 1.84,
  lo: 1.8,
  hi: 1.88,
  truthMeters: 1.86,
  closingMps: 0.21,
  trackId: 7,
  catName: "Mochi",
};

export type Capability = {
  icon: IconName;
  title: string;
  body: string;
  tag: string;
};

export const capabilities: Capability[] = [
  {
    icon: "ruler",
    title: "Distance ± CI",
    tag: "How far",
    body:
      "Pinhole geometry and metric depth are fused into a confidence-weighted median, " +
      "so you get meters with a real uncertainty band — not a single hopeful number.",
  },
  {
    icon: "route",
    title: "Where it will be",
    tag: "Prediction",
    body:
      "Per-track motion is extrapolated over an adjustable lead time. A ghost box shows " +
      "the landing spot and its predicted distance, so the camera is ready before the cat is.",
  },
  {
    icon: "robot",
    title: "Robot follow",
    tag: "Control",
    body:
      "An anti-oscillation controller drives the chassis to hold a safe distance and keep " +
      "the cat centered — smooth, with a hard ultrasonic stop in firmware.",
  },
];

export type Step = {
  n: string;
  icon: IconName;
  title: string;
  body: string;
};

export const steps: Step[] = [
  {
    n: "01",
    icon: "target",
    title: "Detect",
    body: "YOLO11 or RT-DETR finds the cat (COCO class 15) on the undistorted frame.",
  },
  {
    n: "02",
    icon: "fingerprint",
    title: "Track",
    body: "BoT-SORT + ReID keeps a stable identity through full occlusion.",
  },
  {
    n: "03",
    icon: "ruler",
    title: "Distance",
    body: "Geometry ⊕ metric depth → meters ± a conformal confidence interval.",
  },
  {
    n: "04",
    icon: "route",
    title: "Predict & follow",
    body: "Extrapolate the next position, then drive the robot to hold its distance.",
  },
];

export type Hardware = {
  icon: IconName;
  name: string;
  role: string;
  link: string;
  detail: string;
};

export const hardware: Hardware[] = [
  {
    icon: "camera",
    name: "Tapo C211",
    role: "Eyes",
    link: "Wi-Fi · RTSP",
    detail: "Live frames over the network, with optional pan/tilt.",
  },
  {
    icon: "chip",
    name: "Arduino Mega",
    role: "Motion",
    link: "Bluetooth · Serial",
    detail: "Drives the wheels and the camera-pan servo from the laptop brain.",
  },
  {
    icon: "wave",
    name: "HC-SR04",
    role: "Ground truth",
    link: "±1 cm ultrasonic",
    detail: "Confirms the model live: “1.84 m” estimated, “1.86 m” measured.",
  },
];

export const footer = {
  tagline: "Detect · Track · Measure · Predict",
  columns: [
    {
      title: "Product",
      links: ["Console", "Admin", "Live demo", "Changelog"],
    },
    {
      title: "Pipeline",
      links: ["Detection", "Tracking", "Distance", "Prediction"],
    },
    {
      title: "Hardware",
      links: ["Tapo C211", "Arduino Mega", "HC-SR04", "Go2"],
    },
  ],
};
