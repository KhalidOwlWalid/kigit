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
import urllib.parse
from pathlib import Path

import nicegui
from fastapi import Request
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


def grid_page(boards: list[tuple[str, str, str]]) -> str:
    """Several boards side by side: (name in the cache, title, subtitle)
    each, with their views linked."""
    cells = "".join(
        f'<iframe title="{html.escape(t)}" src="/board3d/{n}?'
        f'{urllib.parse.urlencode({"title": t, "subtitle": sub})}"></iframe>' for n, t, sub in boards)
    cols = len(boards) if len(boards) <= 3 else 2
    return _GRID.replace("%%COLS%%", str(cols)).replace("%%CELLS%%", cells).replace("%%N%%", str(len(boards)))


@app.get("/board3d-grid")
async def _grid(request: Request) -> Response:
    from .app import CACHE, MAX_3D

    q = request.query_params
    names, titles, subs = q.getlist("b"), q.getlist("t"), q.getlist("s")
    if not 1 <= len(names) <= MAX_3D or any(not _NAME.match(n) or not (CACHE / n).is_file() for n in names):
        return Response("No such 3D boards.", status_code=404)
    pad = lambda xs: xs + [""] * (len(names) - len(xs))
    return HTMLResponse(grid_page(list(zip(names, pad(titles), pad(subs)))))


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
/* Narrow (a cell of the side-by-side view): title on top, buttons at the
   bottom, no hint. */
@media (max-width: 760px) {
  #info { max-width: calc(100% - 24px); padding: 6px 10px; }
  #tools { top: auto; bottom: 12px; right: 50%; transform: translateX(50%); padding: 4px; gap: 2px; }
  #tools button { padding: 4px 7px; }
  #hint { display: none; }
}
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
  <button id="mask" class="on" title="Show or hide the solder mask. Off, the copper lies bare and every trace is easy to follow, as in KiCad's 3D viewer (M)">Mask</button>
  <button id="silk" class="on" title="Show or hide the silkscreen (K)">Silk</button>
  <button id="parts" class="on" title="Show or hide the parts' 3D models (P)">Parts</button>
  <span class="sep newtab" hidden></span>
  <button id="newtab" class="newtab" hidden title="Open this 3D view in a new browser tab">&#x2197; New tab</button>
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
renderer.toneMappingExposure = 1.35;
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
  scene.environmentIntensity = 0.3;  // more washes the mask out seen from above (measured against KiCad's render)
}
scene.add(new THREE.HemisphereLight(0xffffff, 0x404650, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.8);
scene.add(sun);
const under = new THREE.DirectionalLight(0xffffff, 1.0);  // the bottom side gets light too
scene.add(under);

const MASK_OPACITY = 0.8;  // KiCad exports 0.83; a little less lets traces show
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
// Layers to show or hide: the solder mask, the silkscreen and the parts.
// Side by side, the other boards follow (see the grid page).
const layers = { mask: [], silk: [], parts: [] };
const toggles = { mask: document.getElementById("mask"), silk: document.getElementById("silk"),
                  parts: document.getElementById("parts") };
const partsBtn = toggles.parts;
function setLayer(name, on, tell = true) {
  toggles[name].classList.toggle("on", on);
  layers[name].forEach((o) => (o.visible = on));
  redraw();
  if (tell && window.parent !== window) parent.postMessage({ kigit3d: "layer", name, on }, "*");
}
const toggleLayer = (name) => setLayer(name, !toggles[name].classList.contains("on"));
const toggleParts = () => toggleLayer("parts");
for (const name of Object.keys(toggles)) toggles[name].addEventListener("click", () => toggleLayer(name));
addEventListener("message", (e) => {
  const m = e.data;
  if (m && m.kigit3d === "setLayer" && toggles[m.name]) setLayer(m.name, !!m.on, false);
});
// Shown inside the GUI's viewer: open this page in its own tab. Not in a
// side-by-side cell (the grid has its own) or in the dock (?dock=1: its bar has one).
if (window !== window.top && window.parent === window.top && !new URLSearchParams(location.search).has("dock")) {
  document.querySelectorAll(".newtab").forEach((el) => { el.hidden = false; });
  document.getElementById("newtab").onclick = () => window.open(location.href, "_blank");
}

addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === "t") view("top"); else if (k === "b") view("bottom"); else if (k === "3") view("iso");
  else if (k === "f") view("fit"); else if (k === "p") toggleParts();
  else if (k === "s") stats.toggle();
  else if (k === "m") toggleLayer("mask"); else if (k === "k") toggleLayer("silk");
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
    // Copper and pads: KiCad exports them as pure metal, which only mirrors
    // the (grey) room and comes out dull olive. Half metal keeps their gold,
    // as in KiCad's viewer. Part models are left as they are.
    if (m.metalness === 1 && !m.transparent) { m.metalness = 0.55; m.roughness = Math.min(m.roughness, 0.35); }
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
  const boardGroup = mergeByMaterial(root.children.filter((n) => !isPart(n)), "board");
  model.add(boardGroup);
  // The board's see-through layers: the solder mask (coloured) and the
  // silkscreen (white), as KiCad exports them. The mask is made a little
  // thinner than KiCad's 0.83 so the copper under it shows a bit more.
  for (const mesh of boardGroup.children) {
    const m = mesh.material, c = m?.color;
    if (!m?.transparent || !c) continue;
    if (Math.min(c.r, c.g, c.b) < 0.5) {
      layers.mask.push(mesh);
      if (m.opacity > MASK_OPACITY) m.opacity = MASK_OPACITY;
      // Pulled towards the camera over the copper, as KiCad does (polygon offset -2).
      m.polygonOffset = true; m.polygonOffsetFactor = -1; m.polygonOffsetUnits = -2;
    } else {
      layers.silk.push(mesh);
      // The silkscreen sits on the mask, nearly in the same plane. Both
      // see-through, which is drawn first flips as the board turns, and at
      // a low angle the mask ends up over the silkscreen and hides it. So,
      // like KiCad (offset -4, in front of the mask's -2): solid, always in
      // front of the mask, and a little self-lit so it stays white when the
      // light only grazes it.
      m.transparent = false; m.opacity = 1; m.depthWrite = true;
      m.polygonOffset = true; m.polygonOffsetFactor = -2; m.polygonOffsetUnits = -4;
      m.roughness = 0.7;
      m.emissive?.copy(m.color).multiplyScalar(0.35);
      m.needsUpdate = true;
    }
  }
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
  layers.parts = parts;
  for (const [name, list] of Object.entries(layers))
    if (!list.length) toggles[name].disabled = true, toggles[name].title = `No ${name} in this board`;
  applying = true; // its first view isn't sent to the other boards: they may have been turned already
  view("iso", false);
  applying = false;
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

