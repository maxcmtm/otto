# AI transparency: what the EU AI Act asks of Otto, and what Otto marks

Date: 2026-09-30 · Owner: Max · Status: marking built and tested; open decisions are listed at the end.

Code: `platform/otto_provenance.py` (the marker and a CLI), called from `genvisuals.py`, `otto_video.py`,
`otto_motion.py`, `otto_paths.ensure_jpeg` and `motion/ad-kit/ship.mjs`. Tests: `platform/tests/test_provenance.py`.
The customer-facing statement is `docs/legal/ai.md` (the legal pack); this document is the engineering and legal basis for it.

Sources were read on 30.09.2026 and are numbered in brackets, for example [G]. The list is at the end.

---

## 1. The rules that apply

**Article 50 of the AI Act (Regulation (EU) 2024/1689) has applied since 2 August 2026** [A][B].

- **Art. 50(2), providers.** A provider of an AI system that generates synthetic audio, image, video or text must
  make sure the outputs are "marked in a machine-readable format and detectable as artificially generated or
  manipulated". The technical solution must be effective, interoperable, robust and reliable "as far as this is
  technically feasible".
  - It does not apply "to the extent the AI systems perform an assistive function for standard editing or do not
    substantially alter the input data provided by the deployer or the semantics thereof".
- **Art. 50(4), deployers.**
  - A deployer that publishes a *deep fake* (image, audio or video) must disclose that it is AI-generated or manipulated.
    Art. 3(60) defines a deep fake as content that "resembles existing persons, objects, places, entities or events and
    would falsely appear to a person to be authentic or truthful".
  - AI-generated text published "with the purpose of informing the public on matters of public interest" must also be
    disclosed, unless a person reviewed it, has editorial control and holds editorial responsibility.
- **Art. 50(5).** The information must be given clearly, at the latest at the first exposure, and must be accessible.
- **Penalties (Art. 99(4), (6)).** Up to €15M or 3% of worldwide turnover. For an SME, whichever of the two is lower.
- **Timing.** The AI Omnibus (Regulation (EU) 2026/1744, in force 27.07.2026) gives generative systems placed on the
  market before 2 August 2026 until **2 December 2026** to meet Art. 50(2) [C].
  - The grace period covers only the marking duty, not Art. 50(4).
  - Content generated before 2 August 2026 does not have to be marked retroactively (Guidelines para 154).
  - Whether Otto counts as "placed on the market" before August depends on the pilot clients. Do not rely on the grace
    period: marking is built now.

### Where Otto sits

| Role | Who | Why |
|---|---|---|
| **Provider (Art. 50(2))** | Otto | A company that offers an image generator or AI agent under its own name to business users is a provider. This holds even when it runs on other companies' models (OpenAI via Leonardo, ElevenLabs, MusicGen, Anthropic), and even when it is outside the EU, as long as the output is used in the EU (Guidelines paras 10–11 [B]; Art. 3(68) "downstream provider"). |
| **Deployer (Art. 50(4))** | The client (the business that approves and publishes) | The deployer decides the purpose and how the output is used (Guidelines paras 12–15). Otto publishes on the client's instruction, so it may also be a co-deployer. This is not settled; the legal pack flags it for the lawyer. |

What the Guidelines [B] and the Code of Practice [D] add for Otto's case:

- **Upstream marks.** A provider may rely on the marking done by the upstream model provider "to the extent … compliant",
  but stays responsible (Guidelines para 74; Code, page 9).
- **Composites.** Content mixed with human-made material is still synthetic (para 59). Composites that change how
  people, objects or facts are shown must be marked (para 92).
- **Advertising workflows.** Only the *final* output has to be marked, not intermediate scene images (para 68). Otto
  marks the intermediates anyway, which costs nothing.
- **What is exempt (para 92).** Grammar fixes, translation, cropping, colour correction, noise removal, rescaling.
  Also short outputs such as captions and UI labels.
- **Audio.** Speech and music are in scope. A video needs both its picture and its audio track marked (para 60).
- **Ad text.** Advertising copy is outside the "public interest text" rule, *except* claims about health, consumer
  safety or sustainability. Those are covered by the human-review exception only when a person reviewed the text and
  someone holds editorial responsibility. In Otto, the client approves every post and campaign, and the approval is
  logged (`decided_at`, `approved_via`, `taste_log`). Keep that log: it is the evidence.
