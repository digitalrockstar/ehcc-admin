function initPage() {
  // Team switcher
  document.querySelectorAll('[data-team-switch]').forEach(sel => sel.addEventListener('change', () => {
    const url = new URL(sel.dataset.teamSwitch, location.origin);
    url.searchParams.set('team', sel.value);
    location.href = url.toString();
  }));

  // Auto-submit forms
  document.querySelectorAll('[data-autosubmit]').forEach(el => el.addEventListener('change', () => el.form.submit()));

  // Confirm dialogs
  document.querySelectorAll('form[data-confirm]').forEach(f => f.addEventListener('submit', e => {
    if (!confirm(f.dataset.confirm)) e.preventDefault();
  }));

  // Clickable table rows
  document.querySelectorAll('tr[data-href]').forEach(tr => tr.addEventListener('click', e => {
    if (e.target.closest('a,button,input,select,summary,form,details,dialog')) return;
    location.href = tr.dataset.href;
  }));

  initSheets();
  initThemeFilter();
  initGlass();

  // Flash messages auto-fade
  document.querySelectorAll('.flash').forEach(el => setTimeout(() => {
    el.classList.add('fade');
    setTimeout(() => el.remove(), 500);
  }, 10000));

  // Transaction form
  const form = document.getElementById('txn-form');
  if (form) initTxnForm(form);
}

document.addEventListener('DOMContentLoaded', initPage);

// AJAX-style form submissions: keep the browser on the page while refreshing
// the returned server-rendered view. File uploads remain regular submissions.
document.addEventListener('submit', async e => {
  const form = e.target;
  if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== 'post' ||
      form.enctype === 'multipart/form-data' || form.dataset.noAjax === 'true') return;
  if (e.defaultPrevented) return;
  e.preventDefault();
  if (form.dataset.ajaxBusy === 'true') return;
  form.dataset.ajaxBusy = 'true';
  const submitters = form.querySelectorAll('button[type="submit"], input[type="submit"]');
  submitters.forEach(b => { b.dataset.wasDisabled = b.disabled ? '1' : '0'; b.disabled = true; });
  const scrollY = window.scrollY;
  try {
    const response = await fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });
    const type = response.headers.get('content-type') || '';
    if (!type.includes('text/html')) throw new Error('Unexpected response from server.');
    const html = await response.text();
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    if (!parsed.body || !parsed.querySelector('main.container')) throw new Error('Could not update this page.');
    document.title = parsed.title;
    const oldTheme = document.querySelector('head style'), newTheme = parsed.querySelector('head style');
    if (oldTheme && newTheme) oldTheme.textContent = newTheme.textContent;
    document.body.innerHTML = parsed.body.innerHTML;
    if (response.url && new URL(response.url).origin === location.origin) {
      history.replaceState({}, '', response.url);
    }
    initPage();
    window.scrollTo(0, Math.min(scrollY, document.documentElement.scrollHeight));
  } catch (err) {
    // Preserve normal form behaviour if the AJAX request fails.
    form.dataset.ajaxBusy = 'false';
    submitters.forEach(b => { b.disabled = b.dataset.wasDisabled === '1'; delete b.dataset.wasDisabled; });
    alert('Could not complete the action without refreshing. Please try again. ' + err.message);
  }
});

