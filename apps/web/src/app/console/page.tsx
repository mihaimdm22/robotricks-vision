import type { Metadata } from "next";
import { Console } from "@/components/console/Console";

export const metadata: Metadata = {
  title: "Console",
  description: "Live robot teleop: drive, track, range, and run eval.",
};

export default function ConsolePage() {
  return <Console />;
}
