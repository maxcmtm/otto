# Otto: design direction for the landing page and the app

29 September 2026 · research pass for `platform/landing.html` and `platform/index.html` · English only

**The direction in one line:** daylight, porcelain and one real object. The only 3D protagonist is a phone with Otto's actual UI on it. Everything else is the real product UI, set in type the way Apple sets it. It should feel alive because things respond to you, not because things float.

---

## 1. Reference board (20 sites)

We checked rows 1–13 in a live browser on 29 September 2026.

| # | Site | Borrow exactly this | Avoid |
|---|---|---|---|
| 1 | Apple, iPhone 18 Pro: https://www.apple.com/iphone-18-pro/ | After the hero, a floating local-nav pill appears ("iPhone 18 Pro · Explore · Buy"). Highlight films carry a pill progress indicator and a **pause button**. | Black stage, chrome type, 14 autoplay videos |
| 2 | Apple, AirPods Pro 3: https://www.apple.com/airpods-pro/ | 12 sticky stages, 16 videos, **0 canvas**: Apple has left image sequences behind. One idea per sticky stage, and only transforms are scrubbed. | Media weight |
| 3 | Linear: https://linear.app | **Two-tone section intros**: the first sentence in ink, the rest in grey, at the same size (Inter Variable 510, −0.022em) | Dark-only canvas; isometric wireframe illustrations (a template trope) |
| 4 | Stripe: https://stripe.com | **One live number above the H1** ("Global GDP running on Stripe: 1.72338220%"), small and tabular | The multicolour WebGL gradient and gradient headline text, which is the AI look itself |
| 5 | Raycast: https://www.raycast.com | Product UI rendered live in HTML; a dock of feature buttons swaps the demo in place | WebGL glass slats with a red glow |
| 6 | Family: https://family.co and https://benji.org/family-values | Bento tiles that each loop **one** micro-interaction (the "Backing Up" pill); trays whose height morphs | Candy-coloured icons |
| 7 | Notion Calendar: https://www.notion.com/product/calendar | Details that match the real date: the icon read "29" on 29 September. A two-word headline. | The generic feature-card grid |
| 8 | Granola: https://www.granola.ai | An honest progress pill ("Enhancing notes" plus a spinner) instead of sparkles | Serif display (too close to Native's Garamond) |
| 9 | Mercury: https://mercury.com | A secondary CTA, **"Launch demo"**, that opens a real sandbox | Photoreal landscape hero (Native's territory) |
| 10 | Lusion: https://lusion.co | Objects that react to the cursor, with one soft key light and a real contact shadow | Preloader bar |
| 11 | Oryzo (Lusion): https://oryzo.ai | One object as protagonist, explained with **CAD dimension lines** | Long intro, orange annotations |
| 12 | Lando Norris, Awwwards Site of the Year 2025: https://landonorris.com | A cursor-driven mask that **reveals a second layer** | Neon lime, custom cursor, loader |
| 13 | Immersive Garden, Awwwards Agency of the Year 2025: https://immersive-g.com | Lighting discipline: one key light, soft falloff, no coloured light | Rendered an **empty grey page** in our GPU-less pane, the exact failure we must never ship |
| 14 | Locomotive: https://locomotive.ca | Line-masked heading reveals; weighted smooth scroll (Locomotive Scroll v5 runs on Lenis) | Long scroll-jacked sequences |
| 15 | Obys: https://obys.agency | Extreme contrast in type scale | Grain, letter scrambles, custom cursors |
| 16 | Active Theory: https://activetheory.net | **One persistent WebGL context** whose camera moves between sections | Full-screen immersive navigation |
| 17 | Resn: https://resn.co.nz | Physics as a **reward after the user acts** | Too many gimmicks |
| 18 | Spline: https://spline.design | Prototype the phone lighting there, then export glTF | Shipping `@splinetool/runtime@2.0.60`; pastel clay |
| 19 | Vaul: https://vaul.emilkowal.ski and https://devouringdetails.com | Sheet physics: velocity-based dismiss, background scaled to 0.94, snap points | shadcn defaults verbatim |
| 20 | Attio: https://attio.com | A hero that is the real product in HTML with realistic data | Announcement bar, cookie wall and chat bubble all in the first viewport |