- **Deep fakes in ads (para 116).**
  - Deep fakes: an AI product image that misleads about the real product, and a realistic synthetic "influencer"
    presenting a product.
  - Not deep fakes: a real product on an AI background (if not misleading), and a synthetic narrator voice where
    nobody is deceived about who is speaking.
- **Detection.** Marking alone is not enough: the provider must also offer a way to check it (paras 69–70; Code
  Commitment 2). Today that is `otto_provenance.py inspect`. See the gaps in section 5.

**The Code of Practice on marking and labelling (final, 10.06.2026) [D]** is voluntary, but it is the benchmark.

- **Measure 1.1** asks for *at least two layers* of machine-readable marking. Layer 1 is digitally signed and
  time-stamped metadata (a C2PA-style manifest; plain unsigned IPTC/XMP does not meet this). Layer 2 is an
  imperceptible watermark. Fingerprinting or logging is optional, and not sufficient on its own.
- **Measure 1.2:** keep the metadata that inputs already carry, and forbid users from removing marks in the terms of use.
- **Measure 1.3:** record the AI system, the provider, the time and the model version.
- **Section 2, deployer labels:** an icon built around the capital letters "AI" (the EU icon or an equivalent),
  noticeable without any user action. On video it is shown at the start. On audio-only content, a short spoken notice.

## 2. What Otto marks today

Otto writes the **IPTC Digital Source Type** [E] into the file's XMP, together with `Iptc4xmpExt:AISystemUsed` (IPTC
2025.1 [F]), `xmp:CreatorTool` = "Otto", and `otto:Kinds` / `otto:Tool` / `otto:Law`. Two values are used:

- `trainedAlgorithmicMedia`: the whole file came out of a generative model.
- `compositeSynthetic`: a mix of elements, at least one of them generated. IPTC's definition is "Mix or composite of
  several elements, at least one of which is Generative AI".

> **Note on the brief.** The brief asked for `compositeWithTrainedAlgorithmicMedia` on composites. IPTC defines that
> term as "Augmentation, correction or enhancement using a Generative AI model, such as with inpainting or outpainting",
> which means GenAI edits of an existing photo, and Otto does not do that. Otto's slides and reels are mixes, so they
> get `compositeSynthetic`. `inspect` reads both terms as AI. If testing shows Instagram labels one and not the other,
> switch the single constant `otto_provenance.COMPOSITE`.

