# SignalVault Refactor Plan

## Vision

Shift from scraping → clustering → classification toward deliberate capture of events, with threads as the primary organizational unit.

**Conceptual model:**
- **Signal** = one event. One primary article. No corroborating-source bloat.
- **Thread** = connected story of signals. Unifies today's chains + narratives.
- **Board** = signals as nodes, threads as colored paths. Node size = centrality (how many threads reference this signal).

**Key insight:** 40 duplicate scraped articles about the same event don't strengthen evidence. They create noise. Quality is set at capture, not filtered after.

## Phase 1 — Browser plugin + stop auto-scraping

Shift ingestion from scraping to deliberate capture.

- Chrome/Firefox extension (Manifest V3). Permissions: `activeTab`, `storage`.
- Toolbar button + `Ctrl+Shift+S` shortcut + right-click context menu.
- On capture:
  - Grab URL, page title, selected text, OpenGraph metadata.
  - POST to existing `POST /api/signals/manual`.
  - Server extracts full article via trafilatura.
  - Popup: title (editable), tags, optional note, Save.
- Kill scheduled scan. Keep `POST /api/signals/search` as on-demand research.
- Hide: review queue, organize-lab, classification tiers, daily scrape cron.

**Value:** stop fighting noise. Every new signal is deliberate.
**Risk:** low — additive + deletion. No schema change.

## Phase 2 — Unify Chains + Narratives → "Threads"

One place for connected stories, empirical or hypothesis-driven.

- New unified "Threads" tab replaces Chains + Narratives.
- Each thread: `title`, `thesis` (markdown, optional), `origin` (`empirical` | `hypothesis` | `mixed`).
- Sequence of signals with inter-node edge labels (chain feature) + per-signal evidence flags (`supporting` | `contradicting` | `neutral`, narrative feature).
- One editor handles both flows.
- Board shows all threads as colored paths — narratives are first-class now.
- Data: keep `causal_paths` + `narratives` tables, expose via one API. Merge in Phase 3.

**Value:** no more redundancy. Narratives become board citizens.
**Risk:** medium — UX reorg, data intact.

## Phase 3 — Signal collapse migration

One article = one signal. Eliminate thread-as-cluster.

- Migration script:
  - Each thread (signal cluster) → pick best article as primary, keep its row in `signals`.
  - Delete the N-1 duplicates.
  - Update `causal_paths`/`narratives` references to point at surviving signals.
- Drop: `signal_clusters`, `signal_cluster_items`, `narratives` (folded into threads).
- `signals` = sole atom table.
- `causal_paths` = sole relation table.
- Board: signals as nodes, node size = centrality.

**Value:** data model matches mental model.
**Risk:** high — destructive migration. Full backup first.

## Phase 4 — Rename throughout

- UI: "Signals" tab (the atoms), "Threads" tab (the relations). Narratives gone.
- Schema: rename `causal_paths` → `threads`, `causal_links` → `thread_links` (or drop if redundant post-unification).
- Code: grep-rename. Keep route aliases for 1 release.

**Value:** labels match model.
**Risk:** low — mechanical.

## Ordering rationale

- Phase 1 first: highest leverage, unblocks everything. Stops generating slop.
- Phase 2 before 3: UI consolidation is reversible, schema migration isn't.
- Phase 3 before 4: migrate with old names, rename with stable schema.
- Each phase produces a working app. Bail anywhere.
