#!/usr/bin/env python3
"""Render a TikTok-style animated edit (1080x1920 @ 30fps) from a single still."""
import math, random, sys, subprocess, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from multiprocessing import Pool

SRC = "/root/.claude/uploads/85c3de5b-a4b6-5537-a068-5498952a58ea/aa099f60-image.png"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1920
FPS = 30
DURATION = 12.5
N = int(DURATION * FPS)
SUP = 2  # supersampled base for sharp zoom-ins

FONT_CAP = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SCRIPT = "/usr/share/fonts/truetype/freefont/FreeSerifBoldItalic.ttf"
FONT_EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

# ---------- easing ----------
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease_out_cubic(t): t = clamp(t); return 1 - (1 - t) ** 3
def ease_in_out(t): t = clamp(t); return t * t * (3 - 2 * t)
def ease_out_back(t, s=1.7):
    t = clamp(t); t -= 1
    return 1 + t * t * ((s + 1) * t + s)
def lerp(a, b, t): return a + (b - a) * t

# ---------- base image ----------
_src = Image.open(SRC).convert("RGB")
sw, sh = _src.size
scale = max(W * SUP / sw, H * SUP / sh)
_big = _src.resize((round(sw * scale), round(sh * scale)), Image.LANCZOS)
bx = (_big.width - W * SUP) // 2
by = (_big.height - H * SUP) // 2
BASE = _big.crop((bx, by, bx + W * SUP, by + H * SUP))  # 2160x3840
del _src, _big

# ---------- shot list (times in seconds) ----------
# each shot: (t0, t1, (z0, cx0, cy0), (z1, cx1, cy1), easing)  coords in 1080x1920 space
FACES = (540, 690)
HER = (380, 720)
SHOTS = [
    (0.0, 4.6, (1.00, 540, 960), (1.28, 540, 800), ease_in_out),
    (4.6, 8.2, (1.95, 520, 700), (2.15, 560, 690), ease_in_out),
    (8.2, 11.0, (1.55, 540, 1300), (1.03, 540, 960), ease_in_out),
    (11.0, DURATION + 1, (1.03, 540, 960), (1.08, 540, 940), ease_in_out),
]
CUTS = [s[0] for s in SHOTS[1:]]
BPM = 120.0
BEAT = 60.0 / BPM

def camera(t):
    for (t0, t1, a, b, ez) in SHOTS:
        if t0 <= t < t1:
            u = ez((t - t0) / (t1 - t0))
            z = lerp(a[0], b[0], u); cx = lerp(a[1], b[1], u); cy = lerp(a[2], b[2], u)
            break
    # beat pulse: small zoom bump decaying over 0.25s after each beat
    tb = (t % BEAT)
    z *= 1 + 0.028 * math.exp(-tb * 14)
    # snap-in at the very start
    if t < 0.6:
        z *= 1 + 0.18 * (1 - ease_out_cubic(t / 0.6))
    # shake after a cut
    dx = dy = 0.0
    for c in CUTS:
        dt = t - c
        if 0 <= dt < 0.25:
            amp = 14 * (1 - dt / 0.25)
            dx += amp * math.sin(dt * 95); dy += amp * math.cos(dt * 77)
    return z, cx + dx, cy + dy

def frame_image(t):
    z, cx, cy = camera(t)
    cw, ch = W / z, H / z
    x0 = clamp(cx - cw / 2, 0, W - cw); y0 = clamp(cy - ch / 2, 0, H - ch)
    box = (x0 * SUP, y0 * SUP, (x0 + cw) * SUP, (y0 + ch) * SUP)
    return BASE.resize((W, H), Image.BILINEAR, box=box)

# ---------- sprites ----------
def heart_sprite(size, color, outline=None):
    s = size * 4
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pts = []
    for i in range(80):
        a = 2 * math.pi * i / 80
        x = 16 * math.sin(a) ** 3
        y = 13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)
        pts.append((s / 2 + x * s / 36, s / 2 - y * s / 36 + s * 0.02))
    d.polygon(pts, fill=color, outline=outline)
    return im.resize((size, size), Image.LANCZOS)

def sparkle_sprite(size, color=(255, 240, 200, 255)):
    s = size * 4
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = s / 2; r = s / 2; w = s * 0.09
    d.polygon([(c, c - r), (c + w, c), (c, c + r), (c - w, c)], fill=color)
    d.polygon([(c - r, c), (c, c - w), (c + r, c), (c, c + w)], fill=color)
    im = im.filter(ImageFilter.GaussianBlur(s * 0.02))
    return im.resize((size, size), Image.LANCZOS)

HEART_COLORS = [(255, 105, 150, 255), (255, 160, 190, 255), (255, 225, 235, 255), (255, 200, 120, 255), (255, 80, 120, 255)]
HEARTS = {}
def get_heart(size, ci):
    key = (size, ci)
    if key not in HEARTS:
        HEARTS[key] = heart_sprite(size, HEART_COLORS[ci], (255, 255, 255, 140))
    return HEARTS[key]
SPARK = {s: sparkle_sprite(s) for s in (24, 36, 52, 70)}

