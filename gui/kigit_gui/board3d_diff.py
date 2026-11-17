"""The 3D diff (beta): a comparison's changes on the board in 3D. Separate
from the 3D view (board3d.py), which stays as it is.

KiCad makes each board's 3D model (kigit --3d, the same models the 3D view
uses); this page draws the newer one and marks what changed, from kigit's
comparison data (kigit --json):

- parts: added (green), changed (amber), moved (blue, with a ghost of the
  old place), removed (a red ghost, from the older board's model);
- tracks and vias: added (green), removed (red), changed (amber), drawn as
  strips on the copper (KiCad exports a layer's copper as one shape).

KiCad's model is in metres in the board's own coordinates: x = X / 1000,
z = Y / 1000, y up (checked on blinky and CM5). The page also says which
graphics chip draws it: built-in graphics may lag on big boards, and with
none the CPU draws it all.

GUI: the header's "3D diff" button (with "beta") opens /board3d-diff/{job}
in a new tab; it waits there while KiCad makes the models, then shows them.
"""

from __future__ import annotations

import html
import json
import re
import secrets
import time
from dataclasses import dataclass, field

from fastapi.responses import HTMLResponse, JSONResponse, Response
from nicegui import app

_NAME = re.compile(r"^[\w.-]+\.(glb|json)$")


@dataclass
class Job:
    """A 3D diff being made: models and the comparison data, then the page."""
    title: str
    new_glb: str
    old_glb: str
    diff_json: str
    expected: float | None = None
    started: float = field(default_factory=time.monotonic)
    done: bool = False
    error: str = ""


jobs: dict[str, Job] = {}


def new_job(job: Job) -> str:
    key = secrets.token_hex(8)
    jobs[key] = job
    return key


@app.get("/board3d-diff/{key}")
async def _page(key: str) -> Response:
    job = jobs.get(key)
    if job is None:
        return HTMLResponse("<p style='font-family:sans-serif;color:#aaa'>This 3D diff is gone (kigit was "
                            "restarted?). Press 3D diff again.</p>", status_code=404)
    if not job.done:
        return HTMLResponse(_WAIT.replace("%%KEY%%", key).replace("%%TITLE%%", html.escape(job.title)))
    return HTMLResponse(page(job))


