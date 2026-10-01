#!/usr/bin/env python3
"""Otto provenance — machine-readable "this is AI-generated" marks on the media Otto generates (EU AI Act Art. 50(2)).

  otto_provenance.py mark <file> [--kind image|voice|music[,…]] [--tool "Leonardo.ai gpt-image-2"] [--composite]
                                 [--no-sidecar] [--json]
  otto_provenance.py inspect <file>… [--json]          # what a file says about itself (exit 1 when none is AI-marked)

What gets written (pure Python, nothing to install; ffmpeg only for the MP4 tags):
  JPEG  an APP1 XMP segment ("http://ns.adobe.com/xap/1.0/\\0"), after APP0/Exif; an existing XMP packet is kept and
        Otto's rdf:Description is added to it (a previous Otto block and any older DigitalSourceType are replaced).
  PNG   an iTXt chunk "XML:com.adobe.xmp" (uncompressed) before the first IDAT; an older XMP chunk is replaced.
  MP4   ffmpeg `-c copy` with the standard `comment` + `description` tags (what ffprobe, players and most
        uploaders read), then an XMP packet in a top-level `uuid` box (Adobe XMP spec part 3, UUID
        BE7ACFCB-97A9-42E8-9C71-999491E3AFAC) appended at the end of the file — appending moves no sample offsets —
        plus a sidecar <file>.provenance.json with the sha256 of the final bytes.
The XMP carries the IPTC Digital Source Type (Iptc4xmpExt:DigitalSourceType, IPTC NewsCodes vocabulary):
  trainedAlgorithmicMedia               the whole file came out of a generative model (genvisuals images)
  compositeSynthetic                    a composite with at least one generated element (a carousel slide = generated
                                        image + text; a reel = generated scenes and/or a synthetic voice + captions).
                                        IPTC reserves compositeWithTrainedAlgorithmicMedia for GenAI edits of existing
                                        media (inpainting / outpainting); inspect() reads both as AI.
plus Iptc4xmpExt:AISystemUsed (the tool), xmp:CreatorTool "Otto" and otto:* fields (kinds, tool, time).
Meta reads IPTC / C2PA on uploads for its "AI info" label. See docs/AI-TRANSPARENCY.md for the legal side and for
why template cards made from the client's real photos + text (otto_render) are NOT marked.

A file that already carries a C2PA manifest (JPEG APP11 JUMBF, PNG caBX, MP4 C2PA uuid) is left byte-for-byte alone:
inserting XMP would break the manifest's hash binding. When the manifest itself declares trainedAlgorithmicMedia the
file counts as marked ("c2pa-upstream"); otherwise mark() raises ProvenanceError rather than invalidate it.

In the data: post["media_ai"][<asset ref>] = record(info) → {"generated": true, "kind": "image|voice|music",
"kinds": [...], "tool": "...", "source_type": "...", "marked": "xmp" | "xmp+mp4-tags+sidecar" | false, "at": ...}.
Marking never breaks a render: callers catch ProvenanceError and store marked=false with the error, so the console
can show AI media that went out unmarked.
"""
import hashlib, json, os, re, shutil, struct, subprocess, sys, tempfile, zlib
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

DST = "http://cv.iptc.org/newscodes/digitalsourcetype/"
TRAINED = DST + "trainedAlgorithmicMedia"
# IPTC: compositeSynthetic = "Mix or composite of several elements, at least one of which is Generative AI" — what Otto's
# composites are (a generated image + text; a reel of generated scenes / synthetic voice + captions).
# compositeWithTrainedAlgorithmicMedia = "Augmentation, correction or enhancement using a Generative AI model, such as with
# inpainting or outpainting" — GenAI edits of existing media; Otto does not make those, but reads it as AI (inspect).
COMPOSITE = DST + "compositeSynthetic"
AI_SOURCE_TYPES = {TRAINED, COMPOSITE, DST + "compositeWithTrainedAlgorithmicMedia", DST + "algorithmicMedia"}
KINDS = ("image", "voice", "music", "video")
NS_IPTC_EXT = "http://iptc.org/std/Iptc4xmpExt/2008-02-29/"
NS_OTTO = "https://dash.monyflow.work/otto/ns/provenance/1.0/"
JPEG_XMP = b"http://ns.adobe.com/xap/1.0/\x00"
PNG_XMP = b"XML:com.adobe.xmp"
MP4_XMP_UUID = bytes.fromhex("BE7ACFCB97A942E89C71999491E3AFAC")
MP4_C2PA_UUID = bytes.fromhex("D8FEC3D61B0E483C92975828877EC481")
MAX_JPEG_XMP = 65535 - 2 - len(JPEG_XMP)
LAW = "EU AI Act Art. 50(2)"


