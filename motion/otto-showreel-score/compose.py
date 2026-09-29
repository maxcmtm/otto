#!/usr/bin/env python3
"""Otto showreel score — a 60 s track synthesized entirely in code (numpy/scipy, no samples).

Why code: every cut in the showreel must land on the beat, so the music is written to the same bar grid
the storyboard uses (120 BPM → 1 beat = 0.5 s, 1 bar = 2 s, 30 bars = 60 s) and exports a cue sheet with
the exact second of every kick, clap, crash, riser peak and section change.

  python3 compose.py [--out otto-score.wav] [--cues cues.json] [--bpm 120]

Arrangement (bars are 0-based, 2 s each):
  0–3   intro     filtered pad, clock ticks, heartbeat sub, riser into 8.0 s
  4–11  build     four-on-the-floor, offbeat bass, pluck arpeggio, hats; claps join at bar 8
  12    lift      kick out, snare roll + riser, filter opens; reverse cymbal into 26.0 s
  13–20 drop      full band, supersaw stabs, open hats, crashes at 26 s and 34 s
  21–24 breakdown pads + pluck motif, no kick, riser in bar 24
  25–28 final     drop returns with the lead motif, crash at 50 s
  29    end       impact at 58.0 s, chord tail to 60 s
Key: A minor, Am–F–C–G (one chord per bar).
"""
import json
import sys

import numpy as np
from scipy import signal

SR = 48000
BPM = 120.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT
BARS = 30
DUR = BARS * BAR
N = int(DUR * SR)
rng = np.random.default_rng(7)

A4 = 440.0
NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def hz(name, octave):
    return A4 * 2 ** ((NOTE[name] - 9) / 12 + (octave - 4))


CHORDS = [  # (root, [tones]) one per bar, cycling
    ("A", [("A", 3), ("C", 4), ("E", 4)]),
    ("F", [("F", 3), ("A", 3), ("C", 4)]),
    ("C", [("C", 4), ("E", 4), ("G", 4)]),
    ("G", [("G", 3), ("B", 3), ("D", 4)]),
]


def chord(bar):
    return CHORDS[bar % 4]


def t_of(bar, beat=0.0):
    return bar * BAR + beat * BEAT


# ── buffers ────────────────────────────────────────────────────────────────────────────────────────
class Bus:
    def __init__(self, name):
        self.name = name
        self.x = np.zeros((2, N + SR * 4))

    def add(self, sig, t, gain=1.0, pan=0.0):
        i = int(round(t * SR))
        if i >= self.x.shape[1]:
            return
        if sig.ndim == 1:
            l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
            sig = np.vstack([sig * l * 1.414, sig * r * 1.414])
        n = min(sig.shape[1], self.x.shape[1] - i)
        self.x[:, i:i + n] += gain * sig[:, :n]


def env_adsr(n, a, d, s, r, sustain_len=None):
    a_n, d_n, r_n = int(a * SR), int(d * SR), int(r * SR)
    s_n = max(0, (n - a_n - d_n - r_n) if sustain_len is None else int(sustain_len * SR))
    e = np.concatenate([np.linspace(0, 1, max(a_n, 1)), np.linspace(1, s, max(d_n, 1)),
                        np.full(s_n, s), np.linspace(s, 0, max(r_n, 1))])
    return e[:n] if len(e) >= n else np.pad(e, (0, n - len(e)))


def lp(x, fc, order=2):
    b, a = signal.butter(order, min(fc, SR * 0.45) / (SR / 2), "low")
    return signal.lfilter(b, a, x)


def hp(x, fc, order=2):
    b, a = signal.butter(order, fc / (SR / 2), "high")
    return signal.lfilter(b, a, x)


def bp(x, lo, hi, order=2):
    b, a = signal.butter(order, [lo / (SR / 2), min(hi, SR * 0.45) / (SR / 2)], "band")
    return signal.lfilter(b, a, x)