---

## 2. What Native looks like, so Otto looks nothing like it

We read native.no live on 29 September 2026 (it is built on Next.js).

- **World:** a painted night fjord with a moon, stars, waterfalls and birches. A **mascot**, a hiker whose head is a star, stands in the hero. Illustrated 3D props sit at the page edges: a cairn, a bollard, brass scales.
- **Colour:** midnight `#0F1420`, cream text `#E8E4D2`, ivory `#F4F1E6`, gold `#E9B638` and `#DCB75E`, browns `#2A2620` and `#5C5649`, teal and green vignettes in the corners.
- **Type:** **EB Garamond** display and italic sub-lines, Inter for UI. The hero is a typewriter: "Marketing for |".
- **Components:** a gold 8-point star logo; cream pills; a "New · Native Autopilot is live" chip; URL, then "Generate", then "50 posts"; an **infinite post marquee**; "Backed by" YC plus angels; **uppercase step labels** ("1. ADD YOUR WEBSITE"); dark glass panels with macOS window dots; a **swipe left/right approval deck** ("12 in queue"); a Refine chat; a comparison table with a highlighted column; a testimonial carousel with an italic serif quote and gold dots.

**Otto therefore:** daylight, not night. Porcelain and graphite, not navy and gold. Sans only. Real posts, never illustration. No character, marquee, swipe deck, typewriter, uppercase labels, window dots or highlighted-column table. **Otto's dark mode is neutral graphite `#0C0D0F`, never navy.**

---

## 3. Landing concepts

**Concept A: "One tap" (recommended).** An Apple-style device story. A real 3D phone in a porcelain finish carries **Otto's live DOM UI** on its screen. The owner taps Approve, and the post lifts off the glass and fans out into its channels. Scroll carries the same phone through the loop: reads, plans, asks, publishes, reports. One object, one camera, one story.

**Concept B: "The month, assembled."** The hero is a 3D month grid of 35 porcelain tiles. A floating browser card of a business's site sheds its photos and colours into tiles that flip over to reveal finished posts. Entering your URL rebuilds the grid from `/otto-peek`.

**Why A:** B's promise ("URL in, month of posts out") is Native's hero promise ("we'll generate 50 posts"). It also hides Otto's real edges: the owner stays in control, Otto speaks first, reports every morning and watches competitors. And B needs the live API to return something convincing in 5 seconds. A explains the product without the visitor reading a word. **Keep B's personalisation** as chapter 1 and the final CTA.

### A: storyboard

