#!/usr/bin/env python3
"""Otto ad-kit: a month's ad matrix → one kit data JSON per faceless video cell.

  python3 from_matrix.py --matrix brands/<id>/ads-YYYY-MM.json --brand brands/<id>/video/brand.json \
                         --presentation brands/<id>/video/presentation-YYYY-MM.json [--only a3-search,a6-search]

For every cell with "format": "video", it writes the kit JSON to the path in the cell's "video.data". The path is
resolved against the brand folder (the matrix's own folder), which is how otto_styles.video_data_path finds it.

- **Copy.** Taken verbatim from the cell's "data". It is the copy that passed compliance, and nothing is rewritten.
  The engine re-checks every string in the kit JSON (otto_styles.cell_texts → otto_compliance).
- **Presentation.** Comes from the presentation file: grounds, music, timing, asset-role mapping, reel cues, and a
  few whitelisted switches (illo, avatar, hero role). Each cell gets its kit's defaults unless overridden.
- **Price-safe packs.** When an end card carries a price ($…), its products are limited to the brand's
  "price_safe_products" (the packs that price is for). The dropped roles are printed.

The written file is {"id", "style": <kit>, "formats", "music", "scene", <content>, "endcard", "timing"?}, which is
the shape build.mjs reads and otto_styles.validate_cell checks (style must equal the cell's kit).
"""
import copy
import json
import re
import sys
from pathlib import Path

CONTENT_KEY = {"notes": "note", "search": "search", "texts": "thread", "versus": "versus", "big": "big", "reel": "reel"}
# the only dotted paths a presentation file may set inside the content (presentation switches, never copy)
SETTABLE = re.compile(r"^(versus\.(left|right)\.(illo|image)|thread\.avatar|big\.hero|big\.phrases\.\d+\.product|search\.result\.image)$")
PRICE = re.compile(r"\$\s?\d")


def arg(name, default=None):
    a = sys.argv
    return a[a.index(f"--{name}") + 1] if f"--{name}" in a else default


def set_path(obj, dotted, value):
    keys = dotted.split(".")
    cur = obj
    for k in keys[:-1]:
        cur = cur[int(k)] if isinstance(cur, list) else cur.setdefault(k, {})
    last = keys[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def map_roles(content, roles):
    """Asset roles named in the copy data (e.g. hero "sachet") → the brand's roles (e.g. "unit")."""
    def walk(x, key=""):
        if isinstance(x, dict):
            return {k: walk(v, k) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v, key) for v in x]
        if isinstance(x, str) and key in ("hero", "product", "image") and x in roles:
            return roles[x]
        return x
    return walk(content)


def main():
    mpath = Path(arg("matrix")).expanduser()
    brand = json.loads(Path(arg("brand")).expanduser().read_text())
    pres = json.loads(Path(arg("presentation")).expanduser().read_text()) if arg("presentation") else {}
    only = set((arg("only") or "").split(",")) - {""}
    m = json.loads(mpath.read_text())
    base = mpath.parent
    safe = brand.get("price_safe_products")
    defaults = pres.get("defaults", {})
    roles = pres.get("roles", {})
    written = 0
    for a in m.get("angles", []):
        for cell in a.get("ads", []):
            if cell.get("format") != "video" or (only and cell.get("id") not in only):
                continue
            if cell.get("status") == "dropped":
                continue
            vid = cell.get("video") or {}
            kit, ref = vid.get("kit"), vid.get("data")
            if kit not in CONTENT_KEY or not isinstance(ref, str):
                print(f"skip {cell.get('id')}: kit {kit!r} / data {ref!r}")
                continue
            src = cell.get("data") or {}
            cp = {**defaults.get(kit, {}), **pres.get("cells", {}).get(cell["id"], {})}
            sizes = cell.get("size") or "story"
            sizes = [sizes] if isinstance(sizes, str) else sizes
            out = {"id": cell["id"], "style": kit, "formats": ["9x16"] + (["4x5"] if "feed" in sizes else [])}
            out["music"] = cp.get("music") or {"bpm": 120, "mood": "punchy" if kit == "big" else "calm"}
            out["scene"] = {"ground": cp.get("ground", "bg")}
            key = CONTENT_KEY[kit]
            if kit == "reel":
                content = {"vo": copy.deepcopy(src.get("vo", [])), "lines": copy.deepcopy(src.get("lines", [])), "cues": cp.get("cues", [])}
                if not content["cues"]:
                    raise SystemExit(f"{cell['id']}: a reel needs 'cues' in the presentation file (voice clip + line + shot per cue)")
            else:
                content = map_roles(copy.deepcopy(src.get(key) or {}), roles)
            for dotted, value in (cp.get("set") or {}).items():
                if not SETTABLE.match(f"{key}.{dotted}" if not dotted.startswith(key + ".") else dotted):
                    raise SystemExit(f"{cell['id']}: presentation may not set {dotted!r} (copy stays as written)")
                set_path({key: content}, dotted if dotted.startswith(key + ".") else f"{key}.{dotted}", value)
            out[key] = content
            ec = copy.deepcopy(src.get("endcard") or {})
            ec["ground"] = cp.get("endground", "bg")
            if "products" not in ec:
                ec["products"] = cp.get("products", ["pack"])
            ec["products"] = [roles.get(p, p) for p in ec["products"]]
            if safe and PRICE.search(" ".join(str(ec.get(k) or "") for k in ("headline", "sub", "fine"))):
                keep = [p for p in ec["products"] if p in safe]
                dropped = [p for p in ec["products"] if p not in safe]
                if dropped:
                    print(f"  {cell['id']}: end card shows a price → products {keep or safe[:1]} (dropped {dropped}: not the priced pack)")
                ec["products"] = keep or safe[:1]
            if cp.get("legal"):
                ec["legal"] = cp["legal"]
            out["endcard"] = ec
            if cp.get("timing"):
                out["timing"] = cp["timing"]
            dest = base / ref
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
            written += 1
            print(f"wrote {dest.relative_to(base)} ({kit})")
    print(f"{written} kit file(s)")


if __name__ == "__main__":
    main()