def saw(f, n, detune_cents=0.0, harmonics_cap=9000.0, phase=0.0):
    """Band-limited saw by additive synthesis (harmonics up to harmonics_cap Hz)."""
    f = f * 2 ** (detune_cents / 1200)
    t = np.arange(n) / SR
    k_max = max(1, int(harmonics_cap / f))
    out = np.zeros(n)
    for k in range(1, k_max + 1):
        out += np.sin(2 * np.pi * k * f * t + phase * k) / k
    return out * (2 / np.pi)


def sweep_lp(x, f0, f1, curve=2.0, block=512):
    """Time-varying low-pass (block-wise one-pole cascade) from f0 to f1."""
    y = np.zeros_like(x)
    z1 = z2 = 0.0
    nb = int(np.ceil(len(x) / block))
    for b in range(nb):
        u = (b / max(nb - 1, 1)) ** curve
        fc = f0 + (f1 - f0) * u
        g = 1 - np.exp(-2 * np.pi * fc / SR)
        seg = x[b * block:(b + 1) * block]
        out = np.empty_like(seg)
        for i, s in enumerate(seg):
            z1 += g * (s - z1)
            z2 += g * (z1 - z2)
            out[i] = z2
        y[b * block:b * block + len(seg)] = out
    return y


# ── instruments ────────────────────────────────────────────────────────────────────────────────────
def kick():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 46 + 110 * np.exp(-t * 32)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 7.5)
    click = hp(rng.standard_normal(n) * np.exp(-t * 400), 2500) * 0.35
    return np.tanh(1.6 * (body + click)) * 0.9


def clap():
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    e = np.zeros(n)
    for off in (0.0, 0.011, 0.022):
        i = int(off * SR)
        e[i:] += np.exp(-(t[: n - i]) * (60 if off < 0.02 else 18))
    return bp(noise * e, 900, 2600) * 0.9


def hat(open_=False):
    n = int((0.28 if open_ else 0.05) * SR)
    t = np.arange(n) / SR
    x = hp(rng.standard_normal(n), 7000, 4) * np.exp(-t * (14 if open_ else 90))
    return x * (0.35 if open_ else 0.28)


def tick():
    n = int(0.03 * SR)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * 3200 * t) * np.exp(-t * 260) * 0.25


def sub_note(f, length):
    n = int(length * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)
    return np.tanh(1.3 * x) * env_adsr(n, 0.005, 0.05, 0.85, 0.04) * 0.55


def pluck(f, length=0.32, bright=4200):
    n = int(length * SR)
    t = np.arange(n) / SR
    x = saw(f, n, harmonics_cap=7000) + 0.5 * saw(f, n, detune_cents=7, harmonics_cap=7000)
    cutoff_env = 300 + bright * np.exp(-t * 18)
    # approximate time-varying LP with two static passes blended by the envelope
    bright_x, dark_x = lp(x, bright), lp(x, 500)
    w = (cutoff_env - 300) / bright
    y = bright_x * w + dark_x * (1 - w)
    return y * np.exp(-t * 9) * 0.22


def supersaw(freqs, length, attack=0.01, release=0.25, cutoff=5200, voices=5, spread=18):
    n = int(length * SR)
    left, right = np.zeros(n), np.zeros(n)
    for f in freqs:
        for v in range(voices):
            det = (v - (voices - 1) / 2) / ((voices - 1) / 2) * spread
            s = saw(f, n, detune_cents=det, harmonics_cap=6500, phase=rng.uniform(0, 6.28))
            pan = (v - (voices - 1) / 2) / ((voices - 1) / 2) * 0.7
            left += s * np.cos((pan + 1) * np.pi / 4)
            right += s * np.sin((pan + 1) * np.pi / 4)
    e = env_adsr(n, attack, 0.08, 0.8, release)
    st = np.vstack([lp(left, cutoff), lp(right, cutoff)]) * e / (len(freqs) * voices) * 1.1
    return st


def pad(freqs, length, cutoff=1800):
    return supersaw(freqs, length, attack=0.6, release=0.9, cutoff=cutoff, voices=4, spread=10) * 0.9


