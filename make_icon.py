"""生成 icon.ico（Claude 橙色圆 + 白色 C），和窗口左上角的 logo 一致。需要 Pillow，只在改图标时运行。"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.ellipse((4, 4, SIZE - 4, SIZE - 4), fill="#D97757")
font = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 150)
d.text((SIZE / 2, SIZE / 2 + 4), "C", fill="white", font=font, anchor="mm")
out = Path(__file__).with_name("icon.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", out)
