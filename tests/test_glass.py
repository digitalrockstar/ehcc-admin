def test_glass_off_by_default_and_toggle_lives_in_settings(client, admin):
    html = admin.get("/settings").text
    assert 'data-glass="off"' in html
    assert "data-glass-switch" in html and 'role="switch"' in html and "Glass theme:" in html
    assert "data-glass-switch" not in admin.get("/").text          # only in Settings > Themes


def test_glass_cookie_turns_it_on(client, admin):
    admin.cookies.set("ehcc_glass", "on")
    html = admin.get("/settings").text
    assert 'data-glass="on"' in html and 'aria-checked="true"' in html


def test_glass_styles_respect_accessibility_signals(client):
    css = client.get("/static/app.css").text
    assert 'html[data-glass="on"]' in css
    assert "prefers-reduced-transparency" in css and "prefers-reduced-motion" in css
    assert "!important" not in css
