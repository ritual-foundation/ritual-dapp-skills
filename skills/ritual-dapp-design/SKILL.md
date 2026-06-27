---
name: ritual-dapp-design
description: Ritual dApp design system — dark-mode-first color tokens, typography, Tailwind config, async lifecycle state visuals, precompile icons, and AI slop prevention. Use when styling a Ritual Chain frontend, building React/Next.js UI components, implementing async precompile status indicators, or reviewing dApp visual design for brand consistency.
metadata:
  version: "2.0"
  author: ritual-foundation
---

# Ritual dApp Design System

Design tokens and visual direction for Ritual Chain dApp frontends. Dark-mode-first, technically precise, and unmistakably Ritual.

## How to Use This Skill

**When styling a new Ritual dApp frontend:**

1. Copy the Tailwind tokens (Section 4) into your `tailwind.config.ts`.
2. Set CSS custom properties for fonts (Section 3).
3. Apply component class patterns (Section 5) to your UI elements.
4. Map async precompile states to the 9-state lifecycle visuals (Section 6).
5. Use the precompile icon table (Section 7) for any precompile selector or status display.
6. Before shipping, run the AI slop self-check (Section 8) against your output.

**When reviewing an existing dApp:**

1. Check the color palette against Section 2 — are semantic meanings preserved?
2. Run the AI slop checklist (Section 8) to flag generic AI-generated patterns.
3. Verify accessibility (Section 9) — especially gray-500 on elevated surfaces (fails WCAG AA).

**Common edge cases:**

- Izoard is a licensed font. If you don't have it, substitute Archivo Black from Google Fonts.
- `gray-500` text on `bg-ritual-elevated` fails WCAG AA (3.7:1 ratio). Use `gray-400` minimum.
- The 9-state lifecycle covers all async precompiles, but synchronous precompiles (ONNX, Ed25519, JQ) don't have lifecycle states — they return in the same block.

---

## 1. Design Philosophy

### Core Principles

1. **Precision over decoration.** Every element earns its pixels. No ornament that doesn't communicate state, identity, or hierarchy. A green glow means TEE-verified. A pink border means AI-generated. If an element has no semantic reason to exist, remove it.

2. **Atmosphere over brightness.** The dark canvas is not a concession to dark mode — it is the medium. Glows, mesh gradients, and noise grain create depth and dimension that only work on black. Light is used surgically: to draw attention, to signal state, to reward completion.

3. **Semantic honesty.** Colors, shapes, and motion always mean what they mean. Green never decorates — it certifies. Gold never highlights — it warns. Pink never accents arbitrarily — it marks machine intelligence. Users learn to read the interface once and trust it forever.

### What Ritual Is NOT

- Not a generic DeFi dashboard (no candy gradients)
- Not a Web2 SaaS (no rounded-everything pastel cards)
- Not cyberpunk (no neon-on-neon chaos)
- Not minimal to the point of sterile (has texture, has atmosphere)

---

## 2. Color Palette

### Backgrounds

| Token | Hex | Usage |
|-------|-----|-------|
| `bg-primary` | `#000000` | Page background, base layer |
| `bg-elevated` | `#111827` | Cards, modals, elevated surfaces |
| `bg-surface` | `#1F2937` | Input fields, dropdown menus |
| `bg-overlay` | `rgba(0,0,0,0.8)` | Modal overlays, sheet backgrounds |

### Accent Colors

| Token | Hex | Usage |
|-------|-----|-------|
| `accent-green` | `#19D184` | Primary CTAs, success states, TEE verified, active indicators |
| `accent-lime` | `#BFFF00` | Highlight text, data emphasis, hover states |
| `accent-pink` | `#FF1DCE` | AI/agent features, persistent agent UI, creative precompiles |
| `accent-gold` | `#FACC15` | Warnings, pending states, fee displays |
| `accent-red` | `#EF4444` | Errors, failed states, destructive actions |