class ProvenanceError(Exception):
    pass


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sniff(path_or_bytes):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        head = bytes(path_or_bytes[:16])
    else:
        with open(path_or_bytes, "rb") as f:
            head = f.read(16)
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[4:8] == b"ftyp":
        return "mp4"
    return None


def _kinds(kinds):
    if isinstance(kinds, str):
        kinds = [k for k in re.split(r"[,+\s]+", kinds) if k]
    out = [k for k in dict.fromkeys(str(k).strip().lower() for k in kinds or ()) if k]
    bad = [k for k in out if k not in KINDS]
    if bad or not out:
        raise ProvenanceError(f"kind must be one or more of {', '.join(KINDS)} (got {kinds!r})")
    return out


def primary_kind(kinds):
    return next((k for k in ("voice", "image", "music", "video") if k in kinds), kinds[0])


def source_uri(composite):
    return COMPOSITE if composite else TRAINED


def describe(kinds, tool, composite):
    what = {"image": "image", "voice": "voice", "music": "music", "video": "video"}
    parts = " and ".join(what[k] for k in kinds)
    head = f"Contains AI-generated {parts}" if composite else f"AI-generated {parts}"
    return f"{head}{f' ({tool})' if tool else ''}. Made with Otto."


# ---------------------------------------------------------------------------------------------------------------
# XMP packet
# ---------------------------------------------------------------------------------------------------------------

def _otto_description(source, kinds, tool, when, with_dc=True):
    note = describe(kinds, tool, source == COMPOSITE)
    dc = (f'\n   <dc:description><rdf:Alt><rdf:li xml:lang="x-default">{escape(note)}</rdf:li></rdf:Alt></dc:description>'
          if with_dc else "")
    return (f'  <rdf:Description rdf:about=""\n'
            f'    xmlns:Iptc4xmpExt="{NS_IPTC_EXT}"\n'
            f'    xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
            f'    xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
            f'    xmlns:otto="{NS_OTTO}">\n'
            f'   <Iptc4xmpExt:DigitalSourceType>{escape(source)}</Iptc4xmpExt:DigitalSourceType>\n'
            + (f'   <Iptc4xmpExt:AISystemUsed>{escape(tool)}</Iptc4xmpExt:AISystemUsed>\n' if tool else "")
            + f'   <xmp:CreatorTool>Otto</xmp:CreatorTool>\n'
            f'   <xmp:MetadataDate>{escape(when)}</xmp:MetadataDate>{dc}\n'
            f'   <otto:Generated>True</otto:Generated>\n'
            f'   <otto:Kinds>{escape(",".join(kinds))}</otto:Kinds>\n'
            + (f'   <otto:Tool>{escape(tool)}</otto:Tool>\n' if tool else "")
            + f'   <otto:Law>{escape(LAW)}</otto:Law>\n'
            f'  </rdf:Description>\n')