function initTxnForm(form) {
  const cats = JSON.parse(document.getElementById('cat-data').textContent);
  const step = parseFloat(form.dataset.step) || 5;
  const catSel = form.querySelector('#f-category');
  const desc = form.querySelector('#f-desc');
  const hint = form.querySelector('#desc-hint');
  const amount = form.elements.amount;
  const checks = () => Array.from(form.querySelectorAll('input[name=charged_to]'));
  const typeNow = () => (form.querySelector('input[name=type]:checked') || form.querySelector('input[type=hidden][name=type]')).value;
  const money = paise => '₹' + (paise / 100).toLocaleString('en-IN', {maximumFractionDigits: 2});

  function otherSelected() {
    const o = catSel.selectedOptions[0];
    return !!(o && o.dataset.other);
  }
  function refreshDesc() {
    const t = typeNow();
    const need = t !== 'transfer' && otherSelected();
    desc.required = need;
    hint.textContent = need ? '(required for Other)' : (t === 'transfer' ? '(optional note)' : '(optional)');
  }
  function preview() {
    const box = form.querySelector('#preview');
    const n = checks().filter(c => c.checked).length;
    form.querySelector('#sel-count').textContent = n + ' selected';
    const amt = Math.round(parseFloat((amount.value || '').replace(/,/g, '')) * 100);
    if (typeNow() !== 'expense' || !(amt > 0) || n < 1) { box.textContent = ''; return; }
    if (n === 1) { box.textContent = 'Charged ' + money(amt) + '.'; return; }
    const stepP = Math.round(step * 100);
    const share = Math.ceil(amt / (n * stepP)) * stepP;
    box.textContent = `Each of ${n} owes ${money(share)}. Total ${money(share * n)}. Team balance increase ${money(share * n - amt)}.`;
  }
  function applyType() {
    const t = typeNow();
    if (catSel) {
      const cur = catSel.value;
      catSel.innerHTML = '<option value="">Select</option>';
      cats.filter(c => c.kind === t).forEach(c => {
        const o = new Option(c.name, c.id);
        o.dataset.other = c.other ? '1' : '';
        if (String(c.id) === cur) o.selected = true;
        catSel.add(o);
      });
    }
    form.querySelectorAll('[data-for]').forEach(el => {
      const on = el.dataset.for.split(' ').includes(t);
      el.hidden = !on;
      if (el.tagName === 'FIELDSET') el.disabled = !on;
      el.querySelectorAll('input,select').forEach(i => { if (i.name !== 'category_id') i.disabled = !on; });
    });
    refreshDesc();
    preview();
  }
  form.querySelectorAll('[name=type]:not([type=hidden])').forEach(t => t.addEventListener('change', applyType));
  catSel && catSel.addEventListener('change', refreshDesc);
  amount.addEventListener('input', preview);
  form.addEventListener('change', e => { if (e.target.name === 'charged_to') preview(); });
  form.querySelectorAll('[data-select]').forEach(b => b.addEventListener('click', () => {
    checks().forEach(c => { c.checked = b.dataset.select === 'players' ? c.dataset.kind === 'player' : false; });
    preview();
  }));
  applyType();
}

// Make transaction cards and rows keyboard- and pointer-accessible.
document.addEventListener('click', function(e) {
  const row = e.target.closest('tr[data-href]');
  if (!row || e.target.closest('a,button,input,select,textarea,summary,form,details,dialog')) return;
  window.location.href = row.dataset.href;
});
document.addEventListener('keydown', function(e) {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('tr[data-href]')) {
    e.preventDefault(); window.location.href = e.target.dataset.href;
  }
});


// ---- Sheets: native <dialog> bottom sheets with drag to dismiss ----
function initSheets() {
  const close = d => {
    if (!d.open || d.classList.contains('closing')) return;
    d.classList.add('closing');
    d.addEventListener('animationend', () => { d.classList.remove('closing'); d.style.transform = ''; d.close(); }, { once: true });
  };
  document.querySelectorAll('[data-sheet-open]').forEach(b => b.addEventListener('click', () => {
    const d = document.getElementById(b.dataset.sheetOpen);
    if (d && !d.open) d.showModal();
  }));
  document.querySelectorAll('dialog.sheet').forEach(d => {
    d.addEventListener('click', e => { if (e.target === d) close(d); });                  // tap the scrim
    d.addEventListener('cancel', e => { e.preventDefault(); close(d); });                // Escape
    d.querySelectorAll('[data-sheet-close]').forEach(b => b.addEventListener('click', () => close(d)));
    d.querySelectorAll('a[href]').forEach(a => a.addEventListener('click', () => close(d)));
    const grip = d.querySelector('.sheet-grip');
    if (!grip) return;
    let drag = null;
    grip.addEventListener('pointerdown', e => {
      grip.setPointerCapture(e.pointerId); d.classList.add('dragging'); d.classList.remove('settling');
      drag = { y: e.clientY, dy: 0, hist: [{ y: e.clientY, t: e.timeStamp }] };
    });
    grip.addEventListener('pointermove', e => {
      if (!drag) return;
      const raw = e.clientY - drag.y;
      drag.dy = raw < 0 ? -(Math.abs(raw) * 0.55) / (1 + Math.abs(raw) / 120) : raw;     // resist upward drag
      drag.hist.push({ y: e.clientY, t: e.timeStamp }); if (drag.hist.length > 6) drag.hist.shift();
      d.style.transform = `translateY(${drag.dy}px)`;                                      // 1:1 with the finger
    });
    const end = () => {
      if (!drag) return;
      const a = drag.hist[0], b = drag.hist[drag.hist.length - 1];
      const v = b.t > a.t ? (b.y - a.y) / (b.t - a.t) : 0;                                 // px/ms
      const landing = drag.dy + v * 1000 * 0.2;                                            // project the flick
      drag = null; d.classList.remove('dragging');
      if (landing > d.offsetHeight * 0.35) { d.style.transition = 'transform .28s cubic-bezier(.32,.72,0,1), opacity .28s'; d.style.transform = 'translateY(100%)'; d.style.opacity = '0'; setTimeout(() => { d.style.transition = d.style.transform = d.style.opacity = ''; d.close(); }, 280); }
      else { d.classList.add('settling'); d.style.transform = ''; setTimeout(() => d.classList.remove('settling'), 420); }
    };
    grip.addEventListener('pointerup', end); grip.addEventListener('pointercancel', end);
  });
}

