import { existsSync } from "node:fs";
import { join } from "node:path";
import Link from "next/link";
import { Icon } from "@/components/icons";
import { GlassCard, SectionHeading } from "@/components/ui";
import { Reveal } from "@/components/reveal";
import { team, teamIntro } from "@/lib/content";
import { TeamAvatar } from "./team-avatar";

function initialsOf(name: string) {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

/** Checked at build time (server component): only request a photo that exists,
 * so missing headshots fall back to initials without a 404/400 from next/image. */
const TEAM_DIR = join(process.cwd(), "public", "team");
function hasPhoto(slug: string) {
  return existsSync(join(TEAM_DIR, `${slug}.jpg`));
}

export function Team() {
  return (
    <section id="team" className="relative px-4 py-24 sm:px-6 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow={teamIntro.eyebrow}
          title={
            <>
              Built by a <span className="text-gradient">four-person</span> crew.
            </>
          }
          intro={teamIntro.intro}
        />

        <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {team.map((m, i) => (
            <Reveal key={m.slug} delay={i * 0.07}>
              <GlassCard className="flex h-full flex-col items-start p-6">
                <TeamAvatar
                  slug={m.slug}
                  name={m.name}
                  initials={initialsOf(m.name)}
                  hasPhoto={hasPhoto(m.slug)}
                />
                <h3 className="mt-5 text-lg font-semibold">{m.name}</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted">{m.role}</p>
                <Link
                  href={m.link}
                  target="_blank"
                  rel="noreferrer"
                  className="pill-outline mt-5 inline-flex items-center gap-2 rounded-full px-4 py-2 text-xs font-medium text-fg"
                >
                  <Icon
                    name={m.linkLabel === "LinkedIn" ? "linkedin" : "users"}
                    className="size-4 text-orange-bright"
                  />
                  {m.linkLabel}
                </Link>
              </GlassCard>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
