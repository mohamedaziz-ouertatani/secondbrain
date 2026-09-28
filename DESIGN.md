---
name: Second Brain
description: A card catalogue for course material; every answer is a working card with its cited fiches pulled beside it.
colors:
  ground: "#dde3e6"
  card: "#fcfcfa"
  card-2: "#f1f3f2"
  ink: "#1d2529"
  muted: "#55626a"
  rule-red: "#d23f36"
  rule-blue: "#c3d3de"
  steel: "#243238"
  steel-2: "#2e3e45"
  steel-3: "#3a4d55"
  steel-ink: "#e6ecef"
  steel-muted: "#a9b8bf"
  primary: "#1f4e79"
  on-primary: "#ffffff"
  focus: "#1f6fd1"
  bad: "#b3261e"
  good: "#2e6b3a"
  sel: "#cfe0f0"
  tint-modeling: "#bcd6ec"
  tint-random: "#f3de8c"
  tint-processing: "#f4c99f"
  tint-sustainable: "#bfe0b8"
  tint-pro: "#f1c3cb"
  tint-seminars: "#d6cceb"
  tint-other: "#d3d9dc"
  ground-dark: "#12181b"
  card-dark: "#1c2327"
  card-2-dark: "#182024"
  ink-dark: "#e3e9ec"
  muted-dark: "#9eabb2"
  rule-red-dark: "#e4675e"
  rule-blue-dark: "#2d3f4b"
  steel-dark: "#0b1013"
  steel-2-dark: "#151d21"
  steel-3-dark: "#1f2a30"
  steel-ink-dark: "#dde5e9"
  steel-muted-dark: "#8fa0a8"
  primary-dark: "#8fb8e8"
  on-primary-dark: "#0b1520"
  bad-dark: "#ff8a80"
  good-dark: "#8fd19e"
  sel-dark: "#2e4a63"
  tint-modeling-dark: "#2b4a63"
  tint-random-dark: "#6a5212"
  tint-processing-dark: "#5e4128"
  tint-sustainable-dark: "#2f5134"
  tint-pro-dark: "#5b3540"
  tint-seminars-dark: "#45395e"
  tint-other-dark: "#3a4449"
typography:
  display:
    fontFamily: "Noto Sans, Noto Sans Arabic, system-ui, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.015em"
  headline:
    fontFamily: "Noto Sans, Noto Sans Arabic, system-ui, sans-serif"
    fontSize: "1.28rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  question-input:
    fontFamily: "Noto Sans, Noto Sans Arabic, system-ui, sans-serif"
    fontSize: "1.2rem"
    fontWeight: 500
    lineHeight: 1.45
  title:
    fontFamily: "Noto Sans, Noto Sans Arabic, system-ui, sans-serif"
    fontSize: "1.02rem"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Noto Sans, Noto Sans Arabic, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
  answer:
    fontFamily: "Noto Sans, Noto Sans Arabic, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.7
  body-small:
    fontFamily: "Noto Sans, Noto Sans Arabic, system-ui, sans-serif"
    fontSize: "0.86rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Noto Sans, Noto Sans Arabic, system-ui, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 500
    lineHeight: 1.4
  callno:
    fontFamily: "Courier Prime, ui-monospace, monospace"
    fontSize: "0.82rem"
    fontWeight: 700
    letterSpacing: "0"
rounded:
  holder: "2px"
  xs: "3px"
  sm: "4px"
  md: "5px"
  tab: "6px"
  hole: "50%"
spacing:
  hair: "0.15rem"
  xs: "0.35rem"
  sm: "0.6rem"
  md: "1rem"
  lg: "1.25rem"
  xl: "2rem"
  margin-column: "3.25rem"
  margin-rule: "2.6rem"
  rail: "248px"
  fiche-column: "320px"
  measure: "72ch"
