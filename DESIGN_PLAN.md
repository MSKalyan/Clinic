# Clinic Operations Dashboard — Design Plan

## Subject Matter & Audience
**Product:** AI Clinic Operations Assistant — multi-tenant SaaS for healthcare clinic operations
**Audience:** Clinic admins, doctors, receptionists — medical professionals who need efficiency, clarity, trust
**Primary Job:** Real-time operational visibility + rapid action (status updates, booking, task resolution)

---

## Color System

**Core Philosophy:** Clinical precision with human warmth. Not sterile blue, not aggressive medical red. A palette that feels competent, calm, and trustworthy — like a well-run clinic.

| Token | Hex | Usage |
|-------|-----|-------|
| `surface` | `#FAFAFA` | Page background — warm off-white, reduces eye strain vs pure white |
| `surface-elevated` | `#FFFFFF` | Cards, modals, dropdowns |
| `surface-subtle` | `#F0F2F5` | Subtle section dividers, disabled states |
| `text-primary` | `#0F172A` | Primary content (slate-950) — high contrast, readable |
| `text-secondary` | `#475569` | Secondary labels, hints (slate-600) |
| `text-muted` | `#94A3B8` | Placeholders, timestamps (slate-400) |
| `border-subtle` | `#E2E8F0` | Hairline borders (slate-200) |
| `border-emphasis` | `#CBD5E1` | Focus rings, active states (slate-300) |
| `brand` | `#0D9488` | **Teal-600** — primary actions, links, active indicators. Clinical trust, not corporate blue. |
| `brand-hover` | `#0F766E` | Teal-700 |
| `brand-light` | `#CCFBF1` | Teal-100 — subtle backgrounds, badges |
| `success` | `#059669` | Emerald-600 — confirmed, present, completed |
| `success-light` | `#D1FAE5` | Emerald-100 |
| `warning` | `#D97706` | Amber-600 — running late, pending, reschedule |
| `warning-light` | `#FEF3C7` | Amber-100 |
| `danger` | `#DC2626` | Red-600 — unavailable, cancelled, no-show, overdue |
| `danger-light` | `#FEE2E2` | Red-100 |
| `info` | `#0284C7` | Sky-600 — scheduled, booked, neutral info |
| `info-light` | `#E0F2FE` | Sky-100 |

**No gradients. No decorative color washes.** Color = meaning.

---

## Typography

**Typeface:** `IBM Plex Sans` — technical, legible, distinctly not Inter/Roboto. Designed for UI density. Available via Google Fonts.

**Scale (modular, 1.25 ratio):**
| Role | Size | Weight | Line-height | Letter-spacing |
|------|------|--------|-------------|----------------|
| Display | 36px / 2.25rem | 600 | 1.15 | -0.02em |
| H1 | 28px / 1.75rem | 600 | 1.2 | -0.01em |
| H2 | 22px / 1.375rem | 600 | 1.3 | 0 |
| H3 | 18px / 1.125rem | 500 | 1.4 | 0 |
| Body-lg | 16px / 1rem | 400 | 1.6 | 0 |
| Body | 14px / 0.875rem | 400 | 1.55 | 0 |
| Body-sm | 13px / 0.8125rem | 400 | 1.5 | 0 |
| Caption | 12px / 0.75rem | 400 | 1.45 | 0.01em |
| Label | 11px / 0.6875rem | 500 | 1.4 | 0.05em |
| Mono | 13px / 0.8125rem | 400 | 1.5 | 0 |

**Principles:**
- No all-caps labels (use `Label` token with letter-spacing instead)
- No single-word accent colors in headlines
- Numbers (counts, times) use tabular numerals: `font-variant-numeric: tabular-nums`
- Line length max 75ch for body text

---

## Layout

**Concept:** "Clinical workstation" — dense but breathable, left-aligned, scannable. Not a marketing page.

**Grid:** 12-column, 24px gutters, 24px page margins. Max content width 1400px.

