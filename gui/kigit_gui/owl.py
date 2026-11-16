"""The owl: a small snowy owl that lives in the GUI, off by default. Its
door (a little owl face in the header, by the kigit logo) lets it in or out.

Perched, it does owl things: blinks, tilts and turns its head, follows the
mouse with its eyes, ruffles, hops. Every so often it flies somewhere else
(the bottom edge, the header, the top of a panel) and lands; shake the mouse
over it and it's startled and flies off. It never takes a click
(pointer-events: none). On or off is remembered in the browser
(kigit.owl). All of it runs in the page: no server work.
"""

from __future__ import annotations

from nicegui import ui

# A snowy owl: white with dark speckles and wing bars, round yellow eyes,
# hardly any ear tufts.
_OWL_SVG = """
<svg viewBox="0 0 64 64" width="56" height="56" aria-hidden="true">
  <g class="o-bob">
    <g class="o-wing o-wl"><path d="M14 30 C3 34 4 49 14 53 C16 45 17 37 14 30Z" fill="#eef1f5" stroke="#c9d0da" stroke-width=".6"/>
      <path d="M8 40 l3 1 M7 45 l3 1 M9 49 l3 .5" stroke="#3a4250" stroke-width="1.3" stroke-linecap="round"/></g>
    <g class="o-wing o-wr"><path d="M50 30 C61 34 60 49 50 53 C48 45 47 37 50 30Z" fill="#eef1f5" stroke="#c9d0da" stroke-width=".6"/>
      <path d="M56 40 l-3 1 M57 45 l-3 1 M55 49 l-3 .5" stroke="#3a4250" stroke-width="1.3" stroke-linecap="round"/></g>
    <ellipse cx="32" cy="42" rx="17" ry="17" fill="#f7f9fb" stroke="#d5dbe3" stroke-width=".6"/>
    <path d="M24 38 l2 1.2 l2-1.2 M34 37 l2 1.2 l2-1.2 M27 45 l2 1.2 l2-1.2 M37 46 l2 1.2 l2-1.2 M22 47 l2 1.2 l2-1.2 M31 52 l2 1.2 l2-1.2"
      stroke="#3a4250" stroke-width="1.1" fill="none" stroke-linecap="round"/>
    <g class="o-feet"><ellipse cx="27" cy="58" rx="4" ry="2.4" fill="#f7f9fb"/><ellipse cx="37" cy="58" rx="4" ry="2.4" fill="#f7f9fb"/>
      <path d="M24.5 60 l.5 1.5 M27 60.4 v1.5 M29.5 60 l-.5 1.5 M34.5 60 l.5 1.5 M37 60.4 v1.5 M39.5 60 l-.5 1.5"
        stroke="#1a1d22" stroke-width="1" stroke-linecap="round"/></g>
    <g class="o-head">
      <path d="M17 11 L20 7 L23 11 Z M47 11 L44 7 L41 11 Z" fill="#eef1f5"/>
      <ellipse cx="32" cy="20" rx="18" ry="15" fill="#ffffff" stroke="#d5dbe3" stroke-width=".6"/>
      <path d="M22 10 l1.5 1 M40 9.5 l1.5 1 M31 8 l1.5 .8" stroke="#3a4250" stroke-width="1" stroke-linecap="round"/>
      <g class="o-eyes"><circle cx="24" cy="20" r="6.2" fill="#f2c230"/><circle cx="40" cy="20" r="6.2" fill="#f2c230"/></g>
      <g class="o-pupils"><circle cx="24" cy="20" r="3.3" fill="#111317"/><circle cx="40" cy="20" r="3.3" fill="#111317"/>
        <circle cx="25.1" cy="18.9" r="1" fill="#fff"/><circle cx="41.1" cy="18.9" r="1" fill="#fff"/></g>
      <g class="o-lids" fill="#ffffff"><rect x="17" y="13" width="14" height="14"/><rect x="33" y="13" width="14" height="14"/></g>
      <path d="M30.4 25 L32 29 L33.6 25 Z" fill="#2b2f36"/>
    </g>
  </g>
</svg>
"""

# The door: a small snowy owl face in the header, next to the kigit logo.
_FACE = ('<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><ellipse cx="12" cy="12.5" rx="10" '
         'ry="9" fill="#f7f9fb"/><circle cx="8.3" cy="11.5" r="3" fill="#f2c230"/><circle cx="15.7" cy="11.5" '
         'r="3" fill="#f2c230"/><circle cx="8.3" cy="11.5" r="1.6" fill="#111317"/><circle cx="15.7" cy="11.5" '
         'r="1.6" fill="#111317"/><path d="M11.2 14.5 L12 16.6 L12.8 14.5Z" fill="#2b2f36"/><path d="M6 6 l1 .7 '
         'M17 6 l1 .7" stroke="#3a4250" stroke-width=".9" stroke-linecap="round"/></svg>')
DOOR = f'<button id="kigit-owl-door" type="button" title="hoo?" aria-label="hoo?">{_FACE}</button>'

