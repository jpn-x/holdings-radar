"""量アイコンのPNG生成（ホーム画面用 apple-touch / PWA manifest）"""
from PIL import Image, ImageDraw, ImageFont
import os, math

OUT = os.path.join(os.path.dirname(__file__), "..")
FONT = r"C:\Windows\Fonts\BIZ-UDGothicB.ttc"
BG = (13, 15, 20)        # #0d0f14
GOLD = (245, 200, 66)    # #f5c842
GREEN = (61, 220, 132)
RED = (255, 92, 92)


def make(size, radius_ratio=0.22, padding_bg=False):
    # 高解像度で描いて縮小（アンチエイリアス）
    S = size * 4
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(S * radius_ratio)
    # 角丸背景
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=BG)
    c = S / 2
    # レーダーリング
    for rr, op in ((0.42, 50), (0.30, 40)):
        rad = S * rr
        d.ellipse([c - rad, c - rad, c + rad, c + rad], outline=GOLD + (op,), width=max(1, S // 320))
    # レーダー掃引（扇形）
    sweep = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sweep)
    rad = S * 0.42
    sd.pieslice([c - rad, c - rad, c + rad, c + rad], -90, -35, fill=GOLD + (20,))
    img = Image.alpha_composite(img, sweep)
    d = ImageDraw.Draw(img)
    # 量
    fsize = int(S * 0.62)
    font = ImageFont.truetype(FONT, fsize)
    bbox = d.textbbox((0, 0), "量", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((c - w / 2 - bbox[0], c - h / 2 - bbox[1]), "量", font=font, fill=GOLD)
    # ブリップ
    d.ellipse([S * 0.78, S * 0.16, S * 0.78 + S * 0.06, S * 0.16 + S * 0.06], fill=GREEN)
    d.ellipse([S * 0.18, S * 0.70, S * 0.18 + S * 0.045, S * 0.70 + S * 0.045], fill=RED)
    return img.resize((size, size), Image.LANCZOS)


# apple-touch-icon は角丸なし（iOSが自動でマスクする）の四角背景が綺麗
def make_square(size):
    S = size * 4
    img = Image.new("RGBA", (S, S), BG + (255,))
    d = ImageDraw.Draw(img)
    c = S / 2
    for rr, op in ((0.42, 50), (0.30, 40)):
        rad = S * rr
        d.ellipse([c - rad, c - rad, c + rad, c + rad], outline=GOLD + (op,), width=max(1, S // 320))
    sweep = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sweep)
    rad = S * 0.42
    sd.pieslice([c - rad, c - rad, c + rad, c + rad], -90, -35, fill=GOLD + (20,))
    img = Image.alpha_composite(img.convert("RGBA"), sweep)
    d = ImageDraw.Draw(img)
    fsize = int(S * 0.62)
    font = ImageFont.truetype(FONT, fsize)
    bbox = d.textbbox((0, 0), "量", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((c - w / 2 - bbox[0], c - h / 2 - bbox[1]), "量", font=font, fill=GOLD)
    d.ellipse([S * 0.78, S * 0.16, S * 0.78 + S * 0.06, S * 0.16 + S * 0.06], fill=GREEN)
    d.ellipse([S * 0.18, S * 0.70, S * 0.18 + S * 0.045, S * 0.70 + S * 0.045], fill=RED)
    return img.resize((size, size), Image.LANCZOS).convert("RGB")


make_square(180).save(os.path.join(OUT, "apple-touch-icon.png"))
make(192).save(os.path.join(OUT, "icon-192.png"))
make(512).save(os.path.join(OUT, "icon-512.png"))
make(32).save(os.path.join(OUT, "favicon-32.png"))
print("icons generated: apple-touch-icon.png, icon-192.png, icon-512.png, favicon-32.png")
