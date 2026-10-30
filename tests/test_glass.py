def test_glass_off_by_default_and_switch_rendered(client):
    html = client.get("/login").text
    assert 'data-glass="off"' in html
    assert "data-glass-switch" in html and 'role="switch"' in html
    assert "/static/apple.css" in html


def test_glass_cookie_turns_it_on(client):
    client.cookies.set("ehcc_glass", "on")
    assert 'data-glass="on"' in client.get("/login").text


def test_glass_styles_respect_accessibility_signals(client):
    css = client.get("/static/apple.css").text
    assert 'html[data-glass="on"]' in css
    assert "prefers-reduced-transparency" in css and "prefers-reduced-motion" in css