// ---- Theme tone filter (All / Light / Dark) ----
function initThemeFilter() {
  const btns = document.querySelectorAll('[data-theme-filter]');
  btns.forEach(b => b.addEventListener('click', () => {
    btns.forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    document.querySelectorAll('.themes form[data-tone]').forEach(f => { f.hidden = b.dataset.themeFilter !== 'all' && f.dataset.tone !== b.dataset.themeFilter; });
  }));
}

// ---- Glass switch: tap or drag, spring driven, interruptible ----
function initGlass() {
  const root = document.documentElement;
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const project = (v, d = 0.998) => (v / 1000) * d / (1 - d);              // px/s -> resting offset in px
  const rubber = (o, c = 0.55) => (o * c) / (1 + c * Math.abs(o));          // soft edge past 0..1
  const isOn = () => root.dataset.glass === 'on';
  const save = on => { document.cookie = 'ehcc_glass=' + (on ? 'on' : 'off') + ';path=/;max-age=31536000;samesite=lax'; };
  const sw = [...document.querySelectorAll('[data-glass-switch]')].map(el => ({ el, p: isOn() ? 1 : 0, v: 0, raf: 0 }));
  const paint = s => s.el.style.setProperty('--p', s.p.toFixed(4));
  const label = on => document.querySelectorAll('[data-glass-state]').forEach(n => { n.textContent = on ? 'ON' : 'OFF'; });

  // Critically damped spring (response 0.3s). Starts from the live value and live velocity.
  function spring(s, target, zeta = 1) {
    cancelAnimationFrame(s.raf);
    if (reduced()) { s.p = target; s.v = 0; paint(s); return; }
    const k = Math.pow((2 * Math.PI) / 0.3, 2), c = 2 * zeta * Math.sqrt(k);
    let last = performance.now();
    const step = now => {
      const dt = Math.min((now - last) / 1000, 1 / 30); last = now;
      s.v += (-k * (s.p - target) - c * s.v) * dt; s.p += s.v * dt; paint(s);
      if (Math.abs(s.p - target) < 0.0005 && Math.abs(s.v) < 0.005) { s.p = target; s.v = 0; paint(s); return; }
      s.raf = requestAnimationFrame(step);
    };
    s.raf = requestAnimationFrame(step);
  }
  function commit(on, from, v = 0) {
    const changed = on !== isOn();
    root.dataset.glass = on ? 'on' : 'off'; save(on); label(on);
    sw.forEach(s => {
      s.el.setAttribute('aria-checked', String(on));
      if (s === from) s.v = v / ((s.el.clientWidth - 32) || 20);
      spring(s, on ? 1 : 0, s === from && Math.abs(v) > 200 ? 0.8 : 1);
    });
    if (changed && navigator.vibrate) navigator.vibrate(8);
  }
  sw.forEach(s => {
    const el = s.el, travel = () => el.clientWidth - 32;
    el.setAttribute('aria-checked', String(isOn())); label(isOn()); paint(s);
    let drag = null;
    el.addEventListener('pointerdown', e => {
      if (e.button) return;
      cancelAnimationFrame(s.raf);                                          // grab it mid-flight
      el.setPointerCapture(e.pointerId); el.classList.add('dragging');
      drag = { x: e.clientX, p: s.p, moved: false, hist: [{ x: e.clientX, t: e.timeStamp }] };
    });
    el.addEventListener('pointermove', e => {
      if (!drag) return;
      const dx = e.clientX - drag.x;
      if (!drag.moved && Math.abs(dx) < 4) return;                          // hysteresis
      drag.moved = true;
      drag.hist.push({ x: e.clientX, t: e.timeStamp }); if (drag.hist.length > 6) drag.hist.shift();
      const raw = drag.p + dx / travel();
      s.p = raw < 0 ? -rubber(-raw) : raw > 1 ? 1 + rubber(raw - 1) : raw; s.v = 0; paint(s);
    });
    el.addEventListener('pointerup', () => {
      if (!drag) return;
      const d = drag; drag = null; el.classList.remove('dragging');
      if (!d.moved) { commit(!isOn(), s); return; }                         // tap
      const a = d.hist[0], b = d.hist[d.hist.length - 1];
      const v = b.t > a.t ? ((b.x - a.x) / (b.t - a.t)) * 1000 : 0;         // px/s
      commit(s.p * travel() + project(v) > travel() / 2, s, v);             // land where the flick is heading
    });
    el.addEventListener('pointercancel', () => { if (drag) { drag = null; el.classList.remove('dragging'); spring(s, isOn() ? 1 : 0); } });
    el.addEventListener('click', e => { if (e.detail === 0) commit(!isOn(), s); }); // keyboard only
  });
}