// Side by side (/board3d-grid): this view's camera goes to the page around
// it, which hands it to the other boards, and theirs come here. All boards
// share KiCad's coordinates, so the same camera shows the same spot.
// `applying` keeps a camera that came in from being sent back out.
let applying = false;
if (window.parent !== window) {
  const arr = (v) => [v.x, v.y, v.z];
  controls.addEventListener("change", () => {
    if (applying || !model) return;
    parent.postMessage({ kigit3d: "camera", p: arr(camera.position), t: arr(controls.target), u: arr(camera.up) }, "*");
  });
  addEventListener("message", (e) => {
    const m = e.data;
    if (!m || m.kigit3d !== "setCamera" || !model) return;
    applying = true;
    camera.position.fromArray(m.p);
    controls.target.fromArray(m.t);
    camera.up.fromArray(m.u);
    controls.update();
    applying = false;
    redraw();
  });
}
redraw();
</script>
</body>
</html>
"""

# The side-by-side page: one /board3d page per board, in a grid. It relays
# each board's camera to the others while "Link views" is on.
_GRID = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>3D boards</title>
<style>
html, body { margin: 0; height: 100%; overflow: hidden; background: #0f1115; color: #9aa4b2;
  font: 13px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
body { display: flex; flex-direction: column; }
.top { flex: none; display: flex; align-items: center; gap: 14px; padding: 4px 12px; border-bottom: 1px solid #29303a;
  background: #161a20; }
.top .n { color: #e6e9ee; }
.grid { flex: 1; min-height: 0; display: grid; grid-template-columns: repeat(%%COLS%%, 1fr); grid-auto-rows: 1fr;
  gap: 2px; background: #29303a; }
iframe { width: 100%; height: 100%; border: 0; display: block; background: #0f1115; }
#link { display: flex; gap: 7px; align-items: center; cursor: pointer; user-select: none; }
#link input { accent-color: #e8b84d; margin: 0; }
#newtab { margin-left: auto; border: 1px solid transparent; background: none; color: #9aa4b2; border-radius: 7px;
  padding: 3px 10px; font: inherit; cursor: pointer; }
#newtab:hover { color: #e6e9ee; background: rgba(255,255,255,.06); }
</style>
</head>
<body>
<div class="top"><span class="n">%%N%% boards, oldest first</span>
  <label id="link" title="Turn one board and the others turn with it (L)"><input type="checkbox" id="linked" checked> Link views</label>
  <button id="newtab" hidden title="Open these boards in a new browser tab">&#x2197; New tab</button></div>
<div class="grid">%%CELLS%%</div>
<script>
const frames = [...document.querySelectorAll("iframe")];
const linked = document.getElementById("linked");
addEventListener("message", (e) => {
  const m = e.data;
  if (!linked.checked || !m || (m.kigit3d !== "camera" && m.kigit3d !== "layer")) return;
  const relay = { ...m, kigit3d: m.kigit3d === "camera" ? "setCamera" : "setLayer" };  // views and layers alike
  for (const f of frames)
    if (f.contentWindow !== e.source) f.contentWindow.postMessage(relay, "*");
});
// L in any board toggles linking (the boards' own keys stay theirs).
const toggle = () => { linked.checked = !linked.checked; };
addEventListener("keydown", (e) => { if (e.key.toLowerCase() === "l") toggle(); });
for (const f of frames) f.addEventListener("load", () => {
  try { f.contentWindow.addEventListener("keydown", (e) => { if (e.key.toLowerCase() === "l") toggle(); }); } catch {}
});
if (window !== window.top && !new URLSearchParams(location.search).has("dock")) {
  const nt = document.getElementById("newtab");
  nt.hidden = false;
  nt.onclick = () => window.open(location.href, "_blank");
}
window.kigit3dGrid = %%N%%;
</script>
</body>
</html>
"""
