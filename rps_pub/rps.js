/* Rock Paper Scissors — embeddable canvas.
 * Keep next to strategies/types/{ROCK,PAPER,SCISSORS}/
 *   RPS.mount('#rps')
 */
(function (global) {
  'use strict';
  const BUILD = { n: 20, gen: 8, games: 9126, at: "2026-09-12 18:53Z", sha: "a14a321" };
  /**
   * rps.js — live-play port of the Python Rock / Paper / Scissors arena.
   * Learning, metrics CSV, and the optimiser stay in Python.
   *
   * Heading convention (same as phys.integrate):
   *   angle 0 = up (−Y),  x += sin(a)*speed,  y -= cos(a)*speed
   *
   * Pipeline per marble, per frame (think):
   *   gameState → pickCard (hold hysteresis) → RankDir 12-sector
   *   → boids / voronoi / chase → applyMoves(JSON fn) → wall/fort slide
   */

  // RPS triangle. PREY = who I convert; FEAR = who converts me.
  const PREY = { ROCK: 'SCISSORS', PAPER: 'ROCK', SCISSORS: 'PAPER' };
  const FEAR = { ROCK: 'PAPER', PAPER: 'SCISSORS', SCISSORS: 'ROCK' };
  const COLOR = {
    ROCK: [236, 78, 108],
    PAPER: [247, 196, 48],
    SCISSORS: [70, 178, 230]
  };
  const DEFAULT_MOTION = {
    ROCK: { speed: 1.22, turn: 14.06 },
    PAPER: { speed: 1.76, turn: 12.06 },
    SCISSORS: { speed: 1.33, turn: 12.84 }
  };
  const CRUISE_MULT = 5.5;
  const LAST_MAN_FEAR_SPEED = 1.25;
  // Match phase machine (arena.MatchPhase).
  const PHASE = {
    TITLE: 'TITLE',
    FORTS: 'FORTS',
    SPAWN: 'SPAWN',
    COUNT: 'COUNT',
    PLAY: 'PLAY',
    WIN: 'WIN',
    FORTS_OUT: 'FORTS_OUT'
  };
  const WALL_RESTITUTION = 0.92;
  const PAIR_RESTITUTION = 0.35;
  const FRIEND_RESTITUTION = 0.55;
  const PAIR_FRICTION = 0.32;
  const FRIEND_FRICTION = 0.06;
  const WALL_FRICTION = 0.04;
  const FORT_FRICTION = 0.08;
  const FORT_RESTITUTION = 0.75;
  const COLLISION_SPEED_KEEP = 0.5;
  const SEPARATION_SLOP = 0.5;
  const SLIP_DAMP = 0.42;
  const SPIN_DAMP = 0.985;
  const THRUST = 0.22;
  const MASS = { ROCK: 1.35, SCISSORS: 1.0, PAPER: 0.72 };
  const FORT_STAGGER_MS = 90;
  const FORT_INTRO_MS = 900;
  const FORT_OUTRO_MS = 800;
  const PARTICLE_RISE_PX = 220;
  const PARTICLE_INTRO_MS = 1100;
  const PARTICLE_STAGGER_MS = 40;
  const ICON_FILE = { ROCK: 'rock.png', PAPER: 'paper.png', SCISSORS: 'scissors.png' };
  const ICONS = { ROCK: null, PAPER: null, SCISSORS: null };
  // config LIGHT_DX/DY + shell Phong z. World-fixed, does not spin with roll.
  const LIGHT = { x: -0.32, y: -0.55, z: 0.76 };
  const COLLIDE_WAV_B64 = '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4f/M/7v/tP+5/8j/3f/w//r/+f/x/+X/2v/U/9P/1f/a/+H/6P/t/+3/6v/n/+T/5P/n/+v/7f/t/+r/4//b/9b/1f/Y/93/4f/j/+b/6//y//f/+f/6//f/8v/q/+L/2v/W/9r/4v/t//X/+f/1/+z/4f/W/9D/0f/b/+n/9/8BAAMA/v/2/+//6f/m/+f/7f/1//3/AwACAPr/6//a/8z/x//O/+D/9v8LABYAFQAIAPj/7P/n/+r/8f/1//X/8v/t/+b/3v/Z/9r/4P/s//r/BgAMAA4ACwAFAP3/9v/w/+v/6f/r//D/9//8//3/+v/1//H/7f/s/+//9f/6////AwAGAAgACgAJAAUA/v/2/+//6//r/+//9f/6//v/+v/3//b/+P/7//7/AAABAAEAAwAGAAgABgAAAPb/6v/h/93/4P/p//T///8FAAUAAwD///3//v8CAAcADQAQABAACgAAAPb/7f/l/+L/4v/n/+//+f8DAAsAEAARAAwABQD+//j/9P/y//L/8//0//f/+//+/wEAAwAEAAEA/f/6//f/9v/4//3/AwAKAA8AEAANAAgAAgD7//P/7f/p/+r/7v/2////BwAOABEAEAAMAAUA/f/1//D/8P/z//r/AgAHAAcABgAEAAEA////////////////AAACAAYACgAKAAcAAQD5//H/7f/w//f/AAAJAA8ADwAKAAMA/f/8////BQAKAA0ADwANAAgAAQD5//P/7//w//L/8//3//3/BQAOABcAHQAcABcADgAFAP7//P/+/wAAAgADAAIA/f/5//X/9P/1//r/AQAJABIAGAAZABUADwAHAAEA/P/7//3/AgAHAAoABwAAAPr/9//4//3/BQANABIAEwAQAAoABAAAAP7//f/9//7//v8AAAUACwASABcAGQAWAA8ABwD///r/+v/9////AAAAAAAAAQAEAAgADAAOABEAEwASAA8ACgAGAAIAAQACAAMABAAFAAUABQAGAAkACwANAA8AEAAOAAoABwADAAAA///+////AgAIAA0ADwAOAAwACAAFAAIAAQACAAUACQAOABEAFAAUABIADQAIAAMAAQABAAMAAwAEAAUABwAJAAwADwARAA8ADAAHAAMAAgAEAAgACwAOAA0ACwAHAAcACAALAA4AEAAPAA4ADQAMAAsACgAKAAkACAAJAAoACwAKAAoACQAHAAcACAAKAA0AEQAWABgAGAAUAA0ABQD+//v//P8BAAcADQASABUAFwAWABMAEAANAAkABwAFAAUABgAIAAsADQAPABEAEwAUABQAEwAQAAwACAAFAAIAAQACAAMABAAGAAsAEAAVABoAGwAZABUADwAKAAgACAAIAAkACQAKAAoADAANAA4ADgAOAA0ACgAIAAYABgAGAAgADAAPABIAEgASABAADQAMAAsACgAKAAsADAANAA8ADwAOAAsACAAEAAIAAwAGAAsAEQAVABYAEwAQAAwACAAFAAQABAAEAAYACQALAA4AEAAQAA4ACwAIAAYABgAIAAsADAAOAA8AEAAPAA0ACgAHAAUABAAEAAYACAAKAAkACAAGAAYABgAIAAoADAANAA4ADgAMAAkABwAGAAUABQAGAAcABwAIAAgACAAIAAkACQAIAAgACAAHAAcABwAHAAcABwAHAAgACAAIAAcABQADAAMAAwAEAAcACQALAAsACwAJAAYABAABAP///v/+/wAAAgAGAAoADQAPAA8ADAAJAAUAAgD///7//v///wEAAwAGAAgACAAHAAUAAwACAAMABAAEAAQABAAEAAMABAAEAAUABQAFAAQAAgABAAEAAQACAAQABgAHAAYABQACAAAA////////AAABAAIAAwADAAMAAwADAAMABAAEAAQAAwABAAAA///+//7///8BAAIAAwAEAAMAAgACAAEAAQD///7//f/8//z//f/+////AQACAAIAAgACAAIAAwADAAIAAQD///7//f/8//z//P/9//7/AAABAAEAAAD//////v/+//////////////////////8AAAAA/////////v/+//3//f/8//3//f/+////AAABAAEAAAAAAP7//f/8//z/+//8//z//f/+//7///////7//v/+//7//v/+//////////////////7//v/9//z/+//7//v//P/9//7//////wAAAAD//////v/9//3//f/9//3//P/8//z//P/9//7//v/////////////////+//3//P/8//z//f/9//7//v/+//7//v/+//7//v/+//7//v/9//3//f/9//3//v/+//3//f/9//3//f/9//3//f/+//7//v/////////+//7//v/+//7//v/+//3//P/8//z//P/8//3//f/+//7////////////+//7//v/9//7//v/+//7//v/+//3//f/9//3//f/+//////////////////7//f/9//z//P/8//z//f/9//7//v////////////////////////////7//v/9//3//f/9//3//f/9//7//v/+//7//v///////////////v/9//3//f/9//3//v/+//7//v/////////////////+//7//f/9//z//f/9//7///////////////7//v/+//7//f/9//3//v/+//7//////////v/+//7//v/9//7//v/+///////+//7//v/9//3//v/+//7//v/+//7//v/+//7//v/+//7//v/////////+//7//v/+//7//v/+//3//f/9//3//v/+//7///8AAAAAAAD///7//v/9//3//f/+//7////////////+//7//f/9//7//v/+//////////7//v/+//7//v/+//7//v/+//////8AAAAA//////7//f/9//3//f/9//7//////wAAAAD////////+//7//v/+//7//v/+//7//v/+//7//v/+//7////////////////////+//7//v/+//7//////////////////v/+//7//v/+//7/////////AAAAAP///////////v///////////////////////////////v/+//7//v////////8AAAAA//////////////////////////////////////////////////////////////////////////////////8AAAAAAAAAAP///////////////////////////////wAAAAAAAAAA/////////////////////wAA/////////////////////wAAAAAAAP////////////////////////////////////////////////////8AAAAAAAAAAAAAAAD//////////////////////////////////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD//////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';


  function AudioBus(base) {
    const root = String(base || './sound/').replace(/\/?$/, '/');
    let ctx = null, enabled = false, lastClick = 0;
    const buffers = {};
    function ac() {
      if (!ctx) {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return null;
        ctx = new AC();
      }
      if (enabled && ctx.state === 'suspended') ctx.resume();
      return ctx;
    }
    function loadWav(name) {
      if (typeof location !== 'undefined' && location.protocol === 'file:') return Promise.resolve();
      return fetch(root + name).then(r => r.ok ? r.arrayBuffer() : null).then(b => {
        if (!b || !ac()) return;
        return new Promise((res) => ctx.decodeAudioData(b.slice(0), res, () => res(null)));
      }).then(buf => { if (buf) buffers[name] = buf; }).catch(() => {});
    }
    function decodeB64(b64) {
      try {
        const bin = atob(b64);
        const buf = new ArrayBuffer(bin.length);
        const v = new Uint8Array(buf);
        for (let i = 0; i < bin.length; i++) v[i] = bin.charCodeAt(i);
        return buf;
      } catch (e) { return null; }
    }
    function loadEmbedded(name, b64) {
      const raw = decodeB64(b64);
      if (!raw || !ac()) return;
      ctx.decodeAudioData(raw.slice(0), (buf) => { buffers[name] = buf; }, () => {});
    }
    if (location.protocol !== 'file:') { loadWav('collide.wav'); loadWav('bounce.wav'); }
    loadEmbedded('collide.wav', COLLIDE_WAV_B64);
    function beep(freq, dur, vol) {
      const c = ac(); if (!c || !enabled) return;
      const o = c.createOscillator(), g = c.createGain();
      o.type = 'square'; o.frequency.value = freq;
      const t0 = c.currentTime;
      g.gain.setValueAtTime(0, t0);
      g.gain.linearRampToValueAtTime(vol, t0 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      o.connect(g); g.connect(c.destination);
      o.start(t0); o.stop(t0 + dur + 0.02);
    }
    function playBuf(name, vol) {
      const c = ac(); if (!c || !enabled) return false;
      const buf = buffers[name]; if (!buf) return false;
      const src = c.createBufferSource(), g = c.createGain();
      g.gain.value = vol;
      src.buffer = buf; src.connect(g); g.connect(c.destination); src.start();
      return true;
    }
    return {
      prime() {
        ac();
        if (!buffers['collide.wav'] && typeof COLLIDE_WAV_B64 === 'string') loadEmbedded('collide.wav', COLLIDE_WAV_B64);
      },
      set on(v) { enabled = !!v; },
      get on() { return enabled; },
      count(n) {
        if (n === 3) beep(440, 0.28, 0.18);
        else if (n === 2) beep(554, 0.28, 0.18);
        else if (n === 1) beep(659, 0.28, 0.18);
        else beep(880, 0.42, 0.22);
      },
      collide() {
        const now = performance.now();
        if (now - lastClick < 40) return;
        lastClick = now;
        if (!playBuf('collide.wav', 0.45)) beep(220, 0.06, 0.12);
      },
      bounce() {
        if (!playBuf('bounce.wav', 0.12)) beep(160, 0.04, 0.06);
      }
    };
  }

  function loadIcons(base) {
    const root = String(base || './images/').replace(/\/?$/, '/');
    function names(t) {
      const pascal = ICON_FILE[t];
      const lower = t.toLowerCase() + '.png';
      const upper = t + '.png';
      return [lower, pascal, upper];
    }
    function tryLoad(t) {
      const list = names(t);
      return new Promise((res) => {
        let i = 0;
        function next() {
          if (i >= list.length) { res(null); return; }
          const img = new Image();
          img.onload = () => { ICONS[t] = img; res(img); };
          img.onerror = () => { i++; next(); };
          img.src = root + list[i];
        }
        next();
      });
    }
    return Promise.all(Object.keys(ICON_FILE).map(tryLoad));
  }

  /** Draw the type PNG (or a coloured disc fallback) centred at x,y. */
  function drawIcon(ctx, type, x, y, size, rot) {
    const img = ICONS[type];
    if (!img || !img.width) return false;
    ctx.save();
    ctx.translate(x, y);
    if (rot) ctx.rotate(rot);
    ctx.drawImage(img, -size / 2, -size / 2, size, size);
    ctx.restore();
    return true;
  }

  function lightAxes() {
    const llen = Math.hypot(LIGHT.x, LIGHT.y) || 1;
    const toL = { x: LIGHT.x / llen, y: LIGHT.y / llen };
    return { toL: toL, shadow: { x: -toL.x, y: -toL.y } };
  }
  /** fort.py fort_occlusion — 0..1, light-aligned shaft + penumbra. */
  function fortOcc(sim, x, y, pr) {
    pr = pr || 0;
    const forts = sim.forts || [];
    if (!forts.length) return 0;
    const toL = lightAxes().toL;
    const lengthK = 5.5, pen = 0.55;
    let best = 0;
    for (let i = 0; i < forts.length; i++) {
      const f = forts[i];
      const sc = f.scale == null ? 1 : f.scale;
      if (sc < 0.15) continue;
      const r = f.r * sc;
      if (r < 4) continue;
      const fx = f.x - x, fy = f.y - y;
      const t = fx * toL.x + fy * toL.y;
      if (t <= 0) continue;
      const maxlen = r * lengthK;
      if (t > maxlen) continue;
      const perp = Math.abs(fx * toL.y - fy * toL.x);
      const half = r + pr + pen * r * (t / Math.max(r, 1)) * 0.25;
      if (perp > half) continue;
      const along = 1 - t / maxlen;
      const across = Math.max(0, 1 - perp / Math.max(half, 1e-6));
      const occ = (0.35 + 0.65 * along) * across * Math.min(1, sc);
      if (occ > best) best = occ;
    }
    return Math.max(0, Math.min(1, best));
  }
  /** fort.py marble_shadow_clip → {mode, ang, occ} none|cap|full. */
  function marbleClip(sim, x, y, rad) {
    const ax = lightAxes();
    const pl = fortOcc(sim, x + ax.toL.x * rad, y + ax.toL.y * rad, 0);
    const pd = fortOcc(sim, x + ax.shadow.x * rad, y + ax.shadow.y * rad, 0);
    const pc = fortOcc(sim, x, y, rad * 0.15);
    const ang = Math.atan2(ax.shadow.x, -ax.shadow.y);
    if (pl < 0.08 && pd < 0.08 && pc < 0.08) return { mode: 'none', ang: ang, occ: 0 };
    if (pl > 0.22 && pd > 0.22) return { mode: 'full', ang: ang, occ: Math.max(pl, pd, pc) };
    if (pd >= pl) return { mode: 'cap', ang: ang, occ: Math.max(pd, pc) };
    return { mode: 'cap', ang: ang + Math.PI, occ: Math.max(pl, pc) };
  }

  function cssRgb(c, a) {
    if (a == null) return 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')';
    return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')';
  }
  function mulberry32(seed) {
    var a = seed | 0;
    return function () {
      a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, a | 1);
      t = t + Math.imul(t ^ t >>> 7, t | 61) | 0;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function rand(a, b) { return a + Math.random() * (b - a); }
  function irand(a, b) { return a + Math.floor(Math.random() * (b - a + 1)); }
  function angNorm(a) {
    a = a % (Math.PI * 2);
    if (a < 0) a += Math.PI * 2;
    return a;
  }
  function snapVal(v, scale) { return Math.floor(v * scale + 0.5) / scale; }
  function snapSigned(v, scale) {
    if (v >= 0) return snapVal(v, scale);
    return -snapVal(-v, scale);
  }
  function ensureVel(p) {
    if (p.vx == null || p.vy == null) {
      const sp = p.speed || 0;
      p.vx = Math.sin(p.angle) * sp;
      p.vy = -Math.cos(p.angle) * sp;
    }
    if (p.omega == null) p.omega = 0;
  }
  function massOf(p) {
    const sz = p.size || 18;
    return (MASS[p.type] || 1) * (sz / 18) * (sz / 18);
  }
  function inertiaOf(p, mass) {
    const sz = p.size || 18;
    const m = mass == null ? massOf(p) : mass;
    return 0.5 * m * sz * sz;
  }
  function omegaCross(omega, rx, ry) {
    return { x: -omega * ry, y: omega * rx };
  }
  function applyPlaneImpulse(p, nx, ny, rx, ry, e, mu) {
    ensureVel(p);
    const mass = massOf(p);
    const inertia = inertiaOf(p, mass);
    const o = omegaCross(p.omega, rx, ry);
    const vcx = p.vx + o.x, vcy = p.vy + o.y;
    const relN = vcx * nx + vcy * ny;
    if (relN >= 0) return;
    const invM = 1 / Math.max(1e-9, mass);
    const jn = -(1 + e) * relN / invM;
    const tx = -ny, ty = nx;
    const relT = vcx * tx + vcy * ty;
    const rxt = rx * ty - ry * tx;
    const kt = invM + (rxt * rxt) / Math.max(1e-9, inertia);
    let jt = -relT / Math.max(1e-9, kt);
    const maxJ = mu * Math.abs(jn);
    if (jt > maxJ) jt = maxJ;
    else if (jt < -maxJ) jt = -maxJ;
    const jx = jn * nx + jt * tx;
    const jy = jn * ny + jt * ty;
    p.vx += jx * invM;
    p.vy += jy * invM;
    p.omega += (rx * jy - ry * jx) / Math.max(1e-9, inertia);
  }
  function applyPairImpulse(a, b, nx, ny, e, mu) {
    ensureVel(a); ensureVel(b);
    const ra = a.size, rb = b.size;
    const rax = nx * ra, ray = ny * ra;
    const rbx = -nx * rb, rby = -ny * rb;
    const ao = omegaCross(a.omega, rax, ray);
    const bo = omegaCross(b.omega, rbx, rby);
    const rvx = (a.vx + ao.x) - (b.vx + bo.x);
    const rvy = (a.vy + ao.y) - (b.vy + bo.y);
    const relN = rvx * nx + rvy * ny;
    if (relN > 0) return;
    const ma = massOf(a), mb = massOf(b);
    const ia = inertiaOf(a, ma), ib = inertiaOf(b, mb);
    const invA = 1 / Math.max(1e-9, ma), invB = 1 / Math.max(1e-9, mb);
    const jn = -(1 + e) * relN / Math.max(1e-9, invA + invB);
    const tx = -ny, ty = nx;
    const relT = rvx * tx + rvy * ty;
    const rxta = rax * ty - ray * tx;
    const rxtb = rbx * ty - rby * tx;
    const kt = invA + invB + (rxta * rxta) / Math.max(1e-9, ia) + (rxtb * rxtb) / Math.max(1e-9, ib);
    let jt = -relT / Math.max(1e-9, kt);
    const maxJ = mu * Math.abs(jn);
    if (jt > maxJ) jt = maxJ;
    else if (jt < -maxJ) jt = -maxJ;
    const jx = jn * nx + jt * tx;
    const jy = jn * ny + jt * ty;
    a.vx += jx * invA; a.vy += jy * invA;
    b.vx -= jx * invB; b.vy -= jy * invB;
    a.omega += (rax * jy - ray * jx) / Math.max(1e-9, ia);
    b.omega += (rbx * jy - rby * jx) / Math.max(1e-9, ib);
    a.speed = Math.hypot(a.vx, a.vy);
    b.speed = Math.hypot(b.vx, b.vy);
  }
  function snapPose(p) {
    p.x = snapVal(p.x, 1e4);
    p.y = snapVal(p.y, 1e4);
    p.angle = snapVal(angNorm(p.angle), 1e6);
    ensureVel(p);
    p.vx = snapSigned(p.vx, 1e4);
    p.vy = snapSigned(p.vy, 1e4);
    p.omega = snapSigned(p.omega, 1e6);
    p.speed = snapVal(Math.max(0, Math.hypot(p.vx, p.vy)), 1e6);
  }
  function angDiff(a, b) {
    return Math.atan2(Math.sin(b - a), Math.cos(b - a));
  }
  /** World heading from A to B under the 0=up convention. */
  function headingTo(ax, ay, bx, by) {
    return Math.atan2(bx - ax, -(by - ay));
  }
  const ROLL_TILT = 0.62;
  /** Project the floor-contact speckle after a no-slip roll (arena/marble.py). */
  function rollSpeckle(heading, roll) {
    // marble.py roll_speckle_proj — floor contact P0=(0,0,-1), axis N×H
    const hx = Math.sin(heading);
    const hy = -Math.cos(heading);
    const s = Math.sin(roll), c = Math.cos(roll);
    const qx = -hx * s, qy = -hy * s, qz = -c;
    if (qz < -0.02 && (qx * hx + qy * hy) > 0.08) return null;
    return { qx: qx, qy: qy, qz: qz, sx: qx, sy: qy - ROLL_TILT * qz };
  }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

  function scriptBase() {
    const scripts = document.getElementsByTagName('script');
    for (let i = scripts.length - 1; i >= 0; i--) {
      const src = scripts[i].src || '';
      if (/rps\.js(\?|$)/i.test(src)) return src.replace(/\/[^\/]*rps\.js(\?.*)?$/i, '/');
    }
    return './';
  }
  function isMobile() {
    const short = Math.min(window.innerWidth || 800, window.innerHeight || 800);
    return !!(window.matchMedia && (
      window.matchMedia('(pointer: coarse)').matches ||
      window.matchMedia('(max-width: 800px)').matches
    )) || short < 720;
  }
  function marbleScale() { const w = (typeof window !== 'undefined' && window) ? Math.min(window.innerWidth || 900, window.innerHeight || 900) : 900; return w < 600 ? 1 : 2; }
  function fitCanvas(canvas, el) {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const vv = window.visualViewport;
    const cw = Math.max(320, Math.floor((vv && vv.width) || el.clientWidth || window.innerWidth || 800));
    const ch = Math.max(240, Math.floor((vv && vv.height) || el.clientHeight || window.innerHeight || 600));
    canvas.style.width = cw + 'px';
    canvas.style.height = ch + 'px';
    canvas.width = Math.floor(cw * dpr);
    canvas.height = Math.floor(ch * dpr);
    const ctx = canvas.getContext('2d');
    if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { w: cw, h: ch, dpr: dpr };
  }

  async function loadJSON(url) {
    if (location.protocol === 'file:') return null;
    const r = await fetch(url, { cache: 'no-store', mode: 'cors', credentials: 'omit' });
    if (!r.ok) return null;
    return r.json();
  }
  async function loadTeamBook(base, type) {
    const root = base.replace(/\/+$/, '') + '/' + type + '/';
    const book = { type: type, cards: {}, base: {} };
    book.base = (await loadJSON(root + '_base.json')) || {};
    let names = [
      'PACK_HUNT','CLEAR_SPLIT','CLEAR_FAN','FINISH_CLOCK','LAST_MAN_RUN',
      'SURVIVE_FEAR','LAST_PREY_CARE','LAST_MEAL_STALL','ESCORT_RING',
      'ORBIT_KITE','FORT_KITE','OPEN_KITE','SHADOW_PREY','HOLD_COVER',
      'REGROUP_MASS','SCATTER_RAID','SCREEN_HUNT','GIVE_GROUND'
    ];
    try {
      const idx = await loadJSON(root + 'index.json');
      if (Array.isArray(idx)) names = idx;
    } catch (e) {}
    book.cards = Object.assign({}, DEFAULT_CARDS);
    if (location.protocol === 'file:') return book;
    await Promise.all(names.map(async (id) => {
      if (!id || id === 'index' || id[0] === '_') return;
      try {
        const live = await loadJSON(root + id + '.json');
        if (live) book.cards[id] = Object.assign({}, DEFAULT_CARDS[id] || {}, live);
      } catch (e) {}
    }));
    return book;
  }

  // Mirrors config.effective_strategy _game_state (order matters).
  /** effective_strategy _game_state. Order is the Python order. */
  function gameState(counts, type, lastPreyMax) {
    const selfN = counts[type] || 0;
    const preyN = counts[PREY[type]] || 0;
    const fearN = counts[FEAR[type]] || 0;
    const lp = (lastPreyMax != null && isFinite(+lastPreyMax)) ? (+lastPreyMax | 0) : 2;
    if (selfN <= 0) return 'DEAD';
    if (fearN <= 0 && preyN > 0) return 'CLEAR_HUNT';
    if (fearN > 0 && preyN <= 0) return 'NO_PREY_FEAR_ALIVE';
    if (selfN === 1 && fearN > 0) return 'LAST_MAN';
    if (selfN <= 2 && fearN > 0) return 'NEAR_WIPE';
    if (fearN > 0 && preyN <= lp) return 'LAST_PREY_RISK';
    if (fearN > selfN) return 'OUTNUMBERED';
    if (selfN <= 3 && fearN > 0) return 'SMALL_UNIT';
    return 'CONTESTED';
  }
  const CARD_FOR_STATE = {
    CLEAR_HUNT: ['CLEAR_SPLIT', 'CLEAR_FAN', 'FINISH_CLOCK', 'PACK_HUNT'],
    LAST_PREY_RISK: ['LAST_PREY_CARE', 'DELAY_FEAST', 'LAST_MEAL_ORBIT'],
    LAST_MAN: ['LAST_MAN_RUN', 'SURVIVE_FEAR', 'ORBIT_KITE'],
    NEAR_WIPE: ['BODY_CHECK', 'LAST_MAN_RUN', 'SURVIVE_FEAR', 'SCATTER_RAID'],
    NO_PREY_FEAR_ALIVE: ['SURVIVE_FEAR', 'ORBIT_KITE', 'SHADOW_PREY', 'HOLD_COVER'],
    OUTNUMBERED: ['GIVE_GROUND', 'HOLD_COVER', 'SHADOW_PREY'],
    SMALL_UNIT: ['SCATTER_RAID', 'OPEN_KITE', 'SCREEN_HUNT'],
    CONTESTED: ['SCREEN_HUNT', 'OPEN_KITE', 'LANE_SWEEP', 'PACK_HUNT']
  };
  /** Play-only pick from JSON. Learning (UCB / Thompson / EI) stays in Python. */

  function cardMean(spec, state) {
    const st = (spec && spec.stats) || {};
    const slot = ((st.by_state || {})[state]) || {};
    const a = +(slot.alpha != null ? slot.alpha : (st.alpha != null ? st.alpha : 1));
    const b = +(slot.beta != null ? slot.beta : (st.beta != null ? st.beta : 1));
    if (!isFinite(a) || !isFinite(b) || a + b <= 0) return 0.33;
    return a / (a + b);
  }

  function legalFromJson(book, state) {
    const cards = (book && book.cards) || {};
    const type = (book && book.type) || '';
    const meta = (book && book.meta) || {};
    const banned = (meta.banned && meta.banned[type]) || [];
    const force = ((meta.force && meta.force[type]) || {})[state] || [];
    const ids = Object.keys(cards);
    let legal = [];
    for (let i = 0; i < ids.length; i++) {
      const id = ids[i];
      if (!id || id[0] === '_') continue;
      const spec = cards[id] || {};
      if (spec.enabled === false) continue;
      if (banned.indexOf(id) >= 0) continue;
      const states = (spec.when && spec.when.states) || [];
      if (states.indexOf(state) >= 0) legal.push(id);
    }
    if (force.length) {
      const forced = [];
      for (let i = 0; i < force.length; i++) {
        const id = force[i];
        if (cards[id] && banned.indexOf(id) < 0) forced.push(id);
      }
      if (forced.length) legal = forced;
    }
    if (!legal.length) {
      const pool = CARD_FOR_STATE[state] || CARD_FOR_STATE.CONTESTED;
      for (let i = 0; i < pool.length; i++) {
        if (cards[pool[i]] && banned.indexOf(pool[i]) < 0) legal.push(pool[i]);
      }
    }
    if (state === 'LAST_PREY_RISK') {
      const care = CARD_FOR_STATE.LAST_PREY_RISK || [];
      legal = legal.filter(function (id) { return care.indexOf(id) >= 0; });
      if (!legal.length) {
        for (let i = 0; i < care.length; i++) {
          if (cards[care[i]] && banned.indexOf(care[i]) < 0) legal.push(care[i]);
        }
      }
    }
    return legal;
  }

  const DEFAULT_CARDS = {
    PACK_HUNT: { movement: [{fn:'sectors.orient',blend:0.35},{fn:'desync.heading',blend:0.35},{fn:'intercept.heading',blend:0.4},{fn:'lanes.heading',blend:0.3}] },
    SCREEN_HUNT: { movement: [{fn:'sectors.orient',blend:0.4},{fn:'boids.desired_heading',blend:0.35},{fn:'lanes.heading',blend:0.3}] },
    OPEN_KITE: { movement: [{fn:'orbit.heading',blend:0.45},{fn:'sectors.orient',blend:0.3}] },
    ESCORT_RING: { movement: [{fn:'form.slot_heading',blend:0.4},{fn:'boids.desired_heading',blend:0.3}] },
    CLEAR_SPLIT: { movement: [{fn:'voronoi.assign',blend:1},{fn:'intercept.heading',blend:0.7}] },
    CLEAR_FAN: { movement: [{fn:'voronoi.assign',blend:1},{fn:'lanes.heading',blend:0.45}] },
    FINISH_CLOCK: { movement: [{fn:'time.heading',blend:0.7},{fn:'intercept.heading',blend:0.5}] },
    LAST_PREY_CARE: { movement: [{fn:'sectors.orient',blend:0.7},{fn:'boids.desired_heading',blend:0.3}] },
    LAST_MEAL_STALL: { movement: [{fn:'orbit.heading',blend:0.65},{fn:'desync.heading',blend:0.3}] },
    GIVE_GROUND: { movement: [{fn:'sectors.orient',blend:0.5},{fn:'cover.cover_heading',blend:0.4}] },
    DELAY_FEAST: { movement: [{fn:'orbit.heading',blend:0.6},{fn:'flow.heading',blend:0.3}] },
    LAST_MAN_RUN: { movement: [{fn:'sectors.orient',blend:0.6},{fn:'cover.cover_heading',blend:0.35}] },
    SURVIVE_FEAR: { movement: [{fn:'sectors.orient',blend:0.55},{fn:'cover.cover_heading',blend:0.45}] },
    ORBIT_KITE: { movement: [{fn:'orbit.heading',blend:0.65}] },
    SHADOW_PREY: { movement: [{fn:'roles.heading',blend:0.4},{fn:'cover.cover_heading',blend:0.3}] },
    HOLD_COVER: { movement: [{fn:'cover.cover_heading',blend:0.7}] },
    REGROUP_MASS: { movement: [{fn:'boids.desired_heading',blend:0.5}] },
    SCATTER_RAID: { movement: [{fn:'boids.desired_heading',blend:0.35},{fn:'intercept.heading',blend:0.45}] },
    BODY_CHECK: { movement: [{fn:'intercept.fear',blend:0.75},{fn:'boids.desired_heading',blend:0.3}] },
    HASH_MELEE: { movement: [{fn:'hash.heading',blend:0.7},{fn:'boids.desired_heading',blend:0.25}] },
    LOS_SPRING: { movement: [{fn:'cover.clear',blend:0.7},{fn:'cover.cover_heading',blend:0.35}] }
  };
  function pickCard(book, state) {
    const legal = legalFromJson(book, state);
    if (!legal.length) {
      const pool = CARD_FOR_STATE[state] || CARD_FOR_STATE.CONTESTED;
      return pool[0];
    }
    const cards = (book && book.cards) || {};
    let best = legal[0], bestS = -1e9;
    for (let i = 0; i < legal.length; i++) {
      const spec = cards[legal[i]] || {};
      const pri = +((spec.when || {}).priority || 50);
      const mu = cardMean(spec, state);
      const s = mu * 10 + pri * 0.01;
      if (s > bestS) { bestS = s; best = legal[i]; }
    }
    return best;
  }
  /** Playbook hold-frame hysteresis per type. */
  function pickCardHold(teamHold, type, book, state) {
    const desired = pickCard(book, state);
    const spec = book && book.cards && book.cards[desired];
    const holdNeed = Math.max(1, intish((spec && spec.switch && spec.switch.hold_frames) || 8));
    const margin = floatish((spec && spec.switch && spec.switch.margin) || 1.0);
    const slot = teamHold[type] || { card: null, frames: 0 };
    if (ENDGAME_STATES[state] && slot.card !== desired) {
      teamHold[type] = { card: desired, frames: 0 };
      return desired;
    }
    if (!slot.card || slot.card === desired) {
      teamHold[type] = { card: desired, frames: 0 };
      return desired;
    }
    const legal = legalFromJson(book, state);
    if (legal.indexOf(slot.card) < 0) {
      teamHold[type] = { card: desired, frames: 0 };
      return desired;
    }
    slot.frames += 1;
    if (slot.frames >= holdNeed * margin) {
      teamHold[type] = { card: desired, frames: 0 };
      return desired;
    }
    teamHold[type] = slot;
    return slot.card;
  }
  function intish(v) { v = +v; return isFinite(v) ? (v | 0) : 8; }
  function floatish(v) { v = +v; return isFinite(v) ? v : 1; }
  function cardMoves(book, id) {
    const spec = (book && book.cards && book.cards[id]) || DEFAULT_CARDS[id];
    return (spec && spec.movement) || (DEFAULT_CARDS.PACK_HUNT.movement);
  }



  // 12-dir RankDir (config.TurnRelative). Centres are relative to facing.
  const SECTORS = [
    { id: 0, name: 'FRONT', c: 0, drag: 1.00 },
    { id: 1, name: 'LEFT', c: -Math.PI / 4, drag: 0.82 },
    { id: 2, name: 'RIGHT', c: Math.PI / 4, drag: 0.82 },
    { id: 3, name: 'LEFT30', c: -Math.PI / 6, drag: 0.90 },
    { id: 4, name: 'RIGHT30', c: Math.PI / 6, drag: 0.90 },
    { id: 5, name: 'LEFT60', c: -Math.PI / 3, drag: 0.72 },
    { id: 6, name: 'RIGHT60', c: Math.PI / 3, drag: 0.72 },
    { id: 7, name: 'LEFT90', c: -Math.PI / 2, drag: 0.55 },
    { id: 8, name: 'RIGHT90', c: Math.PI / 2, drag: 0.55 },
    { id: 9, name: 'LEFT135', c: -Math.PI * 3 / 4, drag: 0.42 },
    { id: 10, name: 'RIGHT135', c: Math.PI * 3 / 4, drag: 0.42 },
    { id: 11, name: 'BACK', c: Math.PI, drag: 0.35 }
  ];
  const ENDGAME_STATES = { CLEAR_HUNT:1, LAST_MAN:1, NO_PREY_FEAR_ALIVE:1, NEAR_WIPE:1, LAST_PREY_RISK:1 };
  const FEAR_BUILD = 0.35, FEAR_DECAY = 0.04, FEAR_DECAY_FAST = 0.18;
  function sectorOf(bearing) {
    let best = 0, bd = 1e9;
    for (let i = 0; i < SECTORS.length; i++) {
      const d = Math.abs(angDiff(SECTORS[i].c, bearing));
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }
  /** Score every sector: fear → risk, prey → reward, friends → packing. */
  function rankDirs(p, particles, c) {
    const selfN = c[p.type] || 0;
    const preyN = c[PREY[p.type]] || 0;
    const fearN = c[FEAR[p.type]] || 0;
    const near = 5 * p.size, far = 30 * p.size;
    const scores = SECTORS.map(function (s) {
      return { id: s.id, name: s.name, c: s.c, risk: 0, reward: 0, conf: 0.4, nFear: 0, nPrey: 0, nFriend: 0 };
    });
    for (let i = 0; i < particles.length; i++) {
      const q = particles[i];
      if (q === p) continue;
      const dx = q.x - p.x, dy = q.y - p.y;
      const dist = Math.hypot(dx, dy);
      if (dist > far || dist < 0.5) continue;
      if (typeof forts !== 'undefined' && fortOccludes(forts, p.x, p.y, q.x, q.y, 2)) continue;
      let df;
      if (dist <= near) df = 1;
      else df = 1 - (dist - near) / (far - near);
      if (df <= 0) continue;
      const bear = angDiff(p.angle, headingTo(p.x, p.y, q.x, q.y));
      const s = scores[sectorOf(bear)];
      if (q.type === FEAR[p.type]) {
        let fm = 1 + 0.35 * df;
        if (dist < 10 * p.size) fm *= 2.6;
        if (fearN >= selfN) fm *= 1.35;
        s.risk += Math.max(0.35, df * fm);
        s.nFear++;
      } else if (q.type === PREY[p.type]) {
        let amt = df;
        if (df > 0.5) amt *= 1.6;
        if (df > 0.8) amt += 0.5;
        if (fearN > 0 && preyN <= 2) amt *= Math.max(0, (preyN - 1) / 3);
        else if (fearN <= 0) amt *= 3.0;
        s.reward += amt;
        s.nPrey++;
        if (df > 0.5) s.risk *= 0.75;
      } else if (q.type === p.type) {
        s.nFriend++;
        if (selfN < fearN) s.risk += df * 0.5;
        if (dist < p.size * 5) s.risk += df * 0.25;
      }
    }
    scores.forEach(function (s) {
      s.score = s.reward + s.conf * 0.2 - s.risk * 1.15;
    });
    return scores;
  }
  /** Midpoint shared-boundary Delaunay edges (VoronoiEndgame._delaunay_adj). */
  function delaunayEdges(pts) {
    // pts: [{id,x,y}] midpoint nearest-pair test (Python VoronoiEndgame._delaunay_adj)
    const n = pts.length, edges = [];
    if (n < 2) return edges;
    if (n === 2) { edges.push([pts[0].id, pts[1].id]); return edges; }
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const mx = 0.5 * (pts[i].x + pts[j].x), my = 0.5 * (pts[i].y + pts[j].y);
        let a = null, b = null, da = 1e18, db = 1e18;
        for (let k = 0; k < n; k++) {
          const d = (mx - pts[k].x) * (mx - pts[k].x) + (my - pts[k].y) * (my - pts[k].y);
          if (d < da) { db = da; b = a; da = d; a = pts[k].id; }
          else if (d < db) { db = d; b = pts[k].id; }
        }
        if ((a === pts[i].id && b === pts[j].id) || (a === pts[j].id && b === pts[i].id)) {
          edges.push([pts[i].id, pts[j].id]);
        }
      }
    }
    return edges;
  }

  /** Slerp-like blend of two headings. w=1 → full b. */
  function blendHeadings(a, b, w) {
    if (b == null) return a;
    if (a == null) return b;
    const px = Math.sin(a), py = -Math.cos(a);
    const sx = Math.sin(b), sy = -Math.cos(b);
    const x = px * (1 - w) + sx * w, y = py * (1 - w) + sy * w;
    if (Math.abs(x) + Math.abs(y) < 1e-9) return a;
    return Math.atan2(x, -y);
  }
  /** Intercept: aim at predicted prey position (lookahead frames). */
  function bodyVel(p) {
    if (p.vx != null && p.vy != null) return { x: p.vx, y: p.vy };
    const sp = p.speed || 0;
    return { x: Math.sin(p.angle) * sp, y: -Math.cos(p.angle) * sp };
  }
  function chaseHeading(p, prey, look) {
    if (!prey) return null;
    const v = bodyVel(prey);
    return headingTo(p.x, p.y, prey.x + v.x * look, prey.y + v.y * look);
  }
  /** Split hunters across remaining prey; overflow walks Delaunay neighbours. */
  function voronoiAssign(hunters, preys) {
    const map = {};
    if (!preys.length || !hunters.length) return map;
    const cap = Math.max(1, Math.ceil(hunters.length / preys.length));
    const load = {};
    preys.forEach(function (pr) { load[pr.id] = 0; });
    const pairs = [];
    for (let i = 0; i < hunters.length; i++) {
      for (let j = 0; j < preys.length; j++) {
        const h = hunters[i], pr = preys[j];
        pairs.push({ h: h, pr: pr, d: (h.x - pr.x) * (h.x - pr.x) + (h.y - pr.y) * (h.y - pr.y) });
      }
    }
    pairs.sort(function (a, b) { return a.d - b.d; });
    for (let i = 0; i < pairs.length; i++) {
      const pair = pairs[i];
      if (map[pair.h.id]) continue;
      if (load[pair.pr.id] >= cap) continue;
      map[pair.h.id] = pair.pr;
      load[pair.pr.id]++;
    }
    hunters.forEach(function (h) {
      if (map[h.id]) return;
      let dest = preys[0], best = 1e18;
      preys.forEach(function (pr) {
        const score = load[pr.id] * 1e9 + (h.x - pr.x) * (h.x - pr.x) + (h.y - pr.y) * (h.y - pr.y);
        if (score < best) { best = score; dest = pr; }
      });
      map[h.id] = dest;
      load[dest.id]++;
    });
    return map;
  }
  /** Compact boids: sep always; coh/ali off in CLEAR_HUNT; fear flee; prey pull. */
  function swarmHeading(p, particles, state, prey, fear, w) {
    w = w || {};
    let sx = 0, sy = 0, cx = 0, cy = 0, ax = 0, ay = 0, nSep = 0, nCoh = 0;
    const sepMul = isFinite(+w.sep_distance) ? Math.max(0.6, Math.min(2.2, +w.sep_distance / 6.5)) : 1;
    const sepR = p.size * 3.0 * sepMul;
    for (let i = 0; i < particles.length; i++) {
      const q = particles[i];
      if (q === p || q.type !== p.type) continue;
      const dx = p.x - q.x, dy = p.y - q.y;
      const d2 = dx * dx + dy * dy;
      if (d2 < sepR * sepR && d2 > 1) {
        sx += dx / d2; sy += dy / d2; nSep++;
      }
      if (state !== 'CLEAR_HUNT' && d2 < (p.size * 14) * (p.size * 14)) {
        cx += q.x; cy += q.y; ax += Math.sin(q.angle); ay += -Math.cos(q.angle); nCoh++;
      }
    }
    let fx = 0, fy = 0;
    const sepW = state === 'CLEAR_HUNT' ? 3.4 : ((state === 'LAST_MAN' || state === 'NEAR_WIPE') ? 2.8 : 2.4);
    if (nSep) {
      const m = nSep >= 3 ? 3.0 : 1.6;
      fx += sx * sepW * m; fy += sy * sepW * m;
    }
    const preyObj = prey && (prey.obj || prey);
    const fearObj = fear && (fear.obj || fear);
    // Hunt > flock. Cohesion is what made colour-ghettos in the screenshots.
    if (nCoh && nSep < 2 && !preyObj && state !== 'CLEAR_HUNT' && state !== 'LAST_MAN'
        && state !== 'CONTESTED' && state !== 'SMALL_UNIT') {
      fx += ((cx / nCoh) - p.x) * 0.002;
      fy += ((cy / nCoh) - p.y) * 0.002;
    }
    if (fearObj && state !== 'CLEAR_HUNT') {
      const dx = p.x - fearObj.x, dy = p.y - fearObj.y;
      const d = Math.hypot(dx, dy) || 1;
      if (d < p.size * 8) {
        const fw = (state === 'LAST_MAN' || state === 'NO_PREY_FEAR_ALIVE') ? 0.9 : 1.1;
        fx += (dx / d) * fw; fy += (dy / d) * fw;
      }
    }
    if (preyObj && state !== 'LAST_PREY_RISK') {
      const pd = Math.hypot(preyObj.x - p.x, preyObj.y - p.y);
      if (pd < p.size * 10 && pd > 1) {
        fx += (preyObj.x - p.x) / pd * 0.35;
        fy += (preyObj.y - p.y) / pd * 0.35;
      }
    } else if (preyObj && state === 'LAST_PREY_RISK') {
      const pd = Math.hypot(preyObj.x - p.x, preyObj.y - p.y) || 1;
      if (pd < p.size * 6) {
        fx += (p.x - preyObj.x) / pd * 1.1;
        fy += (p.y - preyObj.y) / pd * 1.1;
      }
    }
    if (Math.abs(fx) + Math.abs(fy) < 0.05) return null;
    return Math.atan2(fx, -fy);
  }

  /** Segment–circle test used by FortLOS.occludes. */
  function lineHitsCircle(ax, ay, bx, by, cx, cy, r) {
    const abx = bx - ax, aby = by - ay;
    const acx = cx - ax, acy = cy - ay;
    const ab2 = abx * abx + aby * aby || 1;
    let t = (acx * abx + acy * aby) / ab2;
    t = Math.max(0, Math.min(1, t));
    const px = ax + abx * t, py = ay + aby * t;
    return (px - cx) * (px - cx) + (py - cy) * (py - cy) < r * r;
  }
  function fortOccludes(forts, ax, ay, bx, by, margin) {
    margin = margin == null ? 2 : margin;
    for (let i = 0; i < forts.length; i++) {
      const f = forts[i];
      if ((f.scale || 1) < 0.7) continue;
      const r = f.r + margin;
      if (lineHitsCircle(ax, ay, bx, by, f.x, f.y, r)) {
        const da = Math.hypot(ax - f.x, ay - f.y);
        const db = Math.hypot(bx - f.x, by - f.y);
        if (da > r + 1 && db > r + 1) return f;
      }
    }
    return null;
  }
  /** Shadow-side of the best fort vs a threat (FortLOS.cover_heading). */
  function coverHeading(p, threat, forts) {
    if (!threat || !forts.length) return null;
    let best = null, bestS = -1e9;
    for (let i = 0; i < forts.length; i++) {
      const f = forts[i];
      if ((f.scale || 1) < 0.7) continue;
      const tx = threat.x - f.x, ty = threat.y - f.y;
      const td = Math.hypot(tx, ty) || 1;
      const hx = f.x - (tx / td) * (f.r + p.size * 1.4);
      const hy = f.y - (ty / td) * (f.r + p.size * 1.4);
      const d = Math.hypot(p.x - hx, p.y - hy);
      const score = 200 / (d + 20) - (fortOccludes(forts, hx, hy, threat.x, threat.y, 2) ? 0 : 40);
      if (score > bestS) { bestS = score; best = { x: hx, y: hy }; }
    }
    return best ? headingTo(p.x, p.y, best.x, best.y) : null;
  }
  /** Blend into nearby prey of another type to mask from predators. */
  function hideAmongPrey(p, preys, fear) {
    if (!preys.length) return null;
    let sx = 0, sy = 0, n = 0;
    for (let i = 0; i < preys.length; i++) {
      const q = preys[i];
      const d = Math.hypot(q.x - p.x, q.y - p.y);
      if (d < 220) { sx += q.x; sy += q.y; n++; }
    }
    if (!n) return null;
    let h = headingTo(p.x, p.y, sx / n, sy / n);
    if (fear) h = blendHeadings(h, headingTo(fear.x, fear.y, p.x, p.y), 0.25);
    return h;
  }
  /** If chase would pin last prey in a corner while predators live, peel to open field. */
  function antiCornerHerd(p, prey, W, H) {
    if (!prey) return null;
    const m = 120;
    const ex = Math.max(0, 1 - Math.min(prey.x, W - prey.x) / m);
    const ey = Math.max(0, 1 - Math.min(prey.y, H - prey.y) / m);
    const cs = Math.min(1, ex * ey * 1.4 + 0.35 * Math.max(ex, ey) * Math.min(ex, ey));
    if (cs < 0.25) return null;
    return headingTo(p.x, p.y, W * 0.5, H * 0.5);
  }
  /** Tangent + radial spring around prey or fort (maths/orbit.py). */
  function orbitHeading(p, anchor, radius) {
    if (!anchor) return null;
    const dx = p.x - anchor.x, dy = p.y - anchor.y;
    const d = Math.hypot(dx, dy) || 1;
    const rx = dx / d, ry = dy / d;
    let tx = -ry, ty = rx;
    const vx = Math.sin(p.angle), vy = -Math.cos(p.angle);
    if (vx * tx + vy * ty < 0) { tx = -tx; ty = -ty; }
    const R = radius || ((anchor.r || anchor.size || 20) + p.size * 3);
    const radial = (d - R) / R;
    const fx = tx - 0.55 * radial * rx;
    const fy = ty - 0.55 * radial * ry;
    return Math.atan2(fx, -fy);
  }
  /** Stable corridor from particle id, mixed toward prey (maths/lanes.py). */
  function laneHeading(p, W, H, prey, idx) {
    const n = 3;
    const i = ((p.id || 0) + (idx || 0)) % n;
    const x = W * (i + 0.5) / n;
    let tx = x, ty = p.y;
    if (prey) { tx = tx * 0.55 + prey.x * 0.45; ty = ty * 0.55 + prey.y * 0.45; }
    return headingTo(p.x, p.y, tx, ty);
  }
  /** Wedge slot around pack COM facing prey (maths/form.py). */
  function formHeading(p, allies, prey) {
    if (!allies.length) return null;
    let cx = 0, cy = 0;
    for (let i = 0; i < allies.length; i++) { cx += allies[i].x; cy += allies[i].y; }
    cx /= allies.length; cy /= allies.length;
    const hx = prey ? prey.x - cx : Math.sin(p.angle);
    const hy = prey ? prey.y - cy : -Math.cos(p.angle);
    const hd = Math.hypot(hx, hy) || 1;
    const px = -hy / hd, py = hx / hd;
    const gap = p.size * 3.2;
    const idx = allies.indexOf(p);
    const off = (idx - (allies.length - 1) / 2) * gap;
    const sx = cx + (hx / hd) * gap * 0.4 + px * off;
    const sy = cy + (hy / hd) * gap * 0.4 + py * off;
    return headingTo(p.x, p.y, sx, sy);
  }
  /** Wall + fort repulsion field (maths/flow.py). */
  function flowHeading(p, W, H, forts) {
    let fx = 0, fy = 0;
    const m = 70;
    if (p.x < m) fx += (m - p.x) / m;
    if (p.x > W - m) fx -= (p.x - (W - m)) / m;
    if (p.y < m) fy += (m - p.y) / m;
    if (p.y > H - m) fy -= (p.y - (H - m)) / m;
    for (let i = 0; i < forts.length; i++) {
      const f = forts[i];
      const dx = p.x - f.x, dy = p.y - f.y;
      const d = Math.hypot(dx, dy) || 1;
      if (d < f.r + 50) { fx += dx / d; fy += dy / d; }
    }
    if (Math.abs(fx) + Math.abs(fy) < 0.05) return null;
    return Math.atan2(fx, -fy);
  }
  /** Density gradient away from crowded neighbours (maths/pressure.py). */
  function pressureHeading(p, particles) {
    let fx = 0, fy = 0;
    for (let i = 0; i < particles.length; i++) {
      const q = particles[i];
      if (q === p) continue;
      const dx = p.x - q.x, dy = p.y - q.y;
      const d2 = dx * dx + dy * dy;
      if (d2 > 1 && d2 < 160 * 160) { fx += dx / d2; fy += dy / d2; }
    }
    if (Math.abs(fx) + Math.abs(fy) < 1e-6) return null;
    return Math.atan2(fx, -fy);
  }
  /** lead = long lookahead; chord = short cutoff (maths/intercept.py). */
  function interceptHeading(p, prey, mode) {
    if (!prey) return null;
    if (mode === 'chord') {
      const v = bodyVel(prey);
      return headingTo(p.x, p.y, prey.x + v.x * 6, prey.y + v.y * 6);
    }
    return chaseHeading(p, prey, 18);
  }
  /** Chase only if convert ETA beats predator ETA (maths/time.py). */
  function timeHeading(p, prey, fear) {
    if (!prey) return null;
    if (!fear) return chaseHeading(p, prey, 12);
    const etaP = Math.hypot(prey.x - p.x, prey.y - p.y) / Math.max(0.4, p.speed);
    const etaF = Math.hypot(fear.x - p.x, fear.y - p.y) / Math.max(0.4, (fear.speed || p.speed));
    if (etaP + 8 < etaF) return chaseHeading(p, prey, 12);
    return headingTo(fear.x, fear.y, p.x, p.y);
  }
  /** Stable fan offset from id so mirrored cards do not stack (maths/desync.py). */
  function desyncHeading(p, prey) {
    const n = 5, span = 0.55;
    const slot = (p.id || 0) % n;
    const mid = (n - 1) * 0.5;
    const off = ((slot - mid) / Math.max(mid, 1)) * span;
    const base = prey ? headingTo(p.x, p.y, prey.x, prey.y) : p.angle;
    return angNorm(base + off);
  }
  /** SCREEN / BAIT / STRIKE / ESCORT from pack index (maths/roles.py). */
  function rolesAssign(members, fearOf) {
    const n = members.length;
    if (!n) return;
    members.sort(function (a, b) { return (a.id || 0) - (b.id || 0); });
    for (let i = 0; i < n; i++) {
      if (n <= 2) members[i]._role = 'STRIKE';
      else if (i === 0) members[i]._role = 'SCREEN';
      else if (i === n - 1) members[i]._role = 'ESCORT';
      else members[i]._role = (i % 2 ? 'STRIKE' : 'BAIT');
    }
  }
  function rolesHeading(p, prey, fear) {
    const role = p._role || 'STRIKE';
    if (role === 'SCREEN' && fear) return headingTo(p.x, p.y, fear.x, fear.y);
    if (role === 'BAIT' && prey) return orbitHeading(p, prey, p.size * 6);
    if (role === 'ESCORT' && prey) return headingTo(p.x, p.y, prey.x, prey.y);
    return prey ? chaseHeading(p, prey, 12) : null;
  }
  /** maths/dispatch.apply — blend strategy JSON movement[].fn onto heading. */
  function applyMoves(want, steps, ctx) {
    const p = ctx.p, state = ctx.state, mode = ctx.mode;
    const prey = ctx.prey && ctx.prey.obj, fear = ctx.fear && ctx.fear.obj;
    let list = (steps || []).slice();
    const CHASE_FNS = { 'time.heading': 1, 'time.eta': 1, 'intercept.heading': 1, 'intercept.lead': 1, 'intercept.chord': 1, 'lanes.heading': 1 };
    if (state === 'LAST_PREY_RISK' || (ctx.fearN > 0 && ctx.preyN <= 1)) {
      list = list.filter(function (s) { return !CHASE_FNS[String((s || {}).fn || '')]; });
    }
    if (state === 'CONTESTED' || state === 'SMALL_UNIT') {
      list = list.filter(function (s) {
        const fn = String((s || {}).fn || '');
        return fn.indexOf('cover.') !== 0;
      });
    }
    if (state === 'CLEAR_HUNT') {
      list = list.filter(function (s) {
        const fn = String((s || {}).fn || '');
        return fn.indexOf('orbit.') !== 0 && fn.indexOf('pressure.') !== 0 && fn.indexOf('cover.') !== 0;
      });
      if (!list.some(function (s) { return String((s || {}).fn || '').indexOf('chase') >= 0; })) {
        list.unshift({ fn: 'sectors.chase_heading', blend: 0.85 });
      }
    } else if (state === 'LAST_MAN' || state === 'NO_PREY_FEAR_ALIVE' || state === 'NEAR_WIPE') {
      const keep = [{ fn: 'sectors.orient', blend: 0.8 }];
      const raid = (state === 'LAST_MAN' && ctx.preyN > 0) || state === 'NEAR_WIPE';
      list.forEach(function (s) {
        const fn = String((s || {}).fn || '');
        if (!raid && (fn.indexOf('orbit.') === 0 || fn.indexOf('time.') === 0 || fn.indexOf('intercept.') === 0)) return;
        keep.push(s);
      });
      if (raid && !keep.some(function (s) {
        const fn = String((s || {}).fn || '');
        return fn.indexOf('chase') >= 0 || fn.indexOf('intercept.') === 0;
      })) keep.push({ fn: 'sectors.chase_heading', blend: 0.55 });
      list = keep;
    }
    function resolve(fn) {
      if (fn === 'flow.heading' || fn === 'flow.force') return flowHeading(p, ctx.W, ctx.H, ctx.forts);
      if (fn === 'roles.heading') return rolesHeading(p, prey, fear);
      if (fn === 'roles.assign') { rolesAssign(ctx.allies || [], FEAR[p.type]); return null; }
      if (fn === 'form.slot_heading') return formHeading(p, ctx.allies || [], prey);
      if (fn === 'orbit.heading') return orbitHeading(p, prey || fear, null);
      if (fn === 'time.heading' || fn === 'time.eta') return timeHeading(p, prey, fear);
      if (fn === 'pressure.heading' || fn === 'pressure.force') return pressureHeading(p, ctx.particles);
      if (fn === 'lanes.heading') return laneHeading(p, ctx.W, ctx.H, prey);
      if (fn === 'intercept.heading' || fn === 'intercept.lead') return interceptHeading(p, prey, 'lead');
      if (fn === 'intercept.fear' || fn === 'intercept.block') return interceptHeading(p, fear, 'lead');
      if (fn === 'intercept.chord') return interceptHeading(p, prey, 'chord');
      if (fn === 'desync.heading') return desyncHeading(p, prey);
      if (fn === 'voronoi.assign' || fn.indexOf('voronoi') >= 0) {
        return prey ? chaseHeading(p, prey, ctx.look || 12) : null;
      }
      if (fn === 'hash.heading' || fn === 'hash.query' || fn.indexOf('hash') >= 0) {
        return prey ? chaseHeading(p, prey, ctx.look || 12) : null;
      }
      if (fn === 'phys.bounce_heading' || fn === 'phys.bounce_walls' || fn.indexOf('bounce') >= 0) {
        const W = ctx.W, H = ctx.H, m = p.size * 3.2;
        let vx = Math.sin(p.angle), vy = -Math.cos(p.angle);
        let hit = false;
        if (p.x > W - m && vx > 0) { vx = -Math.abs(vx); hit = true; }
        else if (p.x < m && vx < 0) { vx = Math.abs(vx); hit = true; }
        if (p.y > H - m && vy > 0) { vy = -Math.abs(vy); hit = true; }
        else if (p.y < m && vy < 0) { vy = Math.abs(vy); hit = true; }
        return hit ? Math.atan2(vx, -vy) : null;
      }
      if (fn === 'cover.clear' || fn === 'cover.clear_heading' || fn === 'cover.occludes') {
        if (prey && !fortOccludes(ctx.forts, p.x, p.y, prey.x, prey.y, 2)) {
          return chaseHeading(p, prey, ctx.look || 12);
        }
        return coverHeading(p, fear, ctx.forts);
      }
      if (fn === 'sectors.chase_heading' || fn.indexOf('chase') >= 0) return prey ? chaseHeading(p, prey, ctx.look || 12) : null;
      if (fn === 'sectors.orient' || fn.indexOf('fear') >= 0) return fear ? headingTo(fear.x, fear.y, p.x, p.y) : null;
      if (fn === 'boids.desired_heading' || fn.indexOf('boids') >= 0) return swarmHeading(p, ctx.particles, state, ctx.prey, ctx.fear);
      if (fn === 'cover.cover_heading' || fn.indexOf('cover') >= 0) return coverHeading(p, fear, ctx.forts);
      if (fn.indexOf('steer') >= 0 || fn.indexOf('wall') >= 0) return flowHeading(p, ctx.W, ctx.H, ctx.forts);
      if (fn.indexOf('hide') >= 0) return hideAmongPrey(p, ctx.preys || [], fear);
      if (fn.indexOf('corner') >= 0) return antiCornerHerd(p, prey, ctx.W, ctx.H);
      return null;
    }
    for (let i = 0; i < list.length; i++) {
      const step = list[i] || {};
      const fn = String(step.fn || '');
      if (!fn) continue;
      if (step.when && step.when !== mode && step.when !== state && step.when !== 'always' && !(step.when === 'chase' && mode === 'chase')) continue;
      const h = resolve(fn);
      if (h == null) continue;
      let blend = step.blend;
      if (blend == null) blend = step.weight != null ? Math.min(1, +step.weight * 0.5) : 0.45;
      want = blendHeadings(want, h, blend);
    }
    return want;
  }

  /** Symmetric fort ring, inset from walls and HUD. */
  function placeForts(W, H, n, pad, randFn) {
    const rnd = randFn || rand;
    const forts = [];
    n = Math.max(0, n | 0);
    if (!n) return forts;
    const cx = W / 2, cy = H / 2;
    const span = Math.min(W, H);
    const rMul = Math.min(W, H) / 720;
    const gap = Math.max(16, span * 0.07);
    const seeds = [];
    let tries = 0;
    const need = Math.ceil(n / 4);
    while (seeds.length < need && tries++ < 250) {
      const r = rnd(22, 36) * rMul;
      const dist = rnd(span * 0.16, span * 0.34);
      const ang = rnd(0.12, Math.PI / 2 - 0.12);
      const x = clamp(cx + dist * Math.cos(ang), pad + r + 8, W - pad - r - 8);
      const y = clamp(cy + dist * Math.sin(ang), pad + r + 8, H - pad - r - 8);
      if (seeds.every(s => Math.hypot(x - s.x, y - s.y) >= r + s.r + gap)) {
        seeds.push({ x: x, y: y, r: r });
      }
    }
    for (const s of seeds) {
      const mirrors = [
        [s.x, s.y], [2 * cx - s.x, s.y], [s.x, 2 * cy - s.y], [2 * cx - s.x, 2 * cy - s.y]
      ];
      for (const [x, y] of mirrors) {
        if (forts.some(f => Math.hypot(x - f.x, y - f.y) < s.r * 1.4)) continue;
        forts.push({ x: x, y: y, r: s.r, scale: 0 });
        if (forts.length >= n) return forts;
      }
    }
    while (forts.length < n && tries++ < 400) {
      const r = rnd(22, 34) * rMul;
      const dist = rnd(span * 0.18, span * 0.38);
      const ang = rnd(0, Math.PI * 2);
      const x = clamp(cx + dist * Math.cos(ang), pad + r + 8, W - pad - r - 8);
      const y = clamp(cy + dist * Math.sin(ang), pad + r + 8, H - pad - r - 8);
      if (forts.some(f => Math.hypot(x - f.x, y - f.y) < r + f.r + gap)) continue;
      forts.push({ x: x, y: y, r: r, scale: 0 });
    }
    return forts;
  }

  function worldMetrics(W, H) {
    const worldK = Math.min(W, H) / 800;
    return {
      W: W, H: H, worldK: worldK,
      pad: Math.max(16, 28 * worldK),
      body: 18 * worldK
    };
  }

  function spawnParticles(W, H, teamSize, forts, pad, body, randFn) {
    const rnd = randFn || rand;
    const particles = [];
    let id = 1;
    const n = Math.max(1, teamSize | 0);
    function spawn(type) {
      let x = 0, y = 0, ok = false, tries = 0;
      while (!ok && tries++ < 50) {
        x = rnd(pad + body * 1.2, W - pad - body * 1.2);
        y = rnd(pad + body * 1.2, H - pad - body * 1.2);
        ok = forts.every(f => Math.hypot(x - f.x, y - f.y) > f.r + body * 1.5)
          && particles.every(q => Math.hypot(x - q.x, y - q.y) > body * 2.3);
      }
      particles.push({ id: id++, type: type, x: x, y: y, angle: rnd(0, Math.PI * 2) });
    }
    for (let i = 0; i < n; i++) {
      spawn('ROCK'); spawn('PAPER'); spawn('SCISSORS');
    }
    return particles;
  }

  function makeStars(W, H) {
    const stars = [];
    for (let i = 0; i < 90; i++) {
      stars.push({
        x: Math.random() * W,
        y: Math.random() * H,
        r: Math.random() < 0.15 ? 1.6 : 0.8,
        b: 140 + Math.random() * 90,
        tw: Math.random() * Math.PI * 2
      });
    }
    return stars;
  }

  /** Headless-capable match: spawn, think, collide, step. Used by mount() and dryrun.js. */
  function createSim(opts) {
    const W = opts.width || 800;
    const H = opts.height || 600;
    // Same game on any screen: distances and speed scale with the short axis.
    // Reference short-axis 720px ≈ desktop window. Turn/frame stays fixed so
    // heading change per body-length is invariant.
    // PY arena ~1200x800, size 20. Desktop marble is 75% of the old JS 24 → 18.
    const seed = opts.seed != null ? (opts.seed >>> 0) : ((Date.now() ^ (Math.random() * 1e9)) >>> 0);
    const rng = mulberry32(seed);
    function srand(a, b) { return a + rng() * (b - a); }
    const wm = worldMetrics(W, H);
    const worldK = wm.worldK;
    const pad = wm.pad;
    const body = wm.body;
    const teamSize = opts.teamSize || irand(6, 14);
    const nForts = opts.forts != null ? opts.forts : irand(4, 8);
    const books = opts.books || {};
    const lastPreyMax = +(((books.ROCK || books.PAPER || books.SCISSORS || {}).meta || {}).last_prey_risk_max) || 2;
    const motion = Object.assign({}, DEFAULT_MOTION);
    for (const t of Object.keys(books)) {
      const b = books[t].base || {};
      if (b.speed_base) motion[t] = { speed: +b.speed_base, turn: +b.turn_base || motion[t].turn };
    }

    const forts = placeForts(W, H, nForts, pad, srand);
    const particles = spawnParticles(W, H, teamSize, forts, pad, body, srand);
    particles.forEach(function (p) {
      p.speed = (motion[p.type] || DEFAULT_MOTION[p.type]).speed * CRUISE_MULT * 0.1 * worldK;
      p.size = body;
      p.vx = Math.sin(p.angle) * p.speed;
      p.vy = -Math.cos(p.angle) * p.speed;
      p.omega = 0;
      p.roll = 0;
      p.scale = 0;
      p._fear_intensity = 0;
      p._frames_since_fear = 0;
    });
    particles.forEach(function (p, i) {
      p.yOff = PARTICLE_RISE_PX;
      p.scale = 0.05;
      p._intro_delay_ms = (i % 3) * 70 + Math.floor(i / 3) * PARTICLE_STAGGER_MS;
    });

    const counts = () => {
      const c = { ROCK: 0, PAPER: 0, SCISSORS: 0 };
      for (const p of particles) c[p.type]++;
      return c;
    };

    /** Reflect heading (0=up). Corners get an extra aim-to-centre shove. */
    function bounceWall(p) {
      ensureVel(p);
      const e = WALL_RESTITUTION, mu = WALL_FRICTION;
      const m = p.size + 1;
      const r = p.size;
      let hit = false;
      if (p.x > W - m) { p.x = W - m; applyPlaneImpulse(p, -1, 0, r, 0, e, mu); hit = true; }
      else if (p.x < m) { p.x = m; applyPlaneImpulse(p, 1, 0, -r, 0, e, mu); hit = true; }
      if (p.y > H - m) { p.y = H - m; applyPlaneImpulse(p, 0, -1, 0, r, e, mu); hit = true; }
      else if (p.y < m) { p.y = m; applyPlaneImpulse(p, 0, 1, 0, -r, e, mu); hit = true; }
      if (hit) {
        let nx = 0, ny = 0;
        if (p.x <= m + 0.5) nx = 1;
        else if (p.x >= W - m - 0.5) nx = -1;
        if (p.y <= m + 0.5) ny = 1;
        else if (p.y >= H - m - 0.5) ny = -1;
        p.angle = Math.atan2(nx, -ny);
        p.speed = Math.max(Math.hypot(p.vx, p.vy), 2.8);
        p.vx = Math.sin(p.angle) * p.speed;
        p.vy = -Math.cos(p.angle) * p.speed;
      } else {
        p.speed = Math.hypot(p.vx, p.vy);
      }
    }
    function leaveHud(p) {
      const hw = W < 520 ? 56 : 120, hh = W < 520 ? 108 : 210;
      const hx = W - hw, hy = hh;
      if (p.x <= hx || p.y >= hy) return;
      if (p.x - hx <= hy - p.y) p.x = hx;
      else p.y = hy;
      p.angle = headingTo(p.x, p.y, W * 0.42, H * 0.58);
    }
    function packEject(p, particles) {
      const edge = p.size * 5.5;
      const onEdge = p.x < edge || p.x > W - edge || p.y < edge || p.y > H - edge;
      if (!onEdge) return null;
      let nx = 0, ny = 0;
      if (p.x < edge) nx = 1;
      else if (p.x > W - edge) nx = -1;
      if (p.y < edge) ny = 1;
      else if (p.y > H - edge) ny = -1;
      return angNorm(Math.atan2(nx, -ny) + ((p.id % 7) - 3) * 0.22);
    }
    function wallEscape(p) {
      const band = p.size * 4.0;
      let fx = 0, fy = 0;
      if (p.x < band) fx += (band - p.x) / band;
      if (p.x > W - band) fx -= (p.x - (W - band)) / band;
      if (p.y < band) fy += (band - p.y) / band;
      if (p.y > H - band) fy -= (p.y - (H - band)) / band;
      if (Math.abs(fx) + Math.abs(fy) < 0.04) return null;
      const corner = (p.x < band || p.x > W - band) && (p.y < band || p.y > H - band);
      return { h: Math.atan2(fx, -fy), w: corner ? 0.85 : 0.7 };
    }
    function unstickAll() {
      for (let pass = 0; pass < 2; pass++) {
        for (let i = 0; i < particles.length; i++) {
          const p = particles[i];
          const minD = p.size * 2.55;
          const minD2 = minD * minD;
          for (let j = i + 1; j < particles.length; j++) {
            const q = particles[j];
            if (q.type !== p.type) continue;
            const dx = p.x - q.x, dy = p.y - q.y;
            const d2 = dx * dx + dy * dy;
            if (d2 >= minD2 || d2 < 1e-8) continue;
            const d = Math.sqrt(d2);
            const push = (minD - d) * 0.85;
            const nx = dx / d, ny = dy / d;
            p.x += nx * push; p.y += ny * push;
            q.x -= nx * push; q.y -= ny * push;
          }
        }
      }
    }
    function bounceFort(p) {
      ensureVel(p);
      for (const f of forts) {
        if ((f.scale || 1) < 0.85) continue;
        const dx = p.x - f.x, dy = p.y - f.y;
        const dist = Math.hypot(dx, dy);
        const minD = p.size + f.r + SEPARATION_SLOP;
        if (dist >= minD || dist < 1e-8) continue;
        const nx = dist < 1e-5 ? Math.sin(p.angle + Math.PI) : dx / dist;
        const ny = dist < 1e-5 ? -Math.cos(p.angle + Math.PI) : dy / dist;
        p.x = f.x + nx * minD;
        p.y = f.y + ny * minD;
        const r = p.size;
        applyPlaneImpulse(p, nx, ny, nx * r, ny * r, FORT_RESTITUTION, FORT_FRICTION);
        p.angle = Math.atan2(nx, -ny);
        p.speed = Math.max(Math.hypot(p.vx, p.vy), 2.4);
        p.vx = Math.sin(p.angle) * p.speed;
        p.vy = -Math.cos(p.angle) * p.speed;
      }
    }
    function nearest(p, type) {
      let best = null, bestD = 1e12;
      const cap = (30 * p.size) * (30 * p.size);
      for (const q of particles) {
        if (q === p || q.type !== type) continue;
        const d2 = (q.x - p.x) ** 2 + (q.y - p.y) ** 2;
        if (d2 < bestD && d2 <= cap) { bestD = d2; best = q; }
      }
      return best ? { obj: best, d: Math.sqrt(bestD) } : null;
    }
    function com(type) {
      let sx = 0, sy = 0, n = 0;
      for (const q of particles) if (q.type === type) { sx += q.x; sy += q.y; n++; }
      return n ? { x: sx / n, y: sy / n, n: n } : null;
    }

    let winner = null;
    let danceId = null;
    let chargeAng = 1.2;
    let t0 = 0;

    const simVoronoi = { key: '', map: {} };
    const teamHold = {
      ROCK: { card: null, frames: 0 },
      PAPER: { card: null, frames: 0 },
      SCISSORS: { card: null, frames: 0 }
    };

    function cardSpec(p) {
      const book = books[p.type] || {};
      return ((book.cards || {})[p.card]) || {};
    }
    function maxSpeedOf(p, c) {
      const mot = motion[p.type];
      const spec = cardSpec(p);
      const base = spec.base || (books[p.type] && books[p.type].base) || {};
      let sp = (+base.speed_base || mot.speed) * CRUISE_MULT * worldK;
      const selfN = c[p.type] || 0;
      const fearN = c[FEAR[p.type]] || 0;
      if (selfN <= 2) sp *= 1.2;
      if (selfN === 1 && fearN > 0) sp *= LAST_MAN_FEAR_SPEED;
      return Math.max(0.8, sp);
    }

    /** Particle.command compact: state, card hold, lock, sectors, swarm, JSON math, slide. */
    function think(p, c) {
      try {
      const selfN = c[p.type] || 0;
      const preyN = c[PREY[p.type]] || 0;
      const fearN = c[FEAR[p.type]] || 0;
      const state = gameState(c, p.type, lastPreyMax);
      const book = books[p.type] || { cards: {} };
      p.card = pickCardHold(teamHold, p.type, book, state);
      p.state = state;
      const preyT = PREY[p.type], fearT = FEAR[p.type];
      const prey = nearest(p, preyT);
      const fear = nearest(p, fearT);
      if (fear && fearN > 0) {
        const near = 5 * p.size, far = 30 * p.size;
        let df = fear.d < near ? 1 : Math.max(0, 1 - (fear.d - near) / Math.max(1, far - near));
        p._fear_intensity = Math.min(1, (p._fear_intensity || 0) + FEAR_BUILD * Math.max(0.3, df));
        p._frames_since_fear = 0;
      } else {
        p._frames_since_fear = (p._frames_since_fear || 0) + 1;
        const rate = fearN <= 0 ? FEAR_DECAY_FAST : FEAR_DECAY;
        const extra = Math.min(0.06, p._frames_since_fear * 0.002);
        p._fear_intensity = Math.max(0, (p._fear_intensity || 0) - rate - extra);
      }
      const fearMem = p._fear_intensity || 0;
      const mot = motion[p.type];
      const spec = cardSpec(p);
      const base = spec.base || book.base || {};
      const maxTurn = (+base.turn_base || mot.turn) * Math.PI / 180;
      const w = spec.weights || {};
      const cruise = maxSpeedOf(p, c);
      let mode = 'idle';
      let want = p.angle;
      const look = 12;

      if (fear && fear.obj) p._lastFear = { x: fear.obj.x, y: fear.obj.y };
      const fobj = (fear && fear.obj) || p._lastFear || null;

      const sectors = rankDirs(p, particles, c);
      const wlook = 90, wmargin = pad + p.size + 22;
      for (let si = 0; si < sectors.length; si++) {
        const s = sectors[si];
        const hx = Math.sin(p.angle + s.c), hy = -Math.cos(p.angle + s.c);
        let pen = 0;
        for (const frac of [0.35, 0.65, 1]) {
          const ax = p.x + hx * wlook * frac, ay = p.y + hy * wlook * frac;
          if (ax < wmargin) pen = Math.max(pen, (wmargin - ax) / wmargin);
          else if (ax > W - wmargin) pen = Math.max(pen, (ax - (W - wmargin)) / wmargin);
          if (ay < wmargin) pen = Math.max(pen, (wmargin - ay) / wmargin);
          else if (ay > H - wmargin) pen = Math.max(pen, (ay - (H - wmargin)) / wmargin);
        }
        if (pen > 0) s.risk += 1.4 * pen;
        s.score = s.reward + s.conf * 0.2 - s.risk * 1.15;
      }
      let bestS = sectors[0];
      let safest = sectors[0];
      for (let si = 1; si < sectors.length; si++) {
        if (sectors[si].score > bestS.score) bestS = sectors[si];
        if (sectors[si].risk < safest.risk) safest = sectors[si];
      }
      const sectorH = angNorm(p.angle + bestS.c);
      const safeH = angNorm(p.angle + safest.c);

      if (fearN > 0 && preyN <= 1 && prey && prey.d < p.size * 6) {
        want = headingTo(prey.obj.x, prey.obj.y, p.x, p.y);
        want = blendHeadings(want, safeH, 0.55);
        mode = 'evade';
        p._locked = null;
      } else if (state === 'CLEAR_HUNT' && preyN > 0) {
        mode = 'chase';
        const hunters = particles.filter(function (q) { return q.type === p.type; });
        const preysL = particles.filter(function (q) { return q.type === preyT; });
        const key = preyT + ':' + preysL.map(function (q) { return q.id; }).sort().join(',') + ':' + Math.floor((simVoronoi.tick || 0) / 8);
        if (simVoronoi.key !== key) {
          simVoronoi.key = key;
          simVoronoi.map = voronoiAssign(hunters, preysL);
        }
        let tgt = simVoronoi.map[p.id] || simVoronoi.map[String(p.id)];
        if (!tgt || tgt.type !== preyT) {
          const ordered = hunters.slice().sort(function (a, b) { return a.id - b.id; });
          let hi = ordered.indexOf(p);
          if (hi < 0) hi = Math.abs(p.id || 0);
          tgt = preysL[hi % preysL.length];
          simVoronoi.map[p.id] = tgt;
        }
        p._locked = tgt;
        want = chaseHeading(p, tgt, look);
      } else if (fear && fobj && fearN > 0 && state !== 'CLEAR_HUNT') {
        const fearAhead = Math.abs(angDiff(p.angle, headingTo(p.x, p.y, fobj.x, fobj.y))) < Math.PI / 2;
        const fearClose = fear.d < 8 * p.size || (fearAhead && fear.d < 12 * p.size);
        if (fearClose) {
          mode = 'evade';
          want = safeH;
          p._locked = null;
        } else if (prey) {
          mode = 'chase';
          want = blendHeadings(chaseHeading(p, prey.obj, look), sectorH, 0.35);
          p._locked = prey.obj;
        }
      } else if (prey) {
        let closer = 0;
        for (let qi = 0; qi < particles.length; qi++) {
          const q = particles[qi];
          if (q === p || q.type !== p.type) continue;
          if (Math.hypot(q.x - prey.obj.x, q.y - prey.obj.y) + p.size < prey.d) closer++;
        }
        if (closer >= 3) {
          mode = 'bias';
          want = sectorH;
          p._locked = null;
        } else {
          mode = 'chase';
          want = blendHeadings(chaseHeading(p, prey.obj, look), sectorH, 0.35);
          p._locked = prey.obj;
        }
      } else {
        want = sectorH;
        mode = 'bias';
      }

      const we = wallEscape(p);
      if (we) want = blendHeadings(want, we.h, we.w);
      const swarm = swarmHeading(p, particles, state, prey, fear, w);
      if (mode === 'evade') want = blendHeadings(want, swarm, 0.35);
      else if (mode === 'chase' && state !== 'CLEAR_HUNT') want = blendHeadings(want, swarm, 0.25);

      if (p._lock_ttl > 0) p._lock_ttl -= 1;
      if (p._locked && p._lock_ttl <= 0) p._locked = null;
      if (mode === 'chase' && p._locked) p._lock_ttl = 80;

      const allies = particles.filter(function (q) { return q.type === p.type; });
      const preys = particles.filter(function (q) { return q.type === preyT; });
      if (!p._role) rolesAssign(allies);

      const hideH = hideAmongPrey(p, preys, fear && fear.obj);
      if (hideH && (state === 'OUTNUMBERED' || state === 'NO_PREY_FEAR_ALIVE')) want = blendHeadings(want, hideH, 0.35);
      const cornerH = antiCornerHerd(p, prey && prey.obj, W, H);
      if (cornerH && fearN > 0 && mode === 'chase') want = blendHeadings(want, cornerH, 0.4);
      const cov = coverHeading(p, fear && fear.obj, forts);
      if (cov && mode === 'evade' && fear && fear.d < p.size * 6) want = blendHeadings(want, cov, 0.25);

      const assigned = (state === 'CLEAR_HUNT') ? p._locked : (prey && prey.obj);
      want = applyMoves(want, cardMoves(book, p.card), {
        p: p, particles: particles, forts: forts, W: W, H: H,
        prey: assigned ? { obj: assigned, d: 0 } : prey, fear: fear, state: state, mode: mode,
        look: look, fearN: fearN, preyN: preyN, allies: allies, preys: preys
      });
      if (state === 'CLEAR_HUNT' && p._locked && particles.indexOf(p._locked) >= 0) {
        want = chaseHeading(p, p._locked, look);
        mode = 'chase';
      }
      // Python last-prey: steer OFF the meal while predators live. Nothing else may overwrite this.
      if (fearN > 0 && preyN <= 1 && prey && prey.obj && prey.d < p.size * 4) {
        want = safeH;
        mode = 'bias';
        p._locked = null;
      }
      if (mode === 'evade') want = angNorm(want + ((p.id % 7) - 3) * 0.2);
      if (fear && fear.obj && state !== 'NEAR_WIPE') {
        const fd = fear.d;
        const fearH = headingTo(p.x, p.y, fear.obj.x, fear.obj.y);
        const flee = angNorm(fearH + Math.PI);
        const pd = (prey && prey.obj) ? prey.d : 1e9;
        const inPath = Math.abs(angDiff(want != null ? want : p.angle, fearH)) < 0.9;
        if (fd < p.size * 4.5) { want = flee; mode = 'evade'; }
        else if (fd < p.size * 6.5 && (fd < pd || inPath)) want = blendHeadings(want, flee, 0.65);
      }
      const we2 = wallEscape(p);
      if (we2) want = blendHeadings(want, we2.h, we2.w);
      const eject = packEject(p, particles);
      if (eject != null) {
        const ew = (mode === 'chase' && prey && prey.obj) ? 0.35 : 0.85;
        want = blendHeadings(want, eject, ew);
      }
      let nearN = 0;
      const r5 = (p.size * 5) * (p.size * 5);
      for (let ai = 0; ai < allies.length; ai++) {
        const q = allies[ai];
        if (q === p) continue;
        const dx = q.x - p.x, dy = q.y - p.y;
        if (dx * dx + dy * dy < r5) nearN++;
      }
      if (nearN >= 3) want = blendHeadings(want, desyncHeading(p, prey && prey.obj), 0.3);

      // evasion brake / reverse (Python apply_evasion, compact)
      if (mode === 'evade' && fear && fear.d < p.size * 6) {
        const ahead = Math.abs(angDiff(p.angle, headingTo(p.x, p.y, fear.obj.x, fear.obj.y)));
        if (ahead < 0.6) p.speed *= 0.72;
      }

      for (let fi = 0; fi < forts.length; fi++) {
        const f = forts[fi];
        if ((f.scale || 1) < 0.85) continue;
        const dx = p.x - f.x, dy = p.y - f.y;
        const d = Math.hypot(dx, dy);
        if (d < f.r + p.size * 3.2) {
          const t1 = Math.atan2(-dy, dx);
          const t2 = angNorm(t1 + Math.PI);
          const tang = Math.abs(angDiff(want, t1)) <= Math.abs(angDiff(want, t2)) ? t1 : t2;
          const out = Math.atan2(dx, -dy);
          const w = d < f.r + p.size * 1.8 ? 0.92 : 0.5;
          want = blendHeadings(blendHeadings(want, tang, w), out, 0.28);
        }
      }

      if (want != null) {
        const dlt = angDiff(p.angle, want);
        p.angle = angNorm(p.angle + Math.max(-maxTurn, Math.min(maxTurn, dlt)));
      }
      let targetSp = cruise;
      if (mode === 'evade') targetSp = cruise * 1.12;
      if (mode === 'chase' && state === 'CLEAR_HUNT') targetSp = cruise * 1.35;
      if (p.speed < targetSp) p.speed += Math.min(THRUST, targetSp - p.speed);
      else p.speed += (targetSp - p.speed) * THRUST;
      if (p.speed > cruise * 1.35) p.speed = cruise * 1.35;
      } catch (err) {
        if (opts.onThinkError) {
          try { opts.onThinkError(err, p); } catch (e2) {}
        }
      }
    }

    /** Convert-on-contact (RPS) or same-type separate. Collisions halve speed. */
    function collide(allowConvert) {
      if (allowConvert == null) allowConvert = true;
      const cNow = counts();
      const typesAlive = (cNow.ROCK > 0 ? 1 : 0) + (cNow.PAPER > 0 ? 1 : 0) + (cNow.SCISSORS > 0 ? 1 : 0);
      const eatCd = typesAlive <= 2 ? 6 : 10;
      for (let k = 0; k < particles.length; k++) {
        if (particles[k]._eat_cd > 0) particles[k]._eat_cd--;
      }
      for (let i = 0; i < particles.length; i++) {
        const a = particles[i];
        for (let j = i + 1; j < particles.length; j++) {
          const b = particles[j];
          const dx = b.x - a.x, dy = b.y - a.y;
          const dist = Math.hypot(dx, dy);
          const minD = a.size + b.size;
          if (dist >= minD || dist < 1e-8) continue;
          const nx = dx / dist, ny = dy / dist;
          const push = (minD - dist + SEPARATION_SLOP) * (a.type === b.type ? 1.15 : 0.55);
          a.x -= nx * push; a.y -= ny * push;
          b.x += nx * push; b.y += ny * push;
          if (a.type === b.type) continue;
          const aEats = PREY[a.type] === b.type;
          const bEats = PREY[b.type] === a.type;
          if (!aEats && !bEats) continue;
          applyPairImpulse(a, b, nx, ny, PAIR_RESTITUTION, PAIR_FRICTION);
          if (!allowConvert) continue;
          const winnerP = aEats ? a : b;
          if ((winnerP._eat_cd || 0) > 0) continue;
          const hx = Math.sin(winnerP.angle), hy = -Math.cos(winnerP.angle);
          const face = aEats ? (hx * nx + hy * ny) : (-hx * nx - hy * ny);
          if (face < 0.25) continue;
          const loser = aEats ? b : a;
          loser.type = winnerP.type;
          winnerP._eat_cd = eatCd;
          const keep = (motion[winnerP.type] || DEFAULT_MOTION[winnerP.type]).speed * CRUISE_MULT * worldK * COLLISION_SPEED_KEEP;
          a.speed = keep; b.speed = keep;
          a.vx = Math.sin(a.angle) * keep; a.vy = -Math.cos(a.angle) * keep;
          b.vx = Math.sin(b.angle) * keep; b.vy = -Math.cos(b.angle) * keep;
          if (opts.onSfx) opts.onSfx('collide');
        }
      }
    }

    function victorySteer(p, dance, tick) {
      const mot = motion[p.type] || DEFAULT_MOTION[p.type] || { speed: 1.3 };
      const cruise = mot.speed * CRUISE_MULT * worldK;
      const ordered = particles.slice().sort(function (a, b) { return a.id - b.id; });
      const n = Math.max(1, ordered.length);
      let idx = 0;
      for (let i = 0; i < n; i++) if (ordered[i].id === p.id) { idx = i; break; }
      const mrg = Math.min(W, H) * 0.22;
      const x0 = mrg, x1 = W - mrg, y0 = mrg, y1 = H - mrg;
      const cx = 0.5 * (x0 + x1), cy = 0.5 * (y0 + y1);
      const rx = 0.38 * (x1 - x0), ry = 0.38 * (y1 - y0);
      const sign = (dance % 2) ? -1 : 1;
      const scale = (dance === 2 && (idx % 2)) ? 0.62 : 1;
      const t2 = sign * (tick * 0.045 + 2 * Math.PI * idx / n + 0.22);
      p.angle = headingTo(p.x, p.y, cx + Math.cos(t2) * rx * scale, cy + Math.sin(t2) * ry * scale);
      p.speed = cruise * 0.95;
      p.vx = Math.sin(p.angle) * p.speed;
      p.vy = -Math.cos(p.angle) * p.speed;
    }

    /** One simulation tick. move=false during countdown (orient only). */
    function step(move, keepAlive) {
      simVoronoi.tick = (simVoronoi.tick || 0) + 1;
      const c = counts();
      const alive = Object.keys(c).filter(k => c[k] > 0);
      if (!winner && alive.length <= 1) {
        winner = alive[0] || 'NONE';
      }
      const playAI = move && !winner;
      if (winner && danceId == null) {
        const rng = mulberry32((seed + (simVoronoi.tick || 0)) | 0);
        danceId = (rng() * 3) | 0;
        chargeAng = rng() * Math.PI * 2;
        if (opts.onSfx) try { opts.onSfx('win'); } catch (e) {}
      }
      if (playAI || !move) {
        for (const p of particles) {
          think(p, c);
          p.angle = snapVal(angNorm(p.angle), 1e6);
          p.speed = snapVal(Math.max(0, p.speed), 1e6);
        }
      } else if (winner && (move || keepAlive)) {
        for (const p of particles) victorySteer(p, danceId, simVoronoi.tick);
      }
      if (move || keepAlive) {
        for (const p of particles) {
          ensureVel(p);
          const hx = Math.sin(p.angle), hy = -Math.cos(p.angle);
          const sp = p.speed || 0;
          const tx = hx * sp, ty = hy * sp;
          p.vx = p.vx * 0.20 + tx * 0.80;
          p.vy = p.vy * 0.20 + ty * 0.80;
          const ox = p.x, oy = p.y;
          p.x += p.vx;
          p.y += p.vy;
          const dist = Math.hypot(p.x - ox, p.y - oy);
          p.omega *= SPIN_DAMP;
          let roll = (p.roll || 0) + p.omega;
          if (dist > 0.15) roll += 0.35 * dist / Math.max(4, p.size);
          p.roll = roll;
          p.x = snapVal(p.x, 1e4);
          p.y = snapVal(p.y, 1e4);
        }
        collide(!winner);
        unstickAll();
        for (const p of particles) {
          bounceWall(p); bounceFort(p);
          p.x = Math.max(p.size + 2, Math.min(W - p.size - 2, p.x));
          p.y = Math.max(p.size + 2, Math.min(H - p.size - 2, p.y));
          snapPose(p);
        }
      }
    }

    return {
      W: W, H: H, pad: pad, forts: forts, particles: particles,
      counts: counts, step: step,
      get winner() { return winner; },
      startClock() { t0 = performance.now(); },
      elapsed() { return t0 ? (performance.now() - t0) / 1000 : 0; },
      freezeTime: 0,
      teamSize: teamSize
    };
  }

  function fmt(s) {
    const m = Math.floor(s / 60), sec = Math.floor(s % 60);
    return String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
  }

  /** Twinkling background stars + dark play-area frame. */
  function drawStarfield(ctx, W, H, stars, t) {
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, '#0c0e1c');
    g.addColorStop(1, '#182038');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
    for (const s of stars) {
      const tw = 0.55 + 0.45 * Math.sin(t * 0.002 + s.tw);
      ctx.fillStyle = 'rgba(' + s.b + ',' + s.b + ',' + Math.min(255, s.b + 24) + ',' + tw + ')';
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.strokeStyle = 'rgba(0,0,0,0.35)';
    ctx.lineWidth = 28;
    ctx.strokeRect(14, 14, W - 28, H - 28);
  }

  function drawForts(ctx, forts) {
    for (const f of forts) {
      const sc = f.scale == null ? 1 : f.scale;
      if (sc <= 0.02) continue;
      const r = f.r * sc;
      ctx.save();
      ctx.shadowColor = 'rgba(0,0,0,0.45)';
      ctx.shadowBlur = 18;
      ctx.shadowOffsetY = 6;
      const g = ctx.createRadialGradient(f.x - r * 0.2, f.y - r * 0.25, 3, f.x, f.y, r);
      g.addColorStop(0, 'rgba(90,110,160,0.55)');
      g.addColorStop(1, 'rgba(30,40,70,0.55)');
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(f.x, f.y, r, 0, Math.PI * 2); ctx.fill();
      ctx.shadowColor = 'transparent';
      ctx.strokeStyle = 'rgba(160,180,220,0.45)';
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(f.x, f.y, r, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.arc(f.x, f.y, r * 0.42, 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
    }
  }

  /** Marble: Phong-ish disc, contact shadow, facing icon, roll speckle, fort cap/full shade. */
  function drawMarble(ctx, p, sim) {
    const col = COLOR[p.type];
    const vs = p.scale == null ? 1 : p.scale;
    if (vs <= 0.02) return;
    const rad = Math.max(6, p.size * 1.05 * vs);
    const clip = sim ? marbleClip(sim, p.x, p.y, rad) : { mode: 'none', ang: 0, occ: 0 };
    const shaded = clip.mode === 'full' || clip.mode === 'cap';
    const shine = clip.mode === 'full' ? 0.15 : 1.0;
    ctx.save();
    ctx.translate(p.x, p.y + (p.yOff || 0));
    // contact shadow (marble.py: center below disc)
    ctx.fillStyle = 'rgba(0,0,0,' + (0.28 * Math.min(1, vs)) + ')';
    ctx.beginPath();
    ctx.ellipse(0, Math.max(3, rad * 0.5), rad * 0.72, rad * 0.28, 0, 0, Math.PI * 2);
    ctx.fill();
    // World-fixed key light highlight (shell.get_marble lx,ly)
    const llen = Math.hypot(LIGHT.x, LIGHT.y, LIGHT.z) || 1;
    const hx = (LIGHT.x / llen) * rad * 0.42;
    const hy = (LIGHT.y / llen) * rad * 0.42;
    const specK = shaded && clip.mode === 'full' ? 0.12 : (shaded ? 0.35 : 0.95);
    const lift = Math.round(90 * specK);
    const grd = ctx.createRadialGradient(hx, hy, rad * 0.08, 0, 0, rad);
    const hi = [
      Math.min(255, Math.round(col[0] * 1.12 + 12 + lift)),
      Math.min(255, Math.round(col[1] * 1.10 + 8 + lift)),
      Math.min(255, Math.round(col[2] * 1.08 + 8 + lift * 0.85))
    ];
    const mid = [
      Math.min(255, Math.round(col[0] * (shaded ? 0.92 : 1.0))),
      Math.min(255, Math.round(col[1] * (shaded ? 0.92 : 1.0))),
      Math.min(255, Math.round(col[2] * (shaded ? 0.92 : 1.0)))
    ];
    const lo = [
      Math.max(0, Math.round(col[0] * 0.55)),
      Math.max(0, Math.round(col[1] * 0.55)),
      Math.max(0, Math.round(col[2] * 0.58))
    ];
    grd.addColorStop(0, 'rgb(' + hi.join(',') + ')');
    grd.addColorStop(0.45, 'rgb(' + mid.join(',') + ')');
    grd.addColorStop(1, 'rgb(' + lo.join(',') + ')');
    ctx.fillStyle = grd;
    ctx.beginPath(); ctx.arc(0, 0, rad, 0, Math.PI * 2); ctx.fill();
    // glass rim
    ctx.strokeStyle = 'rgba(' + hi[0] + ',' + hi[1] + ',' + hi[2] + ',' + (shaded ? 0.25 : 0.45) + ')';
    ctx.lineWidth = Math.max(1, rad * 0.06);
    ctx.stroke();
    ctx.save();
    ctx.beginPath(); ctx.arc(0, 0, rad, 0, Math.PI * 2); ctx.clip();
    if (clip.mode === 'cap') {
      ctx.save();
      ctx.rotate(clip.ang);
      ctx.globalAlpha = Math.min(0.38, 0.18 + clip.occ * 0.28);
      ctx.fillStyle = '#000';
      ctx.beginPath();
      ctx.arc(0, 0, rad, -Math.PI / 2, Math.PI / 2);
      ctx.fill();
      ctx.restore();
    } else if (clip.mode === 'full') {
      ctx.globalAlpha = 0.16;
      ctx.fillStyle = '#000';
      ctx.beginPath(); ctx.arc(0, 0, rad, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
    }
    drawIcon(ctx, p.type, 0, 0, rad * 2 * 0.42, p.angle || 0);
    const spec = rollSpeckle(p.angle || 0, p.roll || 0);
    if (spec && shine > 0.08) {
      let hide = false;
      if (clip.mode === 'cap') {
        const cx = Math.sin(clip.ang), cy = -Math.cos(clip.ang);
        if (spec.qx * cx + spec.qy * cy > 0) hide = true;
      }
      if (!hide) {
        const face = 0.5 + 0.5 * Math.max(-1, Math.min(1, spec.qz));
        const dot = Math.max(2, (0.38 + 0.62 * face) * rad * 0.20 * (0.55 + 0.45 * shine));
        ctx.globalAlpha = Math.max(0.11, Math.min(1, (70 + 160 * face) * shine / 255));
        ctx.fillStyle = '#fff';
        ctx.beginPath();
        ctx.arc(spec.sx * rad * 0.86, spec.sy * rad * 0.86, dot, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      }
    }
    ctx.restore();
    ctx.restore();
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  /** Top-right counts + timer. Zero count = red ring; winner = green ring. */
  function drawHud(ctx, sim, phase, audioOn) {
    const c = sim.counts();
    const order = ['ROCK', 'PAPER', 'SCISSORS'];
    const narrow = (typeof window !== 'undefined' && window.innerWidth < 520);
    ctx.save();
    if (!narrow) {
      const w = 108, row = 42, h = 16 + order.length * row + 52;
      const x = sim.W - w - 12, y = 12;
      roundRect(ctx, x, y, w, h, 12);
      ctx.fillStyle = 'rgba(18,18,28,0.72)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(80,80,110,0.75)';
      ctx.lineWidth = 2;
      ctx.stroke();
      order.forEach((tp, i) => {
        const cy = y + 22 + i * row;
        const cx = x + 24;
        const n = c[tp];
        ctx.beginPath();
        ctx.arc(cx, cy, 18, 0, Math.PI * 2);
        if (n === 0) {
          ctx.strokeStyle = '#dc2832';
          ctx.lineWidth = 3;
          ctx.stroke();
        } else if ((phase === PHASE.WIN || phase === PHASE.FORTS_OUT) && sim.winner === tp) {
          ctx.strokeStyle = '#28c850';
          ctx.lineWidth = 3;
          ctx.stroke();
        }
        if (!drawIcon(ctx, tp, cx, cy, 34, 0)) {
          ctx.beginPath();
          ctx.arc(cx, cy, 10, 0, Math.PI * 2);
          ctx.fillStyle = cssRgb(COLOR[tp]);
          ctx.fill();
        }
        ctx.fillStyle = n === 0 ? '#ff4646' : '#ebebf5';
        ctx.font = '18px Segoe UI, system-ui, sans-serif';
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'left';
        ctx.fillText(String(n), cx + 24, cy);
      });
      ctx.strokeStyle = 'rgba(70,70,95,0.6)';
      ctx.beginPath();
      ctx.moveTo(x + 10, y + 8 + order.length * row);
      ctx.lineTo(x + w - 10, y + 8 + order.length * row);
      ctx.stroke();
      const secs = phase === PHASE.PLAY ? sim.elapsed() : (sim.freezeTime || 0);
      ctx.fillStyle = '#a0a0b9';
      ctx.font = '11px Segoe UI, system-ui, sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText('TIME', x + 12, y + h - 34);
      ctx.fillStyle = (phase === PHASE.WIN || phase === PHASE.FORTS_OUT) ? '#ff4646' : '#ebebf5';
      ctx.font = '16px Segoe UI, system-ui, sans-serif';
      ctx.fillText(fmt(secs), x + 48, y + h - 34);
      ctx.fillStyle = '#a0a0b9';
      ctx.font = '11px Segoe UI, system-ui, sans-serif';
      ctx.fillText('AUDIO', x + 12, y + h - 14);
      ctx.fillStyle = audioOn ? '#7dffb0' : '#888';
      ctx.fillText(audioOn ? 'ON' : 'OFF', x + 56, y + h - 14);
      ctx.restore();
      return;
    }
    const w = 52, row = 22, pad = 4, iconR = 8;
    const h = pad + order.length * row + 26;
    const x = sim.W - w - 4, y = 4;
    roundRect(ctx, x, y, w, h, 7);
    ctx.fillStyle = 'rgba(18,18,28,0.82)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(80,80,110,0.75)';
    ctx.lineWidth = 1.5;
    ctx.stroke();
    order.forEach((tp, i) => {
      const cy = y + pad + row * 0.5 + i * row;
      const cx = x + pad + iconR + 1;
      const n = c[tp];
      ctx.beginPath();
      ctx.arc(cx, cy, iconR + 1.5, 0, Math.PI * 2);
      if (n === 0) {
        ctx.strokeStyle = '#dc2832';
        ctx.lineWidth = 2;
        ctx.stroke();
      } else if ((phase === PHASE.WIN || phase === PHASE.FORTS_OUT) && sim.winner === tp) {
        ctx.strokeStyle = '#28c850';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      if (!drawIcon(ctx, tp, cx, cy, iconR * 2.1, 0)) {
        ctx.beginPath();
        ctx.arc(cx, cy, iconR - 1, 0, Math.PI * 2);
        ctx.fillStyle = cssRgb(COLOR[tp]);
        ctx.fill();
      }
      ctx.fillStyle = n === 0 ? '#ff4646' : '#ebebf5';
      ctx.font = '11px Segoe UI, system-ui, sans-serif';
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'left';
      ctx.fillText(String(n), cx + iconR + 4, cy);
    });
    ctx.strokeStyle = 'rgba(70,70,95,0.6)';
    ctx.beginPath();
    ctx.moveTo(x + 5, y + pad + order.length * row + 1);
    ctx.lineTo(x + w - 5, y + pad + order.length * row + 1);
    ctx.stroke();
    const secs = phase === PHASE.PLAY ? sim.elapsed() : (sim.freezeTime || 0);
    ctx.font = '10px Segoe UI, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = (phase === PHASE.WIN || phase === PHASE.FORTS_OUT) ? '#ff4646' : '#ebebf5';
    ctx.fillText(fmt(secs), x + w / 2, y + h - 16);
    ctx.fillStyle = audioOn ? '#7dffb0' : '#888';
    ctx.fillText(audioOn ? 'ON' : 'OFF', x + w / 2, y + h - 7);
    ctx.restore();
  }

  /** C64-style title card: raster bars, spinning type orbs. */
  function drawWelcome(ctx, W, H, t, muted) {
    const flicker = 0.92 + 0.08 * Math.sin(t * 0.33);
    const barH = Math.max(10, Math.min(16, H / 40));
    for (let i = 0; i < H / barH + 3; i++) {
      const y = (i * barH + t * 0.09) % (H + barH) - barH;
      const hue = (i * 17 + t * 0.11) % 360;
      ctx.fillStyle = 'hsla(' + hue + ',82%,' + (28 * flicker) + '%,0.28)';
      ctx.fillRect(0, y, W, barH);
    }
    const sweepY = (t * 0.22) % (H + 80) - 40;
    const beam = ctx.createLinearGradient(0, sweepY, 0, sweepY + 28);
    beam.addColorStop(0, 'rgba(180,255,210,0)');
    beam.addColorStop(0.5, 'rgba(180,255,210,0.12)');
    beam.addColorStop(1, 'rgba(180,255,210,0)');
    ctx.fillStyle = beam;
    ctx.fillRect(0, sweepY, W, 28);

    const bounce = 1 + 0.05 * Math.sin(t / 140);
    const hue = (t * 0.14) % 360;
    const maxText = Math.max(80, W - 24);
    const narrow = W < 520;
    const titleLines = narrow ? ['Rock, Paper,', 'Scissors'] : ['Rock, Paper, Scissors'];
    ctx.save();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    let titlePx = Math.min(56, W * 0.11) * bounce;
    ctx.font = 'bold ' + Math.round(titlePx) + 'px Segoe UI, system-ui, sans-serif';
    let widest = 0;
    for (let i = 0; i < titleLines.length; i++) widest = Math.max(widest, ctx.measureText(titleLines[i]).width);
    if (widest > maxText) {
      titlePx *= maxText / widest;
      ctx.font = 'bold ' + Math.round(titlePx) + 'px Segoe UI, system-ui, sans-serif';
    }
    ctx.fillStyle = 'hsl(' + hue + ',100%,60%)';
    ctx.shadowColor = 'hsl(' + ((hue + 48) % 360) + ',100%,50%)';
    ctx.shadowBlur = Math.min(18, titlePx * 0.35);
    const titleY = H * (narrow ? 0.30 : 0.36);
    const lineGap = titlePx * 1.05;
    for (let i = 0; i < titleLines.length; i++) {
      ctx.fillText(titleLines[i], W / 2, titleY + i * lineGap);
    }
    ctx.shadowBlur = 0;
    const byPx = Math.max(13, Math.min(22, W * 0.048));
    ctx.font = byPx + 'px Segoe UI, system-ui, sans-serif';
    ctx.fillStyle = 'rgba(220,230,255,0.85)';
    ctx.fillText('by Simon Barnett', W / 2, titleY + titleLines.length * lineGap + byPx * 0.9);

    const orbitR = Math.min(90, W * 0.22, H * 0.12);
    const orbR = Math.max(16, Math.min(28, W * 0.07));
    const types = ['ROCK', 'PAPER', 'SCISSORS'];
    const orbY = H * (narrow ? 0.64 : 0.62);
    types.forEach((tp, i) => {
      const ang = t * 0.002 + i * (Math.PI * 2 / 3);
      const x = W / 2 + Math.cos(ang) * orbitR;
      const y = orbY + Math.sin(ang) * orbitR * 0.32;
      ctx.beginPath();
      ctx.arc(x, y, orbR, 0, Math.PI * 2);
      ctx.fillStyle = cssRgb(COLOR[tp]);
      ctx.fill();
      drawIcon(ctx, tp, x, y, orbR * 1.7, 0);
    });
    const readyPx = Math.max(12, Math.min(16, W * 0.042));
    ctx.font = readyPx + 'px Segoe UI, system-ui, sans-serif';
    ctx.fillStyle = 'rgba(200,210,230,0.7)';
    ctx.fillText(muted ? 'TAP ANYWHERE FOR SOUND' : 'GET READY', W / 2, Math.min(H * 0.88, orbY + orbitR * 0.5 + readyPx * 3));
    const stampY = Math.min(H - 30, orbY + orbitR * 0.5 + readyPx * 4.6);
    const stampPx = Math.max(10, Math.min(13, W * 0.032));
    ctx.font = stampPx + 'px Segoe UI, system-ui, sans-serif';
    ctx.fillStyle = 'rgba(160,175,200,0.85)';
    const b = BUILD || {};
    ctx.fillText(
      'BUILD ' + (b.n || 0) + '   GEN ' + (b.gen || 0) + '   GAMES ' + (b.games || 0),
      W / 2, stampY);
    if (b.at || b.sha) {
      ctx.fillStyle = 'rgba(140,155,180,0.65)';
      ctx.fillText(String(b.at || '') + (b.sha ? '   ' + b.sha : ''), W / 2, stampY + stampPx + 2);
    }
    ctx.restore();
  }

  /** 3-2-1-GO overlay. */
  function drawCountdown(ctx, W, H, value, local) {
    const label = value > 0 ? String(value) : 'GO';
    const scale = 1 + 0.18 * (1 - local);
    ctx.save();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = 'bold ' + Math.round(140 * scale) + 'px Segoe UI, system-ui, sans-serif';
    ctx.fillStyle = 'rgba(255,230,120,' + (0.92 - local * 0.35) + ')';
    ctx.shadowColor = 'rgba(255,200,80,0.6)';
    ctx.shadowBlur = 24;
    ctx.fillText(label, W / 2, H / 2);
    ctx.restore();
  }

  /** Winner banner with type icon and match time. */
  /** hud.draw_winner_banner — fade 600ms, pulse icon, float, gold title. */
  function drawWinner(ctx, W, H, type, timeStr, elapsed) {
    const fade = Math.min(1, elapsed / 600);
    const pulse = elapsed > 600 ? (1 + 0.06 * Math.sin(elapsed / 280)) : (0.85 + 0.15 * fade);
    const floatY = elapsed > 400 ? 6 * Math.sin(elapsed / 400) : 0;
    const iconSz = 64 * pulse;
    const padX = 28, padY = 20;
    const name = (type || '?') + ' WINS';
    ctx.save();
    ctx.font = 'bold 28px Segoe UI, system-ui, sans-serif';
    const tw = ctx.measureText(name).width;
    ctx.font = '16px Segoe UI, system-ui, sans-serif';
    const sub = 'match over  ·  ' + timeStr;
    const sw = ctx.measureText(sub).width;
    const pw = Math.max(tw, sw, iconSz) + padX * 2;
    const ph = iconSz + 28 + 16 + padY * 2 + 16;
    const x = (W - pw) / 2;
    const y = (H - ph) / 2 + floatY;
    const alpha = 175 / 255 * fade;
    roundRect(ctx, x, y, pw, ph, 14);
    ctx.fillStyle = 'rgba(18,18,28,' + (0.69 * fade) + ')';
    ctx.fill();
    ctx.strokeStyle = 'rgba(80,80,110,' + Math.min(0.78, alpha + 0.12) + ')';
    ctx.lineWidth = 2;
    ctx.stroke();
    const cx = x + pw / 2, cy = y + padY + iconSz / 2;
    ctx.globalAlpha = fade;
    ctx.beginPath();
    ctx.arc(cx, cy, iconSz / 2 + 4, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(40,200,80,' + (220 / 255 * fade) + ')';
    ctx.lineWidth = 3;
    ctx.stroke();
    if (!drawIcon(ctx, type, cx, cy, iconSz, 0)) {
      ctx.beginPath();
      ctx.arc(cx, cy, iconSz / 2, 0, Math.PI * 2);
      ctx.fillStyle = cssRgb(COLOR[type] || [200, 200, 200]);
      ctx.fill();
    }
    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(255,220,80,' + fade + ')';
    ctx.font = 'bold 28px Segoe UI, system-ui, sans-serif';
    ctx.fillText(name, cx, y + padY + iconSz + 28);
    ctx.font = '16px Segoe UI, system-ui, sans-serif';
    ctx.fillStyle = 'rgba(180,180,200,' + (0.86 * fade) + ')';
    ctx.fillText(sub, cx, y + padY + iconSz + 50);
    ctx.restore();
  }

  const STYLE = `
.rps-wrap{position:fixed;inset:0;width:100%;height:100%;height:100dvh;background:#080b14;overflow:hidden}
.rps-wrap canvas{display:block;width:100%;height:100%}
`;

  /** Embed into a DOM node. Loads strategies/types JSON when served over http. */
  async function mount(target, opts) {
    opts = opts || {};
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) throw new Error('RPS.mount: no element');
    if (!document.getElementById('rps-embed-style')) {
      const st = document.createElement('style');
      st.id = 'rps-embed-style';
      st.textContent = STYLE;
      document.head.appendChild(st);
    }
    await loadIcons(opts.icons || './images/');
    el.classList.add('rps-wrap');
    el.innerHTML = '';
    const canvas = document.createElement('canvas');
    el.style.width = '100%';
    el.style.height = '100%';
    el.style.minHeight = '100dvh';
    el.appendChild(canvas);
    let fit = fitCanvas(canvas, el);
    const ctx = canvas.getContext('2d');
    const origin = String(opts.origin || opts.cdn || scriptBase()).replace(/\/+$/, '');
    const strat = opts.strategies || (origin + '/strategies/types');
    let books = {};
    try {
      books = {
        ROCK: await loadTeamBook(strat, 'ROCK'),
        PAPER: await loadTeamBook(strat, 'PAPER'),
        SCISSORS: await loadTeamBook(strat, 'SCISSORS')
      };
      const metaRoot = String(strat).replace(/\/types\/?$/, '');
      const meta = (await loadJSON(metaRoot + '/meta.json')) || {};
      ['ROCK', 'PAPER', 'SCISSORS'].forEach(function (t) {
        if (books[t]) books[t].meta = meta;
      });
    } catch (e) {}

    let stars = makeStars(fit.w, fit.h);
    const sfx = AudioBus((origin || '.') + '/sound/');
    let audioOn = false;
    sfx.on = false;
    let lastCount = 99;
    function makeSim() { return createSim({ books: books, width: fit.w, height: fit.h, teamSize: opts.teamSize, forts: opts.forts, onSfx: (k) => { if (audioOn) sfx[k] && sfx[k](); } }); }
    let sim = makeSim();
    let phase = PHASE.TITLE;
    let phaseAt = performance.now();
    let raf;
    const TITLE_MS = 4400;
    const FORT_MS = 900;
    const SPAWN_MS = 1100;
    const COUNT_STEP = 900;
    const WIN_MS = 5000;
    const FORT_OUT_MS = FORT_OUTRO_MS;

    function newMatch() {
      fit = fitCanvas(canvas, el);
      stars = makeStars(fit.w, fit.h);
      sim = makeSim(); lastCount = 99;
      phase = PHASE.TITLE;
      phaseAt = performance.now();
    }

    canvas.addEventListener('pointerdown', function () {
      audioOn = !audioOn;
      sfx.on = audioOn;
      if (audioOn) sfx.prime();
    });

    function loop(now) {
      const elms = now - phaseAt;
      if (phase === PHASE.TITLE && elms >= TITLE_MS) {
        phase = PHASE.FORTS; phaseAt = now;
      } else if (phase === PHASE.FORTS && elms >= FORT_INTRO_MS + FORT_STAGGER_MS * Math.max(0, sim.forts.length - 1)) {
        sim.forts.forEach(f => { f.scale = 1; });
        phase = PHASE.SPAWN; phaseAt = now;
      } else if (phase === PHASE.SPAWN) {
        const last = sim.particles[sim.particles.length - 1];
        const need = PARTICLE_INTRO_MS + ((last && last._intro_delay_ms) || 0) + 1000;
        if (elms >= need) {
          sim.particles.forEach(p => { p.scale = 1; p.yOff = 0; });
          phase = PHASE.COUNT; phaseAt = now; lastCount = 99; sfx.prime();
        }
      } else if (phase === PHASE.COUNT && elms >= COUNT_STEP * 4) {
        phase = PHASE.PLAY; phaseAt = now;
        sim.startClock();
      } else if (phase === PHASE.PLAY && sim.winner) {
        sim.freezeTime = sim.elapsed();
        phase = PHASE.WIN; phaseAt = now;
        if (opts.onWin) try { opts.onWin(sim.winner, sim.counts()); } catch (e) {}
      } else if (phase === PHASE.WIN && elms >= WIN_MS) {
        phase = PHASE.FORTS_OUT; phaseAt = now;
      } else if (phase === PHASE.FORTS_OUT && elms >= FORT_OUT_MS) {
        newMatch();
      }

      if (phase === PHASE.FORTS) {
        sim.forts.forEach(function (f, i) {
          const local = elms - i * FORT_STAGGER_MS;
          if (local <= 0) f.scale = 0;
          else if (local >= FORT_INTRO_MS) f.scale = 1;
          else {
            const u = local / FORT_INTRO_MS;
            f.scale = 1 - Math.pow(1 - u, 3);
          }
        });
      }
      if (phase === PHASE.SPAWN) {
        sim.particles.forEach(function (p) {
          const local = elms - (p._intro_delay_ms || 0);
          if (local <= 0) { p.yOff = PARTICLE_RISE_PX; p.scale = 0.05; return; }
          const u = Math.min(1, local / PARTICLE_INTRO_MS);
          const e = 1 - Math.pow(1 - u, 3);
          p.yOff = PARTICLE_RISE_PX * (1 - e);
          p.scale = 0.05 + 0.95 * e;
        });
      }
      if (phase === PHASE.FORTS_OUT) {
        const u = Math.min(1, elms / FORT_OUT_MS);
        sim.forts.forEach(function (f) { f.scale = Math.max(0, 1 - u); });
      }
      if (phase === PHASE.COUNT) {
        const slot = Math.min(3, Math.floor(elms / COUNT_STEP));
        const val = 3 - slot;
        if (val !== lastCount) { lastCount = val; if (audioOn) sfx.count(val); }
        sim.step(false);
      }
      if (phase === PHASE.PLAY) sim.step(true);
      if (phase === PHASE.WIN || phase === PHASE.FORTS_OUT) sim.step(true, true);

      ctx.setTransform(fit.dpr, 0, 0, fit.dpr, 0, 0);
      ctx.fillStyle = '#070814';
      ctx.fillRect(0, 0, fit.w, fit.h);
      drawStarfield(ctx, fit.w, fit.h, stars, now);
      if (phase === PHASE.TITLE) {
        drawWelcome(ctx, fit.w, fit.h, elms, !audioOn);
      } else {
        drawForts(ctx, sim.forts);
        for (const p of sim.particles) drawMarble(ctx, p, sim);
        if (phase === PHASE.COUNT) {
          const slot = Math.min(3, Math.floor(elms / COUNT_STEP));
          const val = 3 - slot;
          drawCountdown(ctx, fit.w, fit.h, val, (elms % COUNT_STEP) / COUNT_STEP);
        }
        if (phase === PHASE.WIN || phase === PHASE.FORTS_OUT) {
          const gone = phase === PHASE.FORTS_OUT ? WIN_MS + elms : elms;
          drawWinner(ctx, fit.w, fit.h, sim.winner, fmt(sim.freezeTime), gone);
        }
        if (phase !== PHASE.TITLE) drawHud(ctx, sim, phase, audioOn);
      }
      raf = requestAnimationFrame(loop);
    }
    raf = requestAnimationFrame(loop);
    window.addEventListener('resize', () => { fit = fitCanvas(canvas, el); });
    return { stop() { cancelAnimationFrame(raf); }, get sim() { return sim; } };
  }

  /** Point the host page at a CDN origin that serves rps.js + strategies/. */
  function embedFrom(cdnOrigin, target, opts) {
    opts = opts || {};
    opts.origin = cdnOrigin;
    opts.strategies = opts.strategies || (String(cdnOrigin).replace(/\/+$/, '') + '/strategies/types');
    return mount(target, opts);
  }
  global.RPS = {
    mount: mount, embedFrom: embedFrom, createSim: createSim,
    COLOR: COLOR, PREY: PREY, FEAR: FEAR,
    pickCard: pickCard, legalFromJson: legalFromJson, gameState: gameState,
    mulberry32: mulberry32, placeForts: placeForts, spawnParticles: spawnParticles,
    worldMetrics: worldMetrics
  };
})(typeof window !== 'undefined' ? window : globalThis);