def xmp_packet(source, kinds, tool="", when=None, existing=None):
    """A complete XMP packet. With `existing` (an older packet from the file) Otto's rdf:Description is merged into it:
    a previous Otto block and any older DigitalSourceType are dropped, everything else is kept."""
    when = when or now_iso()
    if existing and "</rdf:RDF>" in existing:
        body = re.sub(r"\s*<rdf:Description\b[^>]*xmlns:otto=[\"'][^\"']*[\"'][^>]*>.*?</rdf:Description>", "", existing, flags=re.S)
        body = re.sub(r"\s*<Iptc4xmpExt:DigitalSourceType\b[^>]*>.*?</Iptc4xmpExt:DigitalSourceType>", "", body, flags=re.S)
        body = re.sub(r"\s*<Iptc4xmpExt:DigitalSourceType\b[^>]*/>", "", body)
        body = re.sub(r"\s+Iptc4xmpExt:DigitalSourceType=([\"'])[^\"']*\1", "", body)
        block = _otto_description(source, kinds, tool, when, with_dc="dc:description" not in body)
        i = body.rfind("</rdf:RDF>")
        return body[:i] + block + " " + body[i:]
    return ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Otto provenance 1.0">\n'
            ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
            + _otto_description(source, kinds, tool, when) +
            ' </rdf:RDF>\n'
            '</x:xmpmeta>\n'
            '<?xpacket end="w"?>')


def parse_xmp(text):
    """→ {"digital_source_type", "ai_system", "kinds", "tool", "otto"} from an XMP packet (element or attribute form)."""
    if not text:
        return {}
    def one(name):
        m = re.search(r"<" + name + r"\b[^>]*>\s*([^<]*?)\s*</" + name + ">", text) or \
            re.search(r"\b" + name + r"=([\"'])(.*?)\1", text)
        if not m:
            return None
        return (m.group(1) if m.lastindex == 1 else m.group(2)).strip() or None
    dst = one("Iptc4xmpExt:DigitalSourceType")
    kinds = one("otto:Kinds")
    return {"digital_source_type": dst, "ai_system": one("Iptc4xmpExt:AISystemUsed"),
            "kinds": [k for k in (kinds or "").split(",") if k], "tool": one("otto:Tool"),
            "otto": "otto:Generated" in text}


# ---------------------------------------------------------------------------------------------------------------
# JPEG
# ---------------------------------------------------------------------------------------------------------------

def _jpeg_segments(data):
    """(segments before the scan [(start, end, marker, payload_start)], offset of the SOS marker)."""
    if data[:2] != b"\xff\xd8":
        raise ProvenanceError("not a JPEG (no SOI)")
    i, segs, n = 2, [], len(data)
    while i < n:
        if data[i] != 0xFF:
            raise ProvenanceError(f"broken JPEG marker at byte {i}")
        while i + 1 < n and data[i + 1] == 0xFF:           # fill bytes
            i += 1
        if i + 1 >= n:
            break
        m = data[i + 1]
        if m in (0xDA, 0xD9):                              # start of scan / end of image: headers are over
            return segs, i
        if 0xD0 <= m <= 0xD7 or m == 0x01:
            i += 2
            continue
        if i + 4 > n:
            raise ProvenanceError("truncated JPEG segment")
        ln = struct.unpack(">H", data[i + 2:i + 4])[0]
        if ln < 2 or i + 2 + ln > n:
            raise ProvenanceError("bad JPEG segment length")
        segs.append((i, i + 2 + ln, m, i + 4))
        i += 2 + ln
    raise ProvenanceError("JPEG has no image data (no SOS)")


def _jpeg_xmp(data, segs):
    for s, e, m, p in segs:
        if m == 0xE1 and data[p:p + len(JPEG_XMP)] == JPEG_XMP:
            return (s, e), data[p + len(JPEG_XMP):e].decode("utf-8", "replace")
    return None, None


def _jpeg_write(data, packet_fn):
    segs, sos = _jpeg_segments(data)
    old, old_text = _jpeg_xmp(data, segs)
    packet = packet_fn(old_text).encode("utf-8")
    if len(packet) > MAX_JPEG_XMP:                         # an oversized upstream packet: keep only Otto's
        packet = packet_fn(None).encode("utf-8")
    seg = b"\xff\xe1" + struct.pack(">H", 2 + len(JPEG_XMP) + len(packet)) + JPEG_XMP + packet
    if old:
        return data[:old[0]] + seg + data[old[1]:]
    at = 2                                                 # after SOI, APP0 (JFIF) and APP1 (Exif) — the usual order
    for s, e, m, p in segs:
        if m == 0xE0 or (m == 0xE1 and data[p:p + 6] == b"Exif\x00\x00"):
            at = e
        else:
            break
    return data[:at] + seg + data[at:]