### Grays

| Token | Hex | Usage |
|-------|-----|-------|
| `gray-700` | `#374151` | Borders, dividers |
| `gray-500` | `#6B7280` | Secondary text, labels |
| `gray-400` | `#9CA3AF` | Body text (on dark backgrounds) |
| `gray-300` | `#D1D5DB` | Primary text headings |
| `gray-100` | `#F3F4F6` | High-emphasis text (use sparingly) |

### Color Rules

1. **Green = trust.** Use `accent-green` for anything verified, successful, or connected.
2. **Pink = AI.** Any precompile output, agent action, or generated content gets pink accents.
3. **Lime = data.** Highlighted numbers, key metrics, and interactive data points.
4. **Gold = caution.** Pending operations, fee warnings, lock durations.
5. Avoid pure white `#FFFFFF` for backgrounds. Maximum is `gray-100` for text.
6. Prefer green over blue for primary actions. Blue is best reserved for link affordances.

---

## 3. Typography

### Font Stack

| Role | Font | Fallback |
|------|------|----------|
| Display / Headlines | **Izoard** | `'Izoard', system-ui, sans-serif` |
| Body / UI | **Barlow** | `'Barlow', 'Inter', system-ui, sans-serif` |
| Code / Data | **JetBrains Mono** | `'JetBrains Mono', 'Fira Code', monospace` |

**Note:** Izoard is a licensed font from atipo foundry. For open-source projects, substitute with **Archivo** or **Archivo Black** (Google Fonts). The key functional requirement: always use a monospace font for hex addresses, data values, and block numbers.

### Open-Source Font Alternatives

| Role | Licensed | Open-Source Substitute | Google Fonts |
|------|----------|----------------------|-------------|
| Display | Izoard 700 | **Archivo Black** 400 (reads as bold) | Yes |
| Display (lighter) | Izoard 400 | **Archivo** 600 | Yes |
| Body | Barlow 400/600 | Barlow 400/600 (already free) | Yes |
| Mono | JetBrains Mono | JetBrains Mono (already free) | Yes |

### Type Scale

| Element | Font | Size | Weight | Letter-spacing | Transform |
|---------|------|------|--------|---------------|-----------|
| Hero title | Izoard | `4rem` (64px) | 700 | `-0.02em` | — |
| Section title | Izoard | `2.5rem` (40px) | 700 | `-0.01em` | — |
| Card title | Barlow | `1.25rem` (20px) | 600 | `0` | — |
| Body | Barlow | `1rem` (16px) | 400 | `0` | — |
| Body small | Barlow | `0.875rem` (14px) | 400 | `0` | — |
| Data label | Barlow | `0.75rem` (12px) | 500 | `0.1em` | `uppercase` |
| Data value | JetBrains Mono | `0.875rem` (14px) | 500 | `0` | — |
| Hex/address | JetBrains Mono | `0.75rem` (12px) | 400 | `0` | — |
| Button | Barlow | `0.875rem` (14px) | 600 | `0.02em` | — |

### CSS Custom Properties

```css
:root {
  --font-display: 'Izoard', system-ui, sans-serif;
  --font-body: 'Barlow', 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
}
```

### Typographic Rules

- **Italic:** Use only for AI-generated content attribution (e.g., "Generated by claude-sonnet-4-5-20250929") and inline emphasis. Not for body paragraphs.
- **Long-form body text:** `max-width: 65ch`, `line-height: 1.75`, Barlow 16px/400.
- **Fluid display sizes:** Use `clamp()` for hero and section titles to scale without breakpoints: `font-size: clamp(2.5rem, 5vw, 4rem)`.

---

## 4. Tailwind Tokens

Extend your Tailwind config with these Ritual-specific tokens:

