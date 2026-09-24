document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-team-switch]').forEach(sel => sel.addEventListener('change', () => {
    const url = new URL(sel.dataset.teamSwitch, location.origin);
    url.searchParams.set('team', sel.value);
    location.href = url.toString();
  }));
  document.querySelectorAll('[data-autosubmit]').forEach(el => el.addEventListener('change', () => el.form.submit()));
  document.querySelectorAll('form[data-confirm]').forEach(f => f.addEventListener('submit', e => {
    if (!confirm(f.dataset.confirm)) e.preventDefault();
  }));
  document.querySelectorAll('tr[data-href]').forEach(tr => tr.addEventListener('click', e => {
    if (e.target.closest('a,button,input,select,summary,form,details')) return;
    location.href = tr.dataset.href;
  }));
  const form = document.getElementById('txn-form');
  if (form) initTxnForm(form);
});

function initTxnForm(form) {
  const cats = JSON.parse(document.getElementById('cat-data').textContent);
  const step = parseFloat(form.dataset.step) || 5;
  const catSel = form.querySelector('#f-category');
  const desc = form.querySelector('#f-desc');
  const hint = form.querySelector('#desc-hint');
  const amount = form.elements.amount;
  const checks = () => Array.from(form.querySelectorAll('input[name=charged_to]'));
  const typeNow = () => form.elements.type.value;
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
    box.textContent = `Each of ${n} owes ${money(share)}. Total ${money(share * n)}. Surplus to team ${money(share * n - amt)}.`;
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
  const typeSel = form.querySelector('#f-type');
  if (typeSel && !typeSel.disabled) typeSel.addEventListener('change', applyType);
  catSel && catSel.addEventListener('change', refreshDesc);
  amount.addEventListener('input', preview);
  form.addEventListener('change', e => { if (e.target.name === 'charged_to') preview(); });
  form.querySelectorAll('[data-select]').forEach(b => b.addEventListener('click', () => {
    checks().forEach(c => { c.checked = b.dataset.select === 'players' ? c.dataset.kind === 'player' : false; });
    preview();
  }));
  applyType();
}
