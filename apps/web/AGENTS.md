<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## Local notes (CatRanger)

- The `node_modules/next/dist/docs/` path only exists **after `pnpm install`** (run
  `make web-setup` first). If it's still absent post-install, fall back to the pinned
  `next` version's official release notes — never assume App-Router conventions from
  training data.
- Building needs a **non-Conductor Node** on PATH: Conductor's bundled Node refuses to
  load Next's native bindings (next-swc / lightningcss) with a Team-ID / hardened-runtime
  mismatch. Use a system / official Node + pnpm to run `pnpm build` / `pnpm lint`.