| Output | Where it is made | What is written into the file | Recorded in data.json |
|---|---|---|---|
| Post images (GPT Image 2 through the Higgsfield Cloud API, `otto_imagegen`; Leonardo as the fallback) | `genvisuals.save_image`, before the file is made public | Higgsfield's PNGs carry **no** C2PA manifest (checked on a real output, 3 Oct 2026): they are converted to JPEG and get XMP APP1 with `trainedAlgorithmicMedia`, tool "Higgsfield gpt-image-2". For a Leonardo image: if the file still carries **OpenAI's signed C2PA manifest** (`c2pa.created`, `trainedAlgorithmicMedia`), it is left byte for byte as it is: adding XMP would break the manifest's hash. OpenAI also embeds a SynthID watermark in these images (since 19.05.2026 [H]). All four Leonardo images in `assets/posts/` were checked and carry the manifest. Otherwise, XMP APP1 with `trainedAlgorithmicMedia`. | `post.media_ai[<ref>]` with `marked: "c2pa-upstream"` or `"xmp"` |
| Carousel slides (a generated image plus the post's text) | `genvisuals.run` (carousel step) | XMP `compositeSynthetic` | `post.media_ai[<slide ref>]` |
| PNG→JPEG conversion for Instagram | `otto_paths.ensure_jpeg` | The mark is carried over: ffmpeg would drop it | none (a conversion) |
| Reel scene images (Higgsfield GPT Image 2, else Leonardo) | `otto_video.scene_images`, as soon as they are saved | XMP (Higgsfield) or upstream C2PA / XMP (Leonardo), as for post images; the reel's `tool` names the scenes' own marks | none (intermediate) |
| Images we make for Otto's own ads (`otto_imagegen.py gen`) | `otto_imagegen.generate`, as soon as they are written | XMP `trainedAlgorithmicMedia`, tool "Higgsfield gpt-image-2" (`--no-mark` only for an intermediate that is composited and marked later) | none (not engine media) |
| Reels (`otto_video render`) with a generated scene and/or an ElevenLabs voice-over | `otto_video.render`, before publishing | MP4 `comment` and `description` tags (ffmpeg `-c copy`); an XMP packet in a top-level `uuid` box (Adobe XMP part 3), appended at the end of the file so no sample offset moves; and a sidecar `<file>.mp4.provenance.json` with the sha256 of the final bytes (published next to the video). All say `compositeSynthetic`, with kinds `image` / `voice`. | `post.media_ai[<video ref>]`: `kind` "voice" or "image", `kinds`, `tool` (e.g. "Leonardo.ai gpt-image-2 + ElevenLabs eleven_multilingual_v2") |
| Motion reels (`otto_motion finish`) | `otto_motion.finish`, before publishing | As for reels, with kinds `voice` (ElevenLabs via Higgsfield, unless `voice --human-voice`) and `music` (MusicGen bed). The visuals are motion graphics rendered from code. | `post.media_ai[<video ref>]` |
| Ad-kit videos (`motion/ad-kit/ship.mjs`) | after the render and the loudness fix, before anything is copied out | Final MP4 and web MP4 as above, when `sound.json` has voice clips (unless `"voice": "human"`) or a placed image in `assets/img/` carries an AI mark. The posters are marked `compositeSynthetic` when a generated image is in the ad. If marking fails, the ship stops (`--force` ships unmarked, with a warning). | the files' sidecars (the ad-kit has no data.json record) |
| Clients' faceless video ads (`platform/otto_advideo.py`, the ad kit in the brand's look) | after the render and the size check, before the files are made public | The 9:16 / 4:5 MP4s (as above, with a sidecar) and their posters, `compositeSynthetic`, when a picture placed in the ad (the product cut-out, a photo, the logo) carries an AI mark (`otto_provenance.inspect` on the original file). Silent reels have no voice; the music is the kit's procedural score: neither is marked. A failed mark is recorded as `marked: false`, the render is not stopped. | the matrix cell's `render.media_ai[<ref>]` (brands/<id>/ads-<month>.json) + the sidecars |

`media_ai` records use this shape:
`{"generated": true, "kind": "image|voice|music", "kinds": [...], "tool": "...", "source_type": "...", "marked": "xmp" | "c2pa-upstream" | "xmp+mp4-tags+sidecar" | false, "error"?: "...", "at": "..."}`.

- The owner console already receives counts in `brand.compliance.ai_media` (`generated`, `marked`, `unmarked` refs).
- Marking never stops a render. A failure is stored as `marked: false` with the error, so the console can flag media
  that went out unmarked.

### What is not marked, and why

- **Template cards built from the client's real photos plus text** (`otto_render`, `otto_creative` statics and cards).
  - A real photo with a text overlay, a logo and a brand frame is not synthetic image content. The layout is a
    template, and the photo is the deployer's own input, not substantially altered (the Art. 50(2) exception;
    Guidelines para 92 lists cropping, rescaling and colour correction as exempt).
  - The *copy* on the card is AI-assisted, but it is short marketing text. The client approves it and holds editorial
    responsibility, and it is not public-interest text (section 1).
  - **Exception:** when a card is built on an AI-generated image (a genvisuals output), the card contains a generated
    element and must be marked `compositeSynthetic`. `otto_provenance.propagate(src_photo, out_card)` does exactly that,
    and only when the source carries an AI mark. It is **not yet called** in `otto_render` / `otto_creative`, because
    those files belong to the ads-QA work. It is a one-line follow-up there.
- **Captions, hashtags, ad texts, scripts.** Plain text posted as text (see above).
- **The ad-kit music bed** (`audio/score.py`). A procedural synthesiser, not a trained model.
- **`otto_video demo`.** A local test reel that is never sent to a client.
- **Media generated before 2 August 2026.** No retroactive duty (Guidelines para 154). Anything re-rendered now is marked.

### Checking a file