# ---------------------------------------------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------------------------------------------

def _png_chunks(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ProvenanceError("not a PNG")
    i, out, n = 8, [], len(data)
    while i < n:
        if i + 8 > n:
            raise ProvenanceError("truncated PNG chunk")
        ln = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        end = i + 12 + ln
        if end > n:
            raise ProvenanceError("bad PNG chunk length")
        out.append((typ, i, end, data[i + 8:i + 8 + ln]))
        i = end
        if typ == b"IEND":
            break
    if not out or out[0][0] != b"IHDR":
        raise ProvenanceError("PNG without IHDR")
    return out


def _png_itxt_xmp(body):
    """iTXt payload → XMP text when it is the XMP chunk, else None."""
    if not body.startswith(PNG_XMP + b"\x00"):
        return None
    rest = body[len(PNG_XMP) + 1:]
    comp, method, rest = rest[0], rest[1], rest[2:]
    lang_end = rest.index(b"\x00")
    rest = rest[lang_end + 1:]
    tk_end = rest.index(b"\x00")
    text = rest[tk_end + 1:]
    if comp:
        text = zlib.decompress(text)
    return text.decode("utf-8", "replace")


def _png_chunk(typ, body):
    return struct.pack(">I", len(body)) + typ + body + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF)


def _png_write(data, packet_fn):
    chunks = _png_chunks(data)
    old_text = next((t for t in (_png_itxt_xmp(b) for typ, s, e, b in chunks if typ == b"iTXt") if t), None)
    packet = packet_fn(old_text).encode("utf-8")
    chunk = _png_chunk(b"iTXt", PNG_XMP + b"\x00\x00\x00" + b"\x00" + b"\x00" + packet)
    out, placed = [data[:8]], False
    for typ, s, e, body in chunks:
        if typ == b"iTXt" and _png_itxt_xmp(body) is not None:
            continue
        if typ == b"IDAT" and not placed:
            out.append(chunk); placed = True
        out.append(data[s:e])
    if not placed:
        raise ProvenanceError("PNG without IDAT")
    return b"".join(out) + data[chunks[-1][2]:]


# ---------------------------------------------------------------------------------------------------------------
# MP4
# ---------------------------------------------------------------------------------------------------------------

def _mp4_boxes(data):
    """Top-level boxes [(type, start, end, header_len)]; must tile the whole file."""
    i, out, n = 0, [], len(data)
    while i < n:
        if i + 8 > n:
            raise ProvenanceError("truncated MP4 box header")
        size, typ = struct.unpack(">I4s", data[i:i + 8])
        hdr = 8
        if size == 1:
            if i + 16 > n:
                raise ProvenanceError("truncated MP4 largesize")
            size = struct.unpack(">Q", data[i + 8:i + 16])[0]; hdr = 16
        elif size == 0:
            size = n - i
        if size < hdr or i + size > n or not re.fullmatch(rb"[\x20-\x7e]{4}", typ):
            raise ProvenanceError(f"not a well-formed MP4 (box {typ!r} at {i})")
        out.append((typ, i, i + size, hdr))
        i += size
    if not out or out[0][0] != b"ftyp":
        raise ProvenanceError("MP4 does not start with ftyp")
    return out


def _mp4_uuid(data, box, uuid):
    typ, s, e, hdr = box
    return typ == b"uuid" and data[s + hdr:s + hdr + 16] == uuid


def _mp4_xmp(data, boxes):
    for b in boxes:
        if _mp4_uuid(data, b, MP4_XMP_UUID):
            return b, data[b[1] + b[3] + 16:b[2]].decode("utf-8", "replace")
    return None, None


