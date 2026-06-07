import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const DEFAULT_BACKEND = strip(
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080",
);

/** Same-origin MJPEG proxy so the console <img> is not cross-origin (Chromium can
 *  freeze cross-origin multipart streams while WS overlays keep updating). */
export async function GET(req: NextRequest) {
  const backend = resolveBackend(req.nextUrl.searchParams.get("backend"));
  if (!backend) {
    return new Response("Invalid or disallowed backend URL", { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${backend}/video`, { cache: "no-store" });
  } catch {
    return new Response("Video backend unreachable", { status: 502 });
  }

  if (!upstream.ok || !upstream.body) {
    return new Response("Video backend error", { status: upstream.status || 502 });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type":
        upstream.headers.get("Content-Type") ||
        "multipart/x-mixed-replace; boundary=frame",
      "Cache-Control": "no-cache, no-store",
      Pragma: "no-cache",
    },
  });
}

function strip(url: string): string {
  return url.replace(/\/$/, "");
}

function resolveBackend(raw: string | null): string | null {
  const candidate = strip(raw || DEFAULT_BACKEND);
  try {
    const u = new URL(candidate);
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    if (u.username || u.password) return null;
    if (u.pathname !== "" && u.pathname !== "/") return null;
    if (u.search || u.hash) return null;
    const host = u.hostname.toLowerCase();
    if (host === "metadata.google.internal" || host === "169.254.169.254") {
      return null;
    }
    return `${u.protocol}//${u.host}`;
  } catch {
    return null;
  }
}
