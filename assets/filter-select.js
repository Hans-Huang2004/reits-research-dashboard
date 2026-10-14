/* Single-choice filter menus; the original selects remain the event/data source. */
const controls = new Map();
const arrow = '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m6 8 4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
let menu;
let active = null;
let highlighted = -1;
let nativePopover = false;
let typed = '';
let typedAt = 0;
let menuSignature = '';

const optionsFor = control => [...control.select.options].filter(option => !option.disabled);
const signatureFor = control => JSON.stringify([control.select.value, optionsFor(control).map(option => [option.value, option.textContent])]);

function positionMenu() {
  if (!active) return;
  const rect = active.button.getBoundingClientRect();
  const viewport = window.visualViewport;
  const leftEdge = (viewport?.offsetLeft || 0) + 12;
  const topEdge = (viewport?.offsetTop || 0) + 12;
  const rightEdge = leftEdge + (viewport?.width || innerWidth) - 24;
  const bottomEdge = topEdge + (viewport?.height || innerHeight) - 24;
  if (rect.bottom < topEdge || rect.top > bottomEdge) { closeFilterMenu(); return; }
  const width = Math.min(Math.max(rect.width, 208), rightEdge - leftEdge);
  const below = Math.max(0, bottomEdge - rect.bottom - 8);
  const above = Math.max(0, rect.top - topEdge - 8);
  const upward = below < Math.min(menu.scrollHeight, 280) && above > below;
  const height = Math.min(320, upward ? above : below);
  menu.style.width = `${width}px`;
  menu.style.maxHeight = `${height}px`;
  menu.style.left = `${Math.max(leftEdge, Math.min(rect.left, rightEdge - width))}px`;
  menu.style.top = `${upward ? rect.top - Math.min(menu.scrollHeight, height) - 8 : rect.bottom + 8}px`;
  menu.dataset.direction = upward ? 'up' : 'down';
}

function highlight(index, scroll = true) {
  const options = optionsFor(active);
  highlighted = Math.max(0, Math.min(index, options.length - 1));
  [...menu.children].forEach((item, i) => item.classList.toggle('is-highlighted', i === highlighted));
  const item = menu.children[highlighted];
  if (item) {
    active.button.setAttribute('aria-activedescendant', item.id);
    if (scroll) item.scrollIntoView({ block: 'nearest' });
  }
}

function renderMenu() {
  if (!active) return;
  menuSignature = signatureFor(active);
  const options = optionsFor(active);
  menu.replaceChildren(...options.map((option, index) => {
    const item = document.createElement('div');
    item.className = 'filter-option';
    item.id = `filter-option-${active.select.id}-${index}`;
    item.setAttribute('role', 'option');
    item.setAttribute('aria-selected', String(option.value === active.select.value));
    item.dataset.index = index;
    const text = document.createElement('span');
    text.textContent = option.textContent;
    const check = document.createElement('span');
    check.className = 'filter-option-check';
    check.textContent = '✓';
    check.setAttribute('aria-hidden', 'true');
    item.append(text, check);
    return item;
  }));
  highlight(Math.max(0, options.findIndex(option => option.value === active.select.value)), false);
  positionMenu();
}

export function closeFilterMenu(restoreFocus = false) {
  if (!active) return;
  const control = active;
  active = null;
  control.button.setAttribute('aria-expanded', 'false');
  control.button.removeAttribute('aria-activedescendant');
  if (nativePopover && menu.matches(':popover-open')) menu.hidePopover();
  else if (!nativePopover) menu.hidden = true;
  typed = '';
  if (restoreFocus) control.button.focus({ preventScroll: true });
}

function openMenu(control, edge) {
  closeFilterMenu();
  active = control;
  menu.setAttribute('aria-labelledby', control.label.id);
  control.button.setAttribute('aria-expanded', 'true');
  renderMenu();
  if (active !== control) return;
  if (nativePopover) menu.showPopover();
  else menu.hidden = false;
  positionMenu();
  if (active !== control) return;
  if (edge === 'first') highlight(0);
  else if (edge === 'last') highlight(optionsFor(control).length - 1);
  else highlight(highlighted);
}

function choose(index) {
  if (!active) return;
  const control = active;
  const option = optionsFor(control)[index];
  if (!option) return;
  const changed = control.select.value !== option.value;
  control.select.value = option.value;
  closeFilterMenu(true);
  if (changed) control.select.dispatchEvent(new Event('change', { bubbles: true }));
  syncFilterSelects();
}

