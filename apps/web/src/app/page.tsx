import { BackgroundField } from "@/components/background-field";
import { Nav } from "@/components/site/nav";
import { Hero } from "@/components/site/hero";
import { Capabilities } from "@/components/site/capabilities";
import { HowItWorks } from "@/components/site/how-it-works";
import { HardwareStrip } from "@/components/site/hardware-strip";
import { CallToAction } from "@/components/site/cta";
import { Footer } from "@/components/site/footer";

export default function Home() {
  return (
    <>
      <BackgroundField />
      <a
        href="#top"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-orange focus:px-4 focus:py-2 focus:text-sm focus:text-black"
      >
        Skip to content
      </a>
      <Nav />
      <main>
        <Hero />
        <Capabilities />
        <HowItWorks />
        <HardwareStrip />
        <CallToAction />
      </main>
      <Footer />
    </>
  );
}
