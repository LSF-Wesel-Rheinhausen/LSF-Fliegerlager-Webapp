import glob
import os

from PIL import Image


def make_gif(name):
    frame_dir = f"frames/{name}"
    if not os.path.exists(frame_dir):
        return
    files = sorted(glob.glob(f"{frame_dir}/*.png"))
    if not files:
        return

    images = [Image.open(f) for f in files]
    out_path = f"src/static/billing/docs/{name}.gif"

    # Compress by resizing slightly and using optimize
    width, height = images[0].size
    images = [img.resize((int(width * 0.75), int(height * 0.75)), Image.Resampling.LANCZOS) for img in images]

    images[0].save(
        out_path,
        save_all=True,
        append_images=images[1:],
        duration=100,  # 10 fps
        loop=0,
        optimize=True,
    )
    print(f"Saved {out_path} ({len(images)} frames)")


for name in ["kiosk_login", "kiosk_drinks", "kiosk_meals", "kiosk_family", "kiosk_shifts"]:
    make_gif(name)