function onKey(event, control) {
  const opened = active === control;
  const key = event.key;
  if (key === 'Tab') { closeFilterMenu(); return; }
  if (key === 'Escape' && opened) { event.preventDefault(); closeFilterMenu(true); return; }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(key)) {
    event.preventDefault();
    if (!opened) { openMenu(control, key === 'Home' ? 'first' : key === 'End' ? 'last' : undefined); return; }
    if (event.altKey && key === 'ArrowUp') { closeFilterMenu(true); return; }
    if (key === 'Enter' || key === ' ') choose(highlighted);
    else if (key === 'Home') highlight(0);
    else if (key === 'End') highlight(optionsFor(control).length - 1);
    else highlight(highlighted + (key === 'ArrowDown' ? 1 : -1));
    return;
  }
  if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
    event.preventDefault();
    if (!opened) openMenu(control);
    const now = Date.now();
    typed = now - typedAt < 700 ? typed + key : key;
    typedAt = now;
    const index = optionsFor(control).findIndex(option => option.textContent.toLowerCase().startsWith(typed.toLowerCase()));
    if (index >= 0) highlight(index);
  }
}

export function syncFilterSelects() {
  for (const control of controls.values()) {
    control.value.textContent = control.select.selectedOptions[0]?.textContent || control.select.options[0]?.textContent || '全部';
    control.button.classList.toggle('is-filtered', Boolean(control.select.value));
    control.button.disabled = control.select.disabled;
  }
  if (active && signatureFor(active) !== menuSignature) renderMenu();
}

export function enhanceFilterSelects() {
  menu = document.createElement('div');
  menu.className = 'filter-menu';
  menu.id = 'filter-select-options';
  menu.setAttribute('role', 'listbox');
  nativePopover = typeof menu.showPopover === 'function';
  if (nativePopover) menu.setAttribute('popover', 'auto');
  else menu.hidden = true;
  document.body.append(menu);
  document.querySelectorAll('.filters select').forEach(select => {
    const label = document.querySelector(`label[for="${select.id}"]`);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'filter-select';
    button.id = `${select.id}-trigger`;
    button.setAttribute('role', 'combobox');
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', menu.id);
    const value = document.createElement('span');
    value.className = 'filter-select-value';
    value.id = `${select.id}-value`;
    button.setAttribute('aria-labelledby', `${label.id} ${value.id}`);
    button.append(value);
    button.insertAdjacentHTML('beforeend', arrow);
    const control = { select, button, value, label };
    controls.set(select.id, control);
    label.htmlFor = button.id;
    select.hidden = true;
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    select.after(button);
    button.addEventListener('click', () => active === control ? closeFilterMenu() : openMenu(control));
    button.addEventListener('keydown', event => onKey(event, control));
    select.addEventListener('change', syncFilterSelects);
    new MutationObserver(syncFilterSelects).observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled', 'selected'] });
  });
  menu.addEventListener('mousedown', event => {
    if (event.target.closest('[data-index]')) event.preventDefault();
  });
  menu.addEventListener('pointermove', event => {
    const item = event.target.closest('[data-index]');
    if (item && active) highlight(Number(item.dataset.index), false);
  });
  menu.addEventListener('click', event => {
    const item = event.target.closest('[data-index]');
    if (item) choose(Number(item.dataset.index));
  });
  menu.addEventListener('toggle', () => {
    if (active && nativePopover && !menu.matches(':popover-open')) closeFilterMenu();
  });
  document.addEventListener('pointerdown', event => {
    if (active && !menu.contains(event.target) && !active.button.contains(event.target) && event.target !== active.label) closeFilterMenu();
  }, true);
  document.addEventListener('focusin', event => {
    if (active && !active.button.contains(event.target) && !menu.contains(event.target)) closeFilterMenu();
  });
  window.addEventListener('scroll', event => {
    if (active && (!(event.target instanceof Node) || !menu.contains(event.target))) positionMenu();
  }, true);
  window.addEventListener('resize', positionMenu);
  window.visualViewport?.addEventListener('resize', positionMenu);
  window.visualViewport?.addEventListener('scroll', positionMenu);
  syncFilterSelects();
}
