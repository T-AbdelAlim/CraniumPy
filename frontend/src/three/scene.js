import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

// pure Three.js, no React - createScene owns the persistent scene/camera/
// renderer/controls, useThreeScene.js owns wiring this into React's
// lifecycle (mount effect, animation loop, resize, cleanup).
export function createScene(canvas) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x14161a);

  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  // three lights from different angles, each fairly dim, instead of one
  // strong one - a single directional light was crushing whichever side
  // faced away from it into near-black, which made it hard to see the mesh
  // well enough to place landmarks accurately on that side.
  scene.add(new THREE.HemisphereLight(0xffffff, 0x2a2e37, 1.3));
  const keyLight = new THREE.DirectionalLight(0xffffff, 0.55);
  keyLight.position.set(1, 1, 1);
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight(0xffffff, 0.4);
  fillLight.position.set(-1, 0.5, -1);
  scene.add(fillLight);
  const rimLight = new THREE.DirectionalLight(0xffffff, 0.3);
  rimLight.position.set(0, -1, 1);
  scene.add(rimLight);

  function resize(width, height) {
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function fitCameraToObject(object) {
    const box = new THREE.Box3().setFromObject(object);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z, 1);
    const distance = maxDim * 1.8;
    camera.position.set(center.x, center.y, center.z + distance);
    camera.near = distance / 100;
    camera.far = distance * 100;
    camera.updateProjectionMatrix();
    controls.target.copy(center);
    controls.update();
    return maxDim;
  }

  function dispose() {
    controls.dispose();
    renderer.dispose();
  }

  return { scene, camera, renderer, controls, resize, fitCameraToObject, dispose };
}
