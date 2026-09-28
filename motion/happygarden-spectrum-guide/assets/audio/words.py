import json, sys, glob, os
from faster_whisper import WhisperModel
m = WhisperModel(os.environ.get("WHISPER_MODEL", "small.en"), device="cpu", compute_type="int8")
out = {}
for f in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "vo-0[1-7].wav"))):
    segs, info = m.transcribe(f, word_timestamps=True, language="en", vad_filter=False)
    words = [{"text": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)} for s in segs for w in s.words]
    out[os.path.basename(f)] = {"duration": round(info.duration, 3), "words": words}
    print(os.path.basename(f), round(info.duration, 2), " ".join(f"{w['text']}@{w['start']}" for w in words))
json.dump(out, open(os.path.join(os.path.dirname(__file__), "words.json"), "w"), indent=1)
