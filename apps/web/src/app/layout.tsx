import type { Metadata, Viewport } from "next";
import { Space_Grotesk, Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

// Display = wide technical face (mixed outline/fill headline look).
const display = Space_Grotesk({
  variable: "--font-display-src",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  display: "swap",
});

// Body.
const sans = Geist({
  variable: "--font-sans-src",
  subsets: ["latin"],
  display: "swap",
});

// Instrument-readout numerics.
const mono = Geist_Mono({
  variable: "--font-mono-src",
  subsets: ["latin"],
  display: "swap",
});

const SITE = "CatRanger Console";
const DESCRIPTION =
  "Monocular metric distance, real-time cat tracking, and motion prediction — " +
  "from one ordinary camera. Know how far the cat is, and where it will be.";

export const metadata: Metadata = {
  title: {
    default: `${SITE} — know how far, and where next`,
    template: `%s · ${SITE}`,
  },
  description: DESCRIPTION,
  applicationName: SITE,
  openGraph: {
    title: `${SITE} — know how far, and where next`,
    description: DESCRIPTION,
    siteName: SITE,
    type: "website",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0b0710",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${display.variable} ${sans.variable} ${mono.variable} h-full antialiased`}
    >
      <body className="min-h-full">{children}</body>
    </html>
  );
}