**ASCII Wireframe — Dashboard (Today View):**
```
┌─────────────────────────────────────────────────────────────────┐
│  [Clinic Name]          [Clinic Switcher]  [User Menu]         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  TODAY                                    [Refresh]             │
│  Dr. Sharma Clinic · Asia/Kolkata · 09:15 AM                   │
│                                                                 │
│  ┌─────────┬─────────┬─────────┬─────────┐                      │
│  │ Appts   │ Follow- │ Overdue │Unresolv.│  ← Stat cards       │
│  │  24     │   8     │   2     │   1     │                     │
│  └─────────┴─────────┴─────────┴─────────┘                      │
│  ┌─────────┬─────────┬─────────┬─────────┐                      │
│  │Dr.Presnt│Convs.   │Reminders│Canc/NS  │                      │
│  │  6/8    │   3     │   12    │   1/0   │                      │
│  └─────────┴─────────┴─────────┴─────────┘                      │
│                                                                 │
│  ┌───────────────────────────┬───────────────────────────────┐  │
│  │ DOCTOR STATUS             │ UPCOMING APPOINTMENTS         │  │
│  │ ────────────────────────  │ ───────────────────────────── │  │
│  │ Dr. Sharma    ● Present   │ 09:30  Patel, R.   Dr. Sharma │  │
│  │ Dr. Iyer      ◐ Run Late  │ 10:00  Kumar, S.   Dr. Iyer   │  │
│  │ Dr. Reddy     ○ On Leave  │ 10:30  —           Dr. Sharma │  │
│  │ ...                       │ ...                           │  │
│  │ [Manage →]                │ [All appointments →]          │  │
│  └───────────────────────────┴───────────────────────────────┘  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ FOLLOW-UP QUEUE                                         │   │
│  │ ──────────────────────────────────────────────────────  │   │
│  │ Book appt      Patel, R.      High      09:45   Open    │   │
│  │ Callback       Kumar, S.      Normal    10:15   In Prog │   │
│  │ Clinical Q     —              Urgent    09:30   Open    │   │
│  │ [Open queue →]                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**ASCII Wireframe — Doctors Page:**
```
┌─────────────────────────────────────────────────────────────────┐
│  DOCTORS                                    [+ Add Doctor]      │
│  Status is recorded explicitly. A rota entry is a schedule,     │
│  not a confirmation that the doctor has arrived.                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ROSTER                              8 active doctors    │   │
│  │ ──────────────────────────────────────────────────────  │   │
│  │ Dr. Priya Sharma    Cardiology    EN, HI  ● Present     │   │
│  │ Dr. Arjun Iyer      Orthopedics   EN, TA  ◐ Running late│   │
│  │ Dr. Meera Reddy     Dermatology   EN, TE  ○ On leave    │   │
│  │ Dr. Vikram Patel    Pediatrics    EN, GU  ○ Finished    │   │
│  │ ...                                                     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ STATUS HISTORY (Dr. Priya Sharma)                       │   │
│  │ ──────────────────────────────────────────────────────  │   │
│  │ 08:52  ● Present      Dashboard     "Arrived on time"   │   │
│  │ 17:30  ○ Finished     Dashboard     "Clinic closed"     │   │
│  │ 08:48  ● Present      Dashboard     —                   │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Principles

| Component | Principle |
|-----------|-----------|
| **Cards** | Single border-radius (8px), single border (1px, `border-subtle`), no shadows. Elevation = white background + border, not shadow. |
| **Tables** | No zebra striping. Horizontal rules only (`border-subtle`). Dense: 12px vertical padding. Left-aligned everything except numeric columns (tabular nums, right-aligned). |
| **Badges** | Pill shape (9999px), `Label` token text, `* -light` background + `* -600` text. No icons inside. |
| **Buttons** | Primary: `brand` bg, white text. Secondary: `surface-elevated`, `border-subtle`, `text-primary`. Ghost: transparent, `text-secondary`. No rounded-full — 8px radius matches cards. |
| **Inputs** | 40px height, `border-subtle`, focus = 2px `brand` ring (no outline). Label above, not placeholder-only. |
| **Empty States** | Dashed border (`border-emphasis`), centered, single action button. No illustrations. |
| **Loading** | Skeleton bars matching content shape. No spinners in tables. |
| **Modals** | Centered, max-width 560px, `surface-elevated`, backdrop `rgba(15,23,42,0.4)`. |

---

## Motion

**One orchestrated moment:** Page load — cards stagger in (80ms delay each, 200ms duration, ease-out). No hover transitions on cards. Button press = 50ms scale(0.98). Focus ring = immediate.

**Respect `prefers-reduced-motion`** — disable all non-essential motion.

---

## Accessibility Floor

- WCAG AA contrast on all text (verified: `text-primary` on `surface` = 15.3:1)
- Visible focus rings on all interactive elements (2px `brand`, 2px offset)
- Semantic HTML: `<header>`, `<main>`, `<section>`, `<table>`, `<nav>`
- ARIA labels on icon-only buttons
- Live regions for dynamic updates (toast, status changes)

---

## Distinctive Choices (vs. Generic SaaS Defaults)

1. **No card shadows** — borders only. Feels more clinical, less "dashboard kit"
2. **Teal brand** — not blue, not purple. Specific to healthcare trust.
3. **IBM Plex Sans** — not Inter. Technical character, tabular numerals built-in.
4. **Left-aligned everything** — no centered hero, no centered cards.
5. **Dense tables** — 12px padding, not 16px. Professionals scan dense data.
6. **Status = colored badge + dot indicator** — dual encoding (color + shape) for accessibility.
7. **No "eyebrow" labels** — section titles are H2/H3, not ALL-CAPS labels.
8. **Time in clinic timezone** — always displayed with timezone abbreviation (IST, PST, etc.)

---

## Self-Critique Checklist (Pre-Build)

- [ ] Does this look like a generic SaaS dashboard? → If yes, push harder on typography and density.
- [ ] Is teal used decoratively anywhere? → Remove. Teal = action/active only.
- [ ] Are there any gradients? → Remove.
- [ ] Do cards have shadows? → Replace with borders.
- [ ] Is the type scale modular? → Verify.
- [ ] Can a colorblind user distinguish status badges? → Dual-encode with dot indicator.
- [ ] Is the layout responsive down to 375px? → Plan mobile stack order.