| # | Section | Desktop (≥1024px) | Phone (≤430px) |
|---|---|---|---|
| 0 | Nav | 64px, transparent. After 8px of scroll: `rgba(245,247,251,.72)` with `blur(20px) saturate(180%)` and a scroll-edge fade instead of a border. After the hero, an Apple-style pill: "Otto · from €69 · Get started". | 56px; the menu is a full-height sheet |
| 1 | **Hero** | Left, 6 columns: a live line "Tuesday 29 September · 3 posts ready for review"; the **static H1** (the LCP element) "Your marketing department, in your pocket."; the URL field with "Scan my site"; a link "Open the live demo". Right, 6 columns: the **3D phone stage**. | H1 44px, then the field, then a 440px stage. The fan-out goes **downward**. Tier B. |
| 2 | This week's work | A shelf of **real pilot posts** (with consent) showing channel, time and status. Scroll-snap, draggable with inertia; scroll drifts it 120px left. **No marquee.** | Native scroll; cards 78vw |
| 3 | Reads your business (pinned 180vh) | Two-tone intro, plus the sample site as real DOM with a **180px X-ray lens** that reveals hairline CAD annotations ("Voice: warm, practical", "Palette #2F5D50 / #F3EDE2", "Hours → posts at 07:30 and 18:00"). At scroll 0 to 0.6, the annotations **fly (Flip) into the phone** as its Brand profile. "Try it on your site" streams the real `/otto-peek` steps. | Annotations become a tappable list under the site card; not pinned |
| 4 | Plans the month (pinned 160vh) | The phone's mini calendar **expands** into a 1200px month (shared element). Tiles fill in reading order (24ms stagger, 480ms cap). The grid then tilts `rotateX(0→18deg)` and dims. Hovering a day shows the reason: "Payday Friday: offer post". | 7-column mini grid; a day opens a bottom sheet |
| 5 | Asks first (not pinned) | The phone returns face-on with an **interactive Review** screen. Approve → check → the row collapses → toast "Scheduled · Thu 18:00 · Undo". Change opens a sheet with "Warmer", "Shorter" and "Mention the offer"; the caption re-flows word by word. **Hold to approve all** fills a 900ms ring. "Or approve from Telegram." | **No phone inside the phone:** the real UI runs full width in a 28px panel |
| 6 | Publishes everywhere (pinned 140vh) | One post adapts along a rail: IG 1:1, Story 9:16, FB 4:5, Google Business, Search ad, email. Each chip flips from Scheduled to Published as it crosses the centre. The winner gains "Boosted · €10/day". | Carousel with a pill pager |
| 7 | Reports every morning | A notification lands at 07:30 and **morphs** into the report: the line draws in 900ms, bars pop, digits roll. Then a drop alert with [Apply], then three competitor diffs. | Full width; chart 180px tall |
| 8 | What Otto replaces | One calm cost bar chart: agency €1,500–6,000, freelancer plus tools, Otto from €69 | Stacked |
| 9–11 | Pricing, proof, FAQ | See below. The FAQ uses `<details>` with `interpolate-size` where supported. | Same |
| 12 | Final CTA | The hero phone returns: "Your first month is ready to review" (personalised if the visitor scanned) | Same |

### Hero 3D scene: Otto's value in 5 seconds

**The object.** A **generic** phone, never an iPhone replica: flat aluminium sides, a 2mm bezel, no notch, no visible camera plateau.
- Porcelain finish `#D9DCE1` (metalness 1, roughness 0.32); graphite in dark mode.
- It stands at yaw −14° and pitch 6° on a porcelain floor with a **baked contact shadow**.
- The body is WebGL. The **screen is real DOM**, aligned by `CSS3DRenderer` with `matrix3d`, so it is crisp, selectable and tappable.

**The loop** (9.6s): it starts 600ms after LCP, pauses offscreen, and has a 32px pause button.
- **0.8s:** a translucent 44px touch disc (no hand) presses Approve: scale 0.96, then a spring back, then a check drawn in 240ms.
- **1.4s:** the post **lifts off the glass** along +Z, casting its shadow on the screen.
- **2.0s:** it splits into 1:1, 9:16 and 1.91:1. Each re-flows (Flip, 360ms) into a labelled slot: "Instagram · Thu 18:00", "Facebook · Fri 09:00", "Google Business · Sat 10:00".
- **5.2s:** the first chip flips to **Published**, and "Reach 1,284" (sample, labelled) rolls up.
- **6.0s:** the cards return and the screen shows "2 posts ready".

The visitor can tap Approve or Skip at any time. Parallax is yaw ±6° and pitch ±3° (lerp 0.075). Nothing bobs while idle.

**Scene:** FOV 22° (the telephoto product-photo look), `RoomEnvironment` through PMREM at 0.6, one key light from the top left, AgX tone mapping, render on demand.

**Three render tiers:**
- **A (desktop):** WebGL body plus CSS3D screen.
- **B (phones and low power):** a pre-rendered AVIF shell (≤60KB at 2x, transparent screen). The live DOM screen is **corner-pinned** into it with a `matrix3d` homography computed once from the render's four screen corners. CSS parallax ±3°. No WebGL.
- **C (reduced motion or no JS):** the same AVIF, with the final fanned-out state rendered statically.