PAGE = """
<style>
#kigit-owl { position: fixed; left: 0; top: 0; z-index: 9000; pointer-events: none; display: none;
  transition: left var(--fly, 2.4s) cubic-bezier(.45,.05,.4,1), top var(--fly, 2.4s) cubic-bezier(.45,.05,.4,1); }
#kigit-owl.on { display: block; }
#kigit-owl .o-face { transition: transform .25s; }
#kigit-owl.left .o-face { transform: scaleX(-1); }
#kigit-owl .o-head { transform-origin: 32px 30px; transition: transform .45s cubic-bezier(.3,1.4,.5,1); }
#kigit-owl .o-pupils { transition: transform .12s; }
#kigit-owl .o-lids rect { transform-box: fill-box; transform-origin: top; transform: scaleY(0); transition: transform .07s; }
#kigit-owl.blink .o-lids rect { transform: scaleY(1); }
#kigit-owl .o-wing { transform-box: fill-box; }
#kigit-owl .o-wl { transform-origin: right top; } #kigit-owl .o-wr { transform-origin: left top; }
#kigit-owl.ruffle .o-wl { animation: o-ruffle-l .5s ease-in-out 2; }
#kigit-owl.ruffle .o-wr { animation: o-ruffle-r .5s ease-in-out 2; }
@keyframes o-ruffle-l { 50% { transform: rotate(14deg); } } @keyframes o-ruffle-r { 50% { transform: rotate(-14deg); } }
#kigit-owl.hop .o-bob { animation: o-hop .45s ease-out; }
@keyframes o-hop { 40% { transform: translateY(-9px); } 70% { transform: translateY(1px); } }
#kigit-owl.flying .o-wl { animation: o-flap-l .18s ease-in-out infinite alternate; }
#kigit-owl.flying .o-wr { animation: o-flap-r .18s ease-in-out infinite alternate; }
@keyframes o-flap-l { from { transform: rotate(-40deg); } to { transform: rotate(30deg); } }
@keyframes o-flap-r { from { transform: rotate(40deg); } to { transform: rotate(-30deg); } }
#kigit-owl.flying .o-bob { animation: o-glide .6s ease-in-out infinite alternate; }
@keyframes o-glide { from { transform: translateY(-4px); } to { transform: translateY(4px); } }
#kigit-owl.flying .o-feet { opacity: 0; }
#kigit-owl-door { display: inline-grid; place-items: center; width: 28px; height: 28px; padding: 0; border: 0;
  border-radius: 50%; background: none; opacity: .35; cursor: pointer; transition: opacity .3s, transform .3s; }
#kigit-owl-door:hover { opacity: 1; transform: rotate(-12deg) scale(1.1); }
#kigit-owl-door.out { opacity: .12; }  /* the owl is out: its door is empty */
#kigit-owl.startle .o-eyes circle { r: 7.2; } #kigit-owl.startle .o-pupils { transform: scale(.7); transform-origin: 32px 20px; }
#kigit-owl.startle .o-bob { animation: o-hop .3s ease-out; }
@media (prefers-reduced-motion: reduce) { #kigit-owl { transition: none; } }
</style>
<div id="kigit-owl" aria-hidden="true"><div class="o-face">%%OWL%%</div></div>
<script>
(() => {
  const owl = document.getElementById("kigit-owl");
  const door = () => document.getElementById("kigit-owl-door") || { classList: { add() {}, remove() {} } };
  const head = owl.querySelector(".o-head"), pupils = owl.querySelector(".o-pupils");
  const SIZE = 56, rnd = (a, b) => a + Math.random() * (b - a), pick = (xs) => xs[Math.floor(Math.random() * xs.length)];
  const store = { get() { try { return localStorage.getItem("kigit.owl") === "1"; } catch { return false; } },
                  set(v) { try { localStorage.setItem("kigit.owl", v ? "1" : "0"); } catch {} } };
  let on = false, flying = false, idle = null, trip = null, x = -80, y = innerHeight - SIZE;
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const place = (nx, ny, seconds) => {
    owl.style.setProperty("--fly", (seconds || 0) + "s");
    x = nx; y = ny;
    owl.style.left = x + "px"; owl.style.top = y + "px";
  };
  // Where it can sit: the bottom edge, the header bar, the top of a panel.
  function perch() {
    // The header's right half: its buttons, never the folder box on the left.
    const spots = [[rnd(40, innerWidth - 100), innerHeight - SIZE + 2], [rnd(innerWidth * 0.55, innerWidth - 120), 2]];
    for (const el of document.querySelectorAll(".q-drawer--left, .kigit-dock, .q-drawer--right")) {
      const r = el.getBoundingClientRect();
      // A panel's top edge lower down (not one that starts at the header: that's over the folder box).
      if (r.width > 80 && r.top > 120 && r.left >= 0 && r.right <= innerWidth) spots.push([rnd(r.left + 10, r.right - 70), r.top - SIZE + 6]);
    }
    return pick(spots);
  }
  function fly(to, then) {
    flying = true;
    owl.classList.remove("blink", "ruffle", "hop");
    owl.classList.add("flying");
    owl.classList.toggle("left", to[0] < x);
    head.style.transform = "";
    const seconds = still ? 0 : Math.min(4, 1.2 + Math.hypot(to[0] - x, to[1] - y) / 500);
    place(to[0], to[1], seconds);
    clearTimeout(trip);
    trip = setTimeout(() => { flying = false; owl.classList.remove("flying"); then && then(); }, seconds * 1000 + 60);
  }
  // Owl things, now and then, while it sits.
  const acts = {
    blink() { owl.classList.add("blink"); setTimeout(() => owl.classList.remove("blink"), 140); },
    twice() { acts.blink(); setTimeout(acts.blink, 260); },
    tilt() { head.style.transform = `rotate(${pick([-1, 1]) * rnd(12, 24)}deg)`;
             setTimeout(() => { head.style.transform = ""; }, rnd(900, 2200)); },
    turn() { head.style.transform = `translateX(${pick([-3, 3])}px) rotate(${pick([-6, 6])}deg)`;
             setTimeout(() => { head.style.transform = ""; }, rnd(700, 1600)); },
    ruffle() { owl.classList.add("ruffle"); setTimeout(() => owl.classList.remove("ruffle"), 1050); },
    hop() { owl.classList.add("hop"); setTimeout(() => owl.classList.remove("hop"), 460); },
    face() { owl.classList.toggle("left"); },
  };
  function live() {
    clearTimeout(idle);
    if (!on) return;
    if (!flying) pick(["blink", "blink", "twice", "tilt", "tilt", "turn", "ruffle", "hop", "face"]).split(" ")
      .forEach((a) => acts[a]());
    idle = setTimeout(live, rnd(1200, 3800));
  }
  function wander() {
    clearTimeout(wander.t);
    if (!on) return;
    wander.t = setTimeout(() => { if (on && !document.hidden) fly(perch()); wander(); }, rnd(30000, 70000));
  }
  // Its eyes follow the mouse.
  addEventListener("pointermove", (e) => {
    if (!on || flying) return;
    const r = owl.getBoundingClientRect(), dx = e.clientX - (r.left + SIZE / 2), dy = e.clientY - (r.top + SIZE * 0.32);
    const d = Math.hypot(dx, dy) || 1, k = Math.min(1.8, d / 60);
    const flip = owl.classList.contains("left") ? -1 : 1;
    pupils.style.transform = `translate(${flip * dx / d * k}px, ${dy / d * k}px)`;
  }, { passive: true });
  addEventListener("resize", () => { if (on && !flying) place(Math.min(x, innerWidth - SIZE), Math.min(y, innerHeight - SIZE)); });
  function arrive() {
    on = true;
    owl.classList.add("on");
    door().classList.add("out");
    place(-80, rnd(80, innerHeight / 2));  // in from the left
    requestAnimationFrame(() => requestAnimationFrame(() => fly(perch(), () => { live(); wander(); })));
  }
  function leave() {
    on = false;
    door().classList.remove("out");
    clearTimeout(idle); clearTimeout(wander.t);
    fly([innerWidth + 80, rnd(0, innerHeight / 3)], () => owl.classList.remove("on"));
  }
  // The door is in the header, drawn by the page after this runs: listen on the document.
  document.addEventListener("click", (e) => {
    if (!(e.target.closest && e.target.closest("#kigit-owl-door"))) return;
    const want = !on;
    store.set(want);
    want ? arrive() : leave();
  });
  // Shake the mouse over it (back and forth, quickly): it's startled and flies off.
  let lastX = null, lastDir = 0, turns = [];
  addEventListener("pointermove", (e) => {
    if (!on || flying) return;
    const r = owl.getBoundingClientRect();
    const over = e.clientX > r.left - 12 && e.clientX < r.right + 12 && e.clientY > r.top - 12 && e.clientY < r.bottom + 12;
    if (!over) { lastX = null; turns = []; return; }
    if (lastX !== null && Math.abs(e.clientX - lastX) > 2) {
      const dir = Math.sign(e.clientX - lastX);
      if (lastDir && dir !== lastDir) turns.push(performance.now());
      lastDir = dir;
    }
    lastX = e.clientX;
    turns = turns.filter((t) => performance.now() - t < 900);
    if (turns.length >= 4) { turns = []; startle(); }
  }, { passive: true });
  function startle() {
    owl.classList.add("startle");
    acts.ruffle();
    setTimeout(() => {
      owl.classList.remove("startle");
      // Somewhere else, not just next door.
      let to = perch();
      for (let i = 0; i < 6 && Math.hypot(to[0] - x, to[1] - y) < 300; i++) to = perch();
      fly(to);
    }, 280);
  }
  window.kigitOwl = () => ({ on, flying, x, y });
  if (store.get()) setTimeout(arrive, 800);
})();
</script>
"""


def add() -> None:
    """The owl (and how it lives), on this page. Its door goes in the header: door()."""
    ui.add_body_html(PAGE.replace("%%OWL%%", _OWL_SVG))


def door() -> None:
    """The owl's door, where it's put (the header, by the kigit logo)."""
    ui.html(DOOR).mark("owl-door")