@app.get("/board3d-diff/{key}/status")
async def _status(key: str) -> Response:
    job = jobs.get(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    return JSONResponse({"done": job.done, "error": job.error, "elapsed": time.monotonic() - job.started,
                         "expected": job.expected})


def page(job: Job) -> str:
    return (_PAGE.replace("%%NEW%%", json.dumps(f"/diffs/{job.new_glb}"))
            .replace("%%OLD%%", json.dumps(f"/diffs/{job.old_glb}"))
            .replace("%%DIFF%%", json.dumps(f"/diffs/{job.diff_json}"))
            .replace("%%TITLE%%", html.escape(job.title)))


# While KiCad makes the models: a progress bar against the last build's time.
_WAIT = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>3D diff (beta)</title>
<style>
body { margin: 0; height: 100vh; display: grid; place-items: center; background: #0f1115; color: #c7ced8;
  font: 14px system-ui, sans-serif; }
.box { width: min(30rem, 90vw); text-align: center; }
h1 { font-size: 17px; margin: 0 0 4px; color: #e6e9ee; } .beta { font-size: 11px; color: #c39bff;
  border: 1px solid #c39bff; border-radius: 999px; padding: 0 7px; margin-left: 6px; vertical-align: 2px; }
.track { height: 5px; border-radius: 3px; background: #29303a; overflow: hidden; margin: 18px 0 8px; }
.fill { height: 100%; width: 30%; background: #e8b84d; transition: width .4s; }
.fill.unknown { animation: slide 1.4s ease-in-out infinite; }
@keyframes slide { from { margin-left: -30%; } to { margin-left: 100%; } }
.err { color: #f07178; }
</style></head><body><div class="box">
<h1>3D diff<span class="beta">beta</span></h1><div>%%TITLE%%</div>
<div class="track"><div class="fill unknown" id="fill"></div></div>
<div id="msg">KiCad is making the 3D models of both boards...</div>
</div><script>
const fill = document.getElementById("fill"), msg = document.getElementById("msg");
async function poll() {
  let s;
  try { s = await (await fetch("/board3d-diff/%%KEY%%/status")).json(); } catch { setTimeout(poll, 1500); return; }
  if (s.error) { msg.className = "err"; msg.textContent = "Couldn't make the 3D diff: " + s.error; fill.style.width = "0"; return; }
  if (s.done) { location.reload(); return; }
  const t = Math.round(s.elapsed);
  if (s.expected) {
    fill.classList.remove("unknown");
    fill.style.width = Math.min(95, 100 * s.elapsed / s.expected) + "%";
    msg.textContent = `KiCad is making the 3D models... ${t} s of about ${Math.round(s.expected)} s`;
  } else msg.textContent = `KiCad is making the 3D models... ${t} s (a big board takes a minute or two)`;
  setTimeout(poll, 1000);
}
poll();
</script></body></html>"""


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>3D diff (beta) · %%TITLE%%</title>
<script type="importmap">
{"imports": {"three": "/kigit-three/three.module.js", "GLTFLoader": "/kigit-three/modules/GLTFLoader.js",
 "OrbitControls": "/kigit-three/modules/OrbitControls.js",
 "BufferGeometryUtils": "/kigit-three/modules/BufferGeometryUtils.js"}}
</script>
<style>
:root { --bg: #0f1115; --panel: rgba(22, 26, 32, .9); --line: #29303a; --text: #e6e9ee; --muted: #9aa4b2;
  --faint: #6b7584; --accent: #e8b84d; --add: #3fb950; --rem: #f85149; --chg: #e8b84d; --mov: #58a6ff; --beta: #c39bff; }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; overflow: hidden; background: var(--bg); color: var(--text);
  font: 13px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
canvas { display: block; outline: none; }
.bar { position: absolute; display: flex; gap: 6px; align-items: center; padding: 6px; background: var(--panel);
  border: 1px solid var(--line); border-radius: 10px; backdrop-filter: blur(6px); }
#info { left: 12px; top: 12px; flex-direction: column; align-items: flex-start; gap: 2px; padding: 8px 12px; max-width: 46%; }
#info b { font-size: 14px; } .beta { font-size: 10.5px; color: var(--beta); border: 1px solid var(--beta);
  border-radius: 999px; padding: 0 6px; margin-left: 6px; font-weight: 600; vertical-align: 1px; }
#legend { display: flex; flex-wrap: wrap; gap: 4px 12px; color: var(--muted); font-size: 12px; margin-top: 4px; }
#legend span::before { content: ""; display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 5px;
  vertical-align: -1px; background: var(--c); }
#tools { right: 12px; top: 12px; flex-wrap: wrap; justify-content: flex-end; max-width: 54%; }
button { border: 1px solid transparent; background: none; color: var(--muted); border-radius: 7px; padding: 5px 10px;
  font: inherit; cursor: pointer; }
button:hover { color: var(--text); background: rgba(255,255,255,.06); }
button.on { color: var(--accent); border-color: rgba(232,184,77,.45); }
.sep { width: 1px; align-self: stretch; background: var(--line); margin: 2px; }
#gpu { left: 12px; bottom: 12px; font-size: 12px; padding: 6px 10px; max-width: min(40rem, 70vw); }
#gpu.good { color: #7fd99a; } #gpu.meh { color: var(--accent); } #gpu.bad { color: var(--rem); }
#hint { right: 12px; bottom: 12px; color: var(--faint); font-size: 12px; padding: 5px 10px; }
#loading { position: absolute; inset: 0; display: grid; place-items: center; background: var(--bg); color: var(--muted); }
#loading.err { color: var(--rem); }
@media (max-width: 860px) { #info { max-width: calc(100% - 24px); } #tools { top: auto; bottom: 52px; right: 12px; max-width: none; }
  #hint { display: none; } }
</style>
</head>
<body>
<div id="info" class="bar"><b>3D diff<span class="beta">beta</span></b><span>%%TITLE%%</span><div id="legend"></div></div>
<div id="tools" class="bar">
  <button data-view="top" title="Look at the top (T)">Top</button>
  <button data-view="bottom" title="Look at the bottom (B)">Bottom</button>
  <button data-view="iso" title="Angled view (3)">3D</button>
  <button data-view="fit" title="Fit the board in view (F)">Fit</button>
  <span class="sep"></span>
  <button id="changes" class="on" title="Show what changed: parts tinted, removed ones as ghosts, tracks as coloured strips (C)">Changes</button>
  <button id="fade" class="on" title="Fade the parts that didn't change, so the changed ones stand out (U)">Fade others</button>
  <span class="sep"></span>
  <button id="mask" class="on" title="The solder mask (M)">Mask</button>
  <button id="silk" class="on" title="The silkscreen (K)">Silk</button>
  <button id="parts" class="on" title="The parts' 3D models (P)">Parts</button>
</div>
<div id="gpu" class="bar" title="Which graphics chip draws this page, as the browser reports it">Checking the graphics...</div>
<div id="hint" class="bar">Drag to rotate · right-drag to pan · scroll to zoom</div>
<div id="loading">Loading the boards...</div>
<script type="module">
import * as THREE from "three";
import { GLTFLoader } from "GLTFLoader";
import { OrbitControls } from "OrbitControls";
import { mergeGeometries } from "BufferGeometryUtils";

const COLORS = { add: 0x3fb950, rem: 0xf85149, chg: 0xe8b84d, mov: 0x58a6ff, old: 0x8b949e };

// ------------------------------------------------------------ the graphics chip
// What the browser draws with: a dedicated GPU, built-in graphics (laptops:
// may lag on big boards), or none (the CPU draws everything: slow).
const probe = document.createElement("canvas").getContext("webgl2") || document.createElement("canvas").getContext("webgl");
let chip = "", tier = "good";
if (!probe) { tier = "bad"; chip = "no WebGL"; }
else {
  const ext = probe.getExtension("WEBGL_debug_renderer_info");
  chip = (ext ? probe.getParameter(ext.UNMASKED_RENDERER_WEBGL) : probe.getParameter(probe.RENDERER)) || "";
  const c = chip.toLowerCase();
  if (/swiftshader|llvmpipe|softpipe|software|basic render|lavapipe/.test(c)) tier = "bad";
  else if (/nvidia|geforce|quadro|rtx|gtx|radeon rx|radeon pro|arc a\\d|apple m\\d/.test(c)) tier = "good";
  else if (/intel|uhd|iris|hd graphics|radeon\\(tm\\)|radeon graphics|vega \\d+ graphics|mali|adreno|powervr|apple gpu/.test(c)) tier = "meh";
}
// "ANGLE (Vendor, Renderer, API)": the renderer is what people know it by.
let short = chip;
const angle = chip.match(/^ANGLE \\((.*)\\)$/);
if (angle) { const parts = angle[1].split(/, (?![^(]*\\))/); short = (parts[1] || parts[0]).replace(/ Direct3D.*$| \\(0x[0-9A-F]+\\)/gi, ""); }
short = short.slice(0, 90);
const gpu = document.getElementById("gpu");
gpu.className = "bar " + tier;
gpu.textContent = tier === "good" ? `✓ Graphics: ${short}`
  : tier === "meh" ? `⚠ Built-in graphics (${short}): big boards may lag; the CPU and GPU share the work`
  : `⚠ No graphics chip in use (${short || "unknown"}): your CPU draws all of this, so it'll be slow`;
window.kigit3dDiffGpu = { chip, tier };

// ------------------------------------------------------------------ the scene
const renderer = new THREE.WebGLRenderer({ antialias: tier !== "bad" });
renderer.setPixelRatio(tier === "good" ? Math.min(devicePixelRatio, 1.5) : 1);  // less work on weak graphics
renderer.toneMapping = THREE.NeutralToneMapping;
renderer.toneMappingExposure = 1.35;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.prepend(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0f1115);
{
  const room = new THREE.Scene();
  room.add(new THREE.Mesh(new THREE.BoxGeometry(10, 10, 10), new THREE.MeshBasicMaterial({ color: 0x3a3f47, side: THREE.BackSide })));
  const panel = (x, y, z, w, h, k) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(k, k, k) }));
    m.position.set(x, y, z); m.lookAt(0, 0, 0); room.add(m); };
  panel(0, 4.9, 0, 6, 6, 5); panel(0, -4.9, 0, 6, 6, 3); panel(4.9, 2, 2, 3, 3, 2.5); panel(-4.9, 2, -2, 3, 3, 2);
  scene.environment = new THREE.PMREMGenerator(renderer).fromScene(room, 0.04).texture;
  scene.environmentIntensity = 0.3;
}
scene.add(new THREE.HemisphereLight(0xffffff, 0x404650, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.8), under = new THREE.DirectionalLight(0xffffff, 1.0);
scene.add(sun, under);
const camera = new THREE.PerspectiveCamera(35, 1, 0.0001, 100);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.12; controls.screenSpacePanning = true;
let pending = false;
function redraw() { if (pending) return; pending = true; requestAnimationFrame(() => { pending = false; if (controls.update()) redraw(); renderer.render(scene, camera); }); }
controls.addEventListener("change", redraw);
function resize() { renderer.setSize(innerWidth, innerHeight); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); redraw(); }
addEventListener("resize", resize); resize();

let box = new THREE.Box3(), size = 1;
function view(name) {
  const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3());
  const d = Math.max(Math.max(s.x / camera.aspect, s.z) / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) * 1.25, size * 0.6);
  let pos, up = new THREE.Vector3(0, 1, 0);
  if (name === "top") { pos = new THREE.Vector3(0, d, 0); up.set(0, 0, -1); }
  else if (name === "bottom") { pos = new THREE.Vector3(0, -d, 0); up.set(0, 0, -1); }
  else if (name === "fit") pos = camera.position.clone().sub(controls.target).setLength(d);
  else pos = new THREE.Vector3(0, d * 0.75, d * 0.85);
  camera.position.copy(c.clone().add(pos)); camera.up.copy(up); controls.target.copy(c); controls.update(); redraw();
}
document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => view(b.dataset.view)));

// ---------------------------------------------------------------- helpers
function fixMaterials(root) {  // as the 3D view does: KiCad's colours are sRGB; pure-metal copper made half metal
  const seen = new Set();
  root.traverse((o) => [].concat(o.material || []).forEach((m) => {
    if (seen.has(m)) return; seen.add(m);
    m.color?.convertSRGBToLinear();
    if (m.metalness === 1 && !m.transparent) { m.metalness = 0.55; m.roughness = Math.min(m.roughness, 0.35); }
  }));
}
function mergeByMaterial(roots) {  // fewer draw calls for what doesn't change
  const buckets = new Map(), keep = [];
  for (const r of roots) r.traverse((o) => { if (!o.isMesh) return;
    if (Array.isArray(o.material)) { keep.push(o); return; }
    if (!buckets.has(o.material)) buckets.set(o.material, []); buckets.get(o.material).push(o); });
  const g = new THREE.Group();
  for (const [material, meshes] of buckets) {
    const indexed = meshes.every((m) => m.geometry.index);
    const geos = meshes.map((m) => { let x = m.geometry.clone(); if (!indexed && x.index) x = x.toNonIndexed();
      for (const a of Object.keys(x.attributes)) if (a !== "position" && a !== "normal") x.deleteAttribute(a);
      if (!x.attributes.normal) x.computeVertexNormals(); x.applyMatrix4(m.matrixWorld); return x; });
    const merged = mergeGeometries(geos, false); geos.forEach((x) => x.dispose());
    if (!merged) { keep.push(...meshes); continue; }
    g.add(new THREE.Mesh(merged, material));
  }
  for (const m of keep) { const c = m.clone(); m.matrixWorld.decompose(c.position, c.quaternion, c.scale); g.add(c); }
  return g;
}
function inWorld(node, material) {  // a part's meshes, placed as they are, with its own (tinted) materials
  const g = new THREE.Group();
  node.traverse((o) => { if (!o.isMesh) return;
    const c = new THREE.Mesh(o.geometry, material ? material(o.material) : o.material);
    o.matrixWorld.decompose(c.position, c.quaternion, c.scale); g.add(c); });
  return g;
}
const tint = (hex, amount) => (m) => { const t = (Array.isArray(m) ? m[0] : m).clone(); const c = new THREE.Color(hex);
  t.color?.lerp(c, amount); if (t.emissive) { t.emissive.copy(c); t.emissiveIntensity = 0.45; } return t; };
const ghost = (hex) => () => new THREE.MeshStandardMaterial({ color: hex, emissive: hex, emissiveIntensity: 0.35,
  transparent: true, opacity: 0.32, depthWrite: false });
const loadModel = (url) => new Promise((ok, fail) => new GLTFLoader().load(url, (g) => ok(g.scene), undefined, fail));
const rootOf = (loaded) => loaded.children.length === 1 && !loaded.children[0].name ? loaded.children[0] : loaded;
const isPart = (n) => n.name && !n.name.startsWith("=>");

// Tracks and arcs come as SVG paths in board mm ("M x y L x y", "A r r 0 large sweep x y").
function pathPoints(d) {
  const t = d.match(/[MLA]|-?\\d*\\.?\\d+(?:e-?\\d+)?/g) || [];
  const pts = []; let i = 0, cmd = "", cur = null;
  while (i < t.length) {
    if (/[MLA]/.test(t[i])) cmd = t[i++];
    if (cmd === "M" || cmd === "L") { cur = [+t[i], +t[i + 1]]; i += 2; pts.push(cur); }
    else if (cmd === "A") {
      const r = +t[i], large = +t[i + 3], sweep = +t[i + 4], end = [+t[i + 5], +t[i + 6]]; i += 7;
      pts.push(...arcPoints(cur, end, r, large, sweep)); cur = end;
    } else i++;
  }
  return pts;
}
function arcPoints(p0, p1, r, large, sweep) {  // SVG's endpoint arc to points along it
  const dx = (p0[0] - p1[0]) / 2, dy = (p0[1] - p1[1]) / 2, d2 = dx * dx + dy * dy;
  r = Math.max(r, Math.sqrt(d2));
  let k = Math.sqrt(Math.max(0, (r * r - d2) / d2)); if (large === sweep) k = -k;
  const cx = (p0[0] + p1[0]) / 2 + k * dy, cy = (p0[1] + p1[1]) / 2 - k * dx;
  let a0 = Math.atan2(p0[1] - cy, p0[0] - cx), a1 = Math.atan2(p1[1] - cy, p1[0] - cx), da = a1 - a0;
  if (sweep && da < 0) da += 2 * Math.PI; if (!sweep && da > 0) da -= 2 * Math.PI;
  const n = Math.max(4, Math.ceil(Math.abs(da) / 0.15)), out = [];
  for (let s = 1; s <= n; s++) { const a = a0 + da * s / n; out.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]); }
  return out;
}
// Flat strips (and via rings) in one geometry per colour: board mm to model metres, at a height.
function strips(list, y) {
  const pos = [];
  const quad = (a, b, w) => { const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1;
    const nx = -dy / L * w / 2, ny = dx / L * w / 2;
    const v = [[a[0] + nx, a[1] + ny], [b[0] + nx, b[1] + ny], [b[0] - nx, b[1] - ny], [a[0] - nx, a[1] - ny]];
    for (const k of [0, 1, 2, 0, 2, 3]) pos.push(v[k][0] / 1000, y, v[k][1] / 1000); };
  const disc = (c, rOut, rIn) => { const n = 16; for (let s = 0; s < n; s++) {
      const a = 2 * Math.PI * s / n, b = 2 * Math.PI * (s + 1) / n;
      const o0 = [c[0] + rOut * Math.cos(a), c[1] + rOut * Math.sin(a)], o1 = [c[0] + rOut * Math.cos(b), c[1] + rOut * Math.sin(b)];
      const i0 = [c[0] + rIn * Math.cos(a), c[1] + rIn * Math.sin(a)], i1 = [c[0] + rIn * Math.cos(b), c[1] + rIn * Math.sin(b)];
      for (const p of [o0, o1, i1, o0, i1, i0]) pos.push(p[0] / 1000, y, p[1] / 1000); } };
  for (const it of list) {
    if (it.k === "v") { disc([it.x, it.y], it.w / 2, (it.dr || it.w / 3) / 2); continue; }
    const pts = pathPoints(it.d); const w = Math.max(it.w, 0.12);
    for (let s = 1; s < pts.length; s++) quad(pts[s - 1], pts[s], w);
  }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  return g;
}

// ------------------------------------------------------------- the toggles
const groups = { changes: [], fade: [], mask: [], silk: [], parts: [] };
const btn = (id) => document.getElementById(id);
function toggle(name) {
  const b = btn(name), on = !b.classList.contains("on"); b.classList.toggle("on", on);
  if (name === "fade") fadeOthers(on); else groups[name].forEach((o) => (o.visible = on));
  redraw();
}
for (const n of Object.keys(groups)) btn(n).addEventListener("click", () => toggle(n));
addEventListener("keydown", (e) => { if (e.ctrlKey || e.metaKey || e.altKey) return; const k = e.key.toLowerCase();
  if (k === "t") view("top"); else if (k === "b") view("bottom"); else if (k === "3") view("iso"); else if (k === "f") view("fit");
  else if (k === "c") toggle("changes"); else if (k === "u") toggle("fade"); else if (k === "m") toggle("mask");
  else if (k === "k") toggle("silk"); else if (k === "p") toggle("parts"); });
let fadeMats = [];
function fadeOthers(on) { for (const m of fadeMats) { m.transparent = on || m.userData.wasTransparent; m.opacity = on ? 0.22 : m.userData.opacity; m.depthWrite = !on; m.needsUpdate = true; } }

// ------------------------------------------------------------------- load
(async () => {
  const diff = await (await fetch(%%DIFF%%)).json();
  const fps = diff.footprints || [];
  const status = new Map();  // ref -> add | rem | chg | mov
  for (const f of fps) status.set(f.ref, f.st === 1 ? "add" : f.st === 2 ? "rem" : (f.st === 3 || f.moved) ? "mov" : "chg");
  const needOld = [...status.values()].some((s) => s === "rem" || s === "mov");
  const [neu, old] = await Promise.all([loadModel(%%NEW%%), needOld ? loadModel(%%OLD%%) : Promise.resolve(null)]);
  neu.updateMatrixWorld(true); fixMaterials(neu);
  const root = rootOf(neu), partNodes = root.children.filter(isPart);
  const model = new THREE.Group();
  const board = mergeByMaterial(root.children.filter((n) => !isPart(n)));
  for (const mesh of board.children) {  // mask and silkscreen, as in the 3D view
    const m = mesh.material, c = m?.color; if (!m?.transparent || !c) continue;
    if (Math.min(c.r, c.g, c.b) < 0.5) { groups.mask.push(mesh); m.opacity = Math.min(m.opacity, 0.8);
      m.polygonOffset = true; m.polygonOffsetFactor = -1; m.polygonOffsetUnits = -2; }
    else { groups.silk.push(mesh); m.transparent = false; m.opacity = 1; m.depthWrite = true;
      m.polygonOffset = true; m.polygonOffsetFactor = -2; m.polygonOffsetUnits = -4; m.emissive?.copy(m.color).multiplyScalar(0.35); m.needsUpdate = true; }
  }
  model.add(board);
  const bb = new THREE.Box3().setFromObject(board), top = bb.max.y + 0.00003, bottom = bb.min.y - 0.00003;
  // Parts: the changed ones apart and tinted; the rest merged (and faded, to make the changes stand out).
  const changed = [], same = [];
  for (const n of partNodes) (status.has(n.name) && status.get(n.name) !== "rem" ? changed : same).push(n);
  const sameGroup = mergeByMaterial(same);
  sameGroup.traverse((o) => { if (o.isMesh) for (const m of [].concat(o.material)) if (!fadeMats.includes(m)) {
    m.userData.opacity = m.opacity; m.userData.wasTransparent = m.transparent; fadeMats.push(m); } });
  model.add(sameGroup); groups.parts.push(sameGroup);
  const counts = { add: 0, chg: 0, mov: 0, rem: 0 };
  for (const n of changed) { const s = status.get(n.name); counts[s]++;
    const g = inWorld(n, tint(COLORS[s], 0.55)); model.add(g); groups.parts.push(g); groups.changes.push(g); }
  // From the older board: removed parts, and where moved ones were, as ghosts.
  if (old) {
    old.updateMatrixWorld(true); fixMaterials(old);
    for (const n of rootOf(old).children.filter(isPart)) { const s = status.get(n.name);
      if (s !== "rem" && s !== "mov") continue;
      if (s === "rem") counts.rem++;
      const g = inWorld(n, ghost(s === "rem" ? COLORS.rem : COLORS.mov)); model.add(g); groups.changes.push(g); }
  }
  // Parts without a 3D model (a test point, say): an outline around their
  // pads instead, in their colour (removed ones from the old pads).
  const drawn = new Set([...changed.map((n) => n.name)]);
  if (old) for (const n of rootOf(old).children.filter(isPart)) if (status.get(n.name) === "rem") drawn.add(n.name);
  const pads = new Map();  // ref -> {xs, ys, bottom}
  for (const it of diff.items || []) {
    if (it.k !== "p" || !status.has(it.ref) || drawn.has(it.ref)) continue;
    const want = status.get(it.ref) === "rem" ? 2 : null;
    if (want !== null && it.s !== want) continue;
    if (want === null && it.s === 4) continue;  // old positions: not this one's place now
    const p = pads.get(it.ref) || { xs: [], ys: [], bottom: !(it.l || [0]).includes(0) };
    const r = Math.max(it.sw || 1, it.sh || 1) / 2;
    p.xs.push(it.x - r, it.x + r); p.ys.push(it.y - r, it.y + r); pads.set(it.ref, p);
  }
  for (const [ref, p] of pads) {
    const s = status.get(ref), pad = 0.4;
    const x0 = Math.min(...p.xs) - pad, x1 = Math.max(...p.xs) + pad, y0 = Math.min(...p.ys) - pad, y1 = Math.max(...p.ys) + pad;
    const w = 0.25, y = p.bottom ? bottom : top;
    const edge = (a, b) => ({ k: "t", d: `M${a[0]} ${a[1]}L${b[0]} ${b[1]}`, w });
    const outline = [edge([x0, y0], [x1, y0]), edge([x1, y0], [x1, y1]), edge([x1, y1], [x0, y1]), edge([x0, y1], [x0, y0])];
    const mat = new THREE.MeshBasicMaterial({ color: COLORS[s], transparent: true, opacity: 0.95, side: THREE.DoubleSide,
      depthWrite: false, polygonOffset: true, polygonOffsetFactor: -6, polygonOffsetUnits: -8 });
    const m = new THREE.Mesh(strips(outline, y), mat); model.add(m); groups.changes.push(m);
    if (s === "rem") counts.rem++;
  }
  window.kigit3dDiffOutlined = [...pads.keys()];
  // Copper: what changed, as strips on the top and bottom copper (inner layers on top, fainter).
  const layerNames = (diff.layers || []).map((l) => l.name);
  const kinds = { 1: "add", 2: "rem", 5: "chg", 3: "mov", 4: "old" }, tracks = {};
  for (const it of diff.items || []) {
    if ((it.k !== "t" && it.k !== "v") || !kinds[it.s]) continue;
    const layer = layerNames[(it.l || [0])[0]] || "F.Cu";
    const side = it.k === "v" ? "both" : layer === "B.Cu" ? "bottom" : "top";
    const key = kinds[it.s] + "|" + side + "|" + (layer !== "F.Cu" && layer !== "B.Cu" && it.k !== "v" ? "inner" : "");
    (tracks[key] = tracks[key] || []).push(it);
  }
  const copper = { add: 0, rem: 0, chg: 0 };
  for (const [key, list] of Object.entries(tracks)) {
    const [kind, side, inner] = key.split("|");
    if (kind in copper) copper[kind] += list.filter((i) => i.k === "t").length;
    const mat = new THREE.MeshBasicMaterial({ color: COLORS[kind], transparent: true, opacity: kind === "old" ? 0.35 : inner ? 0.5 : 0.9,
      side: THREE.DoubleSide, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -6, polygonOffsetUnits: -8 });
    for (const y of side === "both" ? [top, bottom] : [side === "bottom" ? bottom : top]) {
      const m = new THREE.Mesh(strips(list, y), mat); model.add(m); groups.changes.push(m); }
  }
  scene.add(model);
  // The legend: what changed, with its colour.
  const leg = document.getElementById("legend"), add = (c, t) => { if (!t) return; const s = document.createElement("span"); s.style.setProperty("--c", c); s.textContent = t; leg.append(s); };
  const n = (k, one, many) => counts[k] ? `${counts[k]} ${counts[k] === 1 ? one : many}` : "";
  add("var(--add)", n("add", "part added", "parts added")); add("var(--chg)", n("chg", "part changed", "parts changed"));
  add("var(--mov)", n("mov", "part moved", "parts moved")); add("var(--rem)", n("rem", "part removed", "parts removed"));
  const tr = [copper.add && `+${copper.add}`, copper.rem && `−${copper.rem}`, copper.chg && `~${copper.chg}`].filter(Boolean).join(" ");
  if (tr) add("var(--muted)", `tracks ${tr}`);
  if (!leg.childElementCount) add("var(--faint)", "No part or copper changes to show here (only the 2D view shows everything)");
  fadeOthers(true);
  box.setFromObject(model); size = box.getSize(new THREE.Vector3()).length();
  camera.near = size / 500; camera.far = size * 50; camera.updateProjectionMatrix();
  controls.minDistance = size / 50; controls.maxDistance = size * 10;
  const c = box.getCenter(new THREE.Vector3());
  sun.position.copy(c).add(new THREE.Vector3(size, size * 2, size)); under.position.copy(c).add(new THREE.Vector3(-size, -size * 2, -size));
  document.getElementById("loading").remove();
  view("iso");
  window.kigit3dDiff = { counts, copper, parts: partNodes.length, changed: changed.length, chip, tier };
})().catch((e) => { const l = document.getElementById("loading"); l.className = "err"; l.textContent = "Couldn't show the 3D diff: " + e; console.error(e); });
</script>
</body>
</html>
"""
