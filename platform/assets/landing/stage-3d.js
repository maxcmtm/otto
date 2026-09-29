/* Otto landing · hero stage, Tier A (desktop WebGL).
   The phone body is WebGL; the screen and the three fanned-out posts stay real DOM, placed in the same
   camera by CSS3DRenderer. Geometry is in millimetres and matches the CSS rig in landing.html exactly
   (same px-per-mm, same origin, same yaw and pitch), so the hand-over from Tier B is seamless.
   Renders on demand only: the body re-renders when parallax moves it; the DOM layer when a card moves. */
import * as THREE from 'three';
import { CSS3DRenderer, CSS3DObject } from 'three/addons/renderers/CSS3DRenderer.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const DEG = Math.PI / 180;
const U = 4;                                  /* DOM px per mm inside the CSS3D layer */
const PW = 72, PH = 150, PR = 11, PD = 7.6, BV = 1.3;

function rr(w, h, r) {
  const s = new THREE.Shape(), x = w / 2 - r, y = h / 2 - r;
  s.absarc(x, y, r, 0, Math.PI / 2, false);
  s.absarc(-x, y, r, Math.PI / 2, Math.PI, false);
  s.absarc(-x, -y, r, Math.PI, Math.PI * 1.5, false);
  s.absarc(x, -y, r, Math.PI * 1.5, Math.PI * 2, false);
  return s;
}
function cssColor(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return new THREE.Color(v || fallback);
}
function shadowTexture() {
  const c = document.createElement('canvas'); c.width = 256; c.height = 128;
  const g = c.getContext('2d'), rgb = getComputedStyle(document.documentElement).getPropertyValue('--floor').trim() || '16,24,43';
  g.setTransform(1, 0, 0, 0.5, 0, 0);
  const grd = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  grd.addColorStop(0, `rgba(${rgb},.40)`); grd.addColorStop(0.42, `rgba(${rgb},.15)`); grd.addColorStop(1, `rgba(${rgb},0)`);
  g.fillStyle = grd; g.fillRect(0, 0, 256, 256);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

export async function mount(H) {
  const stage = H.stage, force = /[?&]tier=a/.test(location.search);
  const canvas = document.createElement('canvas');
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance', failIfMajorPerformanceCaveat: !force });
  } catch (e) { return false; }
  if (!renderer.getContext()) return false;
  let dpr = Math.min(window.devicePixelRatio || 1, 1.75);
  renderer.setPixelRatio(dpr);
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = THREE.AgXToneMapping;
  renderer.toneMappingExposure = 1.05;

  const box = document.createElement('div'); box.className = 'stage-gl';
  canvas.setAttribute('aria-hidden', 'true');
  const cssEl = document.createElement('div'); cssEl.className = 'css3d'; cssEl.style.setProperty('--u', U + 'px');
  box.append(canvas, cssEl);
  stage.insertBefore(box, stage.querySelector('.stage-pause'));
  const css = new CSS3DRenderer({ element: cssEl });
  cssEl.style.overflow = 'visible';                                /* cards may leave the stage, as in Tier B */

  /* scene: one soft room, one key light from the top left, AgX */
  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.9;
  const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(-260, 320, 300); scene.add(key);
  const camera = new THREE.PerspectiveCamera(22, 1, 10, 6000);

  const world = new THREE.Group(); scene.add(world);
  const phoneG = new THREE.Group(); world.add(phoneG);
  phoneG.rotation.set(-H.PITCH * DEG, H.YAW * DEG, 0);            /* CSS rotateX(p) rotateY(y), y axis flipped */

  /* a generic phone: flat sides, soft edges, no notch, no camera plateau */
  const metal = new THREE.MeshPhysicalMaterial({ color: cssColor('--metal', '#DADDE2'), metalness: 1, roughness: 0.38, clearcoat: 0.35, clearcoatRoughness: 0.3 });
  const bodyGeo = new THREE.ExtrudeGeometry(rr(PW - 2 * BV, PH - 2 * BV, PR - BV), { depth: PD - 2 * BV, bevelEnabled: true, bevelThickness: BV, bevelSize: BV, bevelSegments: 8, curveSegments: 40 });
  bodyGeo.translate(0, 0, -(PD - 2 * BV) / 2);
  phoneG.add(new THREE.Mesh(bodyGeo, metal));
  const glassMat = new THREE.MeshPhysicalMaterial({ color: 0x0a0b0d, metalness: 0, roughness: 0.08, clearcoat: 1, clearcoatRoughness: 0.04 });
  const glass = new THREE.Mesh(new THREE.ShapeGeometry(rr(PW - 2 * BV + 0.2, PH - 2 * BV + 0.2, PR - BV - 0.2), 40), glassMat);
  glass.position.z = PD / 2 + 0.02; phoneG.add(glass);
  const btnGeo = new THREE.ExtrudeGeometry(rr(2.6, 17, 1.2), { depth: 0.9, bevelEnabled: true, bevelThickness: 0.3, bevelSize: 0.3, bevelSegments: 3, curveSegments: 10 });
  const btn = new THREE.Mesh(btnGeo, metal); btn.rotation.y = Math.PI / 2; btn.position.set(PW / 2 - 0.4, 30, 0.45); phoneG.add(btn);

  /* baked contact shadow on the floor, under the front edge of the tilted phone */
  const base = new THREE.Vector3(0, -PH / 2, 0).applyEuler(phoneG.rotation);
  let shadowTex = shadowTexture();
  const floorMat = new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false, toneMapped: false });
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(132, 66), floorMat);
  floor.rotation.x = -Math.PI / 2; floor.position.set(2, base.y - 0.3, base.z - 1); world.add(floor);

  /* the real DOM: screen on the glass, three cards on pivots at their media centre */
  const home = new Map();
  const remember = (el) => home.set(el, [el.parentNode, el.nextSibling]);
  remember(H.screen);
  const screenObj = new CSS3DObject(H.screen);
  screenObj.scale.setScalar(1 / U); screenObj.position.z = PD / 2 + 0.12; phoneG.add(screenObj);
  const piv = {}, obj = {}, extra = {};
  H.K.forEach((k) => {
    const el = H.cards[k]; remember(el);
    const o = new CSS3DObject(el); o.scale.setScalar(1 / U);
    const p = new THREE.Group(); p.add(o); world.add(p); piv[k] = p; obj[k] = o;
  });

  function layout() {
    const w = Math.max(1, Math.round(stage.clientWidth)), h = Math.max(1, Math.round(stage.clientHeight));
    renderer.setSize(w, h, false); css.setSize(w, h);
    const rig = stage.querySelector('.rig'), u = H.cssAdapter.unit();
    const ox = rig.offsetLeft, oy = rig.offsetTop;
    const D = ((h / 2) / Math.tan(11 * DEG)) / u;                  /* same px-per-mm as the CSS rig */
    camera.aspect = w / h; camera.position.set(0, 0, D);
    camera.setViewOffset(w, h, w / 2 - ox, h / 2 - oy, w, h);
    camera.updateProjectionMatrix();
  }
  function renderGL() { renderer.render(scene, camera); }
  function renderCSS() { css.render(scene, camera); }

  const cssAdapter = H.cssAdapter;
  const adapterA = {
    apply() {
      H.K.forEach((k) => {
        const s = H.S[k], el = H.cards[k];
        el.style.setProperty('--mw', s.mw.toFixed(3)); el.style.setProperty('--mh', s.mh.toFixed(3)); el.style.setProperty('--o', s.o.toFixed(3));
        piv[k].position.set(s.x, s.y, s.z);
        piv[k].rotation.set(-s.rx * DEG, s.ry * DEG, -s.rz * DEG);
        obj[k].position.y = -extra[k] / 2 / U;
      });
      renderCSS();
    },
    parallax(x, y) {
      world.rotation.set(-x * DEG, y * DEG, 0);
      renderGL(); renderCSS(); guard();
    },
    unit() { return U; }
  };

  /* runtime guard: slow frames drop DPR to 1, then hand back to Tier B */
  let last = 0, times = [], lowered = false;
  function guard() {
    const now = performance.now(), dt = now - last; last = now;
    if (dt > 100) return;
    times.push(dt); if (times.length < 60) return;
    const avg = times.reduce((a, b) => a + b, 0) / times.length; times = [];
    if (avg <= 22) return;
    if (!lowered) { lowered = true; dpr = 1; renderer.setPixelRatio(1); layout(); renderGL(); return; }
    fallback();
  }
  function fallback() {
    H.adapter = cssAdapter;
    [H.screen].concat(H.K.map((k) => H.cards[k])).forEach((el) => {
      const [parent, next] = home.get(el);
      parent.insertBefore(el, next);
      el.style.removeProperty('transform'); el.style.removeProperty('position'); el.style.removeProperty('pointer-events'); el.style.removeProperty('user-select');
    });
    stage.classList.remove('is-gl'); document.documentElement.setAttribute('data-tier', 'b');
    H.apply();
    setTimeout(() => { box.remove(); renderer.dispose(); pmrem.dispose(); }, 250);
  }

  /* swap in while the loop is quiet, so the phone does not change renderer mid-gesture */
  await new Promise((res) => { const t = () => (H.quiet() ? res() : setTimeout(t, 90)); t(); });
  layout();
  H.adapter = adapterA;
  H.K.forEach((k) => { const el = H.cards[k]; el.style.setProperty('--mh', H.S[k].mh); extra[k] = 0; });
  renderCSS();
  H.K.forEach((k) => { const el = H.cards[k]; extra[k] = el.offsetHeight - H.S[k].mh * U; });
  adapterA.parallax(H.par.x, H.par.y);
  H.apply();
  requestAnimationFrame(() => stage.classList.add('is-gl'));

  new ResizeObserver(() => { if (H.adapter !== adapterA) return; layout(); renderGL(); H.apply(); }).observe(stage);
  const dark = matchMedia('(prefers-color-scheme: dark)');
  dark.addEventListener('change', () => {
    if (H.adapter !== adapterA) return;
    metal.color.copy(cssColor('--metal', '#DADDE2'));
    shadowTex.dispose(); shadowTex = shadowTexture(); floorMat.map = shadowTex; floorMat.needsUpdate = true;
    renderGL();
  });
  return true;
}
