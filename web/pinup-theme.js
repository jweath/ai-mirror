'use strict';
(() => {
  const allowed = ['auto', 'light', 'dark'];
  const media = matchMedia('(prefers-color-scheme: dark)');
  let selected = 'auto';
  try { const saved = localStorage.getItem('mirror-pinup-theme'); if (allowed.includes(saved)) selected = saved; } catch {}
  function apply() { document.documentElement.dataset.theme = selected === 'auto' ? (media.matches ? 'dark' : 'light') : selected; }
  apply();
  media.addEventListener('change', apply);
  document.addEventListener('DOMContentLoaded', () => {
    const control = document.getElementById('theme');
    control.value = selected;
    control.addEventListener('change', () => {
      selected = allowed.includes(control.value) ? control.value : 'auto';
      try { localStorage.setItem('mirror-pinup-theme', selected); } catch {}
      apply();
    });
  });
})();
