/**
 * Static landing-page content + mock telemetry.
 * When the realtime API exists, the `liveDistance` mock is swapped for the
 * WebSocket-fed store; everything else stays as marketing copy.
 */
import type { IconName } from "@/components/icons";

/** The public landing links out to the repo; the live console is a local tool
 * (`make web` / `catranger serve`), not a hosted feature — see the README. */
export const REPO = "https://github.com/mihaimdm22/robotricks-vision";
export const RUN_LOCALLY = `${REPO}#web-control-panel`;

/** The two Monsson hack-a-ton 2026 challenge themes CatRanger implements and adapts. */
export const CHALLENGES = {
  hackathon: "https://hackaton.ambasada.pro/",
  howFar: "https://hackaton.ambasada.pro/challenges/monsson-how-far/",
  catTracker: "https://hackaton.ambasada.pro/challenges/monsson-cat-tracker/",
};

export const nav = {
  links: [
    { label: "Features", href: "#features" },
    { label: "Architecture", href: "#architecture" },
    { label: "Training", href: "#training" },
    { label: "Hardware", href: "#hardware" },
    { label: "Team", href: "#team" },
    { label: "Docs", href: "#docs" },
  ],
  cta: { label: "View on GitHub", href: REPO },
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
  primary: { label: "Run it locally", href: RUN_LOCALLY },
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

/* ------------------------------------------------------------------ *
 * Architecture — the pipeline, end to end (facts from the README).
 * ------------------------------------------------------------------ */
export type PipelineStage = { icon: IconName; label: string; note: string };

export const pipeline: PipelineStage[] = [
  { icon: "camera", label: "Capture", note: "One ordinary camera, RTSP or webcam." },
  { icon: "target", label: "Undistort", note: "120° FOV / division model rectify." },
  { icon: "target", label: "Detect", note: "YOLO11 or RT-DETR · COCO class 15." },
  { icon: "fingerprint", label: "Track", note: "BoT-SORT + ReID · stable IDs." },
  { icon: "ruler", label: "Distance", note: "Geometry ⊕ depth → m ± CI." },
  { icon: "route", label: "Predict & follow", note: "Extrapolate, then drive the chassis." },
];

export type Approach = {
  tag: string;
  detector: string;
  tracker: string;
  pickWhen: string;
};

export const approaches: Approach[] = [
  {
    tag: "Approach A",
    detector: "YOLO11s — CNN, fast",
    tracker: "ByteTrack",
    pickWhen: "Latency and command smoothness matter most.",
  },
  {
    tag: "Approach B",
    detector: "RT-DETR-l — transformer, NMS-free",
    tracker: "BoT-SORT + ReID",
    pickWhen: "Cluttered, occluded scenes where identity must survive.",
  },
];

/** The distance-fusion explainer — why the number is honest. */
export const fusion = {
  eyebrow: "Honest distance",
  title: "Two estimates, one number, a real interval",
  geometry: {
    label: "Geometry",
    formula: "Z = fy · H_real / h_px",
    body: "Pinhole math on the rectified frame with per-class size priors, down-weighted as boxes drift to the distorted edges.",
  },
  depth: {
    label: "Metric depth",
    formula: "Depth-Anything-V2 / UniDepthV2",
    body: "A metric depth model sampled inside the box, ingesting the camera K for true scale and a per-pixel confidence.",
  },
  fused: {
    label: "Fused",
    formula: "confidence-weighted median ± CI",
    body: "The two are fused into one median, with a confidence interval from estimator spread plus split-conformal residuals.",
  },
};

/* ------------------------------------------------------------------ *
 * Metrics — the frozen-metric doctrine made visible. These name what
 * we optimize against a frozen eval; they are dimensions, not claims.
 * ------------------------------------------------------------------ */
export type Metric = { icon: IconName; value: string; label: string; body: string };

export const metricsIntro = {
  eyebrow: "The frozen metric",
  title: "We only keep what moves the number",
  intro:
    "Every change runs against a frozen eval and is kept only if the metric improves — a keep/reject loop, no moving the goalposts. These are the dimensions we score.",
};

export const metrics: Metric[] = [
  {
    icon: "ruler",
    value: "Distance MAE",
    label: "the scored metric",
    body: "Mean absolute error in meters on the hidden Go2 test set — the one number the challenge is graded on.",
  },
  {
    icon: "gauge",
    value: "Real-time",
    label: "frames per second",
    body: "The pipeline is profiled for FPS so the overlay, the JSON, and the robot all stay live.",
  },
  {
    icon: "fingerprint",
    value: "Track continuity",
    label: "identity through occlusion",
    body: "ReID keeps a cat's ID stable through full occlusion, measured as track breaks per sequence.",
  },
  {
    icon: "wave",
    value: "±1 cm",
    label: "ultrasonic ground truth",
    body: "An HC-SR04 confirms estimates live on the rig — “1.84 m” predicted next to “1.86 m” measured.",
  },
];

/* ------------------------------------------------------------------ *
 * Training & models — how the perception core improves without ever
 * risking the demo. Facts: docs/architecture/training-and-reliability.md
 * and the training policy in ../../CLAUDE.md.
 * ------------------------------------------------------------------ */
export const trainingIntro = {
  eyebrow: "Training & models",
  title: "Fine-tuned only when it earns its keep",
  intro:
    "The pretrained baseline always runs — it is the guaranteed demo. A fine-tune is a stretch on top, kept only if it beats the frozen metric. Nothing trains from scratch.",
};

export type TrainingPillar = { icon: IconName; tag: string; title: string; body: string };

export const trainingPillars: TrainingPillar[] = [
  {
    icon: "gear",
    tag: "Safety net",
    title: "Baseline always runs",
    body:
      "The pretrained model is the guaranteed demo. One command rolls back to it instantly, so no experiment can ever block the live run.",
  },
  {
    icon: "layers",
    tag: "Transfer, not scratch",
    title: "Fine-tune a pretrained YOLO",
    body:
      "We fine-tune yolo11s on a cat dataset with a deterministic seed and a resumable single-file harness — never from scratch, where there are no labels and worse generalization.",
  },
  {
    icon: "target",
    tag: "Keep / reject",
    title: "Kept only if the metric moves",
    body:
      "Each candidate is scored on the same frozen eval and kept only if distance MAE improves past a tolerance band — a proxy gain alone never justifies a keep.",
  },
];

export type TrainStage = { icon: IconName; label: string; note: string };

export const trainPipeline: TrainStage[] = [
  { icon: "layers", label: "Dataset", note: "Roboflow, Open Images, or manual — registered in configs." },
  { icon: "ruler", label: "Prepare", note: "Formatted into one Ultralytics data.yaml." },
  { icon: "chip", label: "Fine-tune", note: "yolo11s.pt · deterministic seed · resumable." },
  { icon: "gauge", label: "Evaluate", note: "Scored on the frozen metrics, against ground truth." },
  { icon: "target", label: "Keep / reject", note: "Beats the baseline, or it is dropped." },
  { icon: "robot", label: "Promote", note: "Winner wired in — gated and baseline-safe." },
];

export const trainingStack = {
  eyebrow: "Pluggable by design",
  title: "Swap the model, swap the data",
  models: {
    label: "Detectors",
    items: ["YOLO11s — CNN, fast", "RT-DETR-l — transformer, NMS-free"],
  },
  datasets: {
    label: "Datasets",
    items: ["Roboflow", "Open Images", "Manual / on-rig"],
  },
  loop: {
    label: "autoresearch",
    body:
      "Fixed-budget experiments sweep the training knobs and auto-apply the same keep/reject contract — as durable jobs that survive a crash and recover on restart.",
  },
};

/* ------------------------------------------------------------------ *
 * Team. Photos are optional: drop apps/web/public/team/<slug>.jpg and
 * it renders; until then each card shows a branded initials avatar.
 * ------------------------------------------------------------------ */
export type Member = {
  slug: string;
  name: string;
  role: string;
  link: string;
  linkLabel: "LinkedIn" | "Profile";
};

export const teamIntro = {
  eyebrow: "The team",
  title: "Built by a four-person crew",
  intro:
    "Product and pitch, robot build, computer vision, and a robotics mechanics champion — Monsson 2026.",
};

export const team: Member[] = [
  {
    slug: "sergiu-ciausu",
    name: "Sergiu Ciausu",
    role: "Deck, landing, UI/UX & product",
    link: "https://www.linkedin.com/in/sergiu-ciausu-475042399/",
    linkLabel: "LinkedIn",
  },
  {
    slug: "andrei-tutea",
    name: "Andrei Iulian Tutea",
    role: "Robot construction & tuning",
    link: "https://www.linkedin.com/in/andrei-iulian-tutea-398344245/",
    linkLabel: "LinkedIn",
  },
  {
    slug: "david-marin",
    name: "David Marin",
    role: "Coding, computer vision & integrations",
    link: "https://www.linkedin.com/in/marinmihaidavid/",
    linkLabel: "LinkedIn",
  },
  {
    slug: "rares-ilasoaia",
    name: "Rares Ilasoaia",
    role: "Robotics mechanics champion",
    link: "https://www.infomatrix.ro/finalists2026/",
    linkLabel: "Profile",
  },
];

/* ------------------------------------------------------------------ *
 * Documentation — go deeper. Links out to the repo's source of truth.
 * ------------------------------------------------------------------ */
export type DocLink = {
  icon: IconName;
  title: string;
  body: string;
  href: string;
  cta: string;
};

export const docsIntro = {
  eyebrow: "Documentation",
  title: "Go deeper",
  intro:
    "Every claim on this page traces back to the repo — run instructions, the fact-checked design rationale, and the per-challenge architecture.",
};

export const docs: DocLink[] = [
  {
    icon: "book",
    title: "README & quickstart",
    body: "Install with uv, run distance on the Go2 stills, track on a video, or follow with the robot.",
    href: `${REPO}#quickstart`,
    cta: "Read the README",
  },
  {
    icon: "layers",
    title: "Research & architecture",
    body: "The full, fact-checked design rationale: detectors, trackers, depth, and the distance fusion.",
    href: `${REPO}/blob/main/docs/01-RESEARCH-ARCHITECTURE.md`,
    cta: "Open the doc",
  },
  {
    icon: "target",
    title: "Audit & decisions",
    body: "What we assumed, what we verified, and the trade-offs behind every scored choice.",
    href: `${REPO}/blob/main/docs/00-AUDIT.md`,
    cta: "Read the audit",
  },
  {
    icon: "gauge",
    title: "Changelog",
    body: "Every release from the hack-a-ton entry to the maintained project — what changed and why.",
    href: `${REPO}/blob/main/CHANGELOG.md`,
    cta: "See the changelog",
  },
];

export type FooterLink = { label: string; href: string };

export const footer = {
  tagline: "Detect · Track · Measure · Predict",
  columns: [
    {
      title: "Product",
      links: [
        { label: "Run locally", href: RUN_LOCALLY },
        { label: "Changelog", href: `${REPO}/blob/main/CHANGELOG.md` },
        { label: "GitHub", href: REPO },
      ] as FooterLink[],
    },
    {
      title: "Pipeline",
      links: [
        { label: "Architecture", href: "#architecture" },
        { label: "Metrics", href: "#metrics" },
        { label: "Training", href: "#training" },
        { label: "Distance", href: "#features" },
        { label: "Hardware", href: "#hardware" },
      ] as FooterLink[],
    },
    {
      title: "Project",
      links: [
        { label: "Team", href: "#team" },
        { label: "Docs", href: "#docs" },
        { label: "Research & architecture", href: `${REPO}/blob/main/docs/01-RESEARCH-ARCHITECTURE.md` },
      ] as FooterLink[],
    },
    {
      // The two Monsson challenge briefs we implement and adapt.
      title: "Challenges",
      links: [
        { label: "How Far?", href: CHALLENGES.howFar },
        { label: "Cat Tracker", href: CHALLENGES.catTracker },
        { label: "Monsson 2026", href: CHALLENGES.hackathon },
      ] as FooterLink[],
    },
  ],
};
