// Dollhouse（docs/10 第 4 节；10-27）：从户型图"立起来"的近似三维视图。几何来自 data/real/photos/<id>/plan3d.json（src/photo/plan3d.py：
// 阈值 + 连通域分房间），语义来自看图模型（房间名、照片归房间），光来自 home.sun 的太阳轨迹（src/sun/solar.py）+ 指北针方向。
// three.js r160（MIT，vendor/three/）；相机像 Domain 的 3D Flyover 一样自动环绕，拖动就暂停、5 秒没动再续；点房间飞过去并列出这间的照片。
// 契约：window.HT_DOLLHOUSE = { available(home) → Promise<boolean>, mount(container, home) → Promise<handle> }，
//       handle = { destroy(), focusRoom(id), setSun(season, hour), pause(), play(), resetView(), plan, el }；模块加载完 document 上发 ht-dollhouse-ready。
// 诚实标注：画布角标 "Approximate: built from the floor plan, not a scan. Room sizes indicative."
import * as THREE from './vendor/three/three.module.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';

const NOTE = 'Approximate: built from the floor plan, not a scan. Room sizes indicative.';
const NORTH_UNKNOWN = 'North unknown: ask the agent for the north arrow';
const COLORS = { living: 0x6f9fe0, dining: 0x8db4e8, kitchen: 0xe8bd5c, bedroom: 0xe59ab3, bathroom: 0x7fcfc4, ensuite: 0x7fcfc4, laundry: 0xb5d08a,
  hall: 0xc9ced6, balcony: 0x9bd394, courtyard: 0x9bd394, storage: 0xd9cbb4, garage: 0xc5c5d8, outside: 0xdddddd, unknown: 0xcccccc };
const WALL_COLOR = 0xe6ecf0;
const RESUME_MS = 5000;
const SEASONS = [['winter', '21 June'], ['summer', '21 Dec']];
const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
const cache = new Map();

function domainIdOf(home) {
  const m = /^\/real\/(\d+)\//.exec((home && home.floorplan && home.floorplan.url) || '');
  return m ? m[1] : null;
}

