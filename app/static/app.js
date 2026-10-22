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
    if (e.target.closest('a,button,input,select,summary,form,details')) return;
    location.href = tr.dataset.href;
  }));

  // Keep the player edit popup inside the visible mobile viewport.
  document.querySelectorAll('details.edit-popover').forEach(details => {
    if (details.dataset.popupPositioner === 'ready') return;
    details.dataset.popupPositioner = 'ready';
    details.addEventListener('toggle', () => {
      const form = details.querySelector('.edit-player-form');
      const trigger = details.querySelector('summary');
      if (!form || !trigger) return;
      if (!details.open) {
        ['position','left','right','top','width','maxHeight','overflowY'].forEach(k => { form.style[k] = ''; });
        return;
      }
      if (!window.matchMedia('(max-width:640px) and (orientation:portrait)').matches) return;
      requestAnimationFrame(() => {
        const rect = trigger.getBoundingClientRect();
        const width = Math.min(280, window.innerWidth - 24);
        form.style.position = 'fixed';
        form.style.width = width + 'px';
        form.style.maxHeight = Math.max(180, window.innerHeight - 100) + 'px';
        form.style.overflowY = 'auto';
        form.style.right = 'auto';
        const left = Math.max(12, (window.innerWidth - width) / 2);
        form.style.left = left + 'px';
        const height = form.getBoundingClientRect().height;
        let top = rect.bottom + 8;
        if (top + height > window.innerHeight - 76) top = rect.top - height - 8;
        form.style.top = Math.max(12, Math.min(top, window.innerHeight - Math.min(height, window.innerHeight - 24) - 12)) + 'px';
      });
    });
  });

  // Sidebar / mobile nav toggle
  const menu = document.getElementById('menu-btn');
  const setNav = open => {
    document.body.classList.toggle('nav-open', open);
    if (menu) menu.setAttribute('aria-expanded', String(open));
  };
  if (menu) menu.addEventListener('click', () => setNav(!document.body.classList.contains('nav-open')));
  const backdrop = document.getElementById('backdrop');
  if (backdrop) backdrop.addEventListener('click', () => setNav(false));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') setNav(false); });
  document.querySelectorAll('#sidebar a').forEach(a => a.addEventListener('click', () => setNav(false)));

  // Bottom nav: close on link click (mobile)
  document.querySelectorAll('.bottomnav a').forEach(a => a.addEventListener('click', () => setNav(false)));

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
  if (!row || e.target.closest('a,button,input,select,textarea,summary,form,details')) return;
  window.location.href = row.dataset.href;
});
document.addEventListener('keydown', function(e) {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('tr[data-href]')) {
    e.preventDefault(); window.location.href = e.target.dataset.href;
  }
});