```typescript
const config = {
  theme: {
    extend: {
      colors: {
        ritual: {
          black: '#000000', elevated: '#111827', surface: '#1F2937',
          green: '#19D184', lime: '#BFFF00', pink: '#FF1DCE', gold: '#FACC15',
        },
      },
      fontFamily: {
        display: ['var(--font-display)', 'system-ui', 'sans-serif'],
        body: ['var(--font-body)', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'Fira Code', 'monospace'],
      },
      boxShadow: {
        'glow-green': '0 0 30px -5px rgba(25, 209, 132, 0.25)',
        'glow-pink': '0 0 30px -5px rgba(255, 29, 206, 0.2)',
        'card': '0 4px 40px -12px rgba(0, 0, 0, 0.5)',
      },
    },
  },
};
```

---

## 5. Component Style Patterns

Class-level patterns. Build your own components around these tokens.

| Element | Recommended Classes |
|---------|-------------------|
| Page background | `bg-black min-h-screen text-gray-300 font-body` |
| Card | `bg-ritual-elevated border border-gray-800 rounded-xl shadow-card p-6` |
| Primary button | `border border-ritual-green text-ritual-green hover:bg-ritual-green/10 px-4 py-2.5 rounded-lg font-semibold` |
| Secondary button | `border border-dashed border-ritual-gold text-ritual-gold hover:bg-ritual-gold/10` |
| Ghost button | `border border-gray-700 text-gray-400 hover:border-gray-600` |
| Danger button | `border border-red-500/50 text-red-400 hover:bg-red-500/10` |
| Text input | `bg-ritual-surface border border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-300` |
| Data label | `text-xs text-gray-500 uppercase tracking-wider` |
| Data value | `text-sm text-gray-300 font-mono` |
| Hex address | `font-mono text-xs text-gray-500` (truncate to `0x1234...5678`) |
| Section divider | `h-px bg-gradient-to-r from-ritual-green/30 via-gray-800 to-transparent` |
| Focus ring | `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ritual-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-black` |

Ritual buttons are **transparent with borders**, not filled. The primary button is a green-bordered outline that glows on hover — filled buttons feel consumer/SaaS, outlines feel technical/crypto-native. Use `rounded-xl` max; mix with sharper corners where appropriate.

---

## 6. Async Lifecycle States

Every async precompile operation passes through up to 9 states. Each state has a distinct visual treatment. Always pair color with an icon and text label — never rely on color alone (see Accessibility).

| State | Dot Color | Animated | Text Color | Icon |
|-------|----------|----------|------------|------|
| Submitting | gray | pulse | `text-gray-400` | `·` |
| Awaiting Executor | gold | pulse | `text-ritual-gold` | `◌` |
| Committed | gold | static | `text-ritual-gold` | `◉` |
| Processing | green | pulse | `text-ritual-green` | `⟳` |
| Result Ready | green | static | `text-ritual-green` | `◈` |
| Settling | gold | static | `text-ritual-gold` | `◎` |
| Settled | green | static | `text-ritual-green` | `✓` |
| Failed | red | static | `text-red-400` | `✗` |
| Expired | gray-600 | none | `text-gray-500` | `⊘` |

---

## 7. Ritual Visual Language

### Precompile Type Icons

Each precompile type has a geometric icon. Green = data operations, pink = AI/inference, lime = cryptographic, gold = scheduling.

| Type | Address | Icon | Color |
|------|---------|------|-------|
| ONNX | `0x0800` | `⬡` | green |
| HTTP | `0x0801` | `⇄` | green |
| LLM | `0x0802` | `◇` | pink |
| JQ | `0x0803` | `{}` | green |
| Long HTTP | `0x0805` | `⟳` | green |
| ZK Long-Running | `0x0806` | `△` | lime | `ritual-dapp-zk` |
| FHE | `0x0807` | `◈` | lime |
| Sovereign Agent | `0x080C` | `▣` | pink |
| Image | `0x0818` | `◐` | pink |
| Audio | `0x0819` | `♫` | pink |
| Video | `0x081A` | `▶` | pink |
| Persistent Agent | `0x0820` | `⊞` | pink |

