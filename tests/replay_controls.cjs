// Node-only control checks with a minimal DOM. Usage: node tests/replay_controls.cjs runs/demo/replay.html
// This exercises the actual embedded JS, but is not a Colab/browser integration test.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
const id = html.match(/<div id="([^"]+)" class="archery-replay"/)[1];
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
let queue = [], rafId = 0;
class Element {
  constructor() { this.handlers = {}; this.children = []; this.style = {}; this.dataset = {}; this.value = ''; this.textContent = ''; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  appendChild(e) { this.children.push(e); }
  replaceChildren() { this.children = []; }
  fire(name) { this.handlers[name](); }
}
function rootElement() {
  const root = new Element(), nodes = new Map();
  root.isConnected = true;
  root.querySelector = selector => {
    if (!nodes.has(selector)) nodes.set(selector, new Element());
    return nodes.get(selector);
  };
  const canvas = root.querySelector('canvas');
  canvas.width = 1120; canvas.height = 620;
  const ctx = new Proxy({}, {get: (target, key) => target[key] || (() => {})});
  canvas.getContext = () => ctx;
  root.querySelector('[data-speed]').options = [.5, 1, 2, 4, 8].map(value => ({value: String(value)}));
  return root;
}
const first = rootElement(), second = rootElement();
let currentRoot = first;
const context = vm.createContext({
  document: {getElementById: () => currentRoot, createElement: () => new Element()},
  requestAnimationFrame: fn => { queue.push(fn); return ++rafId; }, console
});
vm.runInContext(script, context);
const get = s => first.querySelector(`[data-${s}]`);
const fire = (s, event = 'click') => get(s).fire(event);
const advance = milliseconds => { const pending = queue; queue = []; pending.forEach(fn => fn(milliseconds)); };
assert.equal(Number(first.dataset.currentTime), 0);
fire('next'); assert.ok(Number(first.dataset.currentTime) > 0);
fire('prev'); assert.equal(Number(first.dataset.currentTime), 0);
get('seek').value = '12.3'; fire('seek', 'input');
assert.equal(Number(first.dataset.currentTime), 12.3, 'seek should retain requested value across pause/render');
fire('play'); advance(1000); advance(1100);
assert.ok(Math.abs(Number(first.dataset.currentTime) - 12.5) < 1e-8, '2x playback uses wall-clock time');
fire('play'); const paused = first.dataset.currentTime; advance(1200);
assert.equal(first.dataset.currentTime, paused);
get('speed').value = '0.5'; fire('speed', 'change');
fire('play'); advance(2000); advance(2100);
assert.ok(Math.abs(Number(first.dataset.currentTime) - 12.55) < 1e-8);
fire('play');
get('seek').value = get('seek').max; fire('seek', 'input');
assert.ok(get('result').textContent.includes('获胜'));
assert.equal(Number(first.dataset.currentTime), Number(get('seek').max));
fire('play'); assert.equal(Number(first.dataset.currentTime), 0, 'playing a completed replay restarts it');
fire('reset'); assert.equal(first.dataset.playing, 'false');
currentRoot = second; vm.runInContext(script.replaceAll(id, id + '-second'), context);
second.querySelector('[data-next]').fire('click');
assert.equal(Number(first.dataset.currentTime), 0, 'widgets keep independent state');
assert.ok(Number(second.dataset.currentTime) > 0);
console.log('Replay controls passed: seek, step, play/pause, speed, terminal state, restart, independent widgets.');
