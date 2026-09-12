---
name: Neon Arcade Cyberpunk
colors:
  surface: '#131318'
  surface-dim: '#131318'
  surface-bright: '#39383e'
  surface-container-lowest: '#0e0e13'
  surface-container-low: '#1b1b20'
  surface-container: '#1f1f25'
  surface-container-high: '#2a292f'
  surface-container-highest: '#35343a'
  on-surface: '#e4e1e9'
  on-surface-variant: '#b9cacb'
  inverse-surface: '#e4e1e9'
  inverse-on-surface: '#303036'
  outline: '#849495'
  outline-variant: '#3b494b'
  surface-tint: '#00dbe9'
  primary: '#dbfcff'
  on-primary: '#00363a'
  primary-container: '#00f0ff'
  on-primary-container: '#006970'
  inverse-primary: '#006970'
  secondary: '#ffaedb'
  on-secondary: '#610048'
  secondary-container: '#ff38c5'
  on-secondary-container: '#55003f'
  tertiary: '#fff2ff'
  on-tertiary: '#4e0078'
  tertiary-container: '#efceff'
  on-tertiary-container: '#9300dc'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#7df4ff'
  primary-fixed-dim: '#00dbe9'
  on-primary-fixed: '#002022'
  on-primary-fixed-variant: '#004f54'
  secondary-fixed: '#ffd8ea'
  secondary-fixed-dim: '#ffaedb'
  on-secondary-fixed: '#3c002b'
  on-secondary-fixed-variant: '#880067'
  tertiary-fixed: '#f4d9ff'
  tertiary-fixed-dim: '#e5b5ff'
  on-tertiary-fixed: '#30004b'
  on-tertiary-fixed-variant: '#7000a8'
  background: '#131318'
  on-background: '#e4e1e9'
  surface-variant: '#35343a'
typography:
  display-lg:
    fontFamily: Space Grotesk
    fontSize: 56px
    fontWeight: '700'
    lineHeight: 64px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Space Grotesk
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 44px
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: Space Grotesk
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 44px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Space Grotesk
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 34px
    letterSpacing: 0em
  headline-md:
    fontFamily: Space Grotesk
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: 0em
  headline-sm:
    fontFamily: Space Grotesk
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: 0.01em
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
    letterSpacing: 0em
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: 0em
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-lg:
    fontFamily: Space Grotesk
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.06em
  label-md:
    fontFamily: Space Grotesk
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.08em
  label-sm:
    fontFamily: Space Grotesk
    fontSize: 10px
    fontWeight: '700'
    lineHeight: 14px
    letterSpacing: 0.1em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.25rem
  gutter-sm: 0.75rem
  gutter-lg: 2rem
  margin: 1.5rem
  margin-sm: 1rem
  margin-lg: 3rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system channels an electric, high-octane cyberpunk arcade experience engineered for high-performance competitive gaming. It fuses retro-futuristic arcade vibrancy with modern, sleek HUD precision.

- **Brand Personality:** Kinetic, futuristic, high-intensity, hyper-focused, and unapologetic.
- **Target Audience:** Competitive and speedrun gamers, synthwave and cyberpunk culture enthusiasts, and dynamic digital arcade players.
- **Emotional Response:** An adrenaline surge of tactile feedback, high-contrast clarity in low-light environments, and luminous immersion.
- **Design Movement:** High-Contrast Cyberpunk Glass with arcade HUD elements, utilizing luminous emissive glows, deep obsidian panels, and vibrant neon chromatic accents.

## Colors

The palette relies on absolute darkness juxtaposed with electric light. Emissive glows punctuate the architecture while preserving high data legibility.

- **Canvas & Backgrounds:**
  - Base canvas: `#0a0a0f` (deep void black).
  - Panel / Card Surface: `#15151f` (dense charcoal).
  - Structural Borders: `#2a2a3a` (subtle muted slate).
- **Core Neons:**
  - **Primary (Cyan Neon):** `#00f0ff` — Used for main system titles, active state outlines, and hyper-critical interactive indicators.
  - **Secondary (Magenta Neon):** `#ff2ec4` — Used for secondary accents, high-tier achievement tags, and visual blooms.
  - **Tertiary (Electric Purple):** `#b026ff` — Serves as the primary operational action color for buttons and execution points.
  - **Accent / Status Active (Laser Green):** `#39ff14` — High-alert success, live matchmaking, running status, and energetic highlights.
- **Neutrals & Text:**
  - Primary text: `#d0d0da` — High-clarity, desaturated silver-gray to prevent eye fatigue against high-intensity accents.
  - Muted text & idle status: `#2a2a38` — Subdued inactive counters, dormant slots, and structural dividers.

## Typography

The type system blends the geometric, tech-forward cadence of Space Grotesk for arcade HUD displays and numeric callouts with the ergonomic legibility of Plus Jakarta Sans for rapid textual comprehension.

