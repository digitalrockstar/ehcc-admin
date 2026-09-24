"""Themes. Each theme lists five base colours; every text colour is derived and forced to meet WCAG AA (4.5:1)."""
from __future__ import annotations

from functools import lru_cache

# slug: (label, bg, surface, text, primary, accent)
_BASE = {
    "cricket-whites": ("Cricket Whites", "#f4f6f1", "#ffffff", "#1b2a1b", "#1f7a3d", "#c0392b"),
    "paper": ("Paper", "#faf7f0", "#fffdf8", "#2b2b2b", "#8a5a00", "#b5451b"),
    "sky": ("Sky", "#eef6ff", "#ffffff", "#10233a", "#1f6fd1", "#b45309"),
    "sandstone": ("Sandstone", "#f5ede0", "#fffaf1", "#3a2a1a", "#b4581e", "#2f6f6f"),
    "mint-fresh": ("Mint Fresh", "#ecfaf3", "#ffffff", "#0e2a20", "#0f9f6e", "#7c3aed"),
    "solarized-light": ("Solarized Light", "#fdf6e3", "#eee8d5", "#073642", "#268bd2", "#cb4b16"),
    "high-contrast-light": ("High Contrast Light", "#ffffff", "#ffffff", "#000000", "#0000cc", "#b30000"),
    "midnight": ("Midnight", "#0d1117", "#161b22", "#e6edf3", "#58a6ff", "#f0883e"),
    "pitch-night": ("Pitch Night", "#08130c", "#0f1f15", "#e4f3e6", "#3ddc6b", "#ffd166"),
    "solarized-dark": ("Solarized Dark", "#002b36", "#073642", "#eee8d5", "#2aa198", "#cb4b16"),
    "nord": ("Nord", "#2e3440", "#3b4252", "#eceff4", "#88c0d0", "#ebcb8b"),
    "dracula": ("Dracula", "#282a36", "#343746", "#f8f8f2", "#bd93f9", "#ff79c6"),
    "charcoal-amber": ("Charcoal & Amber", "#1c1c1c", "#262626", "#f2f2f2", "#ffb000", "#4dd0e1"),
    "deep-ocean": ("Deep Ocean", "#04202e", "#0a3246", "#e3f6ff", "#33c6ff", "#ffd54f"),
    "high-contrast-dark": ("High Contrast Dark", "#000000", "#0a0a0a", "#ffffff", "#ffff00", "#00ffff"),
    "bubblegum-riot": ("Bubblegum Riot", "#ff8fd0", "#fff0fa", "#14001a", "#7a00cc", "#00704a"),
    "lemon-lime-clash": ("Lemon Lime Clash", "#f4ff3a", "#ffffe0", "#12200a", "#0b7a1a", "#d10086"),
    "neon-noir": ("Neon Noir", "#0a0014", "#180030", "#f5f0ff", "#00ffd5", "#ff2bd6"),
    "sunset-punch": ("Sunset Punch", "#ff7a45", "#fff1e6", "#2b0a00", "#b0003a", "#005f73"),
    "vaporwave": ("Vaporwave", "#2b1055", "#3d1a78", "#ffe8ff", "#ff71ce", "#01cdfe"),
    "toxic-slime": ("Toxic Slime", "#0b1a00", "#16300a", "#eaffd0", "#b6ff00", "#ff3d81"),
    "retro-arcade": ("Retro Arcade", "#1a1a2e", "#232347", "#f7f7f7", "#ffd400", "#ff5c5c"),
    "cotton-candy": ("Cotton Candy", "#cdeeff", "#fff5fb", "#2a1140", "#c2185b", "#1565c0"),
    "pumpkin-spice": ("Pumpkin Spice", "#2a1300", "#3d1d00", "#ffe9d0", "#ff8c1a", "#a3e635"),
    "cricket-ball": ("Cricket Ball", "#7a1010", "#911a1a", "#fff4f0", "#ffe066", "#ffffff"),
}
DEFAULT_THEME = "cricket-whites"


def _rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _hex(c) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in c)


def luminance(h: str) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a: str, b: str, t: float) -> str:
    ca, cb = _rgb(a), _rgb(b)
    return _hex([x + (y - x) * t for x, y in zip(ca, cb)])


def ensure(fg: str, backgrounds: list[str], minimum: float = 4.5) -> str:
    """Nudge fg towards black or white until it clears `minimum` on every background."""
    def worst(c):
        return min(contrast(c, bg) for bg in backgrounds)
    if worst(fg) >= minimum:
        return fg
    target = max(("#000000", "#ffffff"), key=worst)
    for i in range(1, 41):
        c = mix(fg, target, i / 40)
        if worst(c) >= minimum:
            return c
    return target


def _on(color: str) -> str:
    return max(("#000000", "#ffffff"), key=lambda t: contrast(color, t))


@lru_cache(maxsize=None)
def theme_vars(slug: str) -> dict[str, str]:
    label, bg, surface, text, primary, accent = _BASE.get(slug, _BASE[DEFAULT_THEME])
    text = ensure(text, [bg, surface], 7)
    both = [bg, surface]
    dark = luminance(bg) < 0.25
    pos = ensure("#3fb950" if dark else "#1a7f37", both)
    neg = ensure("#ff6b6b" if dark else "#c62828", both)
    return {
        "--bg": bg, "--surface": surface, "--text": text,
        "--muted": ensure(mix(text, surface, 0.32), both),
        "--border": mix(surface, text, 0.28),
        "--primary": primary, "--primary-text": _on(primary),
        "--link": ensure(primary, both),
        "--accent": ensure(accent, both),
        "--pos": pos, "--neg": neg,
        "color-scheme": "dark" if dark else "light",
    }


def theme_list() -> list[dict]:
    return [{"slug": s, "label": v[0], "vars": theme_vars(s), "dark": luminance(v[1]) < 0.25} for s, v in _BASE.items()]


def valid_theme(slug: str) -> bool:
    return slug in _BASE


def css_block(slug: str) -> str:
    return ":root{" + ";".join(f"{k}:{v}" for k, v in theme_vars(slug).items()) + "}"