components:
  button-ask:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    padding: "0.42rem 0.85rem"
  button-quiet:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0.38rem 0.7rem"
  button-quiet-hover:
    backgroundColor: "{colors.card-2}"
  button-icon:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.sm}"
    padding: "0.2rem 0.45rem"
  button-icon-hover:
    backgroundColor: "{colors.card-2}"
    textColor: "{colors.ink}"
  input-search:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0 0.6rem"
  rail:
    backgroundColor: "{colors.steel}"
    textColor: "{colors.steel-ink}"
    width: "{spacing.rail}"
  rail-view:
    textColor: "{colors.steel-muted}"
    rounded: "{rounded.md}"
    padding: "0.4rem 0.5rem"
  rail-view-active:
    backgroundColor: "{colors.steel-3}"
    textColor: "{colors.steel-ink}"
  drawer-front:
    backgroundColor: "{colors.steel-2}"
    textColor: "{colors.steel-ink}"
    rounded: "{rounded.sm}"
    padding: "0.32rem 0.55rem 0.32rem 0.32rem"
  drawer-front-active:
    backgroundColor: "{colors.steel-3}"
  label-holder:
    textColor: "{colors.ink}"
    rounded: "{rounded.holder}"
    padding: "0.14rem 0.5rem 0.12rem"
  working-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "1.1rem 1.25rem 0.7rem 3.25rem"
  answer-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    typography: "{typography.answer}"
    rounded: "{rounded.sm}"
    padding: "1.15rem 1.35rem 1.25rem 3.25rem"
  past-card:
    backgroundColor: "{colors.card-2}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0.55rem 0.9rem"
  fiche:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0.75rem 0.9rem 1.35rem"
  fiche-head:
    textColor: "{colors.ink}"
    typography: "{typography.callno}"
    padding: "0.45rem 0.9rem 0.4rem"
  cite:
    textColor: "{colors.primary}"
    rounded: "{rounded.xs}"
    padding: "0 0.22rem"
  margin-tab:
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
    padding: "0.08rem 0.16rem"
  guide-tab:
    textColor: "{colors.ink}"
    rounded: "{rounded.tab}"
    padding: "0.3rem 0.85rem 0.25rem"
  catalogue-row:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    padding: "0.5rem 0.9rem"
  fresh-mark:
    backgroundColor: "{colors.tint-random}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
    padding: "0.2rem 0.35rem"
  notice:
    backgroundColor: "{colors.tint-random}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0.6rem 0.85rem"
---

# Design System: Second Brain

## Overview

**Creative North Star: "The Card Catalogue"**

Second Brain is a library card catalogue built for one student. Every source is a bristol fiche with a typewritten call number; every question is written on the header line of a working card; every answer carries its citations in a ruled margin column, with the cited fiches pulled half out of the drawer beside it. Navigation is a dark steel cabinet whose drawer fronts carry slotted label cards. The world is physical and specific: pale steel ground, off-white card stock, a red header rule and a red margin line, small paper radii, a punched rod hole at the foot of each fiche.

Density is working-desk, not dashboard: one measure-wide card column (72ch), one 320px column of pulled fiches, one 248px cabinet rail. Colour is carried almost entirely by the six teaching-unit bristol tints, and a tint always marks where something is filed, never decoration. Depth comes from tone and soft paper shadows; motion is small physical displacement (a drawer slides out 8px, a fiche is pulled 10px, a margin tab nudges 4px). Dark mode is the same cabinet at night: dimmed card stock, deep steel, darkened tints, lighter rules.

The build explicitly rejects the chat-bubble column with source chips, coloured side stripes on cards, and dimming text to show selection.

**Key Characteristics:**
- Bristol card stock on a pale steel ground, red header rule and red margin line.
- One bristol tint per teaching unit, used as label cards, heading bands, tabs and highlights.
- Typewritten call numbers (Courier Prime 700) against Noto Sans text, with Noto Sans Arabic for RTL.
- Margin citation column and sentence-level, two-way claim tracing between answer and fiche.
- Small paper radii (2 to 6px), soft ambient shadows, no hard offsets.
- Physical micro-motion on one expo-out curve, fully disabled under reduced motion.

## Colors

A cool steel-and-paper neutral base with one warm structural red and six pastel bristol tints that encode the filing system.

### Primary
- **Catalogue Ink Blue** (primary; dark: primary-dark): the one action and link colour. The Ask button fill, links, citation numerals in running text, link hover in the catalogue. In dark mode it lightens to a pale blue with near-black text on it (on-primary-dark).
- **Index Red** (rule-red; dark: rule-red-dark): structural, not decorative. The header rule under the question (2px), the vertical margin line on working, answer and reader-page cards (1px at 2.6rem), the rule under each fiche heading band, the catalogue's column-header rule, the question caret, the streaming caret and the live-status dot.

### Tertiary: the bristol tints
One tint per teaching unit, resolved at runtime from the module to unit map and passed down as a local tint variable. Data Modeling is blue (tint-modeling), Random Models and Optimisation is yellow (tint-random), Data Processing is orange (tint-processing), Sustainable Development is green (tint-sustainable), Preparation for professional life is pink (tint-pro), Séminaires is lilac (tint-seminars), and unknown modules fall back to a grey card (tint-other). Dark mode swaps each for a deep, desaturated version of the same hue (the `-dark` keys) and keeps ink text on top.