rng = random.Random(7)
PARTICLES = []
for i in range(70):
    PARTICLES.append(dict(
        kind="heart" if rng.random() < 0.72 else "spark",
        x=rng.uniform(40, W - 40),
        t0=rng.uniform(-3, DURATION),
        life=rng.uniform(3.2, 5.5),
        speed=rng.uniform(110, 230),
        size=rng.choice([26, 34, 44, 56, 72, 90]),
        wob=rng.uniform(18, 50), wf=rng.uniform(0.8, 1.8), ph=rng.uniform(0, 6.3),
        rot=rng.uniform(-28, 28), ci=rng.randrange(len(HEART_COLORS)),
    ))

# Light leak sprite: warm radial glow
def light_leak():
    s = 1400
    yy, xx = np.mgrid[0:s, 0:s].astype(np.float32)
    r = np.sqrt((xx - s / 2) ** 2 + (yy - s / 2) ** 2) / (s / 2)
    a = np.clip(1 - r, 0, 1) ** 2.2
    rgb = np.zeros((s, s, 4), np.uint8)
    rgb[..., 0] = 255; rgb[..., 1] = 150; rgb[..., 2] = 90
    rgb[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(rgb, "RGBA")
LEAK = light_leak()

# vignette multiplier
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
rr = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
VIG = (1 - 0.42 * np.clip((rr - 0.55) / 0.75, 0, 1) ** 1.6)[..., None].astype(np.float32)

# ---------- text ----------
_fonts = {}
def font(path, size):
    k = (path, size)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(path, size)
    return _fonts[k]
EMOJI_FONT = ImageFont.truetype(FONT_EMOJI, 109)

def render_emoji(ch, size):
    im = Image.new("RGBA", (140, 140), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((8, 8), ch, font=EMOJI_FONT, embedded_color=True)
    bb = im.getbbox()
    im = im.crop(bb) if bb else im
    h = size
    w = max(1, round(im.width * h / im.height))
    return im.resize((w, h), Image.LANCZOS)

def is_emoji(ch): return ord(ch) > 0x2000 and ch not in "’‘“”…–—"

def text_layer(text, size, fpath=FONT_CAP, fill=(255, 255, 255, 255), stroke=(0, 0, 0, 255), sw=None):
    """Render one line (with emoji) to an RGBA image, with stroke + soft shadow."""
    if sw is None: sw = max(3, size // 9)
    f = font(fpath, size)
    # split into runs
    runs, cur, cur_e = [], "", None
    for ch in text:
        e = is_emoji(ch)
        if cur and e != cur_e: runs.append((cur, cur_e)); cur = ""
        cur += ch; cur_e = e
    if cur: runs.append((cur, cur_e))
    pieces = []
    for s, e in runs:
        if e:
            for ch in s: pieces.append(render_emoji(ch, int(size * 1.05)))
        else:
            bb = f.getbbox(s, stroke_width=sw)
            tw = bb[2] - bb[0]
            im = Image.new("RGBA", (tw + sw * 2 + 8, int(size * 1.32) + sw * 2), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.text((sw + 4 - bb[0], sw + size * 0.12), s, font=f, fill=fill, stroke_width=sw, stroke_fill=stroke)
            pieces.append(im)
    gap = size // 8
    tw = sum(p.width for p in pieces) + gap * (len(pieces) - 1)
    th = max(p.height for p in pieces)
    out = Image.new("RGBA", (tw + 40, th + 40), (0, 0, 0, 0))
    x = 20
    for p in pieces:
        out.alpha_composite(p, (x, 20 + (th - p.height) // 2))
        x += p.width + gap
    # soft shadow
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, 170), mask=out.split()[3])
    sh = sh.filter(ImageFilter.GaussianBlur(10))
    res = Image.new("RGBA", out.size, (0, 0, 0, 0))
    res.alpha_composite(sh, (0, 10)); res.alpha_composite(out)
    return res

_tl = {}
def cached_text(*a, **k):
    key = (a, tuple(sorted(k.items())))
    if key not in _tl: _tl[key] = text_layer(*a, **k)
    return _tl[key]

# caption beats: (t_in, t_out, lines[(text, size, font)], y_center, style)
CAPTIONS = [
    (0.75, 4.45, [("date night in", 92, FONT_CAP), ("Des Moines 🫶", 104, FONT_CAP)], 1500, "pop"),
    (4.75, 8.05, [("the way he", 96, FONT_CAP), ("looks at her 🥹", 96, FONT_CAP)], 1470, "pop"),
    (6.3, 8.05, [("i'm not okay 😭", 72, FONT_CAP)], 1740, "pop"),
    (8.4, 10.9, [("Iowa really said", 90, FONT_CAP), ("romance >>>", 100, FONT_CAP)], 1520, "pop"),
    (11.15, DURATION + 1, [("Iowa", 260, FONT_SCRIPT)], 820, "fade"),
    (11.6, DURATION + 1, [("des moines, ia  💛", 70, FONT_CAP)], 1010, "pop"),
]

def draw_captions(canvas, t):
    for (ti, to, lines, yc, style) in CAPTIONS:
        if not (ti <= t < to): continue
        age = t - ti; left = to - t
        if style == "pop":
            s = ease_out_back(age / 0.32)
            a = clamp(age / 0.12)
        else:
            s = lerp(0.92, 1.0, ease_out_cubic(age / 0.9))
            a = ease_out_cubic(age / 0.6)
        if left < 0.25: a *= clamp(left / 0.25)
        if s <= 0.02 or a <= 0: continue
        layers = [cached_text(txt, sz, fp) for (txt, sz, fp) in lines]
        gap = 6
        th = sum(l.height for l in layers) + gap * (len(layers) - 1)
        y = yc - th / 2
        for l in layers:
            lw, lh = int(l.width * s), int(l.height * s)
            if lw < 2 or lh < 2: continue
            im = l.resize((lw, lh), Image.BILINEAR)
            if a < 1:
                al = im.split()[3].point(lambda v: int(v * a))
                im.putalpha(al)
            canvas.alpha_composite(im, (int(W / 2 - lw / 2), int(y + l.height / 2 - lh / 2)))
            y += l.height + gap

def draw_particles(canvas, t):
    for p in PARTICLES:
        age = t - p["t0"]
        if age < 0 or age > p["life"]: continue
        u = age / p["life"]
        a = clamp(age / 0.5) * clamp((p["life"] - age) / 0.8)
        y = H + 60 - p["speed"] * age
        x = p["x"] + p["wob"] * math.sin(age * p["wf"] + p["ph"])
        if y < -120: continue
        if p["kind"] == "heart":
            sp = get_heart(p["size"], p["ci"]).rotate(p["rot"] + 10 * math.sin(age * 2 + p["ph"]), resample=Image.BILINEAR, expand=True)
            a *= 0.92
        else:
            tw = 0.5 + 0.5 * math.sin(age * 7 + p["ph"])
            sz = sorted(SPARK)[min(3, p["size"] // 24)]
            sp = SPARK[sz].rotate(age * 40, resample=Image.BILINEAR)
            a *= tw
        if a < 0.02: continue
        if a < 0.995:
            sp = sp.copy(); sp.putalpha(sp.split()[3].point(lambda v: int(v * a)))
        canvas.alpha_composite(sp, (int(x - sp.width / 2), int(y - sp.height / 2)))

def render(i):
    t = i / FPS
    img = frame_image(t)
    arr = np.asarray(img).astype(np.float32)
    # candle flicker + warm grade
    fl = 1 + 0.03 * math.sin(t * 9.3) + 0.02 * math.sin(t * 23.1 + 1.3) + 0.012 * math.sin(t * 57.7)
    arr *= fl
    arr[..., 0] *= 1.03; arr[..., 2] *= 0.97
    # chromatic shift right after cuts
    for c in CUTS:
        dt = t - c
        if 0 <= dt < 0.2:
            k = int(12 * (1 - dt / 0.2))
            if k:
                arr[..., 0] = np.roll(arr[..., 0], k, axis=1)
                arr[..., 2] = np.roll(arr[..., 2], -k, axis=1)
    arr *= VIG
    # film grain
    g = np.random.default_rng(i).normal(0, 5.5, (H, W, 1)).astype(np.float32)
    arr += g
    # fades
    fade = 1.0
    if t < 0.5: fade = ease_out_cubic(t / 0.5)
    if t > DURATION - 0.6: fade = clamp((DURATION - t) / 0.6)
    if t >= 11.0: arr *= lerp(1.0, 0.62, ease_in_out((t - 11.0) / 0.6))  # dim for end card
    arr *= fade
    canvas = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    # light leak sweeping
    lx = int(lerp(-900, W + 200, (t / DURATION)))
    ly = int(-500 + 300 * math.sin(t * 0.7))
    lk = LEAK.copy(); lk.putalpha(lk.split()[3].point(lambda v: int(v * 0.55 * fade)))
    canvas.alpha_composite(lk, (lx, ly))
    draw_particles(canvas, t)
    draw_captions(canvas, t)
    return canvas.convert("RGB").tobytes()

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT_DIR, "iowa_date_night_edit.mp4")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
           "-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-level", "4.1", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with Pool(4) as pool:
        for k, fb in enumerate(pool.imap(render, range(N), chunksize=4)):
            proc.stdin.write(fb)
            if k % 60 == 0: print(f"frame {k}/{N}", flush=True)
    proc.stdin.close(); proc.wait()
    print("done", out, proc.returncode)

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "preview":
        # dump a few frames for a contact sheet
        ts = [float(x) for x in sys.argv[2:]]
        tiles = []
        for t in ts:
            fb = render(int(t * FPS))
            tiles.append(Image.frombytes("RGB", (W, H), fb).resize((360, 640), Image.LANCZOS))
        sheet = Image.new("RGB", (360 * len(tiles), 640))
        for j, im in enumerate(tiles): sheet.paste(im, (360 * j, 0))
        sheet.save(os.path.join(OUT_DIR, "preview.jpg"), quality=90)
        print("preview saved")
    else:
        main()
