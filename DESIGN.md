---
name: DHK Paper
description: Existing local paper-trading interface
colors:
  background: "oklch(0.985 0.008 255)"
  foreground: "oklch(0.20 0.04 265)"
  card: "oklch(1 0.004 255)"
  primary: "oklch(0.50 0.18 265)"
  primary-foreground: "oklch(0.985 0.005 255)"
  muted: "oklch(0.95 0.012 255)"
  muted-foreground: "oklch(0.50 0.04 260)"
  border: "oklch(0.88 0.025 255)"
  input: "oklch(0.90 0.02 255)"
  ring: "oklch(0.55 0.18 265)"
  destructive: "oklch(0.45 0.18 27.325)"
typography:
  html:
    fontFamily: "'Geist Variable', sans-serif"
  body:
    fontFamily: "system-ui, -apple-system, sans-serif"
rounded:
  lg: "0.625rem"
  xl: "0.875rem"
spacing:
  panel: "1rem"
  panel-wide: "1.25rem"
  section: "1.5rem"
components:
  panel:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.xl}"
    padding: "{spacing.panel}"
---

# Design System: DHK Paper

## Overview

**Creative North Star: "Operate"**

This factual record preserves the inherited slate/indigo trading interface in Operate mode. The desk emphasizes readable account balances, instrument prices and row actions. Persistent paper-only and synthetic-data labels explain the environment.

**Key Characteristics:**
- Fixed light paper palette with indigo navigation and selection.
- Compact, aligned numeric tables and contained horizontal scrolling.
- Functional green/red actions and explicit virtual-account context.

Recorded from the repaired source and the 6 November 2026 follow-up manifest at `.impeccable/review/audit-followup/manifest.json`: 24 desktop/mobile screenshots with source fingerprints, captured at 1440×900 and 390×844 in Chromium against the production frontend preview and isolated real API/PostgreSQL/Redis. The fresh finish review returned ship with no material fixes for this narrow audit scope; its five reviewed source fingerprints matched. The earlier 20-capture repair set remains at `.impeccable/review/launch-repairs/manifest.json`. This evidence does not certify complete accessibility, every UI branch or public production readiness.

## Colors

The sandbox selector fixes a cool slate palette regardless of light/dark preference. Indigo identifies primary actions, active navigation and selection. Pale surfaces and muted text separate supporting information. Destructive feedback stays red; functional green controls use 700 tones, with 800 hover tones. Dashboard gains use emerald and losses red. Rendered contrast checks passed for BUY (4.95:1), the market error (6.49:1) and partial-exit confirmation (6.29:1). These measurements apply to those inspected states, not every color pairing. The chart line is explicitly `#818cf8`.

## Typography

The HTML font token uses Geist Variable; the body explicitly overrides it with system-ui. Preserve that implementation distinction. Desk titles use semibold 2xl/3xl responsive sizing; balances use xl/2xl semibold. Tables use small text, secondary labels extra-small text, and numeric values tabular figures.

## Layout

Header, navigation, content and footer share a 1440px maximum width. Horizontal padding changes from 16px to 24px at `sm`. Sections use 24px gaps. Balances form two columns, expanding to four at `lg`. Market watch precedes the supporting chart and public references. Navigation and tables allow horizontal overflow; Change and Demo lot columns appear progressively at `sm` and `md`.

Admin overview keeps its title and action links in a wrapping header. Four activity totals share one bordered panel with two columns, expanding to four at `lg`. The account table sits in a separate panel with 20px padding and horizontal scrolling on narrow screens. Positioned scroll containers contain labels and captions; long broker/user names do not expand the page in the checked mobile state; numeric cells align right and retain tabular figures.

## Elevation & Depth

The inspected shell and dashboard panels use borders and tonal backgrounds without explicit panel shadows. Selected rows receive a faint primary tint; hover uses a muted tint.

## Shapes

Panels use rounded-xl corners and thin borders. Labels use smaller rounded corners. Panels typically have 16px padding, increasing to 20px.

## Components

Navigation uses an indigo bottom border for the active route and visible focus outlines. Market filters distinguish selected and outline buttons. Buy uses emerald; Sell uses outline styling. The supporting chart is 230px high.

Market watch treats prices as paused when the client is offline, its market request is paused, no successful update exists, or the latest successful update is older than six seconds. Retained market rows remain visible with “Prices paused — reconnecting” feedback. Buy and Sell actions and submission from an already open order ticket are unavailable until fresh prices return; reconnect and error/retry states remain explicit.

Manager overviews provide a primary Manage users link; Super Admin also sees an outline Paper settings link. Account rows show username and Super Admin/Broker/User role, virtual INR balances and activity counts. Broker views are scoped to their own users. Uninitialized balances read “Not started”; supporting copy explains when balances initialize. A timestamp labels the five-second refresh interval. The implemented loading branch uses status text, failures use an alert with an outline Try again button, and zero customers adds guidance above the account table. The November 6 evidence includes rendered Super Admin and broker views on desktop/mobile, invitation failure and activation, and contained account tables. Loading and every empty/retry branch were not separately captured.

Order tickets retain associated labels, named price controls and synchronous modal focus wrapping, including rapid Tab presses. Partial-exit confirmation uses the selected quantity and states the remaining position. Selected and resulting position states, ticket editing and Tradebook were captured on both viewports. The ticket retains the 4% executed-value fee disclosure; broker ownership and the 3% broker / 1% Super Admin split are unchanged. CNC entries and T+1 settlement remain disabled; existing CNC positions are exit-only.

Platform controls retain unsaved edits until the user saves or chooses “Discard and leave.” Route changes, including Sign out, open the “Keep editing” / “Discard and leave” confirmation before navigation or logout takes effect. Browser reload or closing requests the native unsaved-changes warning. After a revision conflict, “Reload latest controls” refreshes the complete settings result, including the displayed customer count, and replaces the policy, revision and saved baseline together. The user reviews the reloaded controls before saving. The follow-up evidence includes unsaved-control and offline/recovery states at both viewports.

The public USD reference panel was disabled by the test policy. Its live-price rendering, stale/unavailable presentation and provider behavior remain unverified by this capture set; do not infer them from the synthetic market-watch evidence.

## Do's and Don'ts

- Do retain visible synthetic-price, virtual-fund and paper-only labels.
- Do preserve readable numeric alignment and accessible row actions.
- Do keep keyboard focus visible and contained within an open modal.
- Do retain source-owned semantic colors and the checked functional control contrast.
- Do explain paused prices alongside disabled new-order controls.
- Do preserve unsaved-control choices before navigation or sign-out effects.
- Don't infer unverified component states or introduce palette ramps from documentation previews.
- Don't canonize stale CSS commentary describing an amber sandbox: the applied selector and captured interface use slate/indigo.
