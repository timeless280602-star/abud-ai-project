"""A data-driven PNG rank card rendered entirely in memory."""

import io

from PIL import Image, ImageDraw, ImageFont

from app.leveling import progress


def font(size):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size
        )
    except OSError:
        return ImageFont.load_default(size=size)


def rank_card(name, xp, chat_xp, rank):
    image = Image.new("RGB", (960, 300), "#101116")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 951, 291), radius=24, outline="#343540", width=2)
    draw.rounded_rectangle((30, 30, 38, 270), radius=4, fill="#f04452")
    draw.text((62, 30), "ABUD • COMMUNITY LEVEL", font=font(17), fill="#a9abb6")
    # Bound display names to the available width, including wide Unicode names.
    name = "".join(c for c in str(name) if c.isprintable())[:100] or "Member"
    while draw.textlength(name, font=font(32)) > 610:
        name = name[:-2] + "…"
    draw.text((62, 68), name, font=font(32), fill="#ffffff")
    current, earned, needed = progress(xp)
    draw.text((735, 50), f"LEVEL {current}", font=font(28), fill="#ff6370")
    draw.text(
        (64, 130),
        f"Rank #{rank}" if rank else "Belum berperingkat",
        font=font(20),
        fill="#d2d3db",
    )
    draw.text(
        (64, 171),
        f"{earned:,} / {needed:,} XP ke level berikutnya",
        font=font(18),
        fill="#a9abb6",
    )
    draw.rounded_rectangle((62, 209, 899, 227), radius=9, fill="#30313b")
    fill = int(837 * earned / needed)
    if fill:
        draw.rounded_rectangle(
            (62, 209, 62 + fill, 227), radius=min(9, fill // 2), fill="#f04452"
        )
    draw.text(
        (64, 250),
        f"TOTAL {xp:,} XP   •   CHAT {chat_xp:,}",
        font=font(17),
        fill="#a9abb6",
    )
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output