function loadPlan(id) {
  if (!cache.has(id)) {
    cache.set(id, fetch(`/real/${id}/plan3d.json`, { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null));
  }
  return cache.get(id);
}

async function available(home) {
  const id = domainIdOf(home);
  if (!id) return false;
  const plan = await loadPlan(id);
  return !!(plan && Array.isArray(plan.rooms) && plan.rooms.length);
}

async function mount(container, home) {
  const id = domainIdOf(home);
  const plan = id ? await loadPlan(id) : null;
  if (!plan || !plan.rooms || !plan.rooms.length) throw new Error('no dollhouse for this home');
  const house = new Dollhouse(container, home, plan);
  await house.ready;
  return house.handle();
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function baseType(type) {
  return /^bedroom/.test(type || '') ? 'bedroom' : (type || 'unknown');
}

function hourLabel(h) {
  const hh = Math.floor(h), mm = Math.round((h - hh) * 60);
  const ap = hh < 12 ? 'am' : 'pm';
  const h12 = ((hh + 11) % 12) + 1;
  return `${h12}:${mm < 10 ? '0' : ''}${mm} ${ap}`;
}

function hhmm(t) {
  const [h, m] = String(t).split(':').map(Number);
  return h + (m || 0) / 60;
}

function lerpDeg(a, b, f) {
  const d = ((b - a + 540) % 360) - 180;
  return (a + d * f + 360) % 360;
}

// 太阳轨迹（每 20 分钟一点，只有地平线以上）→ 任意小时的 {elev, az}；轨迹外 = 太阳在地平线下
function sunAt(track, hour) {
  if (!track || !track.length) return null;
  const pts = track.map((p) => ({ h: hhmm(p.t), elev: +p.elev, az: +p.az }));
  if (hour < pts[0].h - 0.34 || hour > pts[pts.length - 1].h + 0.34) return null;
  if (hour <= pts[0].h) return { elev: pts[0].elev, az: pts[0].az };
  for (let i = 1; i < pts.length; i++) {
    if (hour <= pts[i].h) {
      const f = (hour - pts[i - 1].h) / (pts[i].h - pts[i - 1].h || 1);
      return { elev: pts[i - 1].elev + (pts[i].elev - pts[i - 1].elev) * f, az: lerpDeg(pts[i - 1].az, pts[i].az, f) };
    }
  }
  const last = pts[pts.length - 1];
  return { elev: last.elev, az: last.az };
}

function textSprite(text, opts = {}) {
  const scale = 2, pad = 10 * scale, fontPx = (opts.fontPx || 26) * scale;
  const c = document.createElement('canvas');
  const ctx = c.getContext('2d');
  ctx.font = `${opts.bold === false ? '' : 'bold '}${fontPx}px "F37 Bolton", Helvetica, Arial, sans-serif`;
  const w = Math.ceil(ctx.measureText(text).width) + pad * 2, h = fontPx + pad * 1.6;
  c.width = w; c.height = h;
  ctx.font = `${opts.bold === false ? '' : 'bold '}${fontPx}px "F37 Bolton", Helvetica, Arial, sans-serif`;
  ctx.fillStyle = opts.bg || 'rgba(30,41,61,.86)';
  const r = h / 2;
  ctx.beginPath();
  ctx.moveTo(r, 0); ctx.lineTo(w - r, 0); ctx.arc(w - r, r, r, -Math.PI / 2, Math.PI / 2); ctx.lineTo(r, h); ctx.arc(r, r, r, Math.PI / 2, Math.PI * 1.5);
  ctx.closePath(); ctx.fill();
  ctx.fillStyle = opts.color || '#fff';
  ctx.textBaseline = 'middle'; ctx.textAlign = 'center';
  ctx.fillText(text, w / 2, h / 2 + fontPx * 0.04);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.minFilter = THREE.LinearFilter;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false, sizeAttenuation: false }));
  sp.userData.ratio = w / h; // 屏幕上固定大小（sizeAttenuation 关掉后 scale 是 NDC 单位），resize() 按画布长宽比重算
  sp.userData.k = opts.k || 0.036;
  sp.scale.set(sp.userData.k * sp.userData.ratio, sp.userData.k, 1);
  sp.renderOrder = 20;
  return sp;
}