```
python3 platform/otto_provenance.py inspect assets/reels/<id>.mp4          # AI … compositeSynthetic · voice,image · ElevenLabs …
python3 platform/otto_provenance.py inspect --json assets/posts/<id>.jpg   # reads XMP, MP4 tags, the sidecar and a C2PA manifest's source type
python3 platform/otto_provenance.py mark <file> --kind voice --tool "ElevenLabs" --composite
```

## 3. Meta, and the visible label

- **Organic posts.** Meta reads C2PA and IPTC metadata on uploaded *images* and shows "AI info" [I]. Video and audio
  depend on self-disclosure, using the "AI info" toggle when publishing photorealistic video or realistic audio [I][J].
  - An IPTC test (18.03.2026) found Instagram recognised IPTC DigitalSourceType but not C2PA, while LinkedIn and YouTube
    read C2PA but not IPTC [K]. That is why Otto keeps the upstream C2PA *and* writes IPTC wherever it can.
  - Meta strips the metadata from the files it serves after reading it (secondary sources, unverified).
- **Ads.** Since 1 June 2026 Meta detects third-party generative AI in ads through industry-standard signals. The
  "AI info" label sits in "About this ad", and next to "Sponsored" when the ad shows an AI photorealistic person [J].
  Ordinary commercial ads need no self-disclosure. Social-issue ads do.
- **Recommended visible policy.** For Max to decide; the legal pack currently says "default on, business can switch off".
  1. **Realistic synthetic people or voices presented as a person** (UGC-style avatars, "creator" videos made with AI;
     for example the German VSL anchor): these are deep fakes under para 116. They always carry a visible "AI" icon in
     a top corner from the first frame, plus "Made with AI" / "Gemaakt met AI" in the caption. Legally the client must
     disclose this, but Otto should not ship it without the label. The legal pack says Otto never presents an AI person
     as a real customer; the ad planner enforces that.
  2. **Photorealistic generated images of products or results**: never for "results" in health, beauty or aesthetics
     (NL Reclamecode Cosmetische Producten art. 2(10) forbids misleading use of AI [L]; UCPD). For other photorealistic
     scenes, Otto recommends a small "AI" corner mark, on by default for health, beauty and food, off by default for
     illustrative scenes.
  3. **Synthetic narrator voice-overs**: not a deep fake (para 116). No visible label is needed beyond the machine-readable
     mark. The "AI info" toggle on Reels is optional.
  4. **Template cards on real photos, and text**: no label.
- **Publishing API.** Otto's publisher does not set Meta's AI-disclosure flag. Whether the Graph API exposes one for
  Reels is unverified. Until it does, rule 1 content is labelled in the pixels and the caption.

## 4. Media flows that strip marks (and how they are handled)

| Step | Effect on the mark | Handling |
|---|---|---|
| ffmpeg re-encode (PNG→JPEG, overlays, reel assembly, web copies) | drops XMP and C2PA | Each pipeline marks *after* its last re-encode: `ensure_jpeg` carries the mark over, carousel slides are marked after the overlay, reels after assembly, and ad-kit after the loudness fix and again on the web copy. |
| Adding XMP to a file that has a C2PA manifest | would invalidate the manifest's hash binding | Such files are left untouched (`c2pa-upstream`). A manifest that does not declare AI is refused, never silently broken. |
| Upload to Meta | Meta reads, then strips (unverified) | nothing to do; the terms of use should ask clients not to strip marks (Code Measure 1.2 [D]). |

## 5. Gaps against the Code of Practice, and decisions for Max

1. **Signed metadata on Otto's own composites.**
   - Images straight from GPT Image keep OpenAI's signed C2PA manifest plus SynthID: two layers, from upstream.
   - Otto's composites (slides, reels, ad videos) carry *unsigned* IPTC XMP, MP4 tags and a sidecar. The Code's layer 1
     wants a signed, time-stamped manifest.
   - Next step: sign a C2PA manifest for each composite with `c2patool` or `c2pa-python`, using an ingredient reference
     to the upstream image. This needs a signing certificate from a CA on the C2PA trust list, and a vendored binary
     (not stdlib).
   - **Decision:** buy or get a certificate and add the step before 2 December 2026?
