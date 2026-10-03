"""Green-screen compositing for Otto's premium ads: find the chroma-key quad a generated scene left for a screen (or a
price tag), warp a real Otto screen into it with a proper perspective transform, despill the green fringe."""
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

PHONE_SCREEN = (84, 136, 816, 1712)      # the screen inside every phones.py cut-out (900x1848 canvas)
PHONE_RADIUS = 100


def key_mask(im, strict=False):
    """Boolean mask of chroma-key green pixels."""
    a = np.asarray(im.convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = (g > 120) & (g - np.maximum(r, b) > (70 if strict else 45))
    return m


def largest_component(m):
    """Keep the largest 4-connected component (pure numpy flood fill on a downsampled grid, then upsample)."""
    from collections import deque
    H, W = m.shape
    lab = np.zeros((H, W), np.int32)
    best, best_n, cur = 0, 0, 0
    ys, xs = np.nonzero(m)
    for y0, x0 in zip(ys[:: max(1, len(ys) // 4000)], xs[:: max(1, len(xs) // 4000)]):
        if lab[y0, x0]:
            continue
        cur += 1
        q = deque([(y0, x0)])
        lab[y0, x0] = cur
        n = 0
        while q:
            y, x = q.popleft()
            n += 1
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < H and 0 <= xx < W and m[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = cur
                    q.append((yy, xx))
        if n > best_n:
            best, best_n = cur, n
    return lab == best


def boundary(m):
    e = m & ~(np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1))
    ys, xs = np.nonzero(e)
    return np.stack([xs, ys], 1).astype(float)


def fit_line(pts):
    c = pts.mean(0)
    u, s, vt = np.linalg.svd(pts - c)
    d = vt[0]
    return c, d


def intersect(l1, l2):
    (c1, d1), (c2, d2) = l1, l2
    A = np.array([d1, -d2]).T
    t = np.linalg.solve(A, c2 - c1)
    return c1 + t[0] * d1


def quad(m):
    """The 4 corners of a (rounded, perspective) rectangle mask, in cyclic order: the convex hull's straight runs (consecutive
    hull edges within 4 degrees merged) — the 4 longest runs are the 4 sides; corners = intersections of adjacent sides."""
    h = hull(boundary(m))
    n = len(h)
    seg = [(h[k], h[(k + 1) % n]) for k in range(n)]
    ang = [np.degrees(np.arctan2(*(b - a)[::-1])) for a, b in seg]
    runs, cur = [], [0]
    for k in range(1, n):
        d = (ang[k] - ang[cur[-1]] + 180) % 360 - 180
        if abs(d) < 4:
            cur.append(k)
        else:
            runs.append(cur)
            cur = [k]
    if runs and abs((ang[runs[0][0]] - ang[cur[-1]] + 180) % 360 - 180) < 4:
        runs[0] = cur + runs[0]
    else:
        runs.append(cur)
    def length(r):
        return np.linalg.norm(seg[r[-1]][1] - seg[r[0]][0])
    sides = sorted(sorted(runs, key=length, reverse=True)[:4], key=lambda r: r[0] if r[0] <= r[-1] else r[0] - n)
    lines = []
    for r in sides:
        P = np.array([seg[k][0] for k in r] + [seg[r[-1]][1]])
        lines.append(fit_line(P) if len(P) > 2 else (P[0], (P[1] - P[0]) / np.linalg.norm(P[1] - P[0])))
    return np.array([intersect(lines[k - 1], lines[k]) for k in range(4)])


def hull(pts):
    P = sorted(set(map(tuple, pts.tolist())))
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in P:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(P):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return np.array(lo[:-1] + up[:-1], float)


def hull4(pts):
    """Convex hull reduced to 4 vertices (Visvalingam: drop the vertex spanning the smallest triangle), in cyclic order."""
    h = list(hull(pts))
    while len(h) > 4:
        n = len(h)
        areas = [abs(np.cross(h[i] - h[i - 1], h[(i + 1) % n] - h[i - 1])) for i in range(n)]
        h.pop(int(np.argmin(areas)))
    return [np.array(x) for x in h]


def orient(c, top="far"):
    """Order 4 corners as the SCREEN's tl, tr, br, bl: the long edges are the phone's sides; the top short edge is the one
    higher in the image (farther away); left/right follow from the phone's own up axis."""
    c = [np.array(x, float) for x in c]
    e = [(i, (i + 1) % 4, np.linalg.norm(c[(i + 1) % 4] - c[i])) for i in range(4)]
    short = sorted(e, key=lambda x: x[2])[:2]
    s1, s2 = short
    m1, m2 = (c[s1[0]] + c[s1[1]]) / 2, (c[s2[0]] + c[s2[1]]) / 2
    topE, botE = (s1, s2) if m1[1] < m2[1] else (s2, s1)
    tm, bm = (c[topE[0]] + c[topE[1]]) / 2, (c[botE[0]] + c[botE[1]]) / 2
    u = tm - bm
    left = np.array([u[1], -u[0]])
    t = sorted([c[topE[0]], c[topE[1]]], key=lambda p: -(p - tm) @ left)
    b = sorted([c[botE[0]], c[botE[1]]], key=lambda p: -(p - bm) @ left)
    return np.array([t[0], t[1], b[1], b[0]])


def homography(src, dst):
    """3x3 H with dst ~ H @ src (4 point pairs)."""
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.array(A, float))
    H = vt[-1].reshape(3, 3)
    return H / H[2, 2]


def warp_into(dst_size, src_img, corners):
    """Warp src_img (its full rectangle) onto the quad `corners` (tl,tr,br,bl) of a canvas of dst_size. RGBA out."""
    w, h = src_img.size
    srcq = [(0, 0), (w, 0), (w, h), (0, h)]
    Hinv = homography(corners, srcq)              # maps output pixel → source pixel (what PIL wants)
    coeffs = (Hinv / Hinv[2, 2]).flatten()[:8]
    return src_img.convert("RGBA").transform(dst_size, Image.PERSPECTIVE, tuple(coeffs), Image.BICUBIC)


def phone_screen(cutout_path, scale=1.0):
    """The screen of a phones.py cut-out, rounded corners transparent."""
    im = Image.open(cutout_path).convert("RGBA").crop(PHONE_SCREEN)
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=PHONE_RADIUS, fill=255)
    im.putalpha(ImageChops.multiply(im.getchannel("A"), mask))
    if scale != 1.0:
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    return im


def despill(im, m_soft, radius=10):
    """Pull the green cast out of pixels near the key (edges, reflections) — G clamped to max(R,B) there."""
    a = np.asarray(im.convert("RGB")).astype(float)
    near = np.asarray(Image.fromarray((m_soft * 255).astype("uint8")).filter(ImageFilter.MaxFilter(radius * 2 + 1))) > 0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lim = np.maximum(r, b) * 1.02
    g2 = np.where(near & (g > lim), lim, g)
    a[..., 1] = g2
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))


