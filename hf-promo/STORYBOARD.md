# STORYBOARD — 医保智审规则库 · 20s 产品宣传片

Total: 20.0s. Five beats. Single composition (index.html).

| # | Time (s) | VO segment | Visual | Motion |
|---|----------|-----------|--------|--------|
| 1 | 0.0 – 3.8 | 医保监管规则与知识库 | Dark hero header bar slides down from top, brand pill "医保监管" appears, then H1 "医保监管规则与知识库" fades up centered on a dark #1d2129 background with a subtle blue tint vignette. | Header: y:-120 → 0, opacity 0→1, 0.6s, power2.out. Pill: scale 0.8→1, opacity 0→1, 0.4s, starts at 0.6s. H1: opacity 0→1, y 16→0, 0.7s, starts at 1.0s. |
| 2 | 3.8 – 7.6 | 收录两万多个医保编码, 一万五千余条临床规则 | Scene cross-fades into a light card on #f5f7fa. Card contains the search bar, the four stat blocks (21,576 知识库 · 28,214 医保编码 · 规则 (31+45) · 16个批次), each stat number tween from 0 to target. | Card: opacity 0→1, scale 0.96→1.0, 0.5s. Stats: stagger 100ms, 0.9s tween per stat from 0 → target. |
| 3 | 7.6 – 12.4 | 药品、耗材、服务项目、中药饮片, 一站式检索 | A row of four colored pill-tags (#e8f3ff/#fff1e8/#e8ffe8/#f3e8ff) slides in below the card with category names. Below: a search-input mock with query "麝香保心丸" and an animated caret, returning rows of recent rule updates. | Tags: stagger 90ms, y 16→0, opacity 0→1. Search results: each row fades in stagger 100ms, translateY 12→0. |
| 4 | 12.4 – 16.5 | 支持中文、拼音首字母、医保编码三种方式 | The search bar morphs through three states: 中文 → "afngw" (pinyin) → "ZD03AAA0043010100166" (code). A small chip below explains each mode. | Search bar text crossfade 3x, 1.2s each. Chip label swap. |
| 5 | 16.5 – 20.0 | 医保智审, 监管就在指尖 | Whole card scales up slightly and dims; the brand pill animates in center bottom: "医保智审 · 监管就在指尖" as a final CTA. | Card: scale 1.0→1.03, opacity 1→0.6. CTA pill: y 24→0, opacity 0→1, 0.7s. |

## Voiceover timing
Narration file generated via hyperframes tts at 1.0× speed, total ~20s.
- 0.0s — 3.8s: Beat 1 (H1 reveal)
- 3.8s — 7.6s: Beat 2 (stats)
- 7.6s — 12.4s: Beat 3 (categories + recent results)
- 12.4s — 16.5s: Beat 4 (3 search modes)
- 16.5s — 20.0s: Beat 5 (closing CTA)

## Asset list
- **Logo / brand pill**: "医保监管" rendered in HTML (text-based, brand-tinted).
- **Stats**: animated numeric tweens, no images required.
- **Tags**: text pills rendered in HTML, four category colors.
- **Search results**: mock rule cards rendered in HTML (no real data fetch).
- **Background**: solid color + radial gradient.
- **Audio**: TTS-generated narration WAV.

All visuals are pure HTML/CSS — no external image dependencies. The captured screenshot is used only for design reference.