### Scroll choreography
1. **One pinned chapter at a time.** Pins run 140–180vh; total pinned length stays ≤480vh.
2. Scrub **space** (transforms and camera) with `scrub: 0.6`. **Never scrub text.** Text reveals once: 560ms, `--ease-out`, lines staggered 60ms.
3. No snapping and no speed hijacking. Lenis runs on desktop wheel only (`lerp 0.12`, `syncTouch false`).
4. A sentence-case progress rail ("Reads · Plans · Asks · Publishes · Reports") shows the current step in ink and the others in `--ink-3`. Steps are clickable.
5. At progress 1, every chapter matches its static HTML exactly.

### Micro-interactions
- **Press:** scale 0.97 on `pointerdown` over 80ms, release on the snappy spring. **Hover:** fill darkens 6% over 140ms. **Focus:** 2px `--accent` ring with a 2px offset.
- The URL button morphs into a progress capsule that names the current step.
- Link underlines draw from the left in 180ms. Cards lift 4px and move from shadow-1 to shadow-2, with the image at 1.02, over 360ms.
- The monthly/yearly segmented thumb slides on a spring, and prices roll with NumberFlow.
- Native cursor only. No sound.

### Real product UI on the page
- One shared layer, `platform/assets/otto-ui.css` and `otto-ui.js`, serves the app.
- The landing mounts it as `<otto-screen view="review" fixture="happygarden">`: shadow DOM, fed by fixture JSON, network sandboxed.
- The same fixtures power "Open the live demo" (`index.html?demo=1`).
- Result: zero screenshots, screens that never go stale, real accessible text.