def composite_screen(scene, screen_img, inset=0.0, grade=0.96, glare=0.10, corners=None, grow=2):
    """Find the green screen in `scene`, warp `screen_img` onto it and composite. Returns (image, corners, mask)."""
    scene = scene.convert("RGB")
    m = largest_component(key_mask(scene))
    if corners is None:
        corners = orient(quad(m))
    c = corners.copy()
    if inset:
        ctr = c.mean(0)
        c = ctr + (c - ctr) * (1 - inset)
    layer = warp_into(scene.size, screen_img, c)
    # the key region (grown by `grow` px so no green rim survives) limits the screen to the generated phone's own shape
    km = Image.fromarray((m * 255).astype("uint8")).filter(ImageFilter.MaxFilter(grow * 2 + 1)).filter(ImageFilter.GaussianBlur(0.8))
    alpha = ImageChops.multiply(layer.getchannel("A"), km)
    # where the key extends beyond the warped screen (rounded corners of the screen image), fill with the screen's bg
    rgb = layer.convert("RGB")
    if grade != 1.0:
        rgb = Image.eval(rgb, lambda v: int(v * grade))
    base = despill(scene, m.astype(float), radius=6)
    fill = Image.new("RGB", scene.size, tuple(int(v * grade) for v in (245, 247, 251)))
    base = Image.composite(fill, base, km)          # whole key area → screen background colour first
    out = Image.composite(rgb, base, alpha)
    if glare:
        g = Image.new("L", scene.size, 0)
        d = ImageDraw.Draw(g)
        tl, tr, br, bl = c
        d.polygon([tuple(tl), tuple(tl + (tr - tl) * 0.55), tuple(bl + (br - bl) * 0.12), tuple(bl)], fill=int(255 * glare))
        g = ImageChops.multiply(g.filter(ImageFilter.GaussianBlur(40)), km)
        out = Image.composite(Image.new("RGB", scene.size, (255, 255, 255)), out, g)
    return out, corners, m