function compassTexture(northDeg) {
  const s = 256, c = document.createElement('canvas');
  c.width = c.height = s;
  const ctx = c.getContext('2d');
  ctx.translate(s / 2, s / 2);
  ctx.rotate((northDeg * Math.PI) / 180); // 页面上顺时针
  ctx.strokeStyle = '#1e293d'; ctx.lineWidth = 6;
  ctx.beginPath(); ctx.arc(0, 0, 92, 0, Math.PI * 2); ctx.stroke();
  ctx.fillStyle = '#1e293d';
  ctx.beginPath(); ctx.moveTo(0, -84); ctx.lineTo(22, 20); ctx.lineTo(0, 6); ctx.lineTo(-22, 20); ctx.closePath(); ctx.fill();
  ctx.font = 'bold 54px "F37 Bolton", Helvetica, Arial, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText('N', 0, 56);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

class Dollhouse {
  constructor(container, home, plan) {
    this.container = container;
    this.home = home;
    this.plan = plan;
    this.m = plan.m_per_px || 0.01;
    this.W = plan.width * this.m;
    this.H = plan.height * this.m;
    this.wallH = plan.wall_height_m || 2.6;
    this.northDeg = typeof plan.north_deg === 'number' ? plan.north_deg : null;
    this.tracks = (home && home.sun && home.sun.tracks) || null;
    this.sunOn = this.northDeg != null && !!(this.tracks && this.tracks.winter && this.tracks.winter.length);
    this.season = 'winter';
    this.hour = 10;
    this.paused = reduced;
    this.resumeAt = 0;
    this.selected = null;
    this.tween = null;
    this.rooms = new Map();
    this.labels = [];
    this.disposed = false;
    this.buildDom();
    this.buildScene();
    this.ready = this.loadTextures().then(() => { this.placePhotos(); this.updateSun(); this.resize(); this.loop(); });
  }

  // ---------------------------------------------------------------- DOM
  buildDom() {
    const root = el('div', 'ht-dollhouse');
    this.root = root;
    const stage = el('div', 'ht-dollhouse-stage');
    this.stage = stage;
    this.canvas = document.createElement('canvas');
    this.canvas.className = 'ht-dollhouse-canvas';
    this.canvas.setAttribute('aria-label', 'Approximate 3D view built from the floor plan');
    stage.appendChild(this.canvas);
    stage.appendChild(el('div', 'ht-dollhouse-badge', NOTE));
    const ctl = el('div', 'ht-dollhouse-controls');
    this.btnPlay = el('button', 'ht-dollhouse-btn', this.paused ? 'Play' : 'Pause');
    this.btnPlay.type = 'button'; this.btnPlay.setAttribute('aria-label', 'Pause or play the orbit');
    this.btnPlay.addEventListener('click', () => (this.paused ? this.play() : this.pause()));
    const bIn = el('button', 'ht-dollhouse-btn', '+'); bIn.type = 'button'; bIn.setAttribute('aria-label', 'Zoom in');
    bIn.addEventListener('click', () => this.zoom(0.8));
    const bOut = el('button', 'ht-dollhouse-btn', '−'); bOut.type = 'button'; bOut.setAttribute('aria-label', 'Zoom out');
    bOut.addEventListener('click', () => this.zoom(1.25));
    const bReset = el('button', 'ht-dollhouse-btn', 'Reset'); bReset.type = 'button';
    bReset.addEventListener('click', () => this.resetView());
    ctl.append(this.btnPlay, bIn, bOut, bReset);
    stage.appendChild(ctl);
    this.hint = el('div', 'ht-dollhouse-hint', 'Drag to look around · click a room for its photos');
    stage.appendChild(this.hint);
    root.appendChild(stage);

    const sun = el('div', 'ht-dollhouse-sun');
    if (this.sunOn) {
      const seasons = el('div', 'ht-dollhouse-seasons');
      this.seasonBtns = {};
      for (const [key, label] of SEASONS) {
        const b = el('button', 'ht-dollhouse-chip' + (key === this.season ? ' is-on' : ''), label);
        b.type = 'button'; b.setAttribute('aria-pressed', key === this.season ? 'true' : 'false');
        b.addEventListener('click', () => this.setSun(key, this.hour));
        this.seasonBtns[key] = b;
        seasons.appendChild(b);
      }
      sun.appendChild(seasons);
      const slider = document.createElement('input');
      slider.type = 'range'; slider.min = '6'; slider.max = '18'; slider.step = '0.25'; slider.value = String(this.hour);
      slider.className = 'ht-dollhouse-slider'; slider.setAttribute('aria-label', 'Hour of the day');
      slider.addEventListener('input', () => this.setSun(this.season, parseFloat(slider.value)));
      this.slider = slider;
      sun.appendChild(slider);
      this.sunLabel = el('span', 'ht-dollhouse-sunlabel', '');
      sun.appendChild(this.sunLabel);
    } else {
      sun.appendChild(el('span', 'ht-dollhouse-sunlabel is-muted', NORTH_UNKNOWN));
    }
    root.appendChild(sun);

    this.photosBox = el('div', 'ht-dollhouse-photos');
    root.appendChild(this.photosBox);
    const models = (this.plan.photo_models && this.plan.photo_models.length ? this.plan.photo_models : [this.plan.model]).join(', ');
    root.appendChild(el('div', 'ht-dollhouse-foot', `Rooms named by ${this.plan.model || 'the vision model'} · photos matched by ${models || 'the vision model'}`));
    this.zoomBox = el('div', 'ht-dollhouse-zoom');
    this.zoomBox.addEventListener('click', () => this.zoomBox.classList.remove('is-open'));
    stage.appendChild(this.zoomBox);
    this.container.appendChild(root);
    this.renderPhotoStrip(null);
  }

  // ---------------------------------------------------------------- scene
  toWorld(px, py) {
    return new THREE.Vector3((px - this.plan.width / 2) * this.m, 0, (py - this.plan.height / 2) * this.m);
  }

  buildScene() {
    const renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: false, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0xf6f7f8, 1);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer = renderer;
    const scene = new THREE.Scene();
    this.scene = scene;
    const span = Math.max(this.W, this.H);
    this.span = span;
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, span * 20);
    this.camera = camera;
    const controls = new OrbitControls(camera, this.canvas);
    controls.enableDamping = true; controls.dampingFactor = 0.08;
    controls.autoRotate = !this.paused; controls.autoRotateSpeed = 0.7;
    controls.maxPolarAngle = Math.PI * 0.46; controls.minDistance = 1.5; controls.maxDistance = span * 4;
    controls.enablePan = true; controls.screenSpacePanning = false;
    controls.addEventListener('start', () => { this.userHold = true; this.tween = null; controls.autoRotate = false; });
    controls.addEventListener('end', () => { this.userHold = false; this.resumeAt = performance.now() + RESUME_MS; });
    this.controls = controls;
    this.home0 = this.defaultCamera();
    this.resetView(true);

    scene.add(new THREE.AmbientLight(0xffffff, 1.35));
    const hemi = new THREE.HemisphereLight(0xffffff, 0xb8c0c8, 0.7);
    scene.add(hemi);
    const sun = new THREE.DirectionalLight(0xfff4e0, 1.5);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    const r = span * 0.75;
    sun.shadow.camera.left = -r; sun.shadow.camera.right = r; sun.shadow.camera.top = r; sun.shadow.camera.bottom = -r;
    sun.shadow.camera.near = 0.5; sun.shadow.camera.far = span * 6;
    sun.shadow.bias = -0.0008; sun.shadow.normalBias = 0.02;
    sun.target.position.set(0, 0, 0);
    scene.add(sun); scene.add(sun.target);
    this.sun = sun;

    // 地板：户型图贴图的平面（贴图加载后换上）
    const floorGeo = new THREE.PlaneGeometry(this.W, this.H);
    floorGeo.rotateX(-Math.PI / 2);
    this.floorMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.95, metalness: 0 });
    const floor = new THREE.Mesh(floorGeo, this.floorMat);
    floor.receiveShadow = true;
    scene.add(floor);
    // 台面：比地板大一圈的浅灰底，接住墙外的影子
    const mat = new THREE.Mesh(new THREE.PlaneGeometry(this.W + span * 0.6, this.H + span * 0.6).rotateX(-Math.PI / 2),
      new THREE.MeshStandardMaterial({ color: 0xeef0f2, roughness: 1 }));
    mat.position.y = -0.01; mat.receiveShadow = true;
    scene.add(mat);

    this.roomGroup = new THREE.Group();
    scene.add(this.roomGroup);
    this.pickables = [];
    for (const room of this.plan.rooms) {
      const wallMat = new THREE.MeshStandardMaterial({ color: WALL_COLOR, transparent: true, opacity: 0.42, roughness: 0.6, side: THREE.DoubleSide });
      const entry = { room, meshes: [], colorMat: null, wallMat };
      this.rooms.set(room.id, entry);
      const poly = (room.polygon || []).map(([x, y]) => this.toWorld(x, y));
      if (poly.length < 3) continue;
      if (room.inside) {
        for (let i = 0; i < poly.length; i++) {
          const a = poly[i], b = poly[(i + 1) % poly.length];
          const dx = b.x - a.x, dz = b.z - a.z, len = Math.hypot(dx, dz);
          if (len < 0.05) continue;
          const wall = new THREE.Mesh(new THREE.BoxGeometry(len, this.wallH, 0.06), wallMat);
          wall.position.set((a.x + b.x) / 2, this.wallH / 2, (a.z + b.z) / 2);
          wall.rotation.y = -Math.atan2(dz, dx);
          wall.castShadow = true; wall.receiveShadow = true;
          this.roomGroup.add(wall);
          entry.meshes.push(wall);
        }
      }
      // 房间地面（点选 + 高亮）：多边形在 XY 平面画，再翻平（y → -z）
      const shape = new THREE.Shape(poly.map((p) => new THREE.Vector2(p.x, -p.z)));
      const geo = new THREE.ShapeGeometry(shape);
      geo.rotateX(-Math.PI / 2);
      const color = COLORS[baseType(room.type)] || COLORS.unknown;
      const cm = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: room.inside ? 0.16 : 0.08, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1 });
      const pad = new THREE.Mesh(geo, cm);
      pad.position.y = 0.012;
      pad.userData.roomId = room.id;
      this.roomGroup.add(pad);
      this.pickables.push(pad);
      entry.colorMat = cm;
      entry.pad = pad;
      if (room.type === 'outside') continue; // 墙外的块不挂牌
      // 标签：房间名 + 置信度低 / 认不出带 "?"
      const unsure = room.confidence === 'low' || room.type === 'unknown';
      const label = textSprite((room.label || 'Room') + (unsure ? ' ?' : ''), { k: room.inside ? 0.036 : 0.03, bg: room.inside ? 'rgba(30,41,61,.86)' : 'rgba(126,133,148,.8)' });
      this.labels.push(label);
      const anchor = this.toWorld(room.anchor ? room.anchor[0] : room.centroid[0], room.anchor ? room.anchor[1] : room.centroid[1]);
      label.position.set(anchor.x, (room.inside ? this.wallH + 0.45 : 0.6), anchor.z);
      this.roomGroup.add(label);
      entry.anchor = anchor;
      entry.label = label;
    }
    // 指北针：地板左下角，按 north_deg 转
    if (this.northDeg != null) {
      const size = Math.max(0.9, span * 0.08);
      const comp = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshBasicMaterial({ map: compassTexture(this.northDeg), transparent: true, depthWrite: false }));
      comp.rotation.x = -Math.PI / 2;
      comp.position.set(-this.W / 2 + size * 0.7, 0.02, this.H / 2 - size * 0.7);
      scene.add(comp);
    }
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.onDown = (e) => { this.downAt = [e.clientX, e.clientY, performance.now()]; };
    this.onUp = (e) => {
      if (!this.downAt) return;
      const [x, y, t] = this.downAt; this.downAt = null;
      if (Math.hypot(e.clientX - x, e.clientY - y) > 6 || performance.now() - t > 500) return;
      const id = this.pick(e.clientX, e.clientY);
      if (id != null) this.focusRoom(id);
    };
    this.onMove = (e) => {
      const id = this.pick(e.clientX, e.clientY);
      this.canvas.style.cursor = id != null ? 'pointer' : '';
    };
    this.canvas.addEventListener('pointerdown', this.onDown);
    this.canvas.addEventListener('pointerup', this.onUp);
    this.canvas.addEventListener('pointermove', this.onMove);
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(this.stage);
  }

  defaultCamera() {
    const dist = this.span * 0.95 + 1.5;
    const el35 = Math.PI * 35 / 180, az = 0.55;
    return { pos: new THREE.Vector3(Math.sin(az) * Math.cos(el35) * dist, Math.sin(el35) * dist, Math.cos(az) * Math.cos(el35) * dist), target: new THREE.Vector3(0, 0, 0) };
  }

  async loadTextures() {
    const loader = new THREE.TextureLoader();
    const load = (url) => new Promise((res) => loader.load(url, (t) => { t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; res(t); }, undefined, () => res(null)));
    const planTex = await load(this.plan.plan_image);
    if (planTex && !this.disposed) { this.floorMat.map = planTex; this.floorMat.needsUpdate = true; }
    this.photoTex = new Map();
    await Promise.all((this.plan.photos || []).map(async (p) => { const t = await load(p.url); if (t) this.photoTex.set(p.url, t); }));
  }

  placePhotos() {
    if (this.disposed) return;
    const byRoom = new Map();
    const loose = [];
    for (const p of this.plan.photos || []) {
      if (p.room_id != null && this.rooms.has(p.room_id)) {
        if (!byRoom.has(p.room_id)) byRoom.set(p.room_id, []);
        byRoom.get(p.room_id).push(p);
      } else loose.push(p);
    }
    this.photosByRoom = byRoom;
    this.loosePhotos = loose;
    const boardH = Math.max(0.9, Math.min(1.4, this.span * 0.09));
    const board = (p, pos) => {
      const tex = this.photoTex.get(p.url);
      if (!tex) return null;
      const img = tex.image, ratio = img && img.width ? img.width / img.height : 1.5;
      const w = boardH * ratio;
      const frame = new THREE.Sprite(new THREE.SpriteMaterial({ color: 0xffffff, transparent: true, opacity: 0.95 }));
      frame.scale.set(w + 0.08, boardH + 0.08, 1); frame.position.copy(pos); frame.renderOrder = 10;
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex }));
      sp.scale.set(w, boardH, 1); sp.position.copy(pos); sp.position.y += 0.001; sp.renderOrder = 11;
      this.roomGroup.add(frame); this.roomGroup.add(sp);
      return sp;
    };
    for (const [rid, list] of byRoom) {
      const entry = this.rooms.get(rid);
      list.forEach((p, i) => {
        const pos = entry.anchor.clone();
        pos.x += i * 0.45 - (list.length - 1) * 0.2; pos.z += i * 0.3; pos.y = 1.2 + i * 0.12;
        board(p, pos);
      });
    }
    // 没归到房间的照片：模型旁边一排
    const x = this.W / 2 + Math.max(1.2, this.span * 0.12);
    loose.forEach((p, i) => {
      const pos = new THREE.Vector3(x, 1.2, -this.H / 2 + boardH * 1.6 * (i + 0.6));
      board(p, pos);
    });
    if (loose.length) {
      const lab = textSprite(`Not placed (${loose.length})`, { k: 0.03, bg: 'rgba(126,133,148,.85)' });
      lab.position.set(x, 2.3, -this.H / 2 + boardH * 0.3);
      this.roomGroup.add(lab);
      this.labels.push(lab);
      this.resize();
    }
  }

  // ---------------------------------------------------------------- sun
  setSun(season, hour) {
    if (!this.sunOn) return;
    this.season = SEASONS.some(([k]) => k === season) ? season : 'winter';
    this.hour = Math.min(18, Math.max(6, +hour || 10));
    if (this.slider) this.slider.value = String(this.hour);
    for (const [k, b] of Object.entries(this.seasonBtns || {})) { b.classList.toggle('is-on', k === this.season); b.setAttribute('aria-pressed', k === this.season ? 'true' : 'false'); }
    this.updateSun();
  }

  updateSun() {
    const sun = this.sun;
    if (!this.sunOn) { // 朝向未知：固定一盏从左上来的灯，只为看出高低
      sun.position.set(-this.span, this.span * 1.2, this.span * 0.6);
      sun.intensity = 1.1;
      return;
    }
    const s = sunAt(this.tracks[this.season], this.hour);
    if (!s) {
      sun.intensity = 0;
      if (this.sunLabel) this.sunLabel.textContent = `${hourLabel(this.hour)} · sun below the horizon`;
      return;
    }
    const theta = ((this.northDeg + s.az) * Math.PI) / 180; // 页面上顺时针，从"上"量
    const e = (s.elev * Math.PI) / 180;
    const d = this.span * 3;
    sun.position.set(Math.sin(theta) * Math.cos(e) * d, Math.sin(e) * d, -Math.cos(theta) * Math.cos(e) * d);
    sun.intensity = 0.8 + 1.1 * Math.min(1, Math.sin(e) * 1.6);
    if (this.sunLabel) this.sunLabel.textContent = `${hourLabel(this.hour)} · sun ${Math.round(s.elev)}° up, bearing ${Math.round(s.az)}°`;
  }

  // ---------------------------------------------------------------- camera
  pause() { this.paused = true; this.controls.autoRotate = false; this.btnPlay.textContent = 'Play'; }
  play() { this.paused = false; this.resumeAt = 0; this.controls.autoRotate = !reduced; this.btnPlay.textContent = 'Pause'; }

  zoom(f) {
    const c = this.controls, cam = this.camera;
    const v = cam.position.clone().sub(c.target).multiplyScalar(f);
    const len = Math.min(c.maxDistance, Math.max(c.minDistance, v.length()));
    cam.position.copy(c.target).add(v.setLength(len));
    c.update();
  }

  resetView(instant) {
    this.selectRoom(null);
    this.flyTo(this.home0.pos, this.home0.target, instant || reduced);
    if (!this.paused) this.play();
  }

  flyTo(pos, target, instant) {
    const c = this.controls, cam = this.camera;
    if (instant) { cam.position.copy(pos); c.target.copy(target); c.update(); this.tween = null; return; }
    this.tween = { p0: cam.position.clone(), t0: c.target.clone(), p1: pos.clone(), t1: target.clone(), start: performance.now(), ms: 900 };
  }

  focusRoom(id) {
    const entry = this.rooms.get(id);
    if (!entry) return;
    this.selectRoom(id);
    const room = entry.room;
    const size = Math.max(room.bbox[2], room.bbox[3]) * this.m;
    const dist = Math.min(this.span * 2, Math.max(7.5, size * 2.8));
    const target = entry.anchor.clone(); target.y = 0.4;
    const dir = this.camera.position.clone().sub(this.controls.target); dir.y = 0;
    if (dir.length() < 0.01) dir.set(0.5, 0, 1);
    dir.normalize();
    const el35 = Math.PI * 60 / 180;
    const pos = target.clone().add(new THREE.Vector3(dir.x * Math.cos(el35) * dist, Math.sin(el35) * dist, dir.z * Math.cos(el35) * dist));
    this.controls.autoRotate = false;
    this.resumeAt = performance.now() + RESUME_MS * 2;
    this.flyTo(pos, target, reduced);
  }

  selectRoom(id) {
    for (const [rid, e] of this.rooms) {
      if (e.wallMat) e.wallMat.opacity = id == null ? 0.42 : (rid === id ? 0.55 : 0.1); // 选中一间时别的墙退淡，看得进去
      if (!e.colorMat) continue;
      e.colorMat.opacity = rid === id ? 0.42 : (e.room.inside ? 0.16 : 0.08);
    }
    this.selected = id;
    this.renderPhotoStrip(id);
  }

  renderPhotoStrip(id) {
    const box = this.photosBox;
    box.replaceChildren();
    const entry = id != null ? this.rooms.get(id) : null;
    const head = el('div', 'ht-dollhouse-photos-head');
    if (!entry) {
      const n = (this.plan.photos || []).filter((p) => p.room_id != null).length;
      head.append(el('strong', null, 'Photos by room'), el('span', 'is-muted', ` · ${n} of ${(this.plan.photos || []).length} photos placed on the plan · click a room`));
      box.appendChild(head);
      return;
    }
    const list = (this.photosByRoom && this.photosByRoom.get(id)) || [];
    const r = entry.room;
    head.append(el('strong', null, r.label || 'Room'), el('span', 'is-muted', ` · ${r.confidence} confidence` + (r.dims_text ? ` · ${r.dims_text}` : '') + (r.label_text ? ` · printed "${r.label_text}"` : '')));
    box.appendChild(head);
    if (!list.length) { box.appendChild(el('div', 'is-muted', 'No listing photo was matched to this room.')); return; }
    const strip = el('div', 'ht-dollhouse-strip');
    for (const p of list) {
      const fig = el('figure', 'ht-dollhouse-thumb');
      const img = document.createElement('img');
      img.src = p.url; img.alt = p.caption || 'Listing photo'; img.loading = 'lazy';
      img.addEventListener('click', () => this.showZoom(p));
      fig.appendChild(img);
      fig.appendChild(el('figcaption', null, (p.caption || p.room) + (p.source === 'model' ? ' · matched by the vision model' : '') + (p.confidence === 'low' ? ' · low confidence' : '')));
      strip.appendChild(fig);
    }
    box.appendChild(strip);
  }

  showZoom(p) {
    this.zoomBox.replaceChildren();
    const img = document.createElement('img');
    img.src = p.url; img.alt = p.caption || 'Listing photo';
    this.zoomBox.appendChild(img);
    this.zoomBox.appendChild(el('div', 'ht-dollhouse-zoom-cap', p.caption || p.room));
    this.zoomBox.classList.add('is-open');
  }

  pick(cx, cy) {
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    this.pointer.set(((cx - rect.left) / rect.width) * 2 - 1, -((cy - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this.pickables, false);
    return hits.length ? hits[0].object.userData.roomId : null;
  }

  // ---------------------------------------------------------------- loop
  resize() {
    if (this.disposed) return;
    const w = this.stage.clientWidth || 640, h = this.stage.clientHeight || 400;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    for (const sp of this.labels) sp.scale.set(sp.userData.k * sp.userData.ratio * (h / w), sp.userData.k, 1);
  }

  loop() {
    if (this.disposed) return;
    this.raf = requestAnimationFrame(() => this.loop());
    const now = performance.now();
    if (this.tween) {
      const t = Math.min(1, (now - this.tween.start) / this.tween.ms);
      const k = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      this.camera.position.lerpVectors(this.tween.p0, this.tween.p1, k);
      this.controls.target.lerpVectors(this.tween.t0, this.tween.t1, k);
      if (t >= 1) this.tween = null;
    }
    if (!this.paused && !reduced && !this.userHold && !this.controls.autoRotate && this.resumeAt && now >= this.resumeAt && !this.tween) {
      this.controls.autoRotate = true;
      this.resumeAt = 0;
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.frames = (this.frames || 0) + 1;
  }

  handle() {
    return {
      el: this.root,
      plan: this.plan,
      destroy: () => this.destroy(),
      focusRoom: (id) => this.focusRoom(id),
      setSun: (season, hour) => this.setSun(season, hour),
      pause: () => this.pause(),
      play: () => this.play(),
      resetView: () => this.resetView(),
      frames: () => this.frames || 0,
      _self: this, // 调试 / 截图脚本用，不是契约
    };
  }

  destroy() {
    if (this.disposed) return;
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.canvas.removeEventListener('pointerdown', this.onDown);
    this.canvas.removeEventListener('pointerup', this.onUp);
    this.canvas.removeEventListener('pointermove', this.onMove);
    this.controls.dispose();
    this.scene.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      const mats = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
      for (const m of mats) { if (m.map) m.map.dispose(); m.dispose(); }
    });
    this.renderer.dispose();
    this.root.remove();
  }
}

window.HT_DOLLHOUSE = { available, mount };
document.dispatchEvent(new CustomEvent('ht-dollhouse-ready'));
export { available, mount };
