# Watch-face design

## Product boundary

The watch inherits context from Omarchy without mirroring the desktop UI.
The desktop companion resolves settings and sends the watch an effective,
versioned profile. The watch stores the latest profile and remains useful when
the desktop is unavailable.

Settings that can be derived from the desktop follow it by default. A future
desktop settings surface can override each one independently. This includes the
theme, timezone, weather location, units, hour cycle, and locale. Hardware- and
face-specific settings are still configured from the desktop, even though they
belong semantically to the watch.

The watch firmware does not need to evaluate preference rules. It receives
resolved values, caches them, and renders them.

## Plain 01

The first face is deliberately one state and one layout. Pairing, invalid-time,
and fatal-error screens are system states rather than face variants.

- 410 x 502 portrait canvas
- resolved Omarchy theme background, represented by a fixed fixture in v0.1
- JetBrains Mono throughout
- left-aligned date, time, and weather
- date is small but uses the same foreground color as all other content
- time is the dominant element
- weather is one monochrome glyph and temperature; v0.1 uses fixture data
- all visible content uses one color; the first face does not use the theme accent
- no controls, cards, separators, status indicators, or secondary labels
- no image background; the face model may gain an optional background later

The default design fixture is `TUE, SEP 8`, `09:41`, and partly cloudy at `68°`.
Deterministic fixture data makes pixel comparisons useful.

## Content-fit contract

Layout safety comes from bounded content and measured fallback tiers, not from
making the default typography unnecessarily small.

- The clock uses tabular, monospaced digits. Its primary form is `HH:MM`. A
  fixed-width suffix slot is always reserved at the right: 12-hour mode shows
  `AM` or `PM`, while 24-hour mode makes it invisible without collapsing it.
  The main clock therefore never moves when the preference changes.
- The date formatter chooses from a short, locale-aware list such as
  `TUE, SEP 8`, `TUE, 8 SEP`, then `SEP 8`. It never clips an arbitrary string.
- Weather shows one fixed-size glyph and a rounded integer temperature. The
  accepted display range is `-99°` through `199°`; invalid or unavailable data
  becomes `--°`.
- Future locale and weather support will use approved font-size tiers. Firmware
  will measure rendered text and select the largest tier that fits rather than
  scaling continuously.
- Before those inputs become live, design fixtures must cover the widest
  digits, negative and three-digit weather, both hour cycles, and the longest
  supported localized date tokens.

The browser prototype and v0.1 LVGL face use the preferred English tier. Their
input is deliberately bounded until the fallback tiers are implemented.

## Theme mapping

The prototype uses the resolved Solitude palette as its initial fixture:

| Face role | Omarchy token | Value |
| --- | --- | --- |
| Canvas | `background` | `#101315` |
| All visible content | `foreground` | `#cacccc` |

The palette values are fixture data, not a separate watch theme. A later
profile revision can carry the accent for faces that use it, but Plain 01
deliberately does not. When theme following is enabled, the desktop companion
will replace the palette as one coherent profile update. When following is
disabled, it will send the selected watch theme through the same interface.

## Evolution constraints

- Old watches must be able to ignore fields introduced by a newer companion.
- A profile update is a full, versioned snapshot rather than a chain of patches.
- Missing optional content must degrade to a valid face, not an error screen.
- Background artwork is optional and must never be required for legibility.
- The browser rendering is a design reference; the physical AMOLED is the final
  authority for font weight, spacing, contrast, and safe-area adjustments.