Tints appear as: the rail label cards, the fiche heading band, the reader heading band, drawer guide tabs, margin tabs, a hovered or active citation, a traced claim (70% tint mix), and the 2px outline of a pulled fiche. The yellow also serves as the "new" mark and the caution notice ground.

### Neutral
- **Pale Steel Ground** (ground): the desk behind all cards, and the sticky catalogue column header, which sits on the ground rather than on a card.
- **Bristol White** (card) and **Worn Bristol** (card-2): card stock, and its lower tone for receded past cards, code, skeletons and hover fills.
- **Carbon Ink** (ink) and **Pencil Grey** (muted): text and secondary text.
- **Faint Blue Ruling** (rule-blue): the ruled lines of the card. Dividers under a card head, table and catalogue row lines, fiche-back top rule, quiet button and search borders.
- **Cabinet Steel** (steel, steel-2, steel-3) with **Steel Ink** and **Steel Muted**: the rail only. steel is the cabinet body, steel-2 a drawer front, steel-3 a hovered or open drawer and the label holder frame.
- **Signal colours** (focus, bad, good, sel): focus ring, error text and notices, success, and text selection.

### Named Rules
**The Filing Tint Rule.** A tint means "filed in this teaching unit" and nothing else. It comes from the module map, never chosen per component, and every tinted surface carries ink text at full contrast.

**The Two Reds Rule.** Red draws rules and carets: the header line, the margin line, the heading-band underline, the column-header rule, and the live dot. It never fills a button and never marks an error; errors use bad.

**The Recede, Don't Dim Rule.** When a drawer is open, the other label cards sink by mixing their tint 62% toward steel-2; their text stays at full ink. Measured minimum contrast is 5.27:1 light and 6.06:1 dark. Selection never lowers text contrast.

## Typography

**Body Font:** Noto Sans 400/500/600 (with Noto Sans Arabic, system-ui, sans-serif)
**Arabic:** Noto Sans Arabic 400/600, line-height raised to 1.85 under RTL or `lang="ar"`
**Call-number Font:** Courier Prime 400/700 (with ui-monospace, monospace)

**Character:** A plain, multilingual humanist sans does all the reading; the typewriter face appears only where a catalogue clerk would have typed, on call numbers and page labels. All faces are self-hosted.

### Hierarchy
- **Display** (600, 1.75rem, 1.25, -0.015em): the drawer title. The reader title is the same voice at 1.6rem.
- **Headline** (600, 1.28rem, -0.01em): the question at the head of an answer card.
- **Question input** (500, 1.2rem, 1.45): the text written on the working card's header line; the caret is red.
- **Title** (600, 1.02rem, 1.3): the fiche title, which leads the card face, and in-answer h3/h4 (1.05rem).
- **Body** (400, 16px, 1.6): base text. Answer and reader prose run at 1.7 within a 72ch measure (reader up to 82ch).
- **Body small** (400, 0.85 to 0.86rem, 1.5 to 1.55): fiche snippets (clamped to four lines) and fiche backs.
- **Label** (500, 0.76 to 0.82rem): rail unit names, catalogue column head, card meta, stack label. Sentence case, muted.
- **Call number** (Courier Prime 700, 0.82rem, letter-spacing 0): `MODULE · CHAPTER · p. N`, e.g. PROB2 · CH1 · p. 3. Page labels in the reader use it at 0.85rem.

### Named Rules
**The Typed Call Number Rule.** Courier Prime is reserved for call numbers, page labels and inline code. It never sets headings, body text or buttons.

**The Tabular Count Rule.** Every count, citation numeral, tab, stamp and page number uses tabular figures.

**The Sentence Case Rule.** Labels and headings are sentence case at normal tracking. No uppercase tracked labels above headings.

## Layout

The app is a two-column grid: the 248px steel rail (sticky, full height, cabinet scrolls inside it) and the main desk (padding 1.75rem 2.25rem 4rem). On the Ask view the desk is a grid of a card stack capped at the 72ch measure and a 320px fiche column, 2rem apart. The fiche column is sticky at 1.5rem and scrolls within the viewport height. The drawer view caps at 1080px, the reader at 82ch.

The margin column is the core grid device: working, answer and reader-page cards reserve 3.25rem of left padding with the red rule drawn at 2.6rem, and citation tabs are positioned into that column on the line where each claim's citation sits.

The catalogue is a fixed-column grid (call number 10.5rem, title, kind 11rem, passages 5rem, action 2.4rem) with one sticky column header for the whole drawer. Folder groups are introduced by guide tabs cut in staggered thirds (offset 0, 9rem, 18rem, cycling).

