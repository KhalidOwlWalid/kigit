"""The 3D view: one commit's board as KiCad draws it in 3D.

KiCad makes the model (`kigit --3d`, which runs `kicad-cli pcb export glb`);
this only shows it. The page (`/board3d/{name}`) is loaded in the viewer's
iframe and draws the .glb from the GUI's cache folder with three.js, the copy
that comes with NiceGUI (served at /kigit-three/, so it works offline).

Interactive: drag to orbit, right-drag to pan, scroll to zoom; Top, Bottom
and 3D views; hide or show the parts. It only draws when the view changes,
so a big board doesn't keep the GPU busy.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import nicegui
from fastapi.responses import FileResponse, HTMLResponse, Response
from nicegui import app

THREE = Path(nicegui.__file__).parent / "elements" / "lib" / "three"
# What the page imports; nothing else from the folder is served.
THREE_FILES = {"three.module.js", "modules/GLTFLoader.js", "modules/OrbitControls.js",
               "modules/BufferGeometryUtils.js"}
_NAME = re.compile(r"^[\w.-]+\.glb$")


def page(glb_url: str, title: str = "", subtitle: str = "") -> str:
    """The viewer page for the model at glb_url."""
    return (_PAGE.replace("%%GLB%%", json.dumps(glb_url))
            .replace("%%TITLE%%", html.escape(title or "3D board"))
            .replace("%%SUBTITLE%%", html.escape(subtitle)))


@app.get("/board3d/{name}")
async def _page(name: str, title: str = "", subtitle: str = "") -> Response:
    from .app import CACHE

    if not _NAME.match(name) or not (CACHE / name).is_file():
        return Response("No such 3D board.", status_code=404)
    return HTMLResponse(page(f"/diffs/{name}", title, subtitle))


@app.get("/kigit-three/{path:path}")
async def _three(path: str) -> Response:
    if path not in THREE_FILES:
        return Response(status_code=404)
    return FileResponse(THREE / path, media_type="text/javascript")


# Placeholders are %%NAME%%; the rest is plain CSS and JavaScript.
_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<script type="importmap">
{"imports": {"three": "/kigit-three/three.module.js", "GLTFLoader": "/kigit-three/modules/GLTFLoader.js",
 "OrbitControls": "/kigit-three/modules/OrbitControls.js",
 "BufferGeometryUtils": "/kigit-three/modules/BufferGeometryUtils.js"}}
</script>
<style>
:root { --bg: #0f1115; --panel: rgba(22, 26, 32, .88); --line: #29303a; --text: #e6e9ee; --muted: #9aa4b2;
  --faint: #6b7584; --accent: #e8b84d; }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; overflow: hidden; background: var(--bg); color: var(--text);
  font: 13px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
canvas { display: block; outline: none; }
.bar { position: absolute; display: flex; gap: 6px; align-items: center; padding: 6px; background: var(--panel);
  border: 1px solid var(--line); border-radius: 10px; backdrop-filter: blur(6px); }
#info { left: 12px; top: 12px; flex-direction: column; align-items: flex-start; gap: 0; padding: 8px 12px; max-width: 45%; }
#info b { font-size: 14px; } #info span { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  max-width: 100%; }
#tools { right: 12px; top: 12px; }
button { border: 1px solid transparent; background: none; color: var(--muted); border-radius: 7px; padding: 5px 10px;
  font: inherit; cursor: pointer; }
button:hover { color: var(--text); background: rgba(255,255,255,.06); }
button.on { color: var(--accent); border-color: rgba(232,184,77,.45); }
.sep { width: 1px; align-self: stretch; background: var(--line); margin: 2px 2px; }
#hint { left: 12px; bottom: 12px; color: var(--faint); font-size: 12px; padding: 5px 10px; }
#loading { position: absolute; inset: 0; display: grid; place-items: center; background: var(--bg); }
#loading .box { width: 280px; text-align: center; color: var(--muted); }
#loading .track { height: 4px; border-radius: 2px; background: var(--line); overflow: hidden; margin-top: 10px; }
#loading .fill { height: 100%; width: 0; background: var(--accent); transition: width .15s; }
#loading.err .box { color: #f07178; }
#stats { right: 12px; bottom: 12px; display: none; flex-direction: column; align-items: stretch; gap: 6px; padding: 10px 12px;
  font: 12px/1.45 ui-monospace, Menlo, Consolas, monospace; min-width: 300px; }
#stats.on { display: flex; }
#stats table { border-collapse: collapse; }
#stats th { text-align: left; font-weight: 400; color: var(--muted); padding: 0 12px 0 0; white-space: nowrap; }
#stats td { text-align: right; padding: 0 0 0 10px; font-variant-numeric: tabular-nums; }
#stats .bad { color: #f07178; } #stats .ok { color: #7fd99a; }
#stats .head { display: flex; justify-content: space-between; align-items: center; color: var(--text); }
#stats .note { color: var(--faint); font-family: system-ui, sans-serif; max-width: 320px; }
#stats button { padding: 2px 8px; border-color: var(--line); }
</style>
</head>
<body>
<div id="info" class="bar"><b>%%TITLE%%</b><span>%%SUBTITLE%%</span></div>
<div id="tools" class="bar">
  <button data-view="top" title="Look at the top (T)">Top</button>
  <button data-view="bottom" title="Look at the bottom (B)">Bottom</button>
  <button data-view="iso" title="Angled view (3)">3D</button>
  <button data-view="fit" title="Fit the board in view (F)">Fit</button>
  <span class="sep"></span>
  <button id="parts" class="on" title="Show or hide the parts' 3D models (P)">Parts</button>
</div>
<div id="hint" class="bar">Drag to rotate · right-drag to pan · scroll to zoom</div>
<div id="stats" class="bar" aria-live="off">
  <div class="head"><b>Render stats</b><span><button id="statsReset" title="Start measuring again">Reset</button>
    <button id="statsCopy" title="Copy the numbers as JSON">Copy</button></span></div>
  <table id="statsTable"></table>
  <div class="note">Drag or zoom for a few seconds, then read p50 / p95. S hides this.</div>
</div>
<div id="loading"><div class="box"><div id="msg">Loading the 3D board…</div><div class="track"><div class="fill" id="fill"></div></div></div></div>
<script type="module">
import * as THREE from "three";
import { GLTFLoader } from "GLTFLoader";
import { OrbitControls } from "OrbitControls";
import { mergeGeometries } from "BufferGeometryUtils";

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
renderer.toneMapping = THREE.NeutralToneMapping;  // keeps colours close to KiCad's
renderer.toneMappingExposure = 1.0;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.prepend(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0f1115);
// Soft studio light for the metal (pads, copper) to reflect: a room with a
// few bright panels, blurred into an environment map.
{
  const room = new THREE.Scene();
  const box = new THREE.Mesh(new THREE.BoxGeometry(10, 10, 10), new THREE.MeshBasicMaterial({ color: 0x3a3f47, side: THREE.BackSide }));
  room.add(box);
  const panel = (x, y, z, w, h, k) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(k, k, k) }));
    m.position.set(x, y, z); m.lookAt(0, 0, 0); room.add(m);
  };
  panel(0, 4.9, 0, 6, 6, 5); panel(0, -4.9, 0, 6, 6, 3); panel(4.9, 2, 2, 3, 3, 2.5); panel(-4.9, 2, -2, 3, 3, 2); panel(0, 1, 4.9, 4, 2, 1.5);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(room, 0.04).texture;
  scene.environmentIntensity = 0.7;
}
scene.add(new THREE.HemisphereLight(0xffffff, 0x404650, 0.35));
const sun = new THREE.DirectionalLight(0xffffff, 1.0);
scene.add(sun);
const under = new THREE.DirectionalLight(0xffffff, 0.8);  // the bottom side gets light too
scene.add(under);

const camera = new THREE.PerspectiveCamera(35, 1, 0.0001, 100);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.12;
controls.screenSpacePanning = true;

function resize() {
  renderer.setSize(innerWidth, innerHeight);
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  redraw();
}
addEventListener("resize", resize);
resize();

let model = null, parts = [], box = new THREE.Box3(), size = 1;

// Views. glTF is Y-up; KiCad's board lies in the X-Z plane with its Y
// (downwards on screen) along +Z, so "top" looks down -Y with -Z up.
function view(name, animate = true) {
  if (!model) return;
  const c = box.getCenter(new THREE.Vector3());
  const s = box.getSize(new THREE.Vector3());
  const fit = Math.max(s.x / camera.aspect, s.z) / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) * 1.25;
  const d = Math.max(fit, size * 0.6);
  let pos, up = new THREE.Vector3(0, 1, 0);
  if (name === "top") { pos = new THREE.Vector3(0, d, 0); up.set(0, 0, -1); }
  else if (name === "bottom") { pos = new THREE.Vector3(0, -d, 0); up.set(0, 0, -1); }
  else if (name === "fit") pos = camera.position.clone().sub(controls.target).setLength(d);
  else pos = new THREE.Vector3(0, d * 0.75, d * 0.85);
  const to = c.clone().add(pos);
  if (!animate) { camera.position.copy(to); camera.up.copy(up); controls.target.copy(c); controls.update(); return; }
  const from = camera.position.clone(), fromT = controls.target.clone(), fromUp = camera.up.clone();
  const t0 = performance.now();
  (function step(now) {
    const k = Math.min(1, (now - t0) / 450), e = 1 - Math.pow(1 - k, 3);
    camera.position.lerpVectors(from, to, e);
    controls.target.lerpVectors(fromT, c, e);
    camera.up.lerpVectors(fromUp, up, e).normalize();
    controls.update();
    if (k < 1) requestAnimationFrame(step);
  })(t0);
}

document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => view(b.dataset.view)));
const partsBtn = document.getElementById("parts");
function toggleParts() {
  const on = !partsBtn.classList.contains("on");
  partsBtn.classList.toggle("on", on);
  parts.forEach((p) => (p.visible = on));
  redraw();
}
partsBtn.addEventListener("click", toggleParts);
addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === "t") view("top"); else if (k === "b") view("bottom"); else if (k === "3") view("iso");
  else if (k === "f") view("fit"); else if (k === "p") toggleParts();
  else if (k === "s") stats.toggle();
});

const fill = document.getElementById("fill"), msg = document.getElementById("msg"), loading = document.getElementById("loading");
// KiCad's export is tens of thousands of small meshes (36,759 on a CM5
// carrier), each its own draw call: that, not the triangle count, is what
// makes redraws slow. Nothing moves, so the meshes under `roots` are baked
// into world space and merged into one mesh per material: a few dozen draw
// calls, same picture.
function mergeByMaterial(roots, name) {
  const buckets = new Map(), keep = [];
  for (const r of roots) r.traverse((o) => {
    if (!o.isMesh) return;
    if (Array.isArray(o.material)) { keep.push(o); return; } // several materials: left as it is
    if (!buckets.has(o.material)) buckets.set(o.material, []);
    buckets.get(o.material).push(o);
  });
  const group = new THREE.Group();
  group.name = name;
  for (const [material, meshes] of buckets) {
    // mergeGeometries needs the same attributes everywhere, all indexed or none.
    const indexed = meshes.every((m) => m.geometry.index);
    const geos = meshes.map((m) => {
      let g = m.geometry.clone();
      if (!indexed && g.index) g = g.toNonIndexed();
      for (const a of Object.keys(g.attributes)) if (a !== "position" && a !== "normal") g.deleteAttribute(a);
      if (!g.attributes.normal) g.computeVertexNormals();
      g.applyMatrix4(m.matrixWorld);
      return g;
    });
    const merged = mergeGeometries(geos, false);
    geos.forEach((g) => g.dispose());
    if (!merged) { meshes.forEach((m) => keep.push(m)); continue; } // shouldn't happen; keep them as they are
    const mesh = new THREE.Mesh(merged, material);
    mesh.matrixAutoUpdate = false;
    group.add(mesh);
  }
  for (const m of keep) { // in world space too, outside their old parents
    const c = m.clone();
    m.matrixWorld.decompose(c.position, c.quaternion, c.scale);
    group.add(c);
  }
  return group;
}

new GLTFLoader().load(%%GLB%%, (gltf) => {
  const t0 = performance.now();
  const loaded = gltf.scene;
  loaded.updateMatrixWorld(true);
  // KiCad writes its colours as screen (sRGB) values where glTF expects
  // linear ones, so as they are the dark green mask shows as pale mint.
  // Read them as KiCad means them. Each material once (they're shared).
  const seen = new Set();
  loaded.traverse((o) => [].concat(o.material || []).forEach((m) => {
    if (seen.has(m)) return;
    seen.add(m);
    m.color?.convertSRGBToLinear();
  }));
  // Parts are the top-level nodes named by reference (J502, U3); the board's
  // own layers are named "=>[...]". Each side is merged on its own, so the
  // Parts button still hides just the parts.
  const root = loaded.children.length === 1 && !loaded.children[0].name ? loaded.children[0] : loaded;
  const isPart = (n) => n.name && !n.name.startsWith("=>");
  const partNodes = root.children.filter(isPart);
  const before = { meshes: 0 };
  loaded.traverse((o) => { if (o.isMesh) before.meshes++; });
  model = new THREE.Group();
  model.add(mergeByMaterial(root.children.filter((n) => !isPart(n)), "board"));
  const partsGroup = mergeByMaterial(partNodes, "parts");
  model.add(partsGroup);
  loaded.traverse((o) => { if (o.isMesh) o.geometry.dispose(); }); // the originals aren't drawn any more
  model.updateMatrixWorld(true);
  model.traverse((o) => { o.matrixAutoUpdate = false; o.matrixWorldAutoUpdate = false; });
  scene.add(model);
  let after = 0;
  model.traverse((o) => { if (o.isMesh) after++; });
  window.kigit3dMerge = { meshes_before: before.meshes, meshes_after: after, ms: Math.round(performance.now() - t0) };
  box.setFromObject(model);
  size = box.getSize(new THREE.Vector3()).length();
  camera.near = size / 500; camera.far = size * 50; camera.updateProjectionMatrix();
  controls.minDistance = size / 50; controls.maxDistance = size * 10;
  sun.position.copy(box.getCenter(new THREE.Vector3())).add(new THREE.Vector3(size, size * 2, size));
  under.position.copy(box.getCenter(new THREE.Vector3())).add(new THREE.Vector3(-size, -size * 2, -size));
  parts = partNodes.length ? [partsGroup] : [];
  if (!parts.length) partsBtn.disabled = true, partsBtn.title = "No 3D models of parts in this board";
  view("iso", false);
  loading.remove();
  redraw();
  window.kigit3dReady = true;
}, (p) => {
  if (p.total) { fill.style.width = (100 * p.loaded / p.total) + "%"; msg.textContent = `Loading the 3D board… ${(p.total / 1e6).toFixed(1)} MB`; }
}, (err) => {
  loading.classList.add("err");
  msg.textContent = "Couldn't load the 3D board: " + (err?.message || err);
});

// Render stats (?stats=1 or S): how long each redraw takes and how long
// after your input it's drawn. Nothing is measured while it's hidden.
const stats = (() => {
  const box = document.getElementById("stats"), table = document.getElementById("statsTable");
  const gl = renderer.getContext();
  const timer = gl.getExtension("EXT_disjoint_timer_query_webgl2"); // GPU time; not in every browser
  const KEEP = 600; // samples kept per series
  let on = false, s, inputAt = 0, lastDraw = 0, queries = [], longTasks = 0, longMs = 0;
  let held = false, lastInput = -1e9; // a drag in progress; the last input's time
  const reset = () => {
    s = { input: [], cpu: [], gpu: [], gap: [] };
    inputAt = 0; lastDraw = 0; longTasks = 0; longMs = 0;
  };
  reset();
  const add = (list, v) => { list.push(v); if (list.length > KEEP) list.shift(); };
  const pct = (list, q) => {
    if (!list.length) return null;
    const a = [...list].sort((x, y) => x - y);
    return a[Math.min(a.length - 1, Math.floor(q * a.length))];
  };
  // Input: the first unanswered drag, wheel or click, until a frame is drawn.
  const input = (e) => {
    if (e.type === "pointermove" && !e.buttons) return;
    lastInput = e.timeStamp;
    if (on && !inputAt) inputAt = e.timeStamp;
  };
  addEventListener("pointerdown", () => (held = true));
  addEventListener("pointerup", () => (held = false));
  for (const t of ["pointerdown", "pointermove", "wheel"]) renderer.domElement.addEventListener(t, input, { passive: true });
  try {
    new PerformanceObserver((l) => l.getEntries().forEach((e) => { if (on) { longTasks++; longMs += e.duration; } }))
      .observe({ type: "longtask" });
  } catch {}
  function draw() {
    if (!on) { renderer.render(scene, camera); return; }
    const t0 = performance.now();
    let q = null;
    if (timer && !queries.length) { q = gl.createQuery(); gl.beginQuery(timer.TIME_ELAPSED_EXT, q); }
    renderer.render(scene, camera);
    if (q) { gl.endQuery(timer.TIME_ELAPSED_EXT); queries.push(q); }
    const t1 = performance.now();
    add(s.cpu, t1 - t0);
    if (inputAt) { add(s.input, t1 - inputAt); inputAt = 0; }
    // Time since the last frame, for frames drawn while you drag or zoom
    // (not the pause before you start).
    const busy = held || t0 - lastInput < 400;
    if (lastDraw && busy && lastDraw > lastInput - 400) add(s.gap, t0 - lastDraw);
    lastDraw = busy ? t0 : 0;
  }
  function poll() { // GPU times arrive a frame or two later
    while (queries.length) {
      const q = queries[0];
      if (!gl.getQueryParameter(q, gl.QUERY_RESULT_AVAILABLE)) break;
      if (!gl.getParameter(timer.GPU_DISJOINT_EXT)) add(s.gpu, gl.getQueryParameter(q, gl.QUERY_RESULT) / 1e6);
      gl.deleteQuery(q);
      queries.shift();
    }
  }
  function report() {
    const row = (list) => ({ p50: pct(list, 0.5), p95: pct(list, 0.95), max: list.length ? Math.max(...list) : null, n: list.length });
    const info = renderer.info.render, size = renderer.getDrawingBufferSize(new THREE.Vector2());
    let meshes = 0;
    model?.traverse((o) => { if (o.isMesh && o.visible) meshes++; });
    return {
      input_to_drawn_ms: row(s.input), cpu_ms: row(s.cpu), gpu_ms: timer ? row(s.gpu) : "no GPU timer in this browser",
      frame_gap_ms: row(s.gap), dropped_frames: s.gap.filter((g) => g > 25).length, long_tasks: longTasks,
      long_task_ms: Math.round(longMs), draw_calls: info.calls, triangles: info.triangles, meshes,
      merged: window.kigit3dMerge || null,
      parts_shown: partsBtn.classList.contains("on"), pixels: `${size.x}x${size.y}`,
      pixel_ratio: renderer.getPixelRatio(), gpu: (() => {
        const d = gl.getExtension("WEBGL_debug_renderer_info");
        return d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : "unknown";
      })(),
    };
  }
  const f = (v) => (v == null ? "–" : v.toFixed(1));
  function show() {
    if (!on) return;
    if (timer) poll();
    const r = report();
    const line = (name, x, bad) => `<tr><th>${name}</th><td>${f(x.p50)}</td>` +
      `<td class="${x.p95 == null ? "" : x.p95 > bad ? "bad" : "ok"}">${f(x.p95)}</td><td>${x.n}</td></tr>`;
    table.innerHTML = `<tr><th></th><td>p50</td><td>p95</td><td>n</td></tr>` +
      line("input → drawn ms", r.input_to_drawn_ms, 33) + line("CPU / redraw ms", r.cpu_ms, 16) +
      (timer ? line("GPU / redraw ms", r.gpu_ms, 16) : `<tr><th>GPU / redraw ms</th><td colspan=3>no timer here</td></tr>`) +
      line("frame gap ms", r.frame_gap_ms, 25) +
      `<tr><th>dropped frames</th><td colspan=3 class="${r.dropped_frames ? "bad" : ""}">${r.dropped_frames}</td></tr>` +
      `<tr><th>long tasks</th><td colspan=3>${r.long_tasks} (${r.long_task_ms} ms)</td></tr>` +
      `<tr><th>draw calls</th><td colspan=3>${r.draw_calls.toLocaleString()}</td></tr>` +
      `<tr><th>triangles</th><td colspan=3>${r.triangles.toLocaleString()}</td></tr>` +
      `<tr><th>meshes shown</th><td colspan=3>${r.meshes.toLocaleString()}</td></tr>` +
      (r.merged ? `<tr><th>merged on load</th><td colspan=3>${r.merged.meshes_before.toLocaleString()} → ${r.merged.meshes_after} meshes, ${r.merged.ms} ms</td></tr>` : "") +
      `<tr><th>pixels</th><td colspan=3>${r.pixels} @${r.pixel_ratio}</td></tr>`;
  }
  setInterval(show, 500);
  document.getElementById("statsReset").addEventListener("click", () => { reset(); show(); });
  document.getElementById("statsCopy").addEventListener("click", (e) => {
    navigator.clipboard?.writeText(JSON.stringify(report(), null, 2)).then(() => (e.target.textContent = "Copied"));
    setTimeout(() => (e.target.textContent = "Copy"), 1200);
  });
  const toggle = (want = !on) => { on = want; box.classList.toggle("on", on); if (on) { reset(); redraw(); show(); } };
  window.kigit3dStats = report; // for scripted checks
  return { draw, toggle, get on() { return on; } };
})();
if (new URLSearchParams(location.search).has("stats")) stats.toggle(true);

// Draw only when something changed: a drag, a zoom, a view change, or the
// glide after letting go (controls.update() is true while it's still moving).
var queued = false;  // var: resize() calls redraw() before this line runs
function redraw() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => {
    queued = false;
    if (controls.update()) redraw();
    stats.draw();
  });
}
controls.addEventListener("change", redraw);
redraw();
</script>
</body>
</html>
"""
