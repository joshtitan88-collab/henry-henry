---
title: Henry & Henry — Brand Sandbox
emoji: 🪶
colorFrom: indigo
colorTo: yellow
sdk: static
pinned: false
license: mit
---

# Henry & Henry — Brand Sandbox

A static Space with the visual identity for **Henry & Henry, Investigative Intelligence** — a pre-launch boutique investigations firm. Drop in, vibe-code, ship variants.

## What's here

| File | What it is |
| --- | --- |
| `primary_wordmark.svg` | Canonical horizontal wordmark — `HENRY & HENRY` + gold rule + tagline |
| `wordmark_concepts.svg` | 4-up sheet: horizontal, stacked, monogram seal, letterhead band |
| `wordmark_v2.html` | Same concepts rendered with `Cinzel` + `Cormorant Garamond Italic` web fonts |
| `index.html` | The Space landing page that frames the assets |

## Brand spec (constraints to design within)

- **Wordmark:** `HENRY <em>&</em> HENRY` — caps, serif, generous letter-spacing (~6 units), the ampersand is *italic* + gold
- **Tagline:** `INVESTIGATIVE INTELLIGENCE` — small caps, wide letter-spacing
- **Footer line:** `DEFENSIBLE · AUDIT-READY · DISCREET`
- **Palette**
  - Ink `#1A2238`
  - Gold `#8B6914`
  - Paper `#FAF8F2`
  - Rule `#D3D1C7`
- **Type stack**
  - Display: `Cinzel` → `Trajan Pro` → `Optima` → `Constantia` → Georgia, serif
  - Italic ampersand: `Cormorant Garamond` → `Iowan Old Style` → Palatino, serif italic
  - Body: `Georgia` / `Iowan Old Style` / `Times New Roman`
- **Voice:** restrained, lawyerly, dossier-grade. Not loud, not "techy," not gimmicky.

## Vibe-coding prompts (pick one and go)

1. **One-page marketing site.** Hero with the primary wordmark, three-tier service grid, "Request engagement" CTA, footer with the three-word footer line. Pure HTML/CSS, no framework. Stay inside the palette.
2. **Sales sheet PDF (printable HTML).** A4, two columns, dossier-cover aesthetic. Wordmark top-center, services + sample deliverable list + intake checklist. Print stylesheet included.
3. **Dossier cover generator.** Form: case ID, client name, matter type, date. Output: a downloadable SVG/PNG cover page in the brand. Vanilla JS only.
4. **Animated wordmark.** Subtle reveal — gold rule draws in, ampersand fades from ink → gold, tagline letter-spaces out. CSS or SMIL, no JS deps.
5. **Favicon + social cards.** Generate the monogram `H&H` favicon (16/32/180 px) and a 1200×630 OG image from the existing SVG primitives.

## Out of scope / do not invent

- Don't fabricate addresses, phone numbers, names, or attorney references. Use placeholders (`[city]`, `[phone]`, `[email]`).
- Don't claim certifications, licenses, or bar admissions. The firm is pre-launch.
- Don't add stock photography of "detectives" or surveillance imagery. Restraint > drama.

## License

MIT for the code. The wordmark and brand expression belong to Henry & Henry.
