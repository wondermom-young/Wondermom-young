#!/usr/bin/env python3
"""릴스 자동 편집 프로그램.

순서 (반드시 이 순서):
  1) transcribe  원본 음성을 단어 단위 시간까지 받아쓰기 → words.json / words.md(받아쓰기 표) / plan.json(초안)
  2) (Claude)    받아쓰기 표를 직접 읽고 plan.json 에 "지울 단어 번호"와 "문장별 화면 구성"을 작성
  3) render      plan.json 대로 컷 편집 + 자막/강조/제목/모션그래픽/효과음/배경음 → output/*.mp4
  4) check       완성본 다시 받아쓰기·소리·화면 검수 + 프레임 모아보기

그 밖에: find(작업 폴더 영상 찾기), draft(초안 다시 만들기), feedback(피드백 반영), ref(참고 릴스 분석), selftest
모든 숫자 규칙은 작업 폴더의 style.json 에서 읽는다.
"""
import argparse
import datetime as dt
import difflib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ENGINE = Path(__file__).resolve().parent
WORK = ENGINE.parent
STYLE_PATH = WORK / "style.json"
RULEBOOK = WORK / "편집규칙집.md"
JOBS = WORK / "jobs"
OUTPUT = WORK / "output"
FONTS = WORK / "fonts"
SR = 48000
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts"}


# ───────────────────────── 공통 ─────────────────────────
def log(*a):
    print(*a, flush=True)


def load_style():
    return json.loads(STYLE_PATH.read_text(encoding="utf-8"))


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"명령 실패: {' '.join(map(str, cmd))}\n{r.stderr[-2000:]}")
    return r


def ffprobe(path):
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    return json.loads(r.stdout)


def video_info(path):
    info = ffprobe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    if "rotate" in (v.get("tags") or {}):
        rot = int(v["tags"]["rotate"])
    if abs(rot) % 180 == 90:
        w, h = h, w
    return {"w": w, "h": h, "duration": float(info["format"]["duration"])}


def read_wav(path):
    import soundfile as sf
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return x.mean(axis=1), sr


def write_wav(path, x, sr=SR):
    import soundfile as sf
    sf.write(str(path), x.astype(np.float32), sr, subtype="FLOAT")


def extract_audio(src, dst, sr=SR):
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), "-c:a", "pcm_f32le", str(dst)])


def db(x):
    return 20 * np.log10(np.maximum(x, 1e-9))


def frame_db(x, sr=SR, hop=0.01):
    """10ms 단위 소리 크기(dB)."""
    n = int(sr * hop)
    m = len(x) // n
    if m == 0:
        return np.array([-120.0])
    fr = x[: m * n].reshape(m, n)
    return db(np.sqrt((fr ** 2).mean(axis=1)))


def speech_threshold(env):
    floor = np.percentile(env, 10)
    top = np.percentile(env, 95)
    return floor + max(8.0, 0.3 * (top - floor)), floor


def ascii_name(p):
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(p).stem).strip("_")
    if len(stem) < 3:
        stem = "video_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return stem[:40]


def hex_to_ass(c):
    c = c.lstrip("#")
    return f"&H00{c[4:6]}{c[2:4]}{c[0:2]}&".upper()


def hex_to_ass_inline(c):
    c = c.lstrip("#")
    return f"&H{c[4:6]}{c[2:4]}{c[0:2]}&".upper()


def ass_time(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def job_dir(arg):
    p = Path(arg)
    if p.is_dir():
        return p.resolve()
    p = JOBS / arg
    if p.is_dir():
        return p
    raise SystemExit(f"작업을 찾을 수 없어요: {arg}")


# ───────────────────────── 1) 받아쓰기 ─────────────────────────
def load_whisper():
    from faster_whisper import WhisperModel
    name = os.environ.get("REELS_WHISPER_MODEL", "large-v3-turbo")
    try:
        return WhisperModel(name, device="cpu", compute_type="int8", download_root=str(WORK / "models"),
                            cpu_threads=os.cpu_count() or 4)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "받아쓰기 모델(faster-whisper large-v3-turbo)을 불러오지 못했어요.\n"
            "인터넷에서 huggingface.co 접속이 막혀 있으면 생기는 문제예요.\n"
            f"자세한 오류: {e}") from e


def whisper_words(model, wav16, vocab=None):
    segs, _ = model.transcribe(str(wav16), language="ko", word_timestamps=True, beam_size=5,
                               condition_on_previous_text=False, vad_filter=False,
                               initial_prompt=vocab or None, no_speech_threshold=0.5)
    out = []
    for si, seg in enumerate(segs):
        for w in seg.words or []:
            t = w.word
            if not t.strip():
                continue
            out.append({"w": t, "s0": round(w.start, 3), "e0": round(w.end, 3), "p": round(w.probability, 3), "seg": si})
    return out


def refine_words(words, x, sr=SR):
    """받아쓰기 시각이 앞쪽 무음까지 먹는 문제를 소리 크기로 다시 잡는다."""
    env = frame_db(x, sr)
    thr, floor = speech_threshold(env)
    nfr = len(env)
    for k, w in enumerate(words):
        a, b = int(w["s0"] * 100), max(int(w["s0"] * 100) + 1, int(math.ceil(w["e0"] * 100)))
        a, b = max(0, min(a, nfr - 1)), max(1, min(b, nfr))
        seg = env[a:b]
        voiced = np.where(seg >= thr)[0]
        if len(voiced) == 0:
            w["s"], w["e"], w["db"], w["quiet"] = w["s0"], w["e0"], round(float(seg.max()) if len(seg) else -90, 1), True
            continue
        s, e = a + voiced[0], a + voiced[-1] + 1
        # 끝이 너무 일찍 잘렸으면 소리가 이어지는 만큼 최대 0.08초 늘림
        nxt = int(words[k + 1]["s0"] * 100) if k + 1 < len(words) else nfr
        lim = min(nfr, e + 8, max(e, nxt))
        while e < lim and env[e] >= thr:
            e += 1
        prv = int(words[k - 1]["e0"] * 100) if k else 0
        lim = max(0, s - 5, min(s, prv))
        while s > lim and env[s - 1] >= thr:
            s -= 1
        w["s"], w["e"] = round(s / 100, 3), round(e / 100, 3)
        w["db"] = round(float(env[a + voiced].mean()), 1)
    # 단어끼리 겹치지 않게
    for p, w in zip(words, words[1:]):
        if w["s"] < p["e"]:
            mid = round((w["s"] + p["e"]) / 2, 3)
            p["e"], w["s"] = max(p["s"] + 0.01, mid), mid
    return words, float(thr), float(floor)


def write_words_md(path, words, meta):
    L = [f"# 받아쓰기 표 — {meta['name']}", "",
         f"- 원본 길이: {meta['duration']:.2f}초 / 단어 {len(words)}개 / 말소리 기준선 {meta['thr']:.1f}dB",
         "- 시간은 소리 크기로 다시 잡은 실제 말소리 구간(초). 음량(dB)이 평소보다 8dB 이상 작으면 속삭임 테이크일 수 있음.",
         "- ⏸ 줄은 단어 사이 멈춤(0.3초 이상).", "",
         "| # | 시작 | 끝 | 음량dB | 단어 | 메모 |", "|---:|---:|---:|---:|---|---|"]
    med = float(np.median([w["db"] for w in words])) if words else 0
    for i, w in enumerate(words):
        if i:
            gap = w["s"] - words[i - 1]["e"]
            if gap >= 0.3:
                L.append(f"| | | | | ⏸ {gap:.2f}초 | |")
        memo = []
        if w.get("quiet"):
            memo.append("소리 거의 없음")
        if w["db"] < med - 8:
            memo.append("작음(속삭임?)")
        if w["p"] < 0.5:
            memo.append(f"불확실 {w['p']:.2f}")
        L.append(f"| {i} | {w['s']:.2f} | {w['e']:.2f} | {w['db']:.1f} | {w['w'].strip()} | {', '.join(memo)} |")
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


