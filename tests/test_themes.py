from app.themes import _BASE, contrast, theme_vars


def test_at_least_20_themes():
    assert len(_BASE) >= 20


def test_every_theme_meets_wcag_aa():
    for slug in _BASE:
        v = theme_vars(slug)
        pairs = {
            "text/bg": (v["--text"], v["--bg"]), "text/surface": (v["--text"], v["--surface"]),
            "muted/surface": (v["--muted"], v["--surface"]), "muted/bg": (v["--muted"], v["--bg"]),
            "button": (v["--primary-text"], v["--primary"]),
            "link/bg": (v["--link"], v["--bg"]), "link/surface": (v["--link"], v["--surface"]),
            "accent/surface": (v["--accent"], v["--surface"]), "accent/bg": (v["--accent"], v["--bg"]),
            "pos/surface": (v["--pos"], v["--surface"]), "pos/bg": (v["--pos"], v["--bg"]),
            "neg/surface": (v["--neg"], v["--surface"]), "neg/bg": (v["--neg"], v["--bg"]),
        }
        for name, (fg, bg) in pairs.items():
            assert contrast(fg, bg) >= 4.5, f"{slug} {name} {contrast(fg, bg):.2f}"
