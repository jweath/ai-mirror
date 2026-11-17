const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {appendHttpsNote} = require('../web/progress/note-links.js');

// A small DOM adapter keeps these tests offline; no HTML is parsed or executed.
const doc = {
  createTextNode(text) { return {textContent:text}; },
  createElement(tagName) { return {tagName, textContent:''}; },
};
function render(text) {
  const children=[];
  appendHttpsNote({ownerDocument:doc, append(node) {children.push(node);}},text);
  return {text:children.map(n=>n.textContent).join(''), links:children.filter(n=>n.tagName==='a')};
}
test('preserves original prose, labels and newlines around multiple links',()=>{
  const text='Keep the human next step.\n\nCreative links:\nPoster: https://example.com/a?x=1&y=2\nActivity: https://example.net/b';
  const result=render(text);
  assert.equal(result.text,text);
  assert.deepEqual(result.links.map(a=>a.href),['https://example.com/a?x=1&y=2','https://example.net/b']);
  for(const anchor of result.links) {
    assert.equal(anchor.target,'_blank'); assert.equal(anchor.rel,'noopener noreferrer');
  }
});
test('HTML, scripts and javascript/data/http links remain inert text',()=>{
  const text='<img src=x onerror=alert(1)> <script>alert(2)</script> javascript:alert(3) data:text/html,hi http://example.com';
  assert.deepEqual(render(text),{text,links:[]});
});
test('only HTTPS and complete hostnames become links',()=>{
  const text='https:// https:///bad:port https://example.com:bad https://safe.example/path';
  const result=render(text);
  assert.equal(result.text,text);
  assert.deepEqual(result.links.map(a=>a.href),['https://safe.example/path']);
});
test('credential-bearing links remain plain text',()=>{
  const text='https://user:password@example.com/a https://user@example.com/b';
  assert.deepEqual(render(text),{text,links:[]});
});
test('surrounding punctuation is retained outside anchors',()=>{
  const text='See (https://example.com/a), [https://example.org/b].';
  const result=render(text);
  assert.equal(result.text,text);
  assert.deepEqual(result.links.map(a=>a.href),['https://example.com/a','https://example.org/b']);
});
test('balanced parentheses in paths are preserved',()=>{
  const result=render('https://example.com/a_(b)');
  assert.equal(result.links[0].href,'https://example.com/a_(b)');
});
test('quoted attribute-looking content is text, never anchor markup',()=>{
  const text='https://example.com/" onclick="alert(1) <b>hello</b>';
  const result=render(text);
  assert.equal(result.text,text);
  assert.equal(result.links.length,1);
  assert.equal(result.links[0].href,'https://example.com/');
  assert.equal(result.links[0].onclick,undefined);
});
test('empty notes and repeated links preserve exact text',()=>{
  assert.equal(render('').text,'');
  const text='https://example.com https://example.com';
  assert.equal(render(text).text,text); assert.equal(render(text).links.length,2);
});
test('card, detail and timeline use the renderer loaded before progress code',()=>{
  const source=readFileSync(require.resolve('../web/progress/progress.js'),'utf8');
  const page=readFileSync(require.resolve('../web/progress/index.html'),'utf8');
  assert.equal((source.match(/appendHttpsNote\(/g)||[]).length,3);
  assert.ok(page.indexOf('/assets/note-links.js')<page.indexOf('/assets/progress.js'));
});