def cmd_transcribe(a):
    src = Path(a.video).resolve()
    if not src.exists():
        raise SystemExit(f"영상이 없어요: {src}")
    name = a.name or ascii_name(src)
    jd = JOBS / name
    jd.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower() or ".mp4"
    dst = jd / f"source{ext}"
    if not dst.exists():
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    info = video_info(dst)
    log(f"① 받아쓰기 시작: {src.name} ({info['duration']:.1f}초)")
    extract_audio(dst, jd / "audio48.wav", SR)
    extract_audio(dst, jd / "audio16.wav", 16000)
    model = load_whisper()
    words = whisper_words(model, jd / "audio16.wav", a.vocab)
    x, _ = read_wav(jd / "audio48.wav")
    words, thr, floor = refine_words(words, x)
    for i, w in enumerate(words):
        w["i"] = i
    data = {"name": name, "source": str(dst), "original": str(src), "duration": info["duration"],
            "video": info, "thr": thr, "floor": floor, "words": words}
    (jd / "words.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    write_words_md(jd / "words.md", words, data)
    plan = make_draft(data, load_style())
    (jd / "plan.draft.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    if not (jd / "plan.json").exists() or a.force:
        (jd / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"   단어 {len(words)}개 → {jd/'words.md'}")
    log(f"   초안 → {jd/'plan.json'}  (다음: 받아쓰기 표를 읽고 plan.json 을 다듬은 뒤 render)")
    log(f"JOB={jd}")


# ───────────────────────── 2) 교정 대본 초안 ─────────────────────────
FILLERS = {"음", "어", "그", "아", "저", "에", "으", "흠", "음음", "어어", "그니까", "막", "뭐", "이제", "약간"}
SOFT_FILLERS = {"막", "뭐", "이제", "약간", "그니까"}  # 내용일 수도 있어 짧고 앞뒤 멈춤 있을 때만
EMO = [("충격|대박|놀라|미쳤", "😲"), ("감동|울컥|눈물|고마", "😭"), ("꿀팁|방법|비법|노하우", "💡"),
       ("돈|무료|공짜|할인|원", "💰"), ("맛있|맛|먹", "😋"), ("사랑|선물", "💝")]


def clean(t):
    return re.sub(r"[^\w가-힣?!]", "", t)


def sentences_from_words(words):
    sents, cur = [], []
    for i, w in enumerate(words):
        if cur:
            gap = w["s"] - words[i - 1]["e"]
            if gap > 0.6 or re.search(r"[.?!。]$", words[i - 1]["w"].strip()):
                sents.append(cur)
                cur = []
        cur.append(i)
    if cur:
        sents.append(cur)
    return sents


def sent_text(words, idx, delete=()):
    return "".join(words[i]["w"] for i in idx if i not in delete).strip()


def make_draft(data, style):
    """규칙 기반 초안. Claude 가 받아쓰기 표를 읽고 반드시 다듬는다."""
    words = data["words"]
    if not words:
        return {"delete": [], "fix": {}, "sentences": [], "hook": {}, "cta_keyword": ""}
    delete = set()
    # 더듬기·군말
    for i, w in enumerate(words):
        c = clean(w["w"])
        prev_gap = w["s"] - words[i - 1]["e"] if i else 1
        next_gap = words[i + 1]["s"] - w["e"] if i + 1 < len(words) else 1
        if c in FILLERS - SOFT_FILLERS:
            delete.add(i)
        elif c in SOFT_FILLERS and (prev_gap > 0.25 or next_gap > 0.25) and w["e"] - w["s"] < 0.45:
            delete.add(i)
        if i + 1 < len(words):
            n = clean(words[i + 1]["w"])
            if c and (c == n or (len(c) >= 1 and n.startswith(c) and len(n) > len(c) and next_gap < 0.6 and w["e"] - w["s"] < 0.5)):
                delete.add(i)  # "그러 그러니까", "이거 이거"
    sents = sentences_from_words(words)
    sdb = []
    for idx in sents:
        v = [words[i]["db"] for i in idx if not words[i].get("quiet")]
        sdb.append(float(np.mean(v)) if v else -90.0)
    med = float(np.median(sdb))
    tk = style["takes"]
    dropped = set()
    # 속삭이며 대본 보는 테이크
    for k, d in enumerate(sdb):
        if d < med - tk["whisper_db_below_median"]:
            dropped.add(k)
    # 같은 문장 다시 읽기: 비슷한 문장 묶음 중 마지막 테이크(더 크게 읽은 쪽)만 남김
    texts = [clean(sent_text(words, idx, delete)) for idx in sents]
    k = 0
    while k < len(sents):
        group = [k]
        j = k + 1
        while j < len(sents) and j <= group[-1] + 2:
            a, b = texts[group[-1]], texts[j]
            if a and b and (difflib.SequenceMatcher(None, a, b).ratio() > 0.6 or (len(a) >= 4 and b.startswith(a[: max(4, len(a) // 2)]))):
                group.append(j)
            j += 1
        if len(group) > 1:
            cands = [g for g in group if g not in dropped] or group
            best = cands[-1]
            loud = max(cands, key=lambda g: sdb[g])
            if sdb[loud] - sdb[best] > tk["prefer_louder_if_db"]:
                best = loud
            for g in group:
                if g != best:
                    dropped.add(g)
            k = group[-1] + 1
        else:
            k += 1
    for kk in dropped:
        delete.update(sents[kk])
    kept = [(k, idx) for k, idx in enumerate(sents) if k not in dropped and any(i not in delete for i in idx)]
    # 화면 구성
    out = []
    emph_n = 0
    for n, (k, idx) in enumerate(kept):
        txt = sent_text(words, idx, delete)
        s = {"from": idx[0], "to": idx[-1], "text": txt}
        if n == 0:
            s.update(layout="face", role="hook")
        elif "댓글" in txt and not any(o.get("role") == "cta" for o in out):
            s.update(layout="face", role="cta")
        elif n < len(kept) - 1 and emph_n < style["layout"]["max_face_emphasis"] and re.match(r"^\s*(근데|그런데|하지만|사실|그래서|결론)", txt) and len(kept) > 5:
            s.update(layout="face", role="emphasis")
            emph_n += 1
        else:
            s.update(layout="split", scene=guess_scene(txt, style))
        out.append(s)
    first = out[0]["text"] if out else ""
    kw = ""
    for o in out:
        if o.get("role") == "cta":
            m = re.search(r"['\"“‘]([^'\"”’]+)['\"”’]", o["text"]) or re.search(r"(\S+?)(?:이?라고|라고)\s*댓글", o["text"]) or re.search(r"댓글(?:에|로)?\s*(\S+?)(?:이?라고|라고|을|를)?\s", o["text"] + " ")
            kw = clean(m.group(1)) if m else ""
    return {
        "_안내": "Claude 가 words.md 를 직접 읽고 고친다. delete=지울 단어 번호, fix=자막 표기만 고칠 단어, sentences=문장별 화면 구성",
        "delete": sorted(delete),
        "fix": {},
        "highlight_words": [],
        "cta_keyword": kw,
        "hook": make_hook(first, style),
        "sentences": out,
    }


def make_hook(text, style):
    t = re.sub(r"[,.…]", "", text).strip()
    ej = t.split()
    n = style["title"]["chars_per_line"]
    l1, l2 = "", ""
    for e in ej:
        if len(l1) + len(e) <= n + 2 and not l2:
            l1 = (l1 + " " + e).strip()
        elif len(l2) + len(e) <= n + 2:
            l2 = (l2 + " " + e).strip()
        else:
            break
    emoji = "🔥"
    for pat, em in EMO:
        if re.search(pat, t):
            emoji = em
            break
    hl = [e for e in style["emphasis"]["words"] if e in t][:2]
    hl += re.findall(r"\d[\d,.]*\S?", t)[:1]
    return {"lines": [l for l in (l1, l2) if l], "highlight": hl, "emoji": emoji}


def guess_scene(txt, style):
    t = re.sub(r"[,.…]", "", txt).strip()
    m = re.search(r"(\d[\d,.]*)\s*(%|퍼센트|년|원|만원|만|천|억|배|개|명|분|초|일|시간|가지|번|살|kg)?", t)
    if m:
        v = m.group(1).replace(",", "")
        try:
            float(v)
            return {"template": "countup", "value": v, "suffix": m.group(2) or "", "label": short(t.replace(m.group(0), "").strip(), 16)}
        except ValueError:
            pass
    if re.search(r"댓글", t) and re.search(r"DM|디엠|보내", t):
        return {"template": "comment_dm", "comment": None, "dm": short(t, 18)}
    if re.search(r"전에는|예전|원래|바뀌|달라|이제는", t):
        return {"template": "beforeafter", "before": {"title": "전", "items": [None]}, "after": {"title": "후", "items": [short(t, 12)]}}
    if re.search(r"후기|리뷰|사진", t) and list((WORK / "assets" / "reviews").glob("*")):
        imgs = sorted(str(p.relative_to(WORK)) for p in (WORK / "assets" / "reviews").glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
        return {"template": "photos", "images": imgs[:4], "caption": short(t, 14)}
    words = [w for w in style["emphasis"]["words"] if w in t]
    text = short(t, 26)
    for w in words:
        text = text.replace(w, f"**{w}**", 1)
    return {"template": "statement", "text": text}


def strip_punct(t):
    return re.sub(r"[,.…]", "", t).strip()


def short(t, n):
    if len(t) <= n:
        return t
    out = ""
    for e in t.split():
        if len(out) + len(e) + 1 > n:
            break
        out = (out + " " + e).strip()
    return out or t[:n]


def cmd_draft(a):
    jd = job_dir(a.job)
    data = json.loads((jd / "words.json").read_text(encoding="utf-8"))
    plan = make_draft(data, load_style())
    (jd / "plan.draft.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    if a.force or not (jd / "plan.json").exists():
        (jd / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"초안 저장: {jd/'plan.draft.json'}")


# ───────────────────────── 3) 컷 편집 계산 ─────────────────────────
def build_edit(data, plan, style, x):
    words = data["words"]
    C = style["cut"]
    pad, maxp, minp = C["word_pad"], C["max_pause"], C["min_piece"]
    cf = C["crossfade_ms"] / 1000
    delete = set(int(i) for i in plan.get("delete", []))
    ext_end = {int(k): float(v) for k, v in (plan.get("extend_end") or {}).items()}
    ext_start = {int(k): float(v) for k, v in (plan.get("extend_start") or {}).items()}
    dur_src = len(x) / SR
    env = frame_db(x)
    thr = data.get("thr") or speech_threshold(env)[0]

    sents = []
    for si, s in enumerate(plan["sentences"]):
        idx = [i for i in range(int(s["from"]), int(s["to"]) + 1) if i not in delete and 0 <= i < len(words)]
        if idx:
            sents.append(dict(s, idx=idx, si=si))
    if not sents:
        raise SystemExit("남길 단어가 없어요. plan.json 을 확인하세요.")

    # 조각 만들기 (말이 붙어 있으면 한 조각, 멈춤이 길면 끊어서 앞뒤 0.05초만 남김)
    pieces = []
    for sn, s in enumerate(sents):
        run_ = [s["idx"][0]]
        for i in s["idx"][1:]:
            p = run_[-1]
            if i == p + 1 and words[i]["s"] - words[p]["e"] <= maxp:
                run_.append(i)
            else:
                pieces.append({"words": run_, "sent": sn})
                run_ = [i]
        pieces.append({"words": run_, "sent": sn})

    for p in pieces:
        f, l = p["words"][0], p["words"][-1]
        lo = words[f - 1]["e"] + 0.005 if f > 0 else 0.0       # 앞 단어(지운 단어 포함) 침범 금지
        hi = words[l + 1]["s"] - 0.005 if l + 1 < len(words) else dur_src
        s = max(lo, words[f]["s"] - pad - ext_start.get(f, 0))
        e = min(hi, words[l]["e"] + pad + ext_end.get(l, 0))
        # 단어 끝 잘림 방지: 끝부분 소리가 아직 크면 조금 더 늘림
        k = int(e * 100)
        lim = min(int(hi * 100), k + int(C["end_extend_max"] * 100))
        while k < lim and k < len(env) and env[k] >= thr:
            k += 1
        e = max(e, k / 100)
        if e - s < minp:  # 0.12초보다 짧은 조각 금지
            need = minp - (e - s)
            s2 = max(lo, s - need / 2)
            e = min(hi, e + need - (s - s2))
            s = s2
            if e - s < minp:
                s = max(0.0, e - minp)
        p["s"], p["e"] = round(s, 4), round(e, 4)
    # 마지막 말 0.3초 뒤에 끝
    lastw = pieces[-1]["words"][-1]
    pieces[-1]["tail"] = words[lastw]["e"] + C["outro_after_last_word"]
    lim = words[lastw + 1]["s"] - 0.005 if lastw + 1 < len(words) else dur_src
    pieces[-1]["e"] = round(min(max(pieces[-1]["e"], pieces[-1]["tail"]), lim), 4)

    # 겹치는 조각 정리
    for a_, b_ in zip(pieces, pieces[1:]):
        if b_["s"] < a_["e"]:
            mid = (a_["e"] + b_["s"]) / 2
            a_["e"], b_["s"] = mid, mid

    # 문장별 소리 크기 맞추기
    LM = style["level_match"]
    sl = []
    for s in sents:
        segs = [x[int(words[i]["s"] * SR): int(words[i]["e"] * SR)] for i in s["idx"]]
        v = np.concatenate(segs) if segs else np.zeros(1)
        sl.append(float(db(np.sqrt((v ** 2).mean() + 1e-12))))
    target = float(np.median(sl))
    for s, l in zip(sents, sl):
        s["gain_db"] = round(float(np.clip(target - l, -LM["max_cut_db"], LM["max_boost_db"])), 2)
        s["level_db"] = round(l, 1)

    # 출력 시간축
    t = 0.0
    for n, p in enumerate(pieces):
        p["out_s"] = round(t, 4)
        d = p["e"] - p["s"]
        p["dur"] = d
        t += d - (cf if n < len(pieces) - 1 else 0)
    total = t
    lastp = pieces[-1]
    total = max(total, lastp["out_s"] + (lastp["tail"] - lastp["s"]))

    wout = {}
    for p in pieces:
        for i in p["words"]:
            wout[i] = (round(p["out_s"] + words[i]["s"] - p["s"], 4), round(p["out_s"] + words[i]["e"] - p["s"], 4))
    for sn, s in enumerate(sents):
        ps = [p for p in pieces if p["sent"] == sn]
        s["out_s"] = ps[0]["out_s"]
        s["out_e"] = ps[-1]["out_s"] + ps[-1]["dur"]
    return {"sents": sents, "pieces": pieces, "wout": wout, "total": round(total, 4), "delete": sorted(delete)}


def src_time(pieces, t):
    """출력 시각 → 원본 시각."""
    lo, hi = 0, len(pieces) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if pieces[mid]["out_s"] <= t:
            lo = mid
        else:
            hi = mid - 1
    p = pieces[lo]
    return p["s"] + max(0.0, t - p["out_s"])


# ───────────────────────── 화면 구성(레이아웃) ─────────────────────────
def build_spans(ed, plan, style, words):
    sents, total, wout = ed["sents"], ed["total"], ed["wout"]
    bounds = [s["out_s"] for s in sents[1:]] + [total]
    spans = []
    for n, s in enumerate(sents):
        st = 0.0 if n == 0 else s["out_s"]
        en = bounds[n]
        spans.append({"start": round(st, 4), "end": round(en, 4), "layout": s.get("layout", "split"),
                      "role": s.get("role", ""), "sent": n, "scene": s.get("scene"), "text": s.get("text", "")})

    def ratio():
        return sum(x["end"] - x["start"] for x in spans if x["layout"] == "split") / max(total, 1e-6)

    warn = []
    lim = style["layout"]
    # 비율이 모자라면 얼굴 문장의 앞 1.8초만 얼굴로, 뒤는 그래픽으로 (강조 → 댓글유도 → 첫 문장 순)
    order = [x for x in spans if x["layout"] == "face" and x["role"] == "emphasis"] + \
            [x for x in spans if x["layout"] == "face" and x["role"] == "cta"] + \
            [x for x in spans if x["layout"] == "face" and x["role"] == "hook"] + \
            [x for x in spans if x["layout"] == "face" and x["role"] not in ("emphasis", "cta", "hook")]
    for sp in order:
        if ratio() >= lim["split_ratio_min"]:
            break
        s = sents[sp["sent"]]
        cut_at = None
        for i in s["idx"]:
            ws = wout[i][0]
            if ws - sp["start"] >= 1.8:
                cut_at = ws
                break
        if cut_at is None or sp["end"] - cut_at < 0.6:
            if sp["role"] == "emphasis":
                sp["layout"] = "split"
                sp["scene"] = sp["scene"] or {"template": "statement", "text": short(strip_punct(sp["text"]), 26)}
                warn.append(f"그래픽 비율을 맞추려고 강조 문장을 위아래 화면으로 바꿨어요: {sp['text'][:20]}")
            continue
        tail = dict(sp, start=round(cut_at, 4), layout="split", role=sp["role"] + "_tail",
                    scene=sp["scene"] or {"template": "statement", "text": short(strip_punct(sp["text"]), 26)})
        sp["end"] = round(cut_at, 4)
        spans.insert(spans.index(sp) + 1, tail)
        warn.append(f"그래픽 비율을 맞추려고 얼굴 문장의 뒷부분을 그래픽으로 바꿨어요: {sp['text'][:20]}")
    r = ratio()
    if r < lim["split_ratio_min"] - 1e-6:
        warn.append(f"⚠ 모션그래픽 비율 {r*100:.0f}% (기준 {lim['split_ratio_min']*100:.0f}% 이상) — plan.json 의 화면 구성을 고쳐야 해요")
    if r > lim["split_ratio_max"] + 1e-6:
        warn.append(f"⚠ 모션그래픽 비율 {r*100:.0f}% (기준 {lim['split_ratio_max']*100:.0f}% 이하) — 강조 문장을 얼굴 화면으로 바꾸세요")
    # 이어지는 장면(scene == "continue") 합치기
    merged = []
    for sp in spans:
        if merged and sp["layout"] == "split" and merged[-1]["layout"] == "split" and (sp.get("scene") == "continue"):
            merged[-1]["end"] = sp["end"]
            continue
        if sp["layout"] == "split" and (not sp.get("scene") or sp.get("scene") == "continue"):
            sp["scene"] = {"template": "statement", "text": short(strip_punct(sp["text"]), 26)}
        merged.append(sp)
    return merged, r, warn


# ───────────────────────── 자막 ─────────────────────────
JOSA = ["으로부터", "에서부터", "이라고", "라고", "으로", "에서", "에게", "한테", "까지", "부터", "처럼", "보다", "이랑", "하고",
        "이나", "이요", "은", "는", "이", "가", "을", "를", "에", "도", "만", "의", "로", "랑", "요", "야", "죠", "나"]
NUM_RE = re.compile(r"^(\d[\d,.]*(?:%|퍼센트|만원|천원|년|원|만|천|억|배|개|명|분|초|일|시간|가지|번|살|kg|키로|위|등)?)")


def split_highlight(token, keys):
    """강조 키워드 글자만 노란색, 뒤 조사·어미는 흰색. (앞, 키워드, 뒤) 반환"""
    m = NUM_RE.match(token)
    if m:
        return "", m.group(1), token[len(m.group(1)):]
    for k in sorted(keys, key=len, reverse=True):
        if k and token.startswith(k):
            return "", k, token[len(k):]
        if k and len(k) >= 2 and k in token:
            i = token.index(k)
            if i <= 1:
                return token[:i], k, token[i + len(k):]
    return token, "", ""


def subtitle_text(t, style):
    S = style["subtitle"]
    for ch in S["remove_chars"]:
        t = t.replace(ch, "")
    return t.strip()


def build_subs(ed, plan, style, words, spans, face_sub_y):
    S, E = style["subtitle"], style["emphasis"]
    fix = {int(k): v for k, v in (plan.get("fix") or {}).items()}
    keys = list(E["words"]) + list(plan.get("highlight_words") or [])
    if plan.get("cta_keyword"):
        keys.append(plan["cta_keyword"])
    wout = ed["wout"]
    chunks = []
    for n, s in enumerate(ed["sents"]):
        ej = []  # 어절
        for i in s["idx"]:
            raw = fix.get(i, words[i]["w"])
            txt = subtitle_text(raw, style)
            new = raw.startswith(" ") or not ej or i in fix and fix[i].startswith(" ")
            if not txt:
                continue
            if new or not ej:
                ej.append({"t": txt, "s": wout[i][0], "e": wout[i][1], "ids": [i], "end_punct": bool(re.search(r"[.?!,]$", raw.strip()))})
            else:
                ej[-1]["t"] += txt
                ej[-1]["e"] = wout[i][1]
                ej[-1]["ids"].append(i)
                ej[-1]["end_punct"] = bool(re.search(r"[.?!,]$", raw.strip()))
        cur = []
        groups = []
        for k, e in enumerate(ej):
            cand = cur + [e]
            text_len = len(" ".join(x["t"] for x in cand))
            if cur and (text_len > S["max_chars"] or len(cand) > S["max_words"]):
                groups.append(cur)
                cur = [e]
            else:
                cur = cand
            if len(cur) >= S["min_words"] and cur[-1]["end_punct"] and k < len(ej) - 1:
                groups.append(cur)
                cur = []
        if cur:
            if groups and len(cur) == 1 and len(" ".join(x["t"] for x in groups[-1] + cur)) <= S["max_chars"] and len(groups[-1]) < S["max_words"]:
                groups[-1] += cur
            else:
                groups.append(cur)
        for g in groups:
            chunks.append({"sent": n, "ej": g, "s": g[0]["s"], "e": g[-1]["e"]})
    # 시간: 말과 정확히 맞춰 나타나고 다음 덩어리가 시작될 때 바뀜
    for k, c in enumerate(chunks):
        nxt = chunks[k + 1]["s"] if k + 1 < len(chunks) else ed["total"]
        if k + 1 < len(chunks) and chunks[k + 1]["sent"] == c["sent"] and nxt - c["e"] < 0.6:
            c["end"] = nxt
        else:
            c["end"] = min(nxt, c["e"] + 0.25)
        c["start"] = c["s"]
    # 강조 단어 찾기 + 팝(4~6초에 1번)
    cands = []
    for c in chunks:
        for e in c["ej"]:
            pre, kw, post = split_highlight(e["t"], keys)
            e["hl"] = (pre, kw, post) if kw else None
            if kw:
                cands.append((e["s"], c, e))
    pops, last = [], -1e9
    for t, c, e in sorted(cands, key=lambda z: z[0]):
        if t - last >= E["pop_min_gap"]:
            pops.append(t)
            c.setdefault("pop", t)
            last = t
    # 위치
    hl = hex_to_ass_inline(S["highlight_color"])
    wh = hex_to_ass_inline(S["color"])
    events = []
    for c in chunks:
        lay = layout_at(spans, c["start"] + 0.01)
        y = S["y_split"] if lay == "split" else face_sub_y
        parts = []
        for e in c["ej"]:
            if e["hl"]:
                pre, kw, post = e["hl"]
                parts.append(f"{pre}{{\\c{hl}}}{kw}{{\\c{wh}}}{post}")
            else:
                parts.append(e["t"])
        tags = f"\\an5\\pos(540,{y})"
        if "pop" in c:
            t0 = int((c["pop"] - c["start"]) * 1000)
            half = E["pop_ms"] // 2
            sc = E["pop_scale"]
            tags += f"\\t({t0},{t0+half},\\fscx{sc}\\fscy{sc})\\t({t0+half},{t0+2*half},\\fscx100\\fscy100)"
        events.append({"start": c["start"], "end": c["end"], "text": "{" + tags + "}" + " ".join(parts),
                       "plain": " ".join(e["t"] for e in c["ej"]), "y": y, "layout": lay})
    return events, pops


def layout_at(spans, t):
    for sp in spans:
        if sp["start"] <= t < sp["end"]:
            return sp["layout"]
    return spans[-1]["layout"]


def write_ass(path, events, style):
    S = style["subtitle"]
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {style['video']['width']}
PlayResY: {style['video']['height']}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{S['font']},{S['font_size']},{hex_to_ass(S['color'])},&H000000FF&,&H00000000&,&H80000000&,0,0,0,0,100,100,0,0,1,{S['outline']},{S['shadow']},5,30,30,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [f"Dialogue: 0,{ass_time(e['start'])},{ass_time(e['end'])},Sub,,0,0,0,,{e['text']}" for e in events]
    Path(path).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


# ───────────────────────── 얼굴 위치 ─────────────────────────
def face_track(src, cw, ch, duration, step=0.5):
    import cv2
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    sw = 360
    sh = int(round(ch * sw / cw))
    cmd = ["ffmpeg", "-loglevel", "error", "-i", str(src), "-vf", f"fps={1/step},scale={sw}:{sh}", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    pts = []
    k = 0
    while True:
        buf = p.stdout.read(sw * sh)
        if len(buf) < sw * sh:
            break
        img = np.frombuffer(buf, np.uint8).reshape(sh, sw)
        faces = casc.detectMultiScale(img, 1.1, 5, minSize=(sw // 10, sw // 10))
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            sc = cw / sw
            pts.append((k * step, (x + w / 2) * sc, (y + h / 2) * sc, w * sc, h * sc))
        k += 1
    p.wait()
    if not pts:
        return None
    a = np.array(pts)
    # 튀는 값 정리(중앙값 필터)
    for c in (1, 2, 3, 4):
        v = a[:, c].copy()
        for i in range(len(v)):
            a[i, c] = np.median(v[max(0, i - 3): i + 4])
    return a


def face_at(track, t, cw, ch):
    if track is None:
        return cw / 2, ch * 0.40, cw * 0.30, cw * 0.30
    ts = track[:, 0]
    return tuple(float(np.interp(t, ts, track[:, c])) for c in (1, 2, 3, 4))


# ───────────────────────── 효과음·배경음 만들기 ─────────────────────────
def synth_sfx():
    rng = np.random.default_rng(7)
    from scipy.signal import butter, sosfilt
    out = {}
    # 휙
    n = int(0.42 * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    sig = np.zeros(n)
    for k in range(0, n, 1024):
        f = 300 + 4200 * math.sin(math.pi * min(1, k / n)) ** 1.5
        sos = butter(2, [max(80, f * 0.6), min(SR / 2 - 100, f * 1.4)], btype="band", fs=SR, output="sos")
        sig[k:k + 1024] = sosfilt(sos, noise[max(0, k - 2048):k + 1024])[-len(sig[k:k + 1024]):]
    env = np.sin(np.pi * t / t[-1]) ** 2
    out["whoosh"] = sig * env
    # 팝
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    f = 650 * np.exp(-t * 18) + 220
    ph = 2 * np.pi * np.cumsum(f) / SR
    out["pop"] = np.sin(ph) * np.exp(-t * 38) + 0.3 * rng.standard_normal(n) * np.exp(-t * 300)
    # 딩
    n = int(1.3 * SR)
    t = np.arange(n) / SR
    ding = sum(a * np.sin(2 * np.pi * fr * t) * np.exp(-t * d) for fr, a, d in [(1318.5, 1, 3.2), (2637, 0.45, 5), (3955, 0.2, 7), (1975.5, 0.25, 4)])
    out["ding"] = ding * np.minimum(1, t / 0.004)
    for k in out:
        out[k] = (out[k] / np.max(np.abs(out[k]))).astype(np.float32)
    return out


def synth_bgm(length):
    """잔잔한 로파이 비트 (직접 생성, 저작권 없음)."""
    rng = np.random.default_rng(11)
    bpm = 88
    beat = 60 / bpm
    n = int((length + 1) * SR)
    t = np.arange(n) / SR
    y = np.zeros(n)
    chords = [[57, 60, 64, 67], [53, 57, 60, 64], [48, 52, 55, 59], [55, 59, 62, 65]]  # Am7 Fmaj7 Cmaj7 G7
    bar = beat * 4
    from scipy.signal import butter, sosfilt
    for b in range(int(length / bar) + 2):
        ch = chords[b % 4]
        s0 = int(b * bar * SR)
        s1 = min(n, int((b + 1) * bar * SR) + int(0.3 * SR))
        if s0 >= n:
            break
        tt = np.arange(s1 - s0) / SR
        env = np.minimum(1, tt / 0.6) * np.exp(-tt * 0.35)
        pad = sum(np.sin(2 * np.pi * 440 * 2 ** ((m - 69) / 12) * tt + 0.3 * np.sin(2 * np.pi * 0.4 * tt)) for m in ch) / 4
        y[s0:s1] += 0.22 * pad * env
        bass = np.sin(2 * np.pi * 440 * 2 ** ((ch[0] - 24 - 69) / 12) * tt) * np.exp(-tt * 1.2)
        y[s0:s1] += 0.25 * bass
    for k in range(int(length / beat) + 2):
        s0 = int(k * beat * SR)
        if s0 >= n:
            break
        if k % 2 == 0:  # 킥
            m = min(n - s0, int(0.35 * SR))
            tt = np.arange(m) / SR
            y[s0:s0 + m] += 0.5 * np.sin(2 * np.pi * (50 + 80 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 9)
        else:  # 스네어(부드럽게)
            m = min(n - s0, int(0.2 * SR))
            tt = np.arange(m) / SR
            y[s0:s0 + m] += 0.12 * rng.standard_normal(m) * np.exp(-tt * 22)
        for h in (0, 0.5):  # 하이햇
            s1 = int((k + h) * beat * SR)
            m = min(n - s1, int(0.05 * SR))
            if m > 0:
                tt = np.arange(m) / SR
                y[s1:s1 + m] += 0.05 * rng.standard_normal(m) * np.exp(-tt * 90)
    sos = butter(4, 5000, btype="low", fs=SR, output="sos")
    y = sosfilt(sos, y)
    return (y / (np.max(np.abs(y)) + 1e-9) * 0.5)[: int(length * SR)].astype(np.float32)


def load_bgm(length):
    bdir = WORK / "bgm"
    files = sorted(p for p in bdir.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}) if bdir.exists() else []
    if files:
        tmp = JOBS / "_bgm_cache.wav"
        tmp.parent.mkdir(exist_ok=True)
        extract_audio(files[0], tmp)
        y, _ = read_wav(tmp)
        if len(y) < length * SR:
            y = np.tile(y, int(length * SR / max(1, len(y))) + 1)
        return y[: int(length * SR)], files[0].name
    return synth_bgm(length), "직접 만든 잔잔한 비트"


def lufs(x):
    import pyloudnorm as pyln
    if len(x) < SR * 0.5:
        x = np.pad(x, (0, int(SR * 0.5) - len(x)))
    return pyln.Meter(SR).integrated_loudness(x.astype(np.float64))


def limiter(x, peak_db):
    from scipy.ndimage import minimum_filter1d, uniform_filter1d
    thr = 10 ** (peak_db / 20)
    g = np.minimum(1.0, thr / np.maximum(np.abs(x), 1e-9))
    w = int(0.006 * SR)
    g = minimum_filter1d(g, size=2 * w + 1)
    g = uniform_filter1d(g, size=w)
    y = x * g
    return np.clip(y, -thr, thr)


# ───────────────────────── 4) 렌더 ─────────────────────────
def assemble_voice(x, ed, style):
    cf = int(style["cut"]["crossfade_ms"] / 1000 * SR)
    total = int(math.ceil(ed["total"] * SR)) + cf
    out = np.zeros(total, np.float32)
    joints = []
    for n, p in enumerate(ed["pieces"]):
        g = 10 ** (ed["sents"][p["sent"]]["gain_db"] / 20)
        seg = x[int(p["s"] * SR): int(p["e"] * SR)].astype(np.float32) * g
        L = len(seg)
        if L == 0:
            continue
        k = min(cf, L // 2)
        fin = np.sin(np.linspace(0, np.pi / 2, k)) ** 2 if k else None
        if n > 0 and k:
            seg[:k] *= fin
        else:
            k0 = min(int(0.005 * SR), L)
            seg[:k0] *= np.linspace(0, 1, k0)
        if n < len(ed["pieces"]) - 1 and k:
            seg[-k:] *= fin[::-1]
        else:
            k1 = min(int(0.03 * SR), L)
            seg[-k1:] *= np.linspace(1, 0, k1)
        o = int(round(p["out_s"] * SR))
        e = min(total, o + L)
        out[o:e] += seg[: e - o]
        if n:
            joints.append(p["out_s"])
    return out[: int(math.ceil(ed["total"] * SR))], joints


def place_sfx(ed, spans, pops, style):
    lead, gap = style["sfx"]["lead"], style["sfx"]["min_gap"]
    ev = []
    wout = ed["wout"]
    prev = None
    for sp in spans:
        # 장면/주제 전환 → 휙
        if prev is not None and (sp["layout"] != prev["layout"] or sp["layout"] == "split"):
            ev.append({"t": first_word_at(ed, sp["start"]) - lead, "kind": "whoosh", "pri": 1})
        if sp["role"] == "cta":
            ev.append({"t": first_word_at(ed, sp["start"]) - lead, "kind": "ding", "pri": 3})
        prev = sp
    for t in pops:
        ev.append({"t": t - lead, "kind": "pop", "pri": 2})
    ev = [e for e in ev if e["t"] >= 0.2]
    keep = []
    for e in sorted(ev, key=lambda e: -e["pri"]):
        if all(abs(e["t"] - k["t"]) >= gap for k in keep):
            keep.append(e)
    return sorted(keep, key=lambda e: e["t"])


def first_word_at(ed, t):
    cand = [s for s, _ in ed["wout"].values() if s >= t - 1e-3]
    return min(cand) if cand else t


def mix_audio(voice, ed, sfx_events, style, jd):
    total = len(voice)
    vpk = np.percentile(np.abs(voice), 99.9) + 1e-6
    sfx = synth_sfx()
    sfx_track = np.zeros(total, np.float32)
    g = vpk * 10 ** (style["sfx"]["gain_db"] / 20)
    for e in sfx_events:
        s = sfx[e["kind"]]
        o = int(e["t"] * SR)
        if e["kind"] == "whoosh":
            o -= int(0.25 * SR)  # 휙의 가장 큰 곳이 단어 직전에 오도록
        a, b = max(0, o), min(total, o + len(s))
        if b > a:
            sfx_track[a:b] += s[a - o: b - o] * g * (0.8 if e["kind"] == "whoosh" else 1.0)
    B = style["bgm"]
    bgm, bgm_name = load_bgm(total / SR)
    bgm = bgm[:total]
    if len(bgm) < total:
        bgm = np.pad(bgm, (0, total - len(bgm)))
    lv = lufs(voice) if np.any(voice) else -30
    lb = lufs(bgm)
    if np.isfinite(lb) and np.isfinite(lv):
        bgm = bgm * 10 ** ((lv - B["below_voice_db"] - lb) / 20)
    # 말할 때 더 줄이기
    act = np.zeros(total, np.float32)
    for s, e in ed["wout"].values():
        act[max(0, int((s - 0.08) * SR)): min(total, int((e + 0.12) * SR))] = 1
    from scipy.ndimage import uniform_filter1d
    act = uniform_filter1d(act, size=int(0.15 * SR))
    bgm = bgm * 10 ** (-B["duck_db"] * act / 20)
    fi, fo = int(B["fade_in"] * SR), int(B["fade_out"] * SR)
    bgm[:fi] *= np.linspace(0, 1, fi)
    bgm[-fo:] *= np.linspace(1, 0, fo)
    mix = voice + sfx_track + bgm
    L = style["loudness"]
    lm = lufs(mix)
    if np.isfinite(lm):
        mix = mix * 10 ** ((L["target_lufs"] - lm) / 20)
    mix = limiter(mix, L["peak_dbfs"])
    write_wav(jd / "voice.wav", voice)
    write_wav(jd / "mix.wav", np.stack([mix, mix], axis=1))
    return bgm_name, lufs(mix)


class FrameReader:
    def __init__(self, src, cw, ch, fps):
        self.cw, self.ch = cw, ch
        self.size = cw * ch * 3
        self.p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", str(src), "-vf", f"fps={fps},scale={cw}:{ch}:flags=lanczos",
                                   "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, bufsize=self.size * 2)
        self.idx = -1
        self.frame = np.zeros((ch, cw, 3), np.uint8)

    def get(self, k):
        while self.idx < k:
            buf = self.p.stdout.read(self.size)
            if len(buf) < self.size:
                self.idx = k  # 끝: 마지막 프레임 유지
                break
            self.frame = np.frombuffer(buf, np.uint8).reshape(self.ch, self.cw, 3)
            self.idx += 1
        return self.frame

    def close(self):
        self.p.kill()


def crop_resize(img, cx, cy, w, h, ow, oh):
    import cv2
    H, W = img.shape[:2]
    w, h = min(w, W), min(h, H)
    x0 = int(round(min(max(cx - w / 2, 0), W - w)))
    y0 = int(round(min(max(cy - h / 2, 0), H - h)))
    crop = img[y0:y0 + int(round(h)), x0:x0 + int(round(w))]
    return cv2.resize(crop, (ow, oh), interpolation=cv2.INTER_LINEAR if w < ow else cv2.INTER_AREA)


def zoom_at(t, ed, pops, style):
    Z, E = style["zoom"], style["emphasis"]
    ps = ed["pieces"]
    lo = 0
    for i, p in enumerate(ps):
        if p["out_s"] <= t:
            lo = i
    p = ps[lo]
    prog = min(1.0, max(0.0, (t - p["out_s"]) / max(p["dur"], 1e-3)))
    z = Z["cut_from"] + (Z["cut_to"] - Z["cut_from"]) * prog
    for tp in pops:
        d = t - (tp - 0.04)
        if 0 <= d <= E["zoom_hold"] + 0.25:
            if d < 0.08:
                k = d / 0.08
            elif d < E["zoom_hold"]:
                k = 1
            else:
                k = 1 - (d - E["zoom_hold"]) / 0.25
            z = max(z, 1 + (E["zoom"] - 1) * (0.5 - 0.5 * math.cos(math.pi * max(0, min(1, k)))))
    return z


def cmd_render(a):
    import cv2
    jd = job_dir(a.job)
    style = load_style()
    data = json.loads((jd / "words.json").read_text(encoding="utf-8"))
    plan = json.loads((jd / "plan.json").read_text(encoding="utf-8"))
    words = data["words"]
    V, LY, T = style["video"], style["layout"], style["title"]
    W, H, FPS = V["width"], V["height"], V["fps"]
    src = Path(data["source"])
    log("③ 컷 편집 계산")
    x, _ = read_wav(jd / "audio48.wav")
    ed = build_edit(data, plan, style, x)
    spans, ratio, warns = build_spans(ed, plan, style, words)
    for w in warns:
        log("   " + w)
    vi = video_info(src)
    c = max(W / vi["w"], H / vi["h"])
    cw, ch = int(round(vi["w"] * c / 2) * 2), int(round(vi["h"] * c / 2) * 2)
    log("   얼굴 위치 찾는 중")
    track = face_track(src, cw, ch, vi["duration"])
    if track is None:
        log("   (얼굴을 못 찾아서 화면 가운데 기준으로 확대해요)")
    # 얼굴 화면 자막 위치: 턱 아래
    if track is not None:
        fy, fh = float(np.median(track[:, 2])), float(np.median(track[:, 4]))
        top = min(max(fy - 0.38 * H, 0), ch - H)
        face_bottom = (fy + fh * 0.62) - top
    else:
        face_bottom = H * 0.55
    S = style["subtitle"]
    face_sub_y = int(min(1640, max(S["y_face"], face_bottom + S["face_margin"] + S["font_size"] * 0.7)))
    log("④ 자막·강조·제목·그래픽 준비")
    events, pops = build_subs(ed, plan, style, words, spans, face_sub_y)
    write_ass(jd / "subs.ass", events, style)
    sfx_events = place_sfx(ed, spans, pops, style)

    # 그래픽 작업 목록
    gdir = jd / "graphics"
    if gdir.exists():
        shutil.rmtree(gdir)
    gdir.mkdir()
    jobs = []
    colors = {k: style["graphics"][k] for k in ("bg", "card", "accent", "good", "bad", "text", "muted")}
    colors["border"] = style["graphics"]["card_border"]
    for k, sp in enumerate(spans):
        if sp["layout"] != "split":
            continue
        dur = sp["end"] - sp["start"]
        scene = dict(sp["scene"])
        if scene.get("cue_words"):
            scene["cues"] = [round(ed["wout"][int(i)][0] - sp["start"], 3) for i in scene["cue_words"] if int(i) in ed["wout"]]
        sp["gdir"] = str(gdir / f"scene_{k:02d}")
        jobs.append({"kind": "scene", "data": scene, "duration": dur + 0.1, "fps": FPS, "out_dir": sp["gdir"],
                     "width": W, "height": LY["graphic_h"], "content_h": LY["graphic_content_h"], "colors": colors})
    hook = plan.get("hook") or {}
    titles = {}
    if hook.get("lines"):
        titles["hook"] = str(gdir / "title_hook.png")
        jobs.append({"kind": "title", "out_png": titles["hook"], "width": W, "height": 560,
                     "data": {"template": "title", "lines": hook["lines"], "highlight": hook.get("highlight", []), "emoji": hook.get("emoji", ""),
                              "font_size": T["font_size"], "highlight_color": T["highlight_color"]}})
    if any(sp["role"] == "cta" for sp in spans):
        kw = plan.get("cta_keyword") or "?"
        lines = [l.replace("{keyword}", kw) for l in T["cta_template"]]
        titles["cta"] = str(gdir / "title_cta.png")
        jobs.append({"kind": "title", "out_png": titles["cta"], "width": W, "height": 560,
                     "data": {"template": "title", "lines": lines, "highlight": [f"'{kw}'", "팔로우"], "emoji": T.get("cta_emoji", ""),
                              "font_size": T["font_size"], "highlight_color": T["highlight_color"]}})
    (jd / "graphics_jobs.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"   모션그래픽 {sum(1 for j in jobs if j['kind']=='scene')}장면 렌더링 (브라우저)")
    r = subprocess.run(["node", str(ENGINE / "render_scenes.js"), str(jd / "graphics_jobs.json"), str(WORK)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("그래픽 렌더 실패:\n" + r.stderr[-3000:])
    title_img = {k: cv2.imread(v, cv2.IMREAD_UNCHANGED) for k, v in titles.items()}
    cta_start = min((sp["start"] for sp in spans if sp["role"] == "cta"), default=None)
    hook_end = spans[0]["end"] if spans and spans[0]["layout"] == "face" else 0

    log("   소리 편집(크로스페이드·음량 맞춤·효과음·배경음)")
    voice, joints = assemble_voice(x, ed, style)
    bgm_name, out_lufs = mix_audio(voice, ed, sfx_events, style, jd)

    OUTPUT.mkdir(exist_ok=True)
    out = OUTPUT / f"{data['name']}_edited.mp4"
    nframes = int(math.ceil(ed["total"] * FPS))
    log(f"⑤ 영상 합성 + 최종 저장 ({nframes}프레임, 마지막에 한 번만 고화질 압축)")
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            "-i", str(jd / "mix.wav"),
                            "-vf", f"ass={jd/'subs.ass'}:fontsdir={FONTS}",
                            "-c:v", "libx264", "-preset", V["preset"], "-crf", str(V["crf"]), "-pix_fmt", "yuv420p", "-r", str(FPS),
                            "-c:a", "aac", "-b:a", V["audio_bitrate"], "-ar", str(SR), "-movflags", "+faststart", "-shortest", str(out)],
                           stdin=subprocess.PIPE)
    reader = FrameReader(src, cw, ch, FPS)
    fh_area = LY["face_h"]
    gh = LY["graphic_h"]
    split_zoom = 1.0
    if track is not None:
        split_zoom = float(np.clip(0.42 * fh_area / max(1, np.median(track[:, 4])), 1.0, 2.2))
    canvas = np.zeros((H, W, 3), np.uint8)
    gcache = {}
    span_i = 0
    for f in range(nframes):
        t = f / FPS
        while span_i < len(spans) - 1 and t >= spans[span_i]["end"]:
            span_i += 1
        sp = spans[span_i]
        st = src_time(ed["pieces"], t)
        img = reader.get(int(round(st * FPS)))
        fx, fy, fw, fhh = face_at(track, st, cw, ch)
        z = zoom_at(t, ed, pops, style)
        if sp["layout"] == "face":
            w_, h_ = W / z, H / z
            cy = fy - 0.38 * h_ + h_ / 2
            canvas[:] = crop_resize(img, fx, cy, w_, h_, W, H)
            show = None
            if t < hook_end and "hook" in title_img:
                show = title_img["hook"]
            if cta_start is not None and t >= cta_start and "cta" in title_img:
                show = title_img["cta"]
            if show is not None:
                y0 = T["y"]
                hh = min(show.shape[0], H - y0)
                al = show[:hh, :, 3:4].astype(np.float32) / 255
                roi = canvas[y0:y0 + hh]
                roi[:] = (roi * (1 - al) + show[:hh, :, :3] * al).astype(np.uint8)
        else:
            gi = int((t - sp["start"]) * FPS)
            gp = Path(sp["gdir"]) / f"{gi:05d}.png"
            if not gp.exists():
                files = sorted(Path(sp["gdir"]).glob("*.png"))
                gp = files[-1]
            key = str(gp)
            g = gcache.get(key)
            if g is None:
                g = cv2.imread(key, cv2.IMREAD_COLOR)
                gcache.clear()
                gcache[key] = g
            canvas[:gh] = g[:gh]
            zz = z * split_zoom
            w_, h_ = W / zz, fh_area / zz
            cy = fy - 0.10 * h_
            canvas[gh:] = crop_resize(img, fx, cy, w_, h_, W, fh_area)
        enc.stdin.write(canvas.tobytes())
        if f % (FPS * 5) == 0:
            log(f"   {t:5.1f}/{ed['total']:.1f}초")
    enc.stdin.close()
    enc.wait()
    reader.close()
    if enc.returncode != 0:
        raise RuntimeError("최종 저장 실패")
    tl = {"name": data["name"], "output": str(out), "orig_duration": data["duration"], "total": ed["total"],
          "deleted_words": len(ed["delete"]), "pieces": ed["pieces"], "joints": joints,
          "sents": [{k: v for k, v in s.items()} for s in ed["sents"]],
          "spans": spans, "split_ratio": ratio, "subs": events, "pops": pops, "sfx": sfx_events,
          "face_sub_y": face_sub_y, "face_bottom": face_bottom, "bgm": bgm_name, "lufs": out_lufs,
          "words_out": {str(k): v for k, v in ed["wout"].items()}, "warnings": warns}
    (jd / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"완성: {out}")
    log(f"   원본 {data['duration']:.1f}초 → 완성 {ed['total']:.1f}초 / 지운 단어 {len(ed['delete'])}개 / 모션그래픽 {ratio*100:.0f}% / 음량 {out_lufs:.1f} LUFS / 배경음: {bgm_name}")
    log(f"OUTPUT={out}")


# ───────────────────────── 5) 검수 ─────────────────────────
def norm_text(t):
    return re.sub(r"[^\w가-힣]", "", t)


def cmd_check(a):
    jd = job_dir(a.job)
    style = load_style()
    tl = json.loads((jd / "timeline.json").read_text(encoding="utf-8"))
    out = Path(tl["output"])
    issues, notes = [], []
    # (1) 다시 받아쓰기 → 자막 비교
    if not a.no_asr:
        try:
            extract_audio(out, jd / "final16.wav", 16000)
            model = load_whisper()
            fw = whisper_words(model, jd / "final16.wav")
            heard = "".join(w["w"] for w in fw)
            subs = " ".join(e["plain"] for e in tl["subs"])
            A, B = norm_text(subs), norm_text(heard)
            sm = difflib.SequenceMatcher(None, A, B, autojunk=False)
            notes.append(f"자막↔완성본 받아쓰기 일치율 {sm.ratio()*100:.1f}%")
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op != "equal" and (i2 - i1 > 0 or j2 - j1 > 1):
                    issues.append({"type": "자막 비교", "subtitle": A[max(0, i1-4):i2+4], "heard": B[max(0, j1-4):j2+4],
                                   "detail": f"자막 '{A[i1:i2]}' ↔ 들린 말 '{B[j1:j2]}'"})
        except Exception as e:  # noqa: BLE001
            notes.append(f"다시 받아쓰기는 건너뜀: {str(e).splitlines()[0]}")
    # (2) 소리: 경계 클릭, 단어 끝 잘림, 말 중간 긴 무음
    v, _ = read_wav(jd / "voice.wav")
    data = json.loads((jd / "words.json").read_text(encoding="utf-8"))
    thr = data["thr"]
    d = np.abs(np.diff(v))
    base = np.median(d) + 1e-6
    for j in tl["joints"]:
        k = int(j * SR)
        w = d[max(0, k - 240): k + 720]
        loc = np.median(d[max(0, k - 4800): k + 4800]) + base
        if len(w) and w.max() > 25 * loc and w.max() > 0.05:
            issues.append({"type": "경계 클릭음", "t": round(j, 2), "detail": f"{j:.2f}초 이음매에서 튀는 소리"})
    env = frame_db(v)
    for p in tl["pieces"][:-1]:
        e_out = p["out_s"] + p["dur"] - style["cut"]["crossfade_ms"] / 1000
        k = int(e_out * 100) - 2
        if 0 <= k < len(env) and env[k] > thr + 6:
            issues.append({"type": "단어 끝 잘림 의심", "t": round(e_out, 2), "word": p["words"][-1],
                           "detail": f"{e_out:.2f}초 조각 끝에 소리가 아직 큼 (단어 #{p['words'][-1]})"})
    ws = sorted(tuple(x) for x in tl["words_out"].values())
    for (s1, e1), (s2, e2) in zip(ws, ws[1:]):
        if s2 - e1 > 0.35:
            issues.append({"type": "말 중간 긴 무음", "t": round(e1, 2), "detail": f"{e1:.2f}~{s2:.2f}초 ({s2-e1:.2f}초)"})
    # (3) 화면: 검은 화면, 멈춘 화면
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out), "-vf", "blackdetect=d=0.1:pix_th=0.06,freezedetect=n=-60dB:d=1.5", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr):
        issues.append({"type": "검은 화면", "t": float(m.group(1)), "detail": f"{m.group(1)}~{m.group(2)}초"})
    for m in re.finditer(r"freeze_start: ([\d.]+)", r.stderr):
        issues.append({"type": "멈춘 화면", "t": float(m.group(1)), "detail": f"{m.group(1)}초부터 화면이 1.5초 이상 그대로"})
    # (4) 겹침 검사 (자막 위치 vs 얼굴·제목·그래픽)
    S, LY, T = style["subtitle"], style["layout"], style["title"]
    half = S["font_size"] * 0.65 + S["outline"]
    for e in tl["subs"]:
        top, bot = e["y"] - half, e["y"] + half
        if e["layout"] == "split":
            if top < LY["graphic_content_h"] or bot > LY["graphic_h"]:
                issues.append({"type": "자막 겹침", "t": e["start"], "detail": "자막이 그래픽/얼굴 칸을 침범"})
        else:
            if top < tl["face_bottom"]:
                issues.append({"type": "자막 겹침", "t": e["start"], "detail": "자막이 얼굴에 걸칠 수 있음"})
            if top < T["y"] + 420:
                issues.append({"type": "자막 겹침", "t": e["start"], "detail": "자막이 제목에 걸칠 수 있음"})
        if len(e["plain"]) > S["max_chars"]:
            issues.append({"type": "자막 길이", "t": e["start"], "detail": f"'{e['plain']}' {len(e['plain'])}자 > {S['max_chars']}자"})
    ratio = tl["split_ratio"]
    if ratio < LY["split_ratio_min"] - 1e-6:
        issues.append({"type": "모션그래픽 부족", "detail": f"{ratio*100:.0f}% < {LY['split_ratio_min']*100:.0f}%"})
    # (5) 프레임 모아보기
    n = max(12, min(40, int(tl["total"] / 1.0)))
    cols = 8 if n > 24 else 6
    rows = math.ceil(n / cols)
    step = tl["total"] / n
    sheet = jd / "contact.jpg"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-vf",
         f"fps=1/{step:.4f},scale=270:480,drawtext=fontfile={FONTS/'Pretendard-Bold.otf'}:text='%{{pts\\:hms}}':x=6:y=6:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6,tile={cols}x{rows}:padding=4:color=0x222222",
         "-frames:v", "1", "-q:v", "3", str(sheet)])
    vi = video_info(out)
    rep = {"output": str(out), "orig": tl["orig_duration"], "final": vi["duration"], "deleted_words": tl["deleted_words"],
           "split_ratio": ratio, "lufs": tl["lufs"], "issues": issues, "notes": notes, "contact": str(sheet)}
    (jd / "check.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    log("⑥ 검수 결과")
    log(f"   원본 {tl['orig_duration']:.1f}초 → 완성 {vi['duration']:.1f}초, 지운 단어 {tl['deleted_words']}개, 모션그래픽 {ratio*100:.0f}%, {tl['lufs']:.1f} LUFS")
    for nn in notes:
        log("   · " + nn)
    if not issues:
        log("   문제 없음")
    for i in issues:
        log(f"   ✗ [{i['type']}] {i['detail']}")
    log(f"   프레임 모아보기: {sheet}")
    if a.autofix:
        plan_p = jd / "plan.json"
        plan = json.loads(plan_p.read_text(encoding="utf-8"))
        ch = 0
        for i in issues:
            if i["type"] == "단어 끝 잘림 의심":
                k = str(i["word"])
                plan.setdefault("extend_end", {})
                plan["extend_end"][k] = round(min(0.15, float(plan["extend_end"].get(k, 0)) + 0.05), 3)
                ch += 1
        if ch:
            plan_p.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"   자동 수정: 단어 끝 {ch}곳 늘림 → 다시 render 하세요")


# ───────────────────────── 기타 ─────────────────────────
def cmd_find(a):
    vids = [p for p in sorted(WORK.rglob("*")) if p.suffix.lower() in VIDEO_EXT and not any(
        part in {"jobs", "output", "refs", ".venv", "node_modules", "models", ".git"} for part in p.relative_to(WORK).parts)]
    for v in vids:
        log(str(v))
    if not vids:
        log("NO_VIDEO")


def set_path(d, path, value):
    ks = path.split(".")
    for k in ks[:-1]:
        d = d.setdefault(k, {})
    try:
        value = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        pass
    old = d.get(ks[-1])
    d[ks[-1]] = value
    return old


def cmd_feedback(a):
    style = load_style()
    changes = []
    for s in a.set or []:
        k, v = s.split("=", 1)
        old = set_path(style, k, v)
        changes.append(f"{k}: {json.dumps(old, ensure_ascii=False)} → {v}")
    today = dt.date.today().isoformat()
    style.setdefault("feedback_log", []).append({"date": today, "note": a.note, "rule": a.rule, "changes": changes})
    STYLE_PATH.write_text(json.dumps(style, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = RULEBOOK.read_text(encoding="utf-8")
    if a.rule:
        md = md.replace("## 피드백으로 추가된 규칙\n(아직 없음)\n", "## 피드백으로 추가된 규칙\n")
        md = md.replace("\n## 피드백 기록", f"- {a.rule} ({today})\n\n## 피드백 기록", 1) if "## 피드백 기록" in md else md
        md = md.replace("\n\n\n## 피드백 기록", "\n\n## 피드백 기록")
    row = f"| {today} | {a.note} | {a.rule or ''} | {'; '.join(changes)} |"
    md = md.rstrip("\n") + "\n" + row + "\n"
    RULEBOOK.write_text(md, encoding="utf-8")
    log("피드백 반영 완료")
    for c in changes:
        log("   " + c)


def cmd_ref(a):
    rd = WORK / "refs" / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    rd.mkdir(parents=True)
    ytdlp = WORK / ".venv" / "bin" / "yt-dlp"
    run([str(ytdlp) if ytdlp.exists() else "yt-dlp", "-o", str(rd / "ref.%(ext)s"), "-f", "mp4/best", a.url])
    vid = next(rd.glob("ref.*"))
    info = video_info(vid)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(vid), "-vf", "select='gt(scene,0.3)',showinfo", "-an", "-f", "null", "-"], capture_output=True, text=True)
    cuts = [float(m.group(1)) for m in re.finditer(r"pts_time:([\d.]+)", r.stderr)]
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(vid), "-vf", "fps=2,scale=216:384,tile=6x5:padding=3", "-frames:v", "1", str(rd / "contact_first15s.jpg")])
    n = max(12, int(info["duration"] / 2))
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(vid), "-vf", f"fps=1/{info['duration']/n:.3f},scale=216:384,tile=8x{math.ceil(n/8)}:padding=3", "-frames:v", "1", str(rd / "contact_all.jpg")])
    extract_audio(vid, rd / "a48.wav")
    y, _ = read_wav(rd / "a48.wav")
    rep = {"url": a.url, "file": str(vid), "duration": info["duration"], "size": [info["w"], info["h"]],
           "scene_cuts": len(cuts), "cuts_per_10s": round(len(cuts) / info["duration"] * 10, 2), "cut_times": cuts[:80], "lufs": lufs(y)}
    try:
        extract_audio(vid, rd / "a16.wav", 16000)
        fw = whisper_words(load_whisper(), rd / "a16.wav")
        rep["words_per_sec"] = round(len(fw) / max(1, info["duration"]), 2)
        rep["transcript"] = "".join(w["w"] for w in fw)
    except Exception as e:  # noqa: BLE001
        rep["transcript_error"] = str(e).splitlines()[0]
    (rd / "ref_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    log(json.dumps({k: v for k, v in rep.items() if k != "cut_times"}, ensure_ascii=False, indent=1))
    log(f"REF={rd}")


def cmd_selftest(a):
    """받아쓰기 없이 나머지 전체를 점검하는 합성 시험 (가짜 말소리 + 가짜 받아쓰기)."""
    name = "selftest"
    jd = JOBS / name
    if jd.exists():
        shutil.rmtree(jd)
    jd.mkdir(parents=True)
    script = [("오늘은 진짜 쉬운 김치 꿀팁 알려드릴게요.", 1.0), ("음", 0.0), ("53년 주부 엄마가 감동했어요.", 0.0),
              ("그 그 비결은 딱 세 가지예요.", 0.0), ("간이 딱 맞고 아삭하고 전부 무료 배송이에요.", 0.0),
              ("전에는 사 먹으면 너무 짰는데 이제는 달라요.", 0.0), ("후기 사진도 이렇게 쏟아져요.", 0.0),
              ("근데 진짜 중요한 건 이거예요.", 0.0), ("받고 싶으면 댓글에 '김치'라고 남겨 주세요.", 0.0)]
    rng = np.random.default_rng(3)
    t = 0.6
    words, audio = [], []
    total = 40.0
    y = 0.003 * rng.standard_normal(int(total * SR)).astype(np.float32)
    for k, (s, _) in enumerate(script):
        quiet = 1.0
        for tok in s.split():
            d = 0.18 + 0.075 * len(re.sub(r"[^가-힣\d]", "", tok))
            n = int(d * SR)
            tt = np.arange(n) / SR
            f0 = 170 + 30 * rng.random()
            sig = sum(np.sin(2 * np.pi * f0 * h * tt) / h for h in range(1, 6)) * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * tt))
            sig *= np.clip(np.sin(np.pi * tt / tt[-1]), 0, 1) ** 0.5 * 0.25 * quiet
            y[int(t * SR): int(t * SR) + n] += sig
            words.append({"w": " " + tok, "s0": round(t - 0.12, 3), "e0": round(t + d, 3), "p": 0.95, "seg": k})
            t += d + 0.06
        t += 0.75 if k != 1 else 0.3
    y = y[: int((t + 0.8) * SR)]
    write_wav(jd / "audio48.wav", y)
    dur = len(y) / SR
    # 가짜 얼굴 영상 (원 하나가 얼굴 역할)
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=1080x1920:r=30:d={dur:.2f}", "-i", str(jd / "audio48.wav"),
         "-vf", "drawbox=x=340:y=520:w=400:h=480:color=0xE0B090@1:t=fill,drawtext=fontfile=" + str(FONTS / "Pretendard-Bold.otf") + ":text='%{pts\\:hms}':x=40:y=1700:fontsize=60:fontcolor=white",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-c:a", "aac", "-shortest", str(jd / "source.mp4")])
    words, thr, floor = refine_words(words, y)
    for i, w in enumerate(words):
        w["i"] = i
    data = {"name": name, "source": str(jd / "source.mp4"), "original": "synthetic", "duration": dur, "video": video_info(jd / "source.mp4"),
            "thr": thr, "floor": floor, "words": words}
    (jd / "words.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    write_words_md(jd / "words.md", words, data)
    plan = make_draft(data, load_style())
    (jd / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"JOB={jd}")


def main():
    ap = argparse.ArgumentParser(description="릴스 자동 편집")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("transcribe"); p.add_argument("video"); p.add_argument("--name"); p.add_argument("--vocab", help="고유명사 힌트(예: 한울김치)"); p.add_argument("--force", action="store_true")
    p = sp.add_parser("draft"); p.add_argument("job"); p.add_argument("--force", action="store_true")
    p = sp.add_parser("render"); p.add_argument("job")
    p = sp.add_parser("check"); p.add_argument("job"); p.add_argument("--no-asr", action="store_true"); p.add_argument("--autofix", action="store_true")
    sp.add_parser("find")
    p = sp.add_parser("feedback"); p.add_argument("--note", required=True); p.add_argument("--rule"); p.add_argument("--set", action="append")
    p = sp.add_parser("ref"); p.add_argument("url")
    sp.add_parser("selftest")
    a = ap.parse_args()
    {"transcribe": cmd_transcribe, "draft": cmd_draft, "render": cmd_render, "check": cmd_check, "find": cmd_find,
     "feedback": cmd_feedback, "ref": cmd_ref, "selftest": cmd_selftest}[a.cmd](a)


if __name__ == "__main__":
    main()
