#!/usr/bin/env python3
"""Otto explainer bed — the showreel's instruments at under-voice energy (same key, same 120 BPM grid).

  python3 bed.py --seconds 40.0 --out bed.wav

Soft pad on every bar (Am–F–C–G), pluck 8ths from bar 2, a light kick on beats 1 and 3 from bar 2 with a
gentle sidechain, offbeat hats, sub on the root; a soft chord hit on the last full bar and a tail.
"""
import sys

import numpy as np

import compose as c


def bed(seconds):
    bars = int(np.ceil(seconds / c.BAR))
    music, drums, bass = c.Bus("m"), c.Bus("d"), c.Bus("b")
    K = c.kick()
    kicks = []
    for b in range(bars):
        root, tones = c.chord(b)
        music.add(c.pad([c.hz(n, o) for n, o in tones], c.BAR + 0.7, cutoff=1500), c.t_of(b), gain=0.85)
        if b >= 1:
            bass.add(c.sub_note(c.hz(root, 1 if root in ("A", "G") else 2), c.BAR * 0.9), c.t_of(b), gain=0.55)
        if b >= 2:
            seq = [c.hz(n, o + 1) for n, o in tones] + [c.hz(tones[0][0], tones[0][1] + 2)]
            for s, idx in enumerate([0, 1, 2, 3, 2, 1, 2, 3]):
                music.add(c.pluck(seq[idx], length=0.28, bright=2600), c.t_of(b, s / 2), gain=0.42, pan=(-0.3 if s % 2 else 0.3))
            for beat in (0, 2):
                drums.add(K, c.t_of(b, beat), gain=0.55); kicks.append(c.t_of(b, beat))
            for beat in range(4):
                drums.add(c.hat(), c.t_of(b, beat + 0.5), gain=0.55, pan=0.2)
    sc = c.sidechain_env(kicks, depth=0.35, release=0.25)
    music.x *= sc; bass.x *= sc
    music.x = c.pingpong(music.x, fb=0.3, mix=0.2)
    music.x = c.reverb(music.x, 2.6, 0.3)
    mix = drums.x * 0.55 + bass.x * 0.6 + music.x * 2.2
    n = int(seconds * c.SR)
    mix = np.vstack([c.hp(mix[0], 30), c.hp(mix[1], 30)])[:, :n]
    fi = int(0.8 * c.SR); mix[:, :fi] *= np.linspace(0, 1, fi)
    fo = int(2.0 * c.SR); mix[:, -fo:] *= np.linspace(1, 0, fo) ** 1.6
    mix = c.limiter(mix / (np.max(np.abs(mix)) or 1) * 1.1)
    return mix


if __name__ == "__main__":
    import soundfile as sf
    a = sys.argv[1:]
    secs = float(a[a.index("--seconds") + 1]) if "--seconds" in a else 40.0
    out = a[a.index("--out") + 1] if "--out" in a else "bed.wav"
    x = bed(secs)
    sf.write(out, x.T.astype(np.float32), c.SR, subtype="PCM_24")
    print(f"wrote {out} {x.shape[1] / c.SR:.2f}s")