def riser(length, f0=200, f1=5000):
    n = int(length * SR)
    t = np.arange(n) / SR
    u = t / length
    noise = rng.standard_normal(n)
    # sweep a band through the noise in blocks
    out = np.zeros(n)
    block = 2048
    for b in range(0, n, block):
        fc = f0 * (f1 / f0) ** (b / n)
        seg = noise[b:b + block]
        out[b:b + len(seg)] = bp(seg, fc * 0.7, fc * 1.4)
    tone = np.sin(2 * np.pi * np.cumsum(180 * 4 ** u) / SR) * 0.25
    return (out * 0.8 + tone) * (u ** 2.2) * 0.5


def reverse_cymbal(length=2.0):
    n = int(length * SR)
    t = np.arange(n) / SR
    x = hp(rng.standard_normal(n), 3500, 2) * np.exp((t - length) * 3.2)
    return x * 0.45


def crash():
    n = int(2.6 * SR)
    t = np.arange(n) / SR
    return hp(rng.standard_normal(n), 4500, 2) * np.exp(-t * 1.9) * 0.3


def impact():
    n = int(3.5 * SR)
    t = np.arange(n) / SR
    boom = np.sin(2 * np.pi * np.cumsum(38 + 60 * np.exp(-t * 6)) / SR) * np.exp(-t * 1.6)
    hit = lp(rng.standard_normal(n), 1800) * np.exp(-t * 9) * 0.8
    return np.tanh(1.4 * (boom + hit)) * 0.95


def snare_roll(start_t, length, bus):
    steps = int(length / (BEAT / 4))
    for i in range(steps):
        u = i / steps
        dt = BEAT / 4 if u < 0.5 else BEAT / 8
        t = start_t + i * (BEAT / 4) * (1 - 0.0 * u)
        bus.add(clap() * (0.25 + 0.75 * u ** 1.5), t, gain=0.55)
        if u > 0.5:
            bus.add(clap() * (0.25 + 0.75 * u ** 1.5), t + dt, gain=0.45)


# ── reverb / delay / sidechain / master ─────────────────────────────────────────────────────────────
def reverb(x, seconds=2.2, mix=0.22, predelay=0.02):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    irl = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)
    irr = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)
    irl, irr = lp(irl, 6000), lp(irr, 6000)
    pd = int(predelay * SR)
    irl, irr = np.pad(irl, (pd, 0)), np.pad(irr, (pd, 0))
    irl /= np.sqrt(np.sum(irl ** 2)); irr /= np.sqrt(np.sum(irr ** 2))
    wet = np.vstack([signal.fftconvolve(x[0], irl)[: x.shape[1]], signal.fftconvolve(x[1], irr)[: x.shape[1]]])
    return x * (1 - mix) + wet * mix * 1.6


def pingpong(x, time=BEAT * 0.75, fb=0.35, mix=0.28, taps=5):
    d = int(time * SR)
    out = x.copy()
    for k in range(1, taps + 1):
        g = mix * fb ** (k - 1)
        ch_from, ch_to = (0, 1) if k % 2 else (1, 0)
        out[ch_to, k * d:] += g * x[ch_from, : x.shape[1] - k * d]
    return out


def sidechain_env(kick_times, depth=0.65, release=0.22):
    e = np.ones(N + SR * 4)
    rel = int(release * SR)
    curve = 1 - depth * (1 - np.linspace(0, 1, rel) ** 0.6)
    for t in kick_times:
        i = int(t * SR)
        seg = e[i:i + rel]
        e[i:i + rel] = np.minimum(seg, curve[: len(seg)])
    return e


def limiter(x, ceiling=0.95):
    return np.tanh(x / ceiling * 1.05) * ceiling