### TEE Verification Badge

A green badge with "TEE Verified" text signals enclave-computed results. Style: `bg-ritual-green/10 text-ritual-green border border-ritual-green/20`. Include a small geometric icon (rotated square suggesting a hexagon) for visual weight.

### AI Output Treatment

Any content produced by an AI precompile (LLM, Agent, Image, etc.) should be visually distinguished with a pink top-border gradient (`border-ritual-pink/20`), a diamond icon `◇` with "AI Output" label, and the model name in gray monospace.

### Scheduler Badge

Transactions from the system scheduler (sender `0x000...fa7e`, type `0x10`) should show a gold `⏲ Scheduled` badge to distinguish them from user-initiated calls.

### spcCalls Receipt Display

Ritual transaction receipts include an `spcCalls` array (precompile input/output pairs inline). Display these as collapsible monospace blocks with a "Decode" action.

### Encrypted Content

ECIES-encrypted results should show a blurred placeholder with a lock icon and "Decrypt" button. Only the user's key can read the content.

---

## 8. AI Slop Detection Checklist

Before shipping any Ritual dApp UI, audit against these signals of generic AI-generated design:

| Red Flag | Why It's Wrong | Fix |
|----------|---------------|-----|
| Purple/violet gradients | Default AI color scheme, screams "ChatGPT made this" | Use Ritual's green/lime/pink accents on black |
| System fonts (Inter everywhere) | No brand identity | Use Izoard for display, Barlow for body |
| Perfectly symmetric grid layouts | Feels templated, no visual tension | Break one column wider, offset elements |
| Generic gray `#f5f5f5` backgrounds | Web2 SaaS energy | Pure black `#000000` with `#111827` cards |
| `box-shadow: 0 2px 8px rgba(0,0,0,0.1)` | The default AI shadow | Use dramatic `shadow-card` or glow variants |
| Rounded-2xl on everything | Friendly/consumer, not crypto-native | Mix sharp corners with selective rounding |
| Blue primary buttons | Every AI default | Green border buttons with glow |
| Stock gradient hero sections | Immediately recognizable as AI | Mesh gradients with noise texture |
| `backdrop-blur-xl` everywhere | Overused glassmorphism | One blur layer max, for overlays only |
| Rainbow/multicolor schemes | No focus, no brand | Disciplined 3-color maximum per screen |
| Centered everything | No visual hierarchy | Left-align text, use asymmetric layouts |
| `animate-bounce` on CTAs | Annoying, unprofessional | Subtle `pulse-green` glow or no animation |

### Self-Check Protocol

Before generating any UI component, check your output for these patterns and replace with the Ritual equivalent:

| Pattern to Detect | Replacement |
|-------------------|-------------|
| `Inter` or `Roboto` as display font | `var(--font-display)` (Izoard / Archivo) |
| `#6366f1` or `#3b82f6` (indigo/blue) | `#19D184` (ritual-green) or `#FF1DCE` (ritual-pink) |
| `bg-white` or `bg-gray-50` | `bg-black` (page) or `bg-ritual-elevated` (card) |
| `shadow-md` or `shadow-lg` | `shadow-card` or `shadow-glow-green` |
| `rounded-2xl` or `rounded-3xl` | `rounded-xl` max |
| `animate-bounce` | `animate-pulse-green` or remove |
| `bg-blue-500 text-white` button | `border border-ritual-green text-ritual-green` |

---

## 9. Accessibility

### Color Contrast Audit