def _mp4_write(data, packet_fn):
    boxes = _mp4_boxes(data)
    old, old_text = _mp4_xmp(data, boxes)
    body = bytearray(data)
    last = boxes[-1]
    if struct.unpack(">I", data[last[1]:last[1] + 4])[0] == 0:          # "to end of file": make the size explicit
        if last[2] - last[1] >= 2 ** 32:
            raise ProvenanceError("last MP4 box runs to EOF and is too large to close")
        body[last[1]:last[1] + 4] = struct.pack(">I", last[2] - last[1])
    if old is not None:
        if old == boxes[-1]:
            del body[old[1]:]                                         # the old XMP box is last: drop it
        else:
            body[old[1] + 4:old[1] + 8] = b"free"                     # elsewhere: neutralise in place (no offset moves)
    packet = packet_fn(old_text).encode("utf-8")
    box = struct.pack(">I", 8 + 16 + len(packet)) + b"uuid" + MP4_XMP_UUID + packet
    return bytes(body) + box


def _ffmpeg_tags(path, comment, description):
    """Rewrite the MP4 with standard comment/description tags (-c copy). True when written."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return False
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix="." + path.stem + ".", suffix=".mp4", dir=str(path.parent))
    os.close(fd)
    try:
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(path), "-map", "0", "-c", "copy", "-map_metadata", "0",
                            "-metadata", f"comment={comment}", "-metadata", f"description={description}",
                            "-movflags", "+faststart", tmp], capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not os.path.getsize(tmp):
            raise ProvenanceError(f"ffmpeg could not tag the MP4: {(r.stderr or '').strip()[-200:]}")
        os.replace(tmp, path)
        return True
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _ffprobe_tags(path):
    fp = shutil.which("ffprobe")
    if not fp:
        return None
    r = subprocess.run([fp, "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return None
    try:
        return (json.loads(r.stdout or "{}").get("format") or {}).get("tags") or {}
    except ValueError:
        return None


def sidecar_path(path):
    return Path(str(path) + ".provenance.json")


# ---------------------------------------------------------------------------------------------------------------
# mark / inspect
# ---------------------------------------------------------------------------------------------------------------

def _atomic_write(path, data):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


C2PA_DST = re.compile(rb"http://cv\.iptc\.org/newscodes/digitalsourcetype/([A-Za-z]+)")


def c2pa_state(path, data=None):
    """(has a C2PA manifest, the AI digital source type URI it declares or None). The manifest is not validated
    (that needs a signature check); its declared source type is read from the JUMBF bytes."""
    data = Path(path).read_bytes() if data is None else data
    kind = sniff(data)
    manifest = b""
    try:
        if kind == "jpeg":
            segs = _jpeg_segments(data)[0]
            manifest = b"".join(data[p:e] for s, e, m, p in segs if m == 0xEB and b"c2pa" in data[p:e])
        elif kind == "png":
            manifest = b"".join(b for typ, s, e, b in _png_chunks(data) if typ == b"caBX")
        elif kind == "mp4":
            manifest = b"".join(data[b[1]:b[2]] for b in _mp4_boxes(data) if _mp4_uuid(data, b, MP4_C2PA_UUID))
    except ProvenanceError:
        return False, None
    if not manifest:
        return False, None
    dsts = [DST + m.decode() for m in C2PA_DST.findall(manifest)]
    return True, next((d for d in dsts if d in AI_SOURCE_TYPES), None)


def mark(path, kinds=("image",), tool="", composite=False, sidecar=None, when=None):
    """Write the AI mark into the file in place. → the record for the data (see record()). Raises ProvenanceError."""
    path = Path(path)
    if not path.is_file():
        raise ProvenanceError(f"{path} does not exist")
    kinds = _kinds(kinds)
    tool = re.sub(r"[\x00-\x1f]+", " ", str(tool or "")).strip()[:160]
    source, when = source_uri(composite), when or now_iso()
    fmt = sniff(path)
    if fmt is None:
        raise ProvenanceError(f"{path.name}: only JPEG, PNG and MP4 can be marked")
    has_c2pa, c2pa_ai = c2pa_state(path)
    if has_c2pa:
        if not c2pa_ai:
            raise ProvenanceError(f"{path.name} carries a C2PA manifest without an AI declaration — left untouched")
        # the model provider's signed manifest already declares it (e.g. OpenAI gpt-image via Leonardo); XMP would break
        # its hash binding, so the file stays as it is and the record names the source type the manifest declares
        return _info(kinds, tool, c2pa_ai, "c2pa-upstream", when)
    fn = lambda old: xmp_packet(source, kinds, tool, when, existing=old)
    how = "xmp"
    if fmt in ("jpeg", "png"):
        data = path.read_bytes()
        _atomic_write(path, (_jpeg_write if fmt == "jpeg" else _png_write)(data, fn))
    else:
        _mp4_boxes(path.read_bytes())                                   # refuse a broken file before ffmpeg touches it
        note = describe(kinds, tool, composite)
        if _ffmpeg_tags(path, f"{note} IPTC DigitalSourceType: {source}", note):
            how += "+mp4-tags"
        _atomic_write(path, _mp4_write(path.read_bytes(), fn))
        if sidecar is not False:
            sc = sidecar_path(path)
            info = dict(_info(kinds, tool, source, how + "+sidecar", when), file=path.name,
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), law=LAW,
                        standard="IPTC Digital Source Type (http://cv.iptc.org/newscodes/digitalsourcetype/)",
                        note=note, made_with="Otto")
            sc.write_text(json.dumps(info, indent=1, ensure_ascii=False) + "\n")
            how += "+sidecar"
    return _info(kinds, tool, source, how, when)


def _info(kinds, tool, source, how, when):
    return {"generated": True, "kind": primary_kind(kinds), "kinds": list(kinds), "tool": tool,
            "source_type": source.rsplit("/", 1)[-1], "marked": how, "at": when}


def record(info=None, error=None, kinds=("image",), tool="", composite=False):
    """The post["media_ai"][ref] entry: the mark() result, or — when marking failed — the same shape with marked=false."""
    if info:
        return dict(info)
    k = _kinds(kinds)
    return {"generated": True, "kind": primary_kind(k), "kinds": k, "tool": tool, "source_type":
            source_uri(composite).rsplit("/", 1)[-1], "marked": False, "error": str(error or "not marked")[:200], "at": now_iso()}


def mark_safely(path, kinds=("image",), tool="", composite=False, sidecar=None, log=print):
    """mark() for the pipelines: never raises; a failure comes back as a marked=false record (and a log line)."""
    try:
        return mark(path, kinds, tool, composite, sidecar)
    except Exception as e:                                           # noqa: BLE001 — a render must never die here
        if log:
            log(f"  provenance: could not mark {Path(path).name}: {type(e).__name__}: {e}")
        try:
            return record(error=f"{type(e).__name__}: {e}", kinds=kinds, tool=tool, composite=composite)
        except ProvenanceError:
            return record(error=str(e), kinds=("image",), tool=tool, composite=composite)


def inspect(path):
    """What the file says about itself. generated=True when an XMP DigitalSourceType, an MP4 tag or a C2PA manifest
    declares AI generation."""
    path = Path(path)
    out = {"file": str(path), "format": None, "xmp": False, "digital_source_type": None, "ai_system": None,
           "kinds": [], "tool": None, "c2pa": False, "generated": False}
    if not path.is_file():
        out["error"] = "missing"
        return out
    data = path.read_bytes()
    fmt = out["format"] = sniff(data)
    text = None
    try:
        if fmt == "jpeg":
            segs = _jpeg_segments(data)[0]
            text = _jpeg_xmp(data, segs)[1]
        elif fmt == "png":
            text = next((t for t in (_png_itxt_xmp(b) for typ, s, e, b in _png_chunks(data) if typ == b"iTXt") if t), None)
        elif fmt == "mp4":
            text = _mp4_xmp(data, _mp4_boxes(data))[1]
    except (ProvenanceError, ValueError, zlib.error) as e:
        out["error"] = str(e)
    if text:
        out["xmp"] = True
        out.update({k: v for k, v in parse_xmp(text).items() if k != "otto"})
    out["c2pa"], c2pa_ai = c2pa_state(path, data)
    if c2pa_ai:
        out["c2pa_source_type"] = c2pa_ai
        out["digital_source_type"] = out["digital_source_type"] or c2pa_ai
    if fmt == "mp4":
        tags = _ffprobe_tags(path)
        if tags is not None:
            out["mp4_tags"] = {k: v for k, v in tags.items() if k.lower() in ("comment", "description")}
        sc = sidecar_path(path)
        if sc.exists():
            try:
                side = json.loads(sc.read_text())
                out["sidecar"] = {"path": str(sc), "sha256_ok": side.get("sha256") == hashlib.sha256(data).hexdigest(),
                                  "source_type": side.get("source_type"), "kinds": side.get("kinds")}
            except ValueError:
                out["sidecar"] = {"path": str(sc), "error": "unreadable"}
    dst = out["digital_source_type"] or ""
    tag_ai = any(t in str(v) for v in (out.get("mp4_tags") or {}).values() for t in AI_SOURCE_TYPES)
    out["generated"] = bool(dst in AI_SOURCE_TYPES or c2pa_ai or tag_ai)
    return out


def is_generated(path):
    try:
        return inspect(path)["generated"]
    except Exception:                                                # noqa: BLE001
        return False


def propagate(src, dst, tool=None, composite=True, log=print):
    """dst was derived from src: when src is AI-marked, mark dst too. composite=True (an overlay / card built on the
    generated image: it now contains a generated element); composite=None keeps src's source type (a plain format
    conversion or resize). → the record, or None when src carries no AI mark."""
    try:
        info = inspect(src)
    except Exception:                                                # noqa: BLE001
        return None
    if not info.get("generated"):
        return None
    kinds = [k for k in info.get("kinds") or [] if k in KINDS] or ["image"]
    if composite is None:
        composite = (info.get("digital_source_type") or "") != TRAINED
    return mark_safely(dst, kinds, tool or info.get("tool") or info.get("ai_system") or "", composite=composite, log=log)


def main(argv):
    a = list(argv)
    as_json = "--json" in a
    a = [x for x in a if x != "--json"]
    if len(a) >= 2 and a[0] == "mark":
        opt = lambda k, d=None: a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else d
        try:
            info = mark(a[1], opt("--kind", "image"), opt("--tool", ""), composite="--composite" in a,
                        sidecar=False if "--no-sidecar" in a else None)
        except ProvenanceError as e:
            print(f"provenance: {e}", file=sys.stderr)
            return 2
        print(json.dumps(info, ensure_ascii=False) if as_json else
              f"marked {a[1]}: {info['source_type']} · {','.join(info['kinds'])} · {info['tool'] or '-'} · {info['marked']}")
        return 0
    if len(a) >= 2 and a[0] == "inspect":
        rows = [inspect(f) for f in a[1:]]
        if as_json:
            print(json.dumps(rows if len(rows) > 1 else rows[0], ensure_ascii=False, indent=1))
        else:
            for r in rows:
                flag = "AI" if r["generated"] else "--"
                print(f"{flag} {r['file']}: {r['format'] or '?'} · {(r['digital_source_type'] or 'no DigitalSourceType').rsplit('/', 1)[-1]}"
                      f"{' · ' + ','.join(r['kinds']) if r['kinds'] else ''}{' · ' + r['tool'] if r.get('tool') else ''}"
                      f"{' · C2PA' if r['c2pa'] else ''}{' · ' + r['error'] if r.get('error') else ''}")
        return 0 if any(r["generated"] for r in rows) else 1
    print(__doc__)
    return 0 if not a else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
