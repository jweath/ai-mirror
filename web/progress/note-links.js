'use strict';

// Render authored notes as text, making only complete HTTPS URLs interactive.
function appendHttpsNote(parent, value) {
  const text = String(value ?? ''), doc = parent.ownerDocument;
  let cursor = 0;
  for (const match of text.matchAll(/https:\/\/[^\s<>"'`]+/gi)) {
    let href = match[0].replace(/[.,;!?]+$/, '');
    for (const [close, open] of [[')', '('], [']', '['], ['}', '{']]) {
      while (href.endsWith(close) && href.split(close).length > href.split(open).length) href = href.slice(0, -1);
    }
    let url;
    try { url = new URL(href); } catch { continue; }
    if (url.protocol !== 'https:' || !url.hostname || url.username || url.password) continue;
    parent.append(doc.createTextNode(text.slice(cursor, match.index)));
    const anchor = doc.createElement('a');
    anchor.textContent = href;
    anchor.href = href;
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
    parent.append(anchor);
    cursor = match.index + href.length;
  }
  parent.append(doc.createTextNode(text.slice(cursor)));
  return parent;
}

if (typeof module !== 'undefined' && module.exports) module.exports = {appendHttpsNote};