2. **Watermark layer on composites and voice.**
   - OpenAI's SynthID is in the source pixels. Whether it survives the Ken Burns zoom, the caption bands and compression
     is not tested.
   - ElevenLabs is rolling SynthID out to all tiers during July 2026, per a help-centre snippet. Whether Otto's API tier
     is watermarked is **unverified**; check it in the ElevenLabs account.
   - No stdlib watermarking is planned; rely on upstream and document it.
3. **Detection tool.**
   - `otto_provenance.py inspect` exists. The Guidelines and the Code expect detection to be available to others.
   - A public "check a file" endpoint needs `otto_api.py`, which another engineer owns; this is a follow-up.
   - Deadline: interoperable watermark detection is due 2 February 2027 (Code Measure 3.4).
4. **Template cards that contain an AI image.** Add `otto_provenance.propagate(src, out)` in `otto_render` / `otto_creative`
   (ads-QA owner).
5. **Visible label defaults.** Section 3. Max decides whether AI images get a small visible "AI" mark by default. The
   legal pack promises one for realistic images unless the business opts out.
6. **Terms of use.** Add "do not remove AI provenance marks from files Otto delivers" (Code Measure 1.2) to the legal pack.
7. **`docs/legal/ai.md` alignment** (legal pack owner):
   - It promises "C2PA Content Credentials" on every AI file. True today only for images straight from GPT Image
     (OpenAI's manifest, kept intact). Otto's composites carry IPTC XMP (plus MP4 tags and a sidecar), not C2PA.
     Reword, or deliver gap 1 first.
   - The "[ENGINEERING: not built yet]" notes about the IPTC digital source type can go: images, carousel slides, reels,
     motion reels and ad-kit videos are marked as in section 2.
   - The visible "Made with AI" note is **not built**. It is a decision (gap 5).

## Sources (read 30.09.2026)

- [A] Regulation (EU) 2024/1689, Art. 3(60), 3(68), 50, 99: https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng
- [B] Commission Guidelines on Art. 50 transparency obligations (20.07.2026): https://ec.europa.eu/newsroom/dae/redirection/document/131215 ; FAQ (24.07.2026): https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act ; quick facts: https://digital-strategy.ec.europa.eu/en/factpages/quick-facts-transparency-rules-ai-systems
- [C] AI Omnibus, Regulation (EU) 2026/1744 (OJ 24.07.2026): https://eur-lex.europa.eu/eli/reg/2026/1744/oj/eng (the grace-period article number comes from a secondary source)
- [D] Code of Practice on marking and labelling AI-generated content (final, 10.06.2026): https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content ; EU AI icons: https://digital-strategy.ec.europa.eu/en/policies/eu-icons-labelling-ai-generated-content
- [E] IPTC Digital Source Type vocabulary: https://cv.iptc.org/newscodes/digitalsourcetype/
- [F] IPTC Photo Metadata Standard 2025.1 (AI System Used and related properties): https://www.iptc.org/std/photometadata/specification/IPTC-PhotoMetadata-2025.1.html ; Adobe XMP Specification Part 3 (JPEG APP1, PNG iTXt, MP4 uuid): https://github.com/adobe/XMP-Toolkit-SDK/blob/main/docs/XMPSpecificationPart3.pdf
- [H] OpenAI content provenance (C2PA; SynthID from 19.05.2026): https://developers.openai.com/api/docs/guides/content-provenance
- [I] Meta, labelling AI-generated images (06.02.2024, updated) and "AI info" (05.04.2024, updated): https://about.fb.com/news/2024/02/labeling-ai-generated-images-on-facebook-instagram-and-threads/ , https://about.fb.com/news/2024/04/metas-approach-to-labeling-ai-generated-content-and-manipulated-media/
- [J] Meta, generative AI transparency in ads (03.02.2025, updated 01.06.2026): https://about.fb.com/news/2025/02/gen-ai-transparency-metas-ads-products/ ; social-issue ads policy: https://transparency.meta.com/policies/ad-standards/SIEP-advertising/SIEP/
- [K] IPTC, "AI disclosure on social media: a work in progress" (18.03.2026): https://iptc.org/news/ai-disclosure-on-social-media-a-work-in-progress/
- [L] Nederlandse Reclame Code, special codes (Reclamecode Cosmetische Producten art. 2(10)): https://www.reclamecode.nl/nederlandse-reclame-code/bijzondere-reclamecodes/