### Social proof and pricing
- **Proof:** real pilot posts (dated, with consent), real numbers with a date and source, and a short **founder note from Max** with a real photo and signature. No logo wall and no invented testimonials.
- **Live counter**, Stripe-style: "Posts prepared this month: 1,284", shown only when it comes from real data.
- **Pricing:** Starter €69, Growth €149, Agency €399, excluding VAT, yearly −20% (`docs/PRICING-EU.md`, pending Max's approval). White cards with hairline borders; Growth is lifted **one elevation level**, not coloured. The founding pilot (€197, one time) sits in a quiet band above. Figures are tabular, with the currency at 0.6× size.

---

## 4. Design system tokens

```css
:root{ /* light: porcelain daylight */
  --bg:#F5F7FB; --surface:#FFFFFF; --surface-2:#EEF1F6; --elevated:#FFFFFF;
  --ink:#10182B;   /* 16.5:1 on bg */
  --ink-2:#5B6478; /* 5.5:1: secondary text */
  --ink-3:#7A8397; /* 3.8:1: ≥18px or non-text only */
  --line:#E4E8F1; --line-soft:#EDF0F6; --hair:1px;
  --accent:#2447F0; --accent-press:#1631B8; --accent-tint:#EDF1FF; --on-accent:#FFFFFF; /* 6.5:1 */
  --green:#0B7A4B; --green-tint:#E5F6EE; --amber:#B45309; --amber-tint:#FFF4E2; --red:#B4231F; --red-tint:#FDEBEA;
  --scrim:rgba(16,24,43,.32);
}
@media (min-resolution:2dppx){ :root{ --hair:.5px } }
:root[data-theme=dark]{ /* neutral graphite, never navy */
  --bg:#0C0D0F; --surface:#16171A; --surface-2:#1E2024; --elevated:#24262B;
  --ink:#F2F3F5; --ink-2:#A3A8B3; /* 7.5:1 */ --ink-3:#8D95A5; /* 6.0:1 */
  --line:#2A2C31; --line-soft:#212327;
  --accent:#6E88FF; /* links 5.7:1 */ --accent-fill:#4461F5; /* white text 4.9:1 */ --accent-tint:#1B2240;
  --green:#34C77B; --amber:#F5A524; --red:#FF6B61; --scrim:rgba(0,0,0,.5);
}
```
Cobalt covers **≤5% of any viewport**: the primary action, the selected state and "Otto is working". Channel logos are monochrome `--ink-2`.

**Type.** The **app uses the system stack only** (the owner's rule): `-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI Variable", Roboto, system-ui, sans-serif`.

The **landing** pairs **Mona Sans** display (Google Fonts, OFL, `wdth,wght@75..125,200..900`, used at wdth 100) with the system stack for body text.
- Mona Sans is a precise neo-grotesk, unlike Native's Garamond and unlike the Inter, Geist and Instrument Sans defaults of AI-built sites.
- Self-host the GitHub release to get its `opsz` axis: Latin subset, ≤60KB woff2, preloaded.
- Paid alternative: Klim's **Untitled Sans**. Avoid Söhne, which is ChatGPT's face.
- Always use `tabular-nums` for numbers, `text-wrap: balance` for headings, `text-wrap: pretty` for paragraphs.

| Token | Size / line-height | Weight | Tracking |
|---|---|---|---|
| display-xl (H1) | clamp(44px, 6.4vw, 92px) / 1.0 | 620 | −0.035em |
| display-l (H2) | clamp(34px, 4.4vw, 64px) / 1.04 | 600 | −0.03em |
| display-m (H3) | clamp(26px, 2.6vw, 40px) / 1.1 | 600 | −0.022em |
| lead (system) | clamp(19px, 1.5vw, 23px) / 1.42 | 400 | −0.01em |
| body · small · caption | 17/1.55 · 15/1.45 · 13/1.35 | 400–500 | 0 to +0.005em |
| App (iOS defaults) | Large Title 34/41 700 · Title2 22/28 600 · Headline 17/22 600 · Body 17/22 · Subhead 15/20 · Footnote 13/18 · Caption 12/16 | | Large Title −0.02em |

**Radii:** 6 (chips), 10 (inputs, thumbnails), 14 (app cards), 20 (panels), 28 (stages), 44 (phone screen), 999 (pills). Nested radius = outer − padding.

**Depth:** at most **three elevations on screen at once**. Resting cards get a hairline and no shadow. Only floating or moving things cast shadows, and **shadows are never tinted** (delete today's cobalt `--shadow-m`).
```css
--shadow-1: 0 1px 2px rgba(16,24,43,.06), 0 1px 1px rgba(16,24,43,.04);             /* floating bars */
--shadow-2: 0 6px 16px -4px rgba(16,24,43,.12), 0 2px 4px rgba(16,24,43,.06);       /* lifted/dragged card, popover */
--shadow-3: 0 24px 48px -12px rgba(16,24,43,.22), 0 8px 16px -8px rgba(16,24,43,.10); /* sheet, hero phone */
/* dark: elevation = lighter surface + inset 0 1px 0 rgba(255,255,255,.06) + 1px var(--line) */
```

**Grid:** 12 columns, max 1200px, 24px gutters and 64px margins at ≥1280px. Tablet: 8 columns, margins 40px. Phone: 4 columns, 16px gutters, 20px margins. Spacing scale (4px base): 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96, 128, 160. Sections are 160px apart on desktop and 96px on phone.

**Motion:**
```css
--dur-press:80ms; --dur-fast:140ms; --dur-base:220ms; --dur-med:360ms; --dur-slow:560ms; --dur-chart:900ms;
--ease-out:cubic-bezier(.22,1,.36,1); --ease-in-out:cubic-bezier(.65,0,.35,1); --ease-in:cubic-bezier(.55,0,1,.45);
/* springs as CSS linear(), from Apple response/damping (mass 1) */
--spring-snappy: linear(0,.084,.246,.412,.562,.681,.771,.839,.888,.922,.947,.964,.975,.983,.989,.993,1);  /* 360ms · k439 c41.9 · response .30, damping 1 */
--spring-smooth: linear(0,.083,.243,.413,.559,.678,.77,.838,.887,.922,.946,.964,.975,.983,.989,.992,1);   /* 480ms · k247 c31.4 · response .40, damping 1 */
--spring-sheet:  linear(0,.056,.177,.317,.457,.579,.683,.765,.831,.881,.917,.944,.963,.976,.985,.991,1);  /* 470ms · k158 c23.1 · bounce .08 */
--spring-pop:    linear(0,.08,.251,.451,.635,.787,.898,.974,1.018,1.039,1.045,1.042,1.035,1.026,1.017,1.01,1); /* 500ms · k195 c19.5 · 4.5% overshoot: success only */
```
- Gestures use JS springs with the same parameters, e.g. `{type:'spring', duration:.3, bounce:0}`.
- Stagger: 40ms for lists (up to 8 items), 24ms for grids (480ms cap).
- Overshoot only after momentum or success.

**Icons:** a custom set of about 24 on a 24px grid. Stroke 1.5px, round caps, 2px corner radius on rectangles; the filled variant only for the active tab. Channel marks are the official glyphs in monochrome. No Lucide defaults, sparkles or wands.

---

## 5. App "alive" spec (`platform/index.html`)

1. **Shared elements.** Thumbnail to detail uses View Transitions (`view-transition-name: post-<id>`, `::view-transition-group(*){animation:360ms var(--spring-smooth)}`). Tab changes are a 180ms crossfade with an 8px directional shift. Supported in Chrome 111+, Safari 18+ and Firefox 144+.
2. **Live activity.** A header pill fed by real job states in `data.json` (polled every 30s):
   - "All caught up · next post Thu 18:00"
   - "Drafting Thursday's reel · 2 of 5"
   - "3 posts need you"
   - "Publishing to Instagram"
   - "Reach down 32%"

   Its width morphs on the smooth spring and the text crossfades in 180ms. A 6px dot pulses only while Otto is working, with no glow. Tapping it opens **Today's timeline** (07:30 report · 09:00 published · 10:12 competitor sweep · 14:00 drafting).
3. **Approval.** Replace the Tinder deck (`attachDrag`, `.rv-card.fly`) with **iOS-Mail row swipes**:
   - Drag right to approve, drag left to skip. Direction locks after 10px, then tracking is 1:1 from the grab offset.
   - It commits past 55% of the width or above 0.5px/ms, rubber-bands past the edge, and gives one haptic tick at the threshold.
   - Detail Approve sequence: press 0.97 → spring → drawn check (240ms) → the row collapses (smooth spring) while the rows below Flip up → toast "Scheduled · Thu 18:00 · Undo" (5s) → the badge rolls down with a pop.
   - "Approve all" is **hold for 900ms** with a ring; releasing early springs it back.
4. **Charts.** SVG. The line draws once (900ms); updates **morph point by point** (480ms), never redraw. Last month is a ghost line in `--ink-3` at 40%. Bars pop with a 40ms stagger, digits use NumberFlow, and scrubbing shows a crosshair with a tabular tooltip.
5. **States.**
   - Skeletons match the rows exactly (72px) with a 4% shimmer, static under reduced motion.
   - Generation shows named steps ("Designing image 2 of 3").
   - Empty: "You're all caught up. Next posts arrive Sunday at 18:00."
   - Error: "Instagram disconnected. Posts are paused until you reconnect." plus Reconnect.
   - No illustrations.
6. **Haptics.** Visual first. On Android, `navigator.vibrate?.(8)` on commit, snap and threshold only. On iOS 18+ Safari, optionally toggle a hidden `<input type="checkbox" switch>` for the system haptic.
7. **Depth.**
   - Three layers. The translucent tab bar and nav use `blur(20px) saturate(180%)` and go solid under `prefers-reduced-transparency`.
   - Sheets dim with `--scrim` and scale the page behind to 0.94 with a 12px radius. Snap points are 50% and 92%.
   - Dismissal uses Apple's projection `v/1000·0.998/(1−0.998)`, and a sheet exits along the path it entered.
8. **Mobile-first.** A 49px tab bar plus the safe area; primary actions in the thumb zone. The large title collapses on scroll (`animation-timeline: scroll()` with a JS fallback). Pull-to-refresh arc. Hit targets ≥44px.

**Everything here is plain CSS and JS:** View Transitions, CSS `linear()` springs, Pointer Events plus WAAPI (always start from the *current* computed transform so motion can be interrupted), and IntersectionObserver. The only dependency is **NumberFlow 0.6.2**. Optionally add `motion/mini` plus `spring` from `motion@13.4.4` (**5.6KB gz, measured**).

---

## 6. Technical plan

| Library (pinned) | URL | gz (measured) |
|---|---|---|
| GSAP 3.15.0 core, ScrollTrigger, SplitText, Flip | https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/{gsap,ScrollTrigger,SplitText,Flip}.min.js | 28.3 / 18.0 / 3.6 / 9.7KB |
| Lenis 1.3.26 | https://cdn.jsdelivr.net/npm/lenis@1.3.26/dist/lenis.min.js plus `lenis.css` | 5.4KB |
| NumberFlow 0.6.2 | https://cdn.jsdelivr.net/npm/number-flow@0.6.2/+esm | 6.1KB |
| three 0.186.1 (Tier A only) | https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.module.min.js (imports `three.core.min.js`) | ~194KB via CDN |
| three add-ons | `…/three@0.186.1/examples/jsm/{loaders/GLTFLoader, renderers/CSS3DRenderer, environments/RoomEnvironment, libs/meshopt_decoder.module}.js` | 25.9 / 3.1 / 1.7 / 7.7KB |

- cdnjs mirrors the same versions (`https://cdnjs.cloudflare.com/ajax/libs/gsap/3.15.0/…`, `…/three.js/0.186.1/…`). Lenis is not on cdnjs.
- **GSAP licence:** since 3.13, all of GSAP, SplitText included, is free for commercial use under the "Standard no-charge license" (https://gsap.com/standard-license). Its one exclusion is products that compete with Webflow, which Otto does not.
- **Self-host a tree-shaken esbuild bundle of three:** 163KB gz measured, against about 230KB for the CDN files. jsDelivr minifies `three.module.min.js` on the fly, so SRI can't be used. Put the bundle in `platform/assets/vendor/`.
- **Fallback for Tier A:** OGL 1.0.11 at 22KB gz (measured, with GLTF), at the cost of hand-written shaders.
- **Not used:** React Three Fiber, `postprocessing`, the Spline runtime, Rive.

**Load order:**
1. An inline head script (≤1KB) sets the `data-theme`, `motion` and `tier` classes.
2. HTML and CSS render the complete page.
3. A deferred module loads GSAP, Lenis and NumberFlow.
4. After LCP, on `requestIdleCallback`, and only for Tier A with the hero in view, `import('stage-3d.js')` loads with a ≤250KB meshopt GLB. The context is created with `failIfMajorPerformanceCaveat:true`; failure falls back to Tier B.

**Tiers:**
- **B:** `pointer:coarse` below 1024px, `saveData`, `deviceMemory<4`, `hardwareConcurrency<4`, or no WebGL2.
- **C:** reduced motion.
- **Runtime guard:** an average frame time above 22ms over 60 frames drops DPR to 1, then swaps to Tier B with a 200ms crossfade.

**Platform features:**
- **CSS scroll-driven animations** are decoration only (nav edge, title collapse), inside `@supports (animation-timeline: view())`. They ship in Chrome 115+ and Safari 26; Firefox stable still has them behind a flag as of September 2026. The story runs on ScrollTrigger.
- **View Transitions:** same-document everywhere in the app. Cross-document (`@view-transition{navigation:auto}`) handles landing → demo in Chrome 126+ and Safari 18.2+.

**Budget (p75):**

| Metric | Budget |
|---|---|
| LCP (the H1, never the canvas) | ≤1.8s desktop, ≤2.5s mid-range Android on 4G |
| INP | ≤150ms |
| CLS | ≤0.02 (the stage reserves its aspect ratio) |
| TBT, mobile | ≤150ms |
| Initial JS | ≤95KB gz |
| Tier A add-on | ≤180KB gz JS + ≤250KB GLB |
| CSS | ≤14KB critical inline, ≤40KB total |
| Font | ≤60KB |
| First-viewport images | ≤250KB (AVIF thumbnails ≈35KB) |
| Page weight | ≤1.6MB desktop, ≤900KB phone |
| GPU | ≤50 draw calls, ≤80k triangles, DPR ≤1.75, render on demand, ≤12ms per frame on M1 or Iris Xe, paused offscreen and on `visibilitychange` |

**Reduced motion:** no Lenis, pins, parallax or loop; the hero shows its final state and transitions become 150ms crossfades. `prefers-reduced-transparency` makes the chrome solid. `prefers-contrast: more` adds 1px borders.

**Accessibility (WCAG 2.2 AA):**
- The canvas is `aria-hidden`, and the DOM screen carries the content.
- The loop has a pause control (SC 2.2.2). A "Skip the story" link sits before the pins.
- Keyboard scrolling works because Lenis keeps native scroll. Contrast ratios are listed in §4, targets are ≥44px, and chips change their text as well as their motion.

**Rule: every section is readable at rest with no JS.** Today, `landing.html:61` sets `.rv{opacity:0}` by default, so screenshots come out blank.
1. **Author the final state in HTML and CSS:** cards fanned out, the calendar filled, the chart drawn.
2. **JS rewinds; it never hides.** A start state is applied only when an element is *armed* (IntersectionObserver, `rootMargin: 50% 0px`, one viewport ahead). A second observer at `threshold .15` plays it. Anything never armed stays visible.
3. All reveal CSS is scoped under `html.motion`, which is set only when there is no reduced motion, `!navigator.webdriver` is true, and there is no `?static=1`. `beforeprint` reveals everything.
4. **CI gate:** Playwright full-page screenshots with JS off, with `?static=1`, and at 390px width. The build fails if any section's text has computed opacity below 1.

---

## 7. Anti-patterns checklist (reject on sight)

1. Purple, blue or multicolour mesh gradients; gradient headline text.
2. Neon glow, coloured shadows, blurred colour blobs (today's radial cobalt and green body background goes).
3. Glass on glass; blur only on nav, tab bar and sheets.
4. Bokeh, particles, starfields, orbs (retire `assets/core-sphere.png` and the gradient 3D logo mark).
5. Sparkle and wand icons; "✨ AI-powered", "Supercharge", "Unlock", "Revolutionize".
6. Emoji in the UI or headings.
7. Mascots, illustrated avatars, clay characters; use initials or real photos.
8. Uppercase letter-spaced mono labels, "01 /" corner numerals, fake terminals.
9. Serif display with navy and gold (that is Native).
10. An infinite marquee or a typewriter headline.
11. A Tinder swipe deck for approvals.
12. Traffic-light window chrome around every demo.
13. Bento tiles that are only an icon, a title and two lines of copy.
14. Idle floating or bobbing; every motion needs a cause.
15. Preloaders, a blank canvas without WebGL, content left at opacity 0.
16. Custom cursors, magnetic buttons, cursor trails.
17. Scroll-jacked speed, forced snapping, pins longer than 200vh.
18. Invented metrics, testimonials, logos or star ratings.
19. Product screenshots instead of live DOM; laptop and handshake stock photos.
20. The default Inter, Lucide, shadcn and Tailwind look (slate-500 text, `rounded-2xl` everywhere, indigo-600 buttons) and one-size letter-spacing.

*Method: versions resolved via the jsDelivr API on 29 September 2026. Sizes were measured by bundling with esbuild in a scratch folder, and nothing was added to the project. Fonts were checked against the Google Fonts CSS2 API.*
