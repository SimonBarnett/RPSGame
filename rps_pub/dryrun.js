/* Headless 5-game dry run of RPS.createSim using the same JSON as Python. */
const { pathToFileURL } = require('url');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const src = fs.readFileSync(__dirname + '/rps.js', 'utf8');
const sandbox = {
  console,
  performance: { now: () => Date.now() },
  Math,
  window: undefined,
  location: { protocol: 'file:' }
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const RPS = sandbox.RPS;
if (!RPS || !RPS.createSim) {
  console.error('RPS.createSim missing');
  process.exit(1);
}

function loadJSON(p) {
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

function loadBooks() {
  const root = path.join(__dirname, 'strategies');
  const meta = loadJSON(path.join(root, 'meta.json'));
  const books = {};
  for (const t of ['ROCK', 'PAPER', 'SCISSORS']) {
    const dir = path.join(root, 'types', t);
    const idx = loadJSON(path.join(dir, 'index.json'));
    const book = { type: t, cards: {}, base: {}, meta: meta };
    try { book.base = loadJSON(path.join(dir, '_base.json')) || {}; } catch (e) {}
    for (const id of idx) {
      if (!id || id[0] === '_') continue;
      const fp = path.join(dir, id + '.json');
      if (!fs.existsSync(fp)) continue;
      book.cards[id] = loadJSON(fp);
    }
    books[t] = book;
  }
  return books;
}

const books = loadBooks();
const nCards = Object.keys(books.ROCK.cards).length;
console.log('js_books', nCards, 'ids', Object.keys(books.ROCK.cards).sort().slice(0, 8).join(','));

function playOne(seed) {
  const thinkErr = [];
  const sim = RPS.createSim({
    width: 800, height: 600,
    teamSize: 8,
    forts: 5,
    seed: seed,
    books: books,
    onThinkError: (err) => { thinkErr.push(String(err && err.message || err)); }
  });
  sim.forts.forEach(f => { f.scale = 1; });
  sim.particles.forEach(p => { p.scale = 1; });
  sim.startClock();
  const t0 = Date.now();
  let frames = 0;
  const cap = 8000;
  while (!sim.winner && frames < cap) {
    sim.step(true);
    frames++;
  }
  const c = sim.counts();
  return {
    seed, frames, ms: Date.now() - t0,
    winner: sim.winner || 'TIMEOUT',
    ROCK: c.ROCK, PAPER: c.PAPER, SCISSORS: c.SCISSORS,
    think_errors: thinkErr.length,
    think_sample: thinkErr.slice(0, 2)
  };
}

const wins = { ROCK: 0, PAPER: 0, SCISSORS: 0, TIMEOUT: 0, NONE: 0 };
const rows = [];
let failed = 0;
for (let i = 0; i < 5; i++) {
  try {
    const r = playOne(1000 + i * 17);
    rows.push(r);
    wins[r.winner] = (wins[r.winner] || 0) + 1;
    console.log(JSON.stringify(r));
    if (r.think_errors) failed += r.think_errors;
  } catch (e) {
    failed++;
    console.error('GAME_FAIL', i, e && e.stack || e);
  }
}
console.log('WINS', JSON.stringify(wins));
console.log('think_errors_total', failed);
if (failed) process.exit(2);