- **Primary Headings (`#00f0ff`):** Rendered in uppercase or tight title-case with an emissive drop blur (`text-shadow: 0 0 12px rgba(0, 240, 255, 0.45), 0 0 24px rgba(0, 240, 255, 0.2)`).
- **Secondary Headings (`#ff2ec4`):** Styled with a concentrated magenta aura (`text-shadow: 0 0 10px rgba(255, 46, 196, 0.5)`).
- **Labels & Overlines:** Set in Space Grotesk with expanded letter-spacing to invoke tactical HUD readouts.
- **Body:** Kept crisp in `#d0d0da` with neutral glow exclusion to maintain optimal reading speed and eliminate ocular fatigue during sustained gameplay sessions.

## Layout & Spacing

The layout is constructed as a 12-column dynamic responsive grid with compact HUD margins to maximize viewable canvas real estate:

- **Desktop (1200px+):** 12 columns, `margin-lg` (3rem), `gutter-lg` (2rem). Densified game statistics and leaderboards snap to modular dashboard docks.
- **Tablet (768px - 1199px):** 8 columns, `margin` (1.5rem), `gutter` (1.25rem). Dynamic folding of telemetry sidebars into collapse-toggles.
- **Mobile (<768px):** 4 columns, `margin-sm` (1rem), `gutter-sm` (0.75rem). Full-width vertical card stacking with sticky bottom controls.
- **Vertical Rhythm:** Strict 4px/8px incremental spacing scale (`space-xs` through `space-xl`) enforces tight, architectural alignment typical of tactical command centers.

## Elevation & Depth

Visual hierarchy is maintained through luminous depth and dark-matter layering rather than realistic sunlight shadows.

- **Base Layer (Ground):** Background `#0a0a0f` with an optional 32px radial grid overlay in `rgba(42, 42, 58, 0.2)`.
- **Card & Panel Tier (Surface-1):** `#15151f` with a 1px solid border of `#2a2a3a`.
- **Hover Glow (Surface-1 Active):** Border shifts to `rgba(0, 240, 255, 0.6)` paired with a dual-stage bloom: `box-shadow: 0 0 15px rgba(0, 240, 255, 0.25), inset 0 0 15px rgba(0, 240, 255, 0.05)`.
- **Floating Modals & Overlays (Surface-2):** `#181824` reinforced by a 1px outline of `#ff2ec4` and ambient bloom `0 12px 40px rgba(0, 0, 0, 0.85), 0 0 25px rgba(255, 46, 196, 0.2)`.

## Shapes

The design system implements a controlled corner curvature that harmonizes sleek high-tech curves with cybernetic sharpness.

- **Standard Elements (`roundedness: 2` / 0.5rem base):** Interactive inputs, data chips, and small controls use 8px–12px corners.
- **Cards and Panels:** Explicitly enforced at **12px (`0.75rem`)** corner radius to strike the exact arcade console balance between geometric precision and polished ergonomics.
- **Pill Accents:** Reserved strictly for status badges, live activity dots, and segmented pill toggles.

## Components

### Buttons
- **Primary Execution Button:** Solid `#b026ff` background with white text, 12px rounded corners, font Space Grotesk 14px bold. Interactive state triggers a neon bloom (`box-shadow: 0 0 18px rgba(176, 38, 255, 0.65)`).
- **Secondary Neon Green (Action / Boost):** `#39ff14` background with `#0a0a0f` dark text for immediate optical contrast. Hover yields intense laser aura (`box-shadow: 0 0 16px rgba(57, 255, 20, 0.7)`).
- **Ghost / HUD Button:** Transparent background, 1px border in `#00f0ff`, cyan text. On hover, fills with `rgba(0, 240, 255, 0.1)`.

### Cards & Panels
- **Container Structure:** Background `#15151f`, 12px corner radius, 1px border `#2a2a3a`.
- **Interactive Cards:** Smooth 200ms transition on hover: border shifts to `#00f0ff` or `#ff2ec4` with an external 15px neon glow and subtle -2px Y-translation.

### Chips & Status Badges
- **Active / Running State:** Border `#39ff14`, background `rgba(57, 255, 20, 0.12)`, text `#39ff14`. Features a pulsing circular dot indicator with `box-shadow: 0 0 8px #39ff14`.
- **Idle / Dormant State:** Border `transparent`, background `#2a2a38`, text `#7d7d8e`. Zero emission.

### Input Fields
- **Default:** Background `#0e0e16`, border 1px solid `#2a2a3a`, text `#d0d0da`, placeholder `#4e4e61`, 12px radius.
- **Focus:** Border transitions to `#00f0ff` with an active inner and outer cyan radiance (`box-shadow: 0 0 12px rgba(0, 240, 255, 0.35)`).

### Checkboxes & Radios
- Square 18px box with 4px radius (checkbox) or circular (radio), `#15151f` base with `#2a2a3a` border.
- **Checked:** Filled with `#00f0ff` or `#ff2ec4`, carrying an interior dark icon and a 6px surrounding light bloom.

### HUD Data Readouts & Leaderboards (Custom Product Components)
- High-contrast segmented rows with alternating background states (`#15151f` / `#12121b`), left neon rank tags (1st `#00f0ff`, 2nd `#ff2ec4`, 3rd `#39ff14`), and Space Grotesk tabular figures for live telemetry and millisecond timings.