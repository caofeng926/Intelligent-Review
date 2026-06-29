# DESIGN — 医保智审规则库 · 20s 产品宣传片

## Style Prompt
A clean, authoritative Chinese government-tech product promo. The visual is a polished screen-capture-style product demo: a soft card stack floating on a light blue-gray background, with subtle scale-in entrances, a confident sans-serif typeface, and the brand blue #1677ff used as the single saturated accent against a near-white backdrop. Mood: precise, trustworthy, professional, modern public-sector data platform. Pacing is calm and rhythmic, with stat numbers sliding up as Chinese narration lands. Motion language is light (8–14px translate, 0.95→1.0 scale), no bounce, no playful arcs.

## Colors
- **Brand blue** #1677ff — primary accent, headline underline, highlight pulses.
- **Brand blue dark** #0e5fd6 — pressed/hover state, secondary accent.
- **Brand blue tint** #e8f3ff — soft background fills, hero gradient start.
- **Page bg** #f5f7fa — outer canvas background.
- **Card bg** #ffffff — card surfaces, navigation bars.
- **Heading text** #1d2129 — display & H1.
- **Body text** #4e5969 — secondary copy.
- **Muted text** #86909c — captions, labels, annotations.
- **Success** #00b42a, **Warn** #ff7d00, **Danger** #f53f3f — used sparingly for badge dots and category tags.
- **Border** #e5e6eb — 1px dividers.

## Typography
- **Display / H1** (CN): PingFang SC, "Microsoft YaHei", system-ui, sans-serif; 64–88px; weight 700; color #ffffff on dark hero, #1d2129 on light.
- **Body / Stats**: same family; 22–36px; weight 500/600; color #4e5969.
- **Captions**: 16–20px; weight 400; color #86909c.
- All text is Chinese Simplified (zh-CN).

## Brand Cheat Sheet
- Logo wordmark: "医保监管" displayed as a pill nav item with blue tint background, white text.
- Search bar: rounded 24px, white fill, #e5e6eb border, magnifier icon left, placeholder text #86909c.
- Stat number: 72–96px, weight 700, color #1d2129 with .万 or unit suffix in 36px #4e5969.
- Stat label: 20–24px, color #4e5969.
- Buttons / tags: rounded 6–8px, soft tint backgrounds (#e8f3ff, #fff1e8, #e8ffe8, #f3e8ff), matching #1677ff/#ff7d00/#00b42a/#722ed1 text.
- Nav header: #1d2129 background (top hero), or white #ffffff (light variant).
- Page chrome: 12px rounded corners on cards, 6px on tags, generous 24–48px internal padding.

## Motion
- Default easing: power2.out, duration 0.5–0.7s.
- Entrance: scale 0.95→1.0 + opacity 0→1, translateY 12px→0.
- Exit: opacity 1→0, translateY 0→-8px, duration 0.4s.
- Stat number tick: tween from 0 to target over 0.9s, ease power3.out.
- Stat card stagger: 80ms between cards.
- Search-bar cursor blink: 1s loop, ease 
one.

## Composition Architecture
- Total duration: 20.0s, single composition (index.html).
- 5 beats driven by voiceover timing.
- Composition canvas: 1920x1080 (16:9).
- Background: solid #f5f7fa with a soft radial-gradient of #e8f3ff at top-left at 60% opacity.
- Subtle floating decorative pills in the far background to add depth.

## Accessibility
- All text meets WCAG AA contrast on its background (verified by hyperframes validate).
- Chinese narration audible over silent ambient; no overlapping audio.
- No flashing animations; transitions ≤0.7s.
