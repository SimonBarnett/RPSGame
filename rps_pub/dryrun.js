/* Headless 10-game dry run of RPS.createSim */
const { pathToFileURL } = require('url');
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(__dirname + '/rps.js', 'utf8');
const sandbox = { console, performance: { now: () => Date.now() }, Math, window: undefined, location: { protocol: 'file:' } };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const RPS = sandbox.RPS;
if (!RPS || !RPS.createSim) {
  console.error('RPS.createSim missing');
  process.exit(1);
}

function playOne(seed) {
  let s = seed;
  const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 0x100000000; };
  const sim = RPS.createSim({ width: 1280, height: 720, teamSize: 8 + (seed % 7), forts: 4 + (seed % 5) });
  sim.forts.forEach(f => { f.scale = 1; });
  sim.particles.forEach(p => { p.scale = 1; });
  sim.startClock();
  const t0 = Date.now();
  let frames = 0;
  const cap = 20000;
  while (!sim.winner && frames < cap) {
    sim.step(true);
    frames++;
  }
  const c = sim.counts();
  return {
    seed, frames, ms: Date.now() - t0,
    winner: sim.winner || 'TIMEOUT',
    ROCK: c.ROCK, PAPER: c.PAPER, SCISSORS: c.SCISSORS,
    leftover: Object.keys(c).filter(k => c[k] > 0).length
  };
}

const wins = { ROCK: 0, PAPER: 0, SCISSORS: 0, TIMEOUT: 0, NONE: 0 };
const rows = [];
for (let i = 0; i < 10; i++) {
  const r = playOne(1000 + i * 17);
  rows.push(r);
  wins[r.winner] = (wins[r.winner] || 0) + 1;
  console.log(JSON.stringify(r));
}
console.log('WINS', JSON.stringify(wins));
const finished = rows.filter(r => r.winner !== 'TIMEOUT');
const avgF = finished.reduce((a, b) => a + b.frames, 0) / Math.max(1, finished.length);
console.log('avg_frames_finished', Math.round(avgF), 'timeouts', wins.TIMEOUT);