# ── arrangement ─────────────────────────────────────────────────────────────────────────────────────
def compose():
    drums, bass, music, fx = Bus("drums"), Bus("bass"), Bus("music"), Bus("fx")
    cues = {"bpm": BPM, "beat_s": BEAT, "bar_s": BAR, "duration_s": DUR, "sections": [], "kicks": [], "claps": [],
            "crashes": [], "impacts": [], "riser_peaks": [], "downbeats": [round(t_of(b), 3) for b in range(BARS)]}

    def section(name, b0, b1):
        cues["sections"].append({"name": name, "start": round(t_of(b0), 3), "end": round(t_of(b1), 3), "bars": [b0, b1 - 1]})

    section("intro", 0, 4); section("build", 4, 12); section("lift", 12, 13); section("drop", 13, 21)
    section("breakdown", 21, 25); section("final", 25, 29); section("end", 29, 30)

    K, CL = kick(), clap()
    kick_bars = list(range(4, 12)) + list(range(13, 21)) + list(range(25, 29))

    # intro: pad + ticks + heartbeat
    for b in range(0, 4):
        root, tones = chord(b)
        music.add(pad([hz(n, o) for n, o in tones], BAR + 0.6, cutoff=700 + 350 * b), t_of(b), gain=0.8)
        for s in range(16):
            fx.add(tick(), t_of(b, s / 4), gain=0.35 if s % 4 else 0.6, pan=(-0.3 if s % 2 else 0.3))
        drums.add(sub_note(hz(root, 1), 0.25), t_of(b), gain=0.8)
    fx.add(riser(4.0), t_of(2), gain=0.9)
    cues["riser_peaks"].append(round(t_of(4), 3))
    fx.add(impact(), t_of(4), gain=0.55); cues["impacts"].append(round(t_of(4), 3))

    # kicks, hats, claps
    for b in kick_bars:
        for beat in range(4):
            t = t_of(b, beat)
            drums.add(K, t, gain=1.0); cues["kicks"].append(round(t, 3))
            drums.add(hat(), t_of(b, beat + 0.5), gain=1.0, pan=0.25)
            if b >= 13:
                drums.add(hat(), t_of(b, beat + 0.25), gain=0.45, pan=-0.3)
                drums.add(hat(), t_of(b, beat + 0.75), gain=0.45, pan=-0.3)
        if b >= 8:
            for beat in (1, 3):
                drums.add(CL, t_of(b, beat), gain=0.8); cues["claps"].append(round(t_of(b, beat), 3))
        if b >= 13 and b % 2 == 1:
            drums.add(hat(True), t_of(b, 3.5), gain=0.8, pan=0.2)

    # bass: offbeat 8ths on the chord root (build/drop/final), long notes in breakdown
    for b in list(range(4, 12)) + list(range(13, 21)) + list(range(25, 29)):
        root, _ = chord(b)
        for beat in range(4):
            bass.add(sub_note(hz(root, 1 if root in ("A", "G") else 2), BEAT * 0.45), t_of(b, beat + 0.5), gain=1.0)

    # pluck arpeggio 16ths (build: from bar 6; drop + final: always)
    pattern = [0, 1, 2, 3, 2, 1, 0, 1, 2, 3, 4, 3, 2, 1, 2, 3]
    for b in list(range(6, 12)) + list(range(13, 21)) + list(range(21, 29)):
        _, tones = chord(b)
        seq = [hz(n, o + 1) for n, o in tones] + [hz(tones[0][0], tones[0][1] + 2), hz(tones[1][0], tones[1][1] + 2)]
        for s, idx in enumerate(pattern):
            if 21 <= b <= 24 and s % 2:  # breakdown: 8ths only, softer
                continue
            g = 0.55 if 21 <= b <= 24 else (0.8 if b >= 13 else 0.6)
            music.add(pluck(seq[idx], bright=5200 if b >= 13 else 3200), t_of(b, s / 4), gain=g, pan=(-0.35 if s % 2 else 0.35))

    # supersaw stabs in drop + final (on the offbeats, sidechained)
    for b in list(range(13, 21)) + list(range(25, 29)):
        _, tones = chord(b)
        fr = [hz(n, o) for n, o in tones] + [hz(tones[0][0], tones[0][1] + 1)]
        for beat in (0.5, 1.5, 2.5, 3.5):
            music.add(supersaw(fr, BEAT * 0.4, release=0.12, cutoff=6200), t_of(b, beat), gain=0.55)

    # pads under breakdown + end
    for b in range(21, 25):
        _, tones = chord(b)
        music.add(pad([hz(n, o) for n, o in tones] + [hz(tones[2][0], tones[2][1] + 1)], BAR + 0.8, cutoff=2400), t_of(b), gain=0.9)

    # lead motif in final (8ths, chord tones one octave up)
    motif = [2, None, 1, 2, 3, None, 2, 1]
    for b in range(25, 29):
        _, tones = chord(b)
        seq = [hz(n, o + 1) for n, o in tones] + [hz(tones[0][0], tones[0][1] + 2)]
        for i, idx in enumerate(motif):
            if idx is None:
                continue
            music.add(supersaw([seq[idx]], BEAT * 0.45, release=0.2, cutoff=7000, voices=3, spread=12), t_of(b, i / 2), gain=0.5)

    # lift bar: snare roll + riser + reverse cymbal
    snare_roll(t_of(12), BAR, drums)
    fx.add(riser(BAR, 300, 8000), t_of(12), gain=1.0); cues["riser_peaks"].append(round(t_of(13), 3))
    fx.add(reverse_cymbal(2.0), t_of(12), gain=0.9)
    fx.add(riser(BAR, 250, 6000), t_of(24), gain=0.9); cues["riser_peaks"].append(round(t_of(25), 3))
    fx.add(reverse_cymbal(2.0), t_of(24), gain=0.8)

    # crashes + impacts
    for t in (t_of(13), t_of(17), t_of(25)):
        fx.add(crash(), t, gain=1.0); cues["crashes"].append(round(t, 3))
    for t in (t_of(13), t_of(25), t_of(29)):
        fx.add(impact(), t, gain=0.8 if t < t_of(29) else 1.0); cues["impacts"].append(round(t, 3))

    # end: final chord hit + tail
    _, tones = chord(0)
    music.add(supersaw([hz(n, o) for n, o in tones] + [hz("A", 4), hz("E", 5)], 2.0, attack=0.005, release=1.6, cutoff=5000), t_of(29), gain=0.9)
    music.add(pad([hz(n, o) for n, o in tones], 2.0, cutoff=1400), t_of(29), gain=0.8)

    # sidechain music + bass to the kicks
    sc = sidechain_env(cues["kicks"])
    music.x *= sc; bass.x *= sc
    music.x = pingpong(music.x)
    music.x = reverb(music.x, 2.4, 0.26)
    fx.x = reverb(fx.x, 3.0, 0.3)
    drums_rev = reverb(drums.x, 1.2, 0.08)

    # section dynamics: the build sits under the drop so the drop actually lifts
    dyn = np.ones(N + SR * 4)
    def ramp(b0, b1, g0, g1):
        i0, i1 = int(t_of(b0) * SR), int(t_of(b1) * SR)
        dyn[i0:i1] = np.linspace(g0, g1, i1 - i0)
    ramp(4, 12, 0.62, 0.8); ramp(12, 13, 0.8, 0.9); ramp(21, 25, 0.85, 0.95)
    mix = (drums_rev * 0.62 + bass.x * 0.5) * dyn + music.x * 2.6 * dyn + fx.x * 1.25
    mix = np.vstack([hp(mix[0], 28), hp(mix[1], 28)])
    mix = mix[:, : N]
    # short fade-in, tail fade on the last 0.6 s
    fi = int(0.02 * SR); mix[:, :fi] *= np.linspace(0, 1, fi)
    fo = int(0.6 * SR); mix[:, -fo:] *= np.linspace(1, 0, fo) ** 1.5
    peak = np.max(np.abs(mix)) or 1
    mix = limiter(mix / peak * 1.25)
    return mix, cues


def main():
    a = sys.argv[1:]
    out = a[a.index("--out") + 1] if "--out" in a else "otto-score.wav"
    cues_path = a[a.index("--cues") + 1] if "--cues" in a else "cues.json"
    import soundfile as sf
    mix, cues = compose()
    sf.write(out, mix.T.astype(np.float32), SR, subtype="PCM_24")
    json.dump(cues, open(cues_path, "w"), indent=1)
    print(f"wrote {out} ({mix.shape[1] / SR:.2f}s) and {cues_path}: {len(cues['kicks'])} kicks, "
          f"{len(cues['claps'])} claps, sections {[s['name'] for s in cues['sections']]}")


if __name__ == "__main__":
    main()