Spacing rhythm is small and paper-like: 0.15 to 0.35rem inside chips and tabs, 0.6 to 1rem between controls, 1.25rem between stacked cards, 2rem between columns.

**Responsive:**
- At 1280px and below, the fiche column narrows to 290px.
- At 1040px and below, the desk becomes one column; fiches follow the answer, unsticky. The catalogue drops its passages column.
- At 860px and below, the rail becomes a sticky top bar: brand, the two views, and a drawer select that replaces the cabinet. Health is hidden. The margin column tightens (padding 2.6rem, rule at 2rem), catalogue rows collapse to title plus action with the call number on its own line above, the column header hides, and guide tabs lose their stagger.

## Elevation & Depth

A hybrid of tonal layering and soft ambient paper shadows. Cards rest on the ground with one low two-layer shadow; lifting is reserved for things the user has pulled or opened. Receded history is conveyed by tone, width and opacity rather than by stacking shadows. The rail's depth is pressed metal: inset highlight and shade lines on drawer fronts, a steel frame ring around each label card.

### Shadow Vocabulary
- **Resting card** (`0 1px 2px rgb(29 37 41 / 0.08), 0 4px 14px rgb(29 37 41 / 0.07)`; dark uses black at 0.35/0.25): all cards, fiches, the catalogue, hovered past cards.
- **Pulled** (`0 2px 4px rgb(29 37 41 / 0.1), 0 12px 28px rgb(29 37 41 / 0.16)` plus a 2px tint ring): a fiche pulled by its citation.
- **Receded** (`0 1px 1px rgb(29 37 41 / 0.06)`): past cards and digest rows.
- **Drawer front** (`inset 0 1px 0 rgb(255 255 255 / 0.05), inset 0 -1px 0 rgb(0 0 0 / 0.25)`); open drawer adds `0 4px 10px rgb(0 0 0 / 0.35)`.
- **Label holder frame** (`0 0 0 2px steel-3, 0 0 0 3px rgb(255 255 255 / 0.12), inset 0 1px 1px rgb(0 0 0 / 0.18)`).
- **Rod hole** (`inset 0 2px 3px rgb(0 0 0 / 0.38), 0 1px 0 hole-lip`): the punched hole at each fiche's foot, filled with the ground colour.

### Named Rules
**The Flat Until Pulled Rule.** Cards rest on one shadow. Only a pulled fiche, an open drawer or a hovered past card lifts, and it lifts by displacement plus a deeper soft shadow, never by a hard offset.

## Shapes

Paper corners: label cards 2px; tabs, citations, code and claim highlights 3px; cards, fiches, inputs and quiet buttons 4px; the Ask button and rail view links 5px; guide tabs 6px on their top corners only, with the catalogue below squared at the top-left to meet the first tab. The only circle is the fiche rod hole and the small status dots. Rules are 1px (margin line, blue rulings) or 2px (the header line, the column-header rule). Tinted heading bands run edge to edge across the top of a fiche or reader head, square below, with a red rule underneath.

## Components

### Buttons
Few and quiet; the Ask button is the only filled one.
- **Ask** (primary, on-primary, 5px, 0.42rem 0.85rem, 600 at 0.92rem, leading icon): lifts 1px on hover, returns on active; disabled at 40% opacity.
- **Quiet** (card ground, rule-blue border, 4px): drawer tools such as Rescan inbox; hover fills card-2; disabled 55%.
- **Icon + label** (transparent, muted, 0.8rem 500): fiche actions Passage, Read, Original; hover and pressed fill card-2 with ink text. Icons are Lucide line SVGs at 15 to 16px, always paired with a word or an accessible name.
- **Focus** everywhere: a 2px focus-colour outline at 2px offset.

### Inputs / Fields
- **Question line:** a borderless textarea sitting on the 2px red header line, 1.2rem 500, red caret, autosizing to 12rem. Enter asks, Shift+Enter breaks a line; the hint sits in the card foot.
- **Search:** card ground, 1px rule-blue border, 4px, leading icon; the border turns focus-blue on focus-within.

### Navigation: the cabinet rail
- Brand, then two view links (Ask, Drawer) as a 2-up grid: steel-muted text, steel-2 on hover, steel-3 with steel-ink when current.
- Drawer fronts grouped under unit names. Each front is steel-2 with a slotted label card in the unit tint, then an optional new mark and a tabular count. Empty drawers are outlined only, with a transparent label and an en dash count.
- **Open drawer:** steel-3, slides out 8px, casts a shadow; its label turns 600 and gains a steel-ink ring. The others recede per the Recede, Don't Dim Rule and restore their tint on hover.
- Health sits at the foot with a small status dot and "Last fiche filed" time.
- Mobile: a sticky top bar with a native select grouped by unit.