| Foreground | Background | Ratio | WCAG AA (4.5:1) |
|-----------|-----------|-------|-----------------|
| gray-300 (`#D1D5DB`) | black (`#000000`) | 13.8:1 | Pass |
| gray-400 (`#9CA3AF`) | black (`#000000`) | 8.3:1 | Pass |
| gray-500 (`#6B7280`) | black (`#000000`) | 4.6:1 | Pass |
| green (`#19D184`) | black (`#000000`) | 7.5:1 | Pass |
| green (`#19D184`) | elevated (`#111827`) | 6.0:1 | Pass |
| pink (`#FF1DCE`) | elevated (`#111827`) | 4.6:1 | Pass |
| red (`#EF4444`) | black (`#000000`) | 4.6:1 | Pass |
| **gray-500 (`#6B7280`)** | **elevated (`#111827`)** | **3.7:1** | **Fail** |

**Key finding:** `gray-500` on `bg-ritual-elevated` fails WCAG AA. Use `gray-400` (`#9CA3AF`) minimum for any text on elevated surfaces.

### Colorblind Safety

Green and red are the primary success/error pair. For red-green colorblind users (~8% of males), never rely on color alone:

| State | Color | Required Non-Color Signal |
|-------|-------|--------------------------|
| Success | Green | Checkmark icon (✓) + "Success" text |
| Error | Red | X icon (✗) + "Failed" text + shake animation |
| Pending | Gold | Clock icon (◌) + "Pending" text + pulse |
| AI output | Pink | Diamond icon (◇) + "AI Output" label |

### ARIA Patterns

| Component | Required ARIA |
|-----------|--------------|
| Status indicators | `role="status"` + `aria-label="Job status: {text}"` |
| Progress bars | `role="progressbar"` + `aria-valuenow` + `aria-valuemax` |
| Streaming text | `role="log"` + `aria-live="polite"` |
| Toasts | `role="alert"` |
| Modals | `role="dialog"` + `aria-modal="true"` + `aria-label="{title}"` |

### Additional Requirements

- **Focus ring on all interactive elements:** `focus-visible:ring-2 focus-visible:ring-ritual-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-black`
- **Reduced motion:** Wrap animations in `@media (prefers-reduced-motion: reduce)` or use Framer Motion's `useReducedMotion`.
- **Touch targets:** 44x44px minimum on mobile for all interactive elements.
- **Semantic HTML:** Use `<main>`, `<nav>`, `<table>`, `<dialog>` — not divs for everything.
- **Skip navigation:** Add a visually-hidden skip link at the top of every page.

---

## 10. Responsive Design

| Breakpoint | Width | Behavior |
|-----------|-------|----------|
| `sm` | 640px | Stack to single column, reduce padding |
| `md` | 768px | Sidebar moves below main content |
| `lg` | 1024px | Two-column layout activates |
| `xl` | 1280px | Maximum content width |

- Transaction status cards stack vertically and become full-width on mobile.
- Hex addresses always truncate to `0x1234...5678`.
- Toast notifications anchor to bottom-center on mobile, bottom-right on desktop.
- Font sizes use fluid `clamp()` — see Typography section.
- Buttons become full-width on mobile (`w-full sm:w-auto`).

---

## Quick Reference

| Concept | Value |
|---------|-------|
| Page background | `bg-black` (`#000000`) |
| Card background | `bg-ritual-elevated` (`#111827`) |
| Primary accent | `ritual-green` (`#19D184`) — trust, success |
| AI accent | `ritual-pink` (`#FF1DCE`) — agent/generated |
| Warning accent | `ritual-gold` (`#FACC15`) — pending, fees |
| Data accent | `ritual-lime` (`#BFFF00`) — metrics, emphasis |
| Display font | Izoard (licensed) / Archivo Black (open-source) |
| Body font | Barlow (free) |
| Mono font | JetBrains Mono (free) |
| Chain ID | 1979 |
| Scheduler system sender | `0x000...fa7e` (type `0x10`) |
| Button style | Transparent + colored border + glow on hover |
| Max rounding | `rounded-xl` — mix with sharper corners |
| Min text on elevated | `gray-400` (`#9CA3AF`) for WCAG AA compliance |
