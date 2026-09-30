#!/usr/bin/env python3
"""Otto ad-kit soundtrack: a light music bed on the ad's beat grid + tasteful UI sounds on the scheduled events,
mixed to -14 LUFS integrated (true peak <= -1 dBTP). Everything is synthesized in code (numpy/scipy), no samples,
no copyrighted music. Deterministic (seeded).

  python3 score.py --sound <project>/sound.json --out <project>/assets/audio/soundtrack.wav [--stems]

sound.json (written by build.mjs):
  { "bpm": 120, "duration": 12.7, "endAt": 9.5, "mood": "calm" | "punchy", "key": "F",
    "events": [ {"t": 0.3, "type": "key"}, {"t": 3.5, "type": "strike"}, ... ] }

Moods
  calm   - electric-piano chords (I-vi-IV-V), 8th-note pluck arpeggio, soft kick on 1 & 3, snaps on 2 & 4,
           16th shaker, sub on the root; the end card lands on the tonic (a small "resolve").
  punchy - riser into the first hit, four-on-the-floor, claps, offbeat bass, a chord stab on every "hit",
           an impact on "impact"; the end card lands on the tonic.

UI sound types: key, space, return, strike, mark, drop, select, enter, card, star, pop, send, dots (silent),
swish, tick, land, cross, check, sheet, riser, hit, impact. Unknown types are ignored.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "otto-showreel-score"))
import compose as c  # noqa: E402  (shared instruments: kick, hat, clap, pluck, sub_note, pad, supersaw, riser, fx)

SR = c.SR
rng = np.random.default_rng(11)

# ── harmony ────────────────────────────────────────────────────────────────────────────────────────
# I – vi – IV – V in the chosen key, voiced for a warm mid register. Notes as (name, octave).
KEYS = {
    "F": {
        "tonic": [("F", 3), ("A", 3), ("C", 4), ("E", 4), ("G", 4)],
        "prog": [
            ("F", [("F", 3), ("A", 3), ("C", 4), ("E", 4)]),
            ("D", [("D", 3), ("F", 3), ("A", 3), ("C", 4)]),
            ("A#", [("A#", 2), ("D", 3), ("F", 3), ("A", 3)]),
            ("C", [("C", 3), ("E", 3), ("G", 3), ("D", 4)]),
        ],
    },
    "C": {
        "tonic": [("C", 3), ("E", 3), ("G", 3), ("B", 3), ("D", 4)],
        "prog": [
            ("C", [("C", 3), ("E", 3), ("G", 3), ("B", 3)]),
            ("A", [("A", 2), ("C", 3), ("E", 3), ("G", 3)]),
            ("F", [("F", 2), ("A", 2), ("C", 3), ("E", 3)]),
            ("G", [("G", 2), ("B", 2), ("D", 3), ("A", 3)]),
        ],
    },
}


def hz(n, o):
    return c.hz(n, o)


# ── instruments (on top of compose.py) ─────────────────────────────────────────────────────────────
def ep(f, length, vel=1.0):
    """FM electric piano: a sine body with a decaying modulation index and a short tine."""
    n = int(length * SR)
    t = np.arange(n) / SR
    idx = 1.7 * np.exp(-t * 7.0) + 0.3
    body = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * t))
    tine = np.sin(2 * np.pi * f * 14.0 * t) * np.exp(-t * 55) * 0.1
    env = np.exp(-t * 1.5) * (1 - np.exp(-t * 350))
    trem = 1 + 0.06 * np.sin(2 * np.pi * 4.6 * t)
    return c.lp((body * 0.8 + tine) * env * trem, 5200) * vel * 0.3


def ep_chord(notes, length, vel=1.0, strum=0.012):
    n = int((length + strum * len(notes)) * SR)
    out = np.zeros((2, n))
    for i, (nm, o) in enumerate(notes):
        s = ep(hz(nm, o), length, vel)
        pan = -0.35 + 0.7 * i / max(1, len(notes) - 1)
        i0 = int(i * strum * SR)
        out[0, i0:i0 + len(s)] += s * np.cos((pan + 1) * np.pi / 4) * 1.414
        out[1, i0:i0 + len(s)] += s * np.sin((pan + 1) * np.pi / 4) * 1.414
    return out


def shaker(v=1.0):
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    x = c.hp(rng.standard_normal(n), 6500, 4) * np.exp(-t * 70) * (1 - np.exp(-t * 900))
    return x * 0.18 * v


def snap(v=1.0):
    n = int(0.14 * SR)
    t = np.arange(n) / SR
    x = c.bp(rng.standard_normal(n), 1300, 3600) * np.exp(-t * 48) + np.sin(2 * np.pi * 1850 * t) * np.exp(-t * 110) * 0.3
    return x * 0.5 * v


def soft_kick():
    return c.lp(c.kick(), 1800) * 0.9


# ── UI sounds ──────────────────────────────────────────────────────────────────────────────────────
def env_exp(n, k, attack=0.002):
    t = np.arange(n) / SR
    return np.exp(-t * k) * (1 - np.exp(-t / max(attack, 1e-4)))


def sfx_key(deep=False):
    """A soft phone-keyboard click: a tiny noise tick + a small 'thock'."""
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    tick = c.bp(rng.standard_normal(n), 2200, 6500) * np.exp(-t * 420)
    f = (150 if deep else 210) * (1 + rng.uniform(-0.08, 0.08))
    thock = np.sin(2 * np.pi * f * t) * np.exp(-t * 95) * (1 - np.exp(-t * 2000))
    lvl = 10 ** (rng.uniform(-2.5, 1.0) / 20)
    return (tick * 0.55 + thock * (0.7 if deep else 0.5)) * lvl


def noise_sweep(length, f0, f1, attack=0.03, decay=None, width=0.6):
    n = int(length * SR)
    noise = rng.standard_normal(n)
    out = np.zeros(n)
    blk = 256
    for b in range(0, n, blk):
        u = b / n
        fc = f0 * (f1 / f0) ** u
        seg = noise[b:b + blk]
        out[b:b + len(seg)] = c.bp(seg, fc * (1 - width / 2), fc * (1 + width / 2), 1)
    t = np.arange(n) / SR
    a = np.clip(t / attack, 0, 1)
    d = np.exp(-t * decay) if decay else np.clip((length - t) / (length * 0.6), 0, 1) ** 1.5
    return out * a * d


def sfx_whoosh(length=0.32, f0=500, f1=3800, level=1.0):
    x = noise_sweep(length, f0, f1, attack=length * 0.35)
    return c.lp(x, 7000) * 0.9 * level


def sfx_pop():
    """Incoming message: two soft sine blips, a fifth apart."""
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    a = np.sin(2 * np.pi * 988 * t) * env_exp(n, 30, 0.004)
    b = np.zeros(n)
    i = int(0.055 * SR)
    b[i:] = np.sin(2 * np.pi * 1480 * t[: n - i]) * env_exp(n - i, 26, 0.004)
    return (a * 0.3 + b * 0.26) * 0.8


def sfx_tick(f=1900, k=160, level=1.0):
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * f * t) * env_exp(n, k, 0.001) * 0.28 * level


def sfx_thump(f=85, level=1.0):
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * (f + 40 * np.exp(-t * 30)) * t) * np.exp(-t * 11)
    air = c.lp(rng.standard_normal(n), 900) * np.exp(-t * 30) * 0.25
    return (body + air) * 0.55 * level


def sfx_ding(freqs=(1396.9, 1760.0), level=1.0):
    n = int(0.6 * SR)
    t = np.arange(n) / SR
    y = sum(np.sin(2 * np.pi * f * t) * np.exp(-t * (7 + i * 3)) for i, f in enumerate(freqs))
    return y * (1 - np.exp(-t * 600)) * 0.16 * level


def sfx_strike():
    """A marker drawn across paper: a short bright swipe."""
    x = noise_sweep(0.24, 1800, 4200, attack=0.02, width=0.9)
    return c.hp(x, 900) * 0.7


def sfx_mark():
    x = noise_sweep(0.42, 900, 2600, attack=0.05, width=1.0)
    return c.lp(x, 5000) * 0.55


def mixin(*xs):
    """Sum mono signals of different lengths."""
    n = max(len(x) for x in xs)
    out = np.zeros(n)
    for x in xs:
        out[: len(x)] += x
    return out


def ui_sound(ev):
    ty = ev["type"]
    g = ev.get("gain", 1.0)
    if ty == "key":
        return sfx_key() * 0.55 * g
    if ty == "space":
        return sfx_key(deep=True) * 0.55 * g
    if ty == "return":
        return sfx_key(deep=True) * 0.8 * g
    if ty == "strike":
        return sfx_strike() * g
    if ty == "mark":
        return mixin(sfx_mark(), sfx_ding((1396.9, 2093.0), 0.8)) * g
    if ty in ("drop",):
        return mixin(sfx_whoosh(0.2, 1200, 3000, 0.45), sfx_tick(1600, 140, 0.6)) * g
    if ty == "select":
        return sfx_tick(2100, 170, 0.8) * g
    if ty == "enter":
        return mixin(sfx_key(deep=True) * 0.8, sfx_tick(1500, 120, 0.6)) * g
    if ty == "card":
        return mixin(sfx_whoosh(0.3, 400, 2600, 0.7), sfx_thump(120, 0.35)) * g
    if ty == "star":
        return sfx_tick(2400 + 180 * rng.integers(0, 5), 90, 0.7) * g
    if ty == "pop":
        return sfx_pop() * g
    if ty == "send":
        return sfx_whoosh(0.3, 450, 4200, 0.95) * g
    if ty == "dots":
        return None
    if ty == "swish":
        return sfx_whoosh(0.26, 700, 3200, 0.6) * g
    if ty == "tick":
        return sfx_tick(1800, 150, 0.9) * g
    if ty == "land":
        return sfx_thump(80, 0.8) * g
    if ty == "cross":
        return mixin(sfx_thump(140, 0.5), sfx_tick(700, 90, 0.5)) * g
    if ty == "check":
        return sfx_ding((1396.9, 1760.0), 1.0) * g
    if ty == "sheet":
        return sfx_whoosh(0.55, 250, 2400, 1.0) * g
    return None


# ── arrangement ────────────────────────────────────────────────────────────────────────────────────
def arrange(snd):
    bpm = snd["bpm"]
    beat = 60.0 / bpm
    bar = 4 * beat
    dur = float(snd["duration"])
    end_at = float(snd["endAt"])
    mood = snd.get("mood", "calm")
    key = KEYS.get(snd.get("key", "F"), KEYS["F"])
    events = snd.get("events", [])
    n = int((dur + 3) * SR)

    class Bus:
        def __init__(self):
            self.x = np.zeros((2, n))

        def add(self, sig, t, gain=1.0, pan=0.0):
            i = int(round(t * SR))
            if i >= n or i < 0:
                return
            if sig.ndim == 1:
                l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
                sig = np.vstack([sig * l * 1.414, sig * r * 1.414])
            m = min(sig.shape[1], n - i)
            self.x[:, i:i + m] += gain * sig[:, :m]

    music, drums, bass, fx, ui = Bus(), Bus(), Bus(), Bus(), Bus()
    kicks = []
    bars = int(np.ceil(dur / bar)) + 1
    groove_end = dur - 0.9  # drums stop just before the tail

    def chord_at(t):
        if t >= end_at - 1e-3:
            return key["prog"][0][0], key["tonic"]
        b = int(t // bar)
        return key["prog"][b % 4]

    if mood == "punchy":
        first_hit = min([e["t"] for e in events if e["type"] in ("hit", "impact")] or [bar])
        # intro: filtered pad + ticks under a riser into the first hit
        root, tones = chord_at(0)
        music.add(c.pad([hz(nm, o) for nm, o in tones], first_hit + 0.3, cutoff=900), 0, gain=0.55)
        k = 0
        while k * beat / 2 < first_hit:
            fx.add(c.tick(), k * beat / 2, gain=0.35 if k % 2 else 0.55)
            k += 1
        for e in events:
            if e["type"] == "riser":
                fx.add(c.riser(e.get("len", first_hit), 250, 6000), 0, gain=0.8)
        t = first_hit
        while t < groove_end - 1e-6:
            bi = int(round((t - first_hit) / beat))
            drums.add(c.kick(), t, gain=0.85)
            kicks.append(t)
            drums.add(c.hat(), t + beat / 2, gain=0.8, pan=0.25)
            if bi % 2 == 1:
                drums.add(c.clap(), t, gain=0.55)
            root, tones = chord_at(t)
            bass.add(c.sub_note(hz(root, 1 if root in ("A", "G", "A#") else 2), beat * 0.45), t + beat / 2, gain=0.9)
            # 16th pluck on the chord tones
            seq = [hz(nm, o + 1) for nm, o in tones[:3]] + [hz(tones[0][0], tones[0][1] + 2)]
            for s in range(4):
                music.add(c.pluck(seq[(bi * 4 + s) % len(seq)], bright=4200), t + s * beat / 4, gain=0.35, pan=(-0.3 if s % 2 else 0.3))
            t += beat
        for e in events:
            if e["type"] in ("hit", "impact"):
                root, tones = chord_at(e["t"])
                fr = [hz(nm, o) for nm, o in tones[:3]] + [hz(tones[0][0], tones[0][1] + 1)]
                music.add(c.supersaw(fr, beat * 0.9, release=0.25, cutoff=5200), e["t"], gain=0.65)
                fx.add(c.crash(), e["t"], gain=0.35 if e["type"] == "hit" else 0.6)
            if e["type"] == "impact":
                fx.add(c.impact(), e["t"], gain=0.5)
        # end card: tonic chord hit, lighter groove
        music.add(ep_chord(key["tonic"], 3.2, 1.0), end_at, gain=1.2)
        music.add(c.pad([hz(nm, o) for nm, o in key["tonic"][:4]], dur - end_at + 0.5, cutoff=1500), end_at, gain=0.5)
    else:
        # calm bed
        for b in range(bars):
            t0 = b * bar
            if t0 >= dur:
                break
            if t0 >= end_at - 1e-3:
                continue
            root, tones = chord_at(t0)
            music.add(ep_chord(tones, bar + 0.6, 1.0), t0, gain=1.0)
            music.add(ep_chord(tones[1:], beat * 1.5, 0.55), t0 + 2.5 * beat, gain=0.8)
            if b >= 1:
                bass.add(c.sub_note(hz(root, 1 if root in ("A", "G", "A#", "B") else 2), bar * 0.92), t0, gain=0.5)
            seq = [hz(nm, o + 1) for nm, o in tones[:3]] + [hz(tones[0][0], tones[0][1] + 2)]
            for s, ix in enumerate([0, 1, 2, 3, 2, 1, 2, 3]):
                music.add(c.pluck(seq[ix], length=0.3, bright=2600), t0 + s * beat / 2, gain=0.24 if b else 0.14, pan=(-0.3 if s % 2 else 0.3))
        t = 0.0
        step = beat / 4
        k = 0
        while t < groove_end - 1e-6:
            if t >= bar - 1e-6:  # drums from bar 2
                pos = k % 16
                if pos in (0, 8):
                    drums.add(soft_kick(), t, gain=0.5)
                    kicks.append(t)
                if pos in (4, 12):
                    drums.add(snap(), t, gain=0.45, pan=-0.1)
            v = [1.0, 0.45, 0.7, 0.45][k % 4]
            drums.add(shaker(v), t, gain=0.9, pan=0.25)
            k += 1
            t = k * step
        # end card lands on the tonic: a fuller chord + a soft swell into it
        fx.add(c.reverse_cymbal(0.8) * 0.5, end_at - 0.8, gain=0.6)
        music.add(ep_chord(key["tonic"], dur - end_at + 1.0, 1.05), end_at, gain=1.1)
        music.add(c.pad([hz(nm, o) for nm, o in key["tonic"][:4]], dur - end_at + 0.6, cutoff=1400), end_at, gain=0.45)
        root, _ = key["prog"][0]
        bass.add(c.sub_note(hz(root, 2), dur - end_at), end_at, gain=0.5)
        seq = [hz(nm, o + 1) for nm, o in key["tonic"][:4]]
        tt, s = end_at + beat, 0
        while tt < dur - 0.6:
            music.add(c.pluck(seq[s % 4], length=0.3, bright=2400), tt, gain=0.2, pan=(-0.3 if s % 2 else 0.3))
            tt += beat / 2
            s += 1

    # UI sounds
    for e in events:
        s = ui_sound(e)
        if s is None:
            continue
        pan = float(rng.uniform(-0.12, 0.12)) if e["type"] in ("key", "space") else 0.0
        ui.add(s, e["t"], pan=pan)

    # voice-over (reel): clips placed on their cues; the bed ducks under the voice
    vo = Bus()
    duck = np.ones(n)
    for v in snd.get("vo") or []:
        import soundfile as sf

        x, sr = sf.read(v["file"], dtype="float64", always_2d=False)
        if x.ndim > 1:
            x = x.mean(axis=1)
        if sr != SR:
            from scipy.signal import resample_poly

            x = resample_poly(x, SR, sr)
        vo.add(x, v["t"], gain=1.0)
        i0, i1 = int(v["t"] * SR), int((v["t"] + len(x) / SR) * SR)
        a, r = int(0.12 * SR), int(0.3 * SR)
        seg = np.ones(n)
        seg[max(0, i0 - a):i0] = np.linspace(1, 0.32, i0 - max(0, i0 - a))
        seg[i0:i1] = 0.32
        seg[i1:min(n, i1 + r)] = np.linspace(0.32, 1, min(n, i1 + r) - i1)
        duck = np.minimum(duck, seg)

    # sidechain + space
    sc = np.ones(n)
    rel = int(0.22 * SR)
    curve = 1 - (0.35 if mood == "calm" else 0.55) * (1 - np.linspace(0, 1, rel) ** 0.6)
    for t in kicks:
        i = int(t * SR)
        m = min(rel, n - i)
        sc[i:i + m] = np.minimum(sc[i:i + m], curve[:m])
    music.x *= sc
    bass.x *= sc
    music.x = c.pingpong(music.x, fb=0.28, mix=0.16)
    music.x = reverb(music.x, 2.2, 0.24)
    ui.x = reverb(ui.x, 0.9, 0.1)
    fx.x = reverb(fx.x, 2.4, 0.25)

    bed = music.x * 1.6 + drums.x * 0.75 + bass.x * 0.55 + fx.x * 0.9
    ui_gain = 0.62 if mood == "calm" else 0.5
    if snd.get("vo"):
        # voice leads: the bed sits well under it and ducks further while someone speaks
        bed = bed * 0.5 * duck
        vx = vo.x / (np.max(np.abs(vo.x)) or 1) * 0.9
        mix = bed + vx * 1.4 + ui.x * ui_gain * 0.7
    else:
        mix = bed + ui.x * ui_gain
    mix = np.vstack([c.hp(mix[0], 30), c.hp(mix[1], 30)])[:, : int(dur * SR)]
    fi = int(0.012 * SR)
    mix[:, :fi] *= np.linspace(0, 1, fi)
    fo = int(0.9 * SR)
    mix[:, -fo:] *= np.linspace(1, 0, fo) ** 1.4
    return mix, bed[:, : int(dur * SR)], ui.x[:, : int(dur * SR)] * ui_gain


def reverb(x, seconds=2.2, mix=0.22, predelay=0.02):
    """compose.reverb, sized to the buffer it is given (compose's own is fixed to the 60 s showreel)."""
    from scipy import signal as sg

    n = int(seconds * SR)
    t = np.arange(n) / SR
    r = np.random.default_rng(5)
    irl = c.lp(r.standard_normal(n) * np.exp(-t * 6.9 / seconds), 6000)
    irr = c.lp(r.standard_normal(n) * np.exp(-t * 6.9 / seconds), 6000)
    pd = int(predelay * SR)
    irl, irr = np.pad(irl, (pd, 0)), np.pad(irr, (pd, 0))
    irl /= np.sqrt(np.sum(irl ** 2))
    irr /= np.sqrt(np.sum(irr ** 2))
    wet = np.vstack([sg.fftconvolve(x[0], irl)[: x.shape[1]], sg.fftconvolve(x[1], irr)[: x.shape[1]]])
    return x * (1 - mix) + wet * mix * 1.6


# ── loudness ───────────────────────────────────────────────────────────────────────────────────────
def measure(x):
    """Integrated loudness (LUFS) and true peak (dBTP) via ffmpeg's EBU R128 meter."""
    import soundfile as sf

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    sf.write(path, x.T.astype(np.float32), SR, subtype="FLOAT")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    os.unlink(path)
    log = r.stderr[r.stderr.rfind("Summary:"):]
    i = float(re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", log).group(1))
    tp = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", log)
    return i, float(tp.group(1)) if tp else 0.0


def soft_limit(x, ceiling_db=-1.2):
    ceil = 10 ** (ceiling_db / 20)
    # 4x oversampled peak awareness is overkill here; a smooth tanh knee above 70% of the ceiling is enough
    knee = 0.7 * ceil
    a = np.abs(x)
    over = a > knee
    y = x.copy()
    y[over] = np.sign(x[over]) * (knee + (ceil - knee) * np.tanh((a[over] - knee) / (ceil - knee)))
    return y


def normalize(x, target=-14.0):
    for _ in range(4):
        i, tp = measure(x)
        if abs(i - target) < 0.15 and tp <= -1.0:
            break
        x = soft_limit(x * 10 ** ((target - i) / 20))
    return x, measure(x)


def main():
    a = sys.argv[1:]
    snd = json.load(open(a[a.index("--sound") + 1]))
    out = a[a.index("--out") + 1]
    import soundfile as sf

    mix, bed, ui = arrange(snd)
    mix, (lufs, tp) = normalize(mix)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    sf.write(out, mix.T.astype(np.float32), SR, subtype="PCM_24")
    if "--stems" in a:
        base = os.path.splitext(out)[0]
        sf.write(base + "-bed.wav", bed.T.astype(np.float32), SR, subtype="PCM_24")
        sf.write(base + "-ui.wav", ui.T.astype(np.float32), SR, subtype="PCM_24")
    print(f"soundtrack {out}: {mix.shape[1] / SR:.2f}s, {lufs:.1f} LUFS, true peak {tp:.1f} dBTP, mood {snd.get('mood')}")


if __name__ == "__main__":
    main()