### Working card
The question card. Red margin line, red header line, question input and Ask button on that line; a muted foot with the drawer it is filed under and the keyboard hint.

### Answer card
Question as headline, a meta row (drawer name, status stamp), a blue rule, then the answer. Status stamps read "Searching your fiches · 12 s", "Writing · 30 s" with a breathing red dot, then "Answered in 36 s", "Not in your fiches" or "Failed". While searching, three shimmering skeleton lines; while writing, a blinking red block caret and the card stays still (dangling list markers are held back so nothing reflows). Invalid citations produce a yellow caution notice; errors a bad-tinted notice.

### Signature: margin citation column
Each claim's citation numbers repeat as tinted tabs in the margin column, left of the red rule, on the line where that claim's citation sits. The inline citation is a small raised numeral in primary with a half-strength underline; pending citations are muted.

### Signature: two-way claim tracing
Answers are split into claims at each citation run. Hovering or focusing a citation pulls its fiche; hovering or focusing a fiche highlights exactly the claims that cite it (70% tint) and nudges their margin tabs 4px left with a small shadow. Highlights clone across line breaks.

### Signature: the fiche and the pulled fiche
A catalogue card: a full-width tint heading band with a white number chip and the typed call number, then the title (it leads the face), a four-line snippet, and icon actions; a rod hole is punched at the foot. When pulled, it slides 10px toward the answer with the pulled shadow and a 2px tint ring.

### Signature: fiche flip
"Passage" turns the card to its back: the full passage under a blue rule, scrolling within 20rem, with the last 1.6rem fading out by mask and padding so the final lines can scroll clear of the fade. "Front" returns.

### Signature: receding history
Past questions stack below the current card as single-line cards on card-2. Each step back (up to four) is 1.1rem narrower, centred, and 13% fainter. Hover or focus brings one forward: full opacity, card ground, resting shadow, 1px lift. Clicking returns it to the front.

### Signature: held new-marks and the drawer
A yellow "N new" mark sits on drawer fronts and catalogue rows for material that arrived after the first visit, and holds until the fiche is opened. The drawer view: title, count and last filed time, search and rescan; then guide tabs in the unit tint, staggered in thirds, over card-ground catalogue blocks with blue row rules and one sticky column header ruled in red. Problem files show a muted title and a bad-coloured note.

### Reader
A heading card whose call number runs as a full-width tint band with a red underline, then title, meta and quiet actions; then one card per page with the red margin line and a typed page label, scroll-margined so deep links land cleanly.

### Motion
One curve, cubic-bezier(0.16, 1, 0.3, 1), at 120 to 200ms for colour and displacement. Loops are limited to live states: the breathing dot (1.4s), the caret blink (1s, stepped), the skeleton shimmer (1.6s) and the rescan spinner. Under prefers-reduced-motion every animation and transition collapses to 0.01ms.

## Do's and Don'ts

### Do:
- **Do** resolve every tint from the module map and pass it as the local tint variable; unknown modules take tint-other.
- **Do** keep ink text at full contrast on every tint in both modes, and show selection by receding surfaces (color-mix toward steel-2 at 62%), not by dimming text.
- **Do** draw the red margin line at 2.6rem inside a 3.25rem left padding on any card that carries text with citations or page content.
- **Do** put the title first on a fiche face and carry the unit on a full-width tint heading band with the typed call number.
- **Do** set call numbers as `MODULE · CHAPTER · p. N` in Courier Prime 700.
- **Do** keep radii between 2px and 6px and shadows soft and ambient.
- **Do** move things by small physical displacement (1px lift, 4px tab nudge, 8px drawer, 10px pull) on the one expo-out curve.
- **Do** give every live wait an honest stamp with elapsed seconds.
- **Do** set `dir="auto"` and plaintext bidi on user and source text so Arabic lays out RTL at 1.85 line-height.

### Don't:
- **Don't** render answers as chat bubbles or sources as chips; answers are cards and sources are fiches.
- **Don't** mark a unit with a coloured side stripe on a card; tint belongs to heading bands, label cards, tabs and highlights that carry content.
- **Don't** dim other items' text to show a selection.
- **Don't** use red for fills, buttons or errors.
- **Don't** use Courier Prime for headings, body or buttons.
- **Don't** add uppercase tracked labels or kickers above headings.
- **Don't** use hard offset shadows or large radii.
- **Don't** mark material new by recency alone; freshness is first_seen after the first visit and holds until opened.
- **Don't** let a streaming card reflow or flash a heading from a half-arrived list marker.
