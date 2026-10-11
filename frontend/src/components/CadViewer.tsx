import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { toCreasedNormals } from 'three/addons/utils/BufferGeometryUtils.js';
import type { ComponentResult } from '../api';

interface Props {
  documentId?: string;
  parts: ComponentResult[];
  selectedId: string | null;
  hiddenIds: string[];
  busy: boolean;
  onSelect: (id: string | null) => void;
}
type View = 'iso' | 'top' | 'front';
type SavedCamera = { documentId?: string; position: THREE.Vector3; target: THREE.Vector3; up: THREE.Vector3 };

export default function CadViewer({ documentId, parts, selectedId, hiddenIds, busy, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const changeView = useRef<(view: View, selection?: boolean) => void>(() => {});
  const highlight = useRef<(id: string | null, hidden: string[]) => void>(() => {});
  const select = useRef(onSelect);
  const blocked = useRef(busy);
  const savedCamera = useRef<SavedCamera | undefined>(undefined);
  const latestSelection = useRef({ selectedId, hiddenIds });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<View>('iso');
  select.current = onSelect;
  blocked.current = busy;
  latestSelection.current = { selectedId, hiddenIds };

  useEffect(() => {
    const host = container.current;
    setError('');
    setLoading(Boolean(host && parts.length));
    if (!host || !parts.length) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      setError('3D preview is unavailable. You can still save the project and export CAD.');
      setLoading(false);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.domElement.setAttribute('aria-label', 'Interactive assembly. Click a part to select it. Drag to orbit and scroll to zoom.');
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#151821');
    const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 100000);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    scene.add(new THREE.HemisphereLight('#eff0ff', '#424560', 2.4));
    const light = new THREE.DirectionalLight('#ffffff', 3.1);
    light.position.set(60, -90, 150);
    scene.add(light);
    const meshes: THREE.Mesh<THREE.BufferGeometry, THREE.MeshStandardMaterial>[] = [];
    const geometries: THREE.BufferGeometry[] = [];
    const materials: THREE.MeshStandardMaterial[] = [];
    const bounds = new THREE.Box3();
    let grid: THREE.GridHelper | undefined;
    let selectedMesh: THREE.Mesh | undefined;
    let outline: THREE.BoxHelper | undefined;
    let disposed = false;
    let frame = 0;
    const abort = new AbortController();
    const resizeRenderer = () => {
      const width = host.clientWidth, height = host.clientHeight;
      if (!width || !height) return;
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const resize = new ResizeObserver(resizeRenderer);
    resize.observe(host);
    resizeRenderer();

    const raycaster = new THREE.Raycaster();
    let down: { x: number; y: number } | undefined;
    const pointerDown = (event: PointerEvent) => { if (event.button === 0) down = { x: event.clientX, y: event.clientY }; };
    const pointerUp = (event: PointerEvent) => {
      const start = down;
      down = undefined;
      if (!start || blocked.current || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return;
      const rect = renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
      raycaster.setFromCamera(mouse, camera);
      const hit = raycaster.intersectObjects(meshes.filter(mesh => mesh.visible), false)[0];
      select.current(hit ? hit.object.userData.componentId as string : null);
    };
    renderer.domElement.addEventListener('pointerdown', pointerDown);
    renderer.domElement.addEventListener('pointerup', pointerUp);

    highlight.current = (id, hidden) => {
      selectedMesh = meshes.find(mesh => mesh.userData.componentId === id);
      meshes.forEach(mesh => {
        mesh.visible = !hidden.includes(mesh.userData.componentId as string);
        const selected = mesh === selectedMesh;
        mesh.material.emissive.set(selected ? '#452354' : '#000000');
        mesh.material.emissiveIntensity = selected ? 0.55 : 0;
        mesh.material.metalness = selected ? 0.15 : 0.28;
      });
      if (outline) {
        scene.remove(outline);
        outline.geometry.dispose();
        (outline.material as THREE.Material).dispose();
        outline = undefined;
      }
      if (selectedMesh?.visible) {
        outline = new THREE.BoxHelper(selectedMesh, '#d9b2f2');
        scene.add(outline);
      }
    };

    Promise.all(parts.map(async part => {
      const response = await fetch(part.preview_url, { signal: abort.signal });
      if (!response.ok) throw new Error(`The preview for ${part.name} could not be loaded.`);
      const buffer = await response.arrayBuffer();
      if (disposed) return;
      const geometry = toCreasedNormals(new STLLoader().parse(buffer), Math.PI / 6);
      geometry.computeBoundingBox();
      geometries.push(geometry);
      // Vertices already contain each part's assembly placement. Keep their common coordinates.
      const material = new THREE.MeshStandardMaterial({ color: part.color, metalness: 0.28, roughness: 0.43 });
      materials.push(material);
      const mesh = new THREE.Mesh(geometry, material);
      mesh.userData.componentId = part.id;
      mesh.name = part.name;
      meshes.push(mesh);
      scene.add(mesh);
      bounds.union(geometry.boundingBox!);
    }))
      .then(() => {
        if (disposed) return;
        const span = Math.max(...bounds.getSize(new THREE.Vector3()).toArray(), 1);
        const centre = bounds.getCenter(new THREE.Vector3());
        grid = new THREE.GridHelper(span * 2, 20, '#45445c', '#2b3042');
        grid.rotation.x = Math.PI / 2;
        grid.position.set(centre.x, centre.y, bounds.min.z - span * 0.003);
        scene.add(grid);
        controls.minDistance = span * 0.05;
        controls.maxDistance = span * 20;
        camera.near = Math.max(span / 10000, 0.001);
        camera.far = Math.max(span * 100, 1000);
        changeView.current = (requested, selection = false) => {
          const box = selection && selectedMesh ? new THREE.Box3().setFromObject(selectedMesh) : bounds;
          const target = box.getCenter(new THREE.Vector3());
          const sizes = box.getSize(new THREE.Vector3());
          const verticalHalfAngle = THREE.MathUtils.degToRad(camera.fov / 2);
          const horizontalHalfAngle = Math.atan(Math.tan(verticalHalfAngle) * camera.aspect);
          const radius = Math.max(sizes.length() / 2, 0.5);
          const distance = radius / Math.sin(Math.min(verticalHalfAngle, horizontalHalfAngle)) * 1.08;
          const direction = requested === 'top' ? new THREE.Vector3(0, 0, 1)
            : requested === 'front' ? new THREE.Vector3(0, -1, 0) : new THREE.Vector3(1.2, -1.6, 1.1).normalize();
          camera.up.set(0, requested === 'top' ? 1 : 0, requested === 'top' ? 0 : 1);
          camera.position.copy(target).addScaledVector(direction, distance);
          controls.target.copy(target);
          camera.updateProjectionMatrix();
          controls.update();
        };
        highlight.current(latestSelection.current.selectedId, latestSelection.current.hiddenIds);
        const previous = savedCamera.current;
        if (previous && previous.documentId === documentId) {
          camera.position.copy(previous.position);
          camera.up.copy(previous.up);
          controls.target.copy(previous.target);
          camera.updateProjectionMatrix();
          controls.update();
        } else {
          changeView.current('iso');
          setView('iso');
        }
        setLoading(false);
      })
      .catch(reason => {
        if (!disposed) {
          setError(reason instanceof Error ? reason.message : 'The assembly preview could not be loaded.');
          setLoading(false);
        }
      });

    function draw() {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(draw);
    }
    draw();
    return () => {
      savedCamera.current = { documentId, position: camera.position.clone(), target: controls.target.clone(), up: camera.up.clone() };
      disposed = true;
      abort.abort();
      cancelAnimationFrame(frame);
      resize.disconnect();
      controls.dispose();
      renderer.domElement.removeEventListener('pointerdown', pointerDown);
      renderer.domElement.removeEventListener('pointerup', pointerUp);
      geometries.forEach(geometry => geometry.dispose());
      materials.forEach(material => material.dispose());
      if (outline) { outline.geometry.dispose(); (outline.material as THREE.Material).dispose(); }
      grid?.geometry.dispose();
      if (grid) (Array.isArray(grid.material) ? grid.material : [grid.material]).forEach(material => material.dispose());
      renderer.dispose();
      host.replaceChildren();
      changeView.current = () => {};
      highlight.current = () => {};
    };
  }, [documentId, parts]);

  useEffect(() => { highlight.current(selectedId, hiddenIds); }, [selectedId, hiddenIds]);

  return <div className="viewer-shell">
    <div className="viewer-canvas" ref={container} />
    {!parts.length && !busy && <div className="viewer-empty">
      <img src="/app-icon.png" alt="" /><h3>Build your idea in 3D</h3>
      <p>Describe a part or an assembly. Each component keeps an editable history.</p>
    </div>}
    {(busy || loading) && <div className="viewer-loading" role="status"><span className="spinner" aria-hidden="true" />{busy ? 'Building and checking your revision…' : 'Loading assembly…'}</div>}
    {error && <div className="viewer-message" role="alert">{error}</div>}
    {parts.length > 0 && !error && <>
      <div className="view-controls" aria-label="Camera views">
        {(['iso', 'top', 'front'] as const).map(item => <button type="button" key={item} disabled={loading || busy}
          aria-pressed={view === item} onClick={() => { changeView.current(item); setView(item); }}>
          {item === 'iso' ? 'Isometric' : item === 'top' ? 'Top' : 'Front'}
        </button>)}
        <button type="button" disabled={loading || busy} onClick={() => changeView.current(view)}>Fit all</button>
        <button type="button" disabled={loading || busy || !selectedId} onClick={() => changeView.current(view, true)}>Fit part</button>
      </div>
      <span className="viewer-hint">Click to select · Drag to orbit · Scroll to zoom</span>
    </>}
  </div>;
}
