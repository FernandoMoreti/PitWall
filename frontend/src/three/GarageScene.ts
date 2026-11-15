/** Estúdio da Garagem: carro grande no centro, órbita, hover/clique por peça e "rolling road". */
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { Engine } from './Engine'
import { CarModel } from './CarModel'
import { isStale, live } from '../stores/telemetry'

export interface CarMeta { car_id: string; number: number; color: string }

const ease = (t: number) => 1 - Math.pow(1 - t, 3)

export class GarageScene {
  readonly engine: Engine
  readonly controls: OrbitControls
  car!: CarModel
  carId = ''
  onHover: (part: string | null, x: number, y: number) => void = () => {}
  onPick: (part: string | null) => void = () => {}
  onFrame: () => void = () => {}
  private ray = new THREE.Raycaster()
  private mouse = new THREE.Vector2()
  private road!: THREE.CanvasTexture
  private ring = new THREE.Group()
  private intro = 0
  private downAt = { x: 0, y: 0 }
  private hoverPart: string | null = null
  autoRotate = true

  constructor(host: HTMLElement, meta: CarMeta) {
    this.engine = new Engine(host, { fov: 32, near: 0.05, far: 200, bloom: 0.4, threshold: 0.92, shadows: true })
    const { scene, camera } = this.engine
    scene.background = new THREE.Color('#05070a')
    scene.fog = new THREE.Fog('#05070a', 14, 40)
    camera.position.set(-2, 1.0, 16)

    this.controls = new OrbitControls(camera, this.engine.renderer.domElement)
    this.controls.target.set(0, 0.45, -0.1)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.06
    this.controls.minDistance = 3.2
    this.controls.maxDistance = 14
    this.controls.maxPolarAngle = Math.PI * 0.49
    this.controls.enablePan = false
    this.controls.enabled = false
    this.controls.addEventListener('start', () => { this.autoRotate = false })

    this.buildStudio()
    this.setCar(meta)

    const el = this.engine.renderer.domElement
    el.addEventListener('pointermove', this.handleMove)
    el.addEventListener('pointerdown', (e) => { this.downAt = { x: e.clientX, y: e.clientY } })
    el.addEventListener('pointerup', this.handleUp)
    el.addEventListener('pointerleave', () => { this.hoverPart = null; this.car.setHovered(null); this.onHover(null, 0, 0) })

    this.engine.onFrame((dt, t) => this.frame(dt, t))
  }

  private buildStudio(): void {
    const { scene } = this.engine
    scene.add(new THREE.HemisphereLight('#a9c1d6', '#050607', 0.35))
    const key = new THREE.SpotLight('#fff3e6', 120, 30, 0.55, 0.6, 1.4)
    key.position.set(3, 9, 4)
    key.target.position.set(0, 0, 0)
    key.castShadow = true
    key.shadow.mapSize.set(2048, 2048)
    key.shadow.bias = -0.0004
    scene.add(key, key.target)
    const rim = new THREE.PointLight('#e0231c', 14, 14, 1.6)
    rim.position.set(-3, 2.2, -5)
    scene.add(rim)
    const fill = new THREE.PointLight('#4aa8ff', 10, 14, 1.6)
    fill.position.set(5, 1.5, -2)
    scene.add(fill)

    // piso com "rolling road" (as linhas correm na velocidade do carro)
    this.road = (() => {
      const c = document.createElement('canvas')
      c.width = 64; c.height = 512
      const g = c.getContext('2d')!
      g.fillStyle = '#0a0d10'; g.fillRect(0, 0, 64, 512)
      g.fillStyle = 'rgba(223,231,224,0.10)'
      for (let y = 0; y < 512; y += 64) g.fillRect(0, y, 64, 2)
      const t = new THREE.CanvasTexture(c)
      t.wrapS = t.wrapT = THREE.RepeatWrapping
      t.repeat.set(1, 4)
      return t
    })()
    const belt = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 9), new THREE.MeshStandardMaterial({ map: this.road, roughness: 0.6, metalness: 0.2 }))
    belt.rotation.x = -Math.PI / 2
    belt.position.y = 0.002
    belt.receiveShadow = true
    scene.add(belt)

    const floorTex = (() => {
      const c = document.createElement('canvas')
      c.width = c.height = 512
      const g = c.getContext('2d')!
      const grad = g.createRadialGradient(256, 256, 10, 256, 256, 256)
      grad.addColorStop(0, '#1a2026'); grad.addColorStop(0.55, '#0b0f12'); grad.addColorStop(1, '#05070a')
      g.fillStyle = grad; g.fillRect(0, 0, 512, 512)
      const t = new THREE.CanvasTexture(c)
      t.colorSpace = THREE.SRGBColorSpace
      return t
    })()
    const floor = new THREE.Mesh(new THREE.CircleGeometry(16, 64), new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.32, metalness: 0.5 }))
    floor.rotation.x = -Math.PI / 2
    floor.receiveShadow = true
    scene.add(floor)

    // anel giratório com marcações (linhas finas do Kage)
    const lineMat = new THREE.MeshBasicMaterial({ color: '#dfe7e0', transparent: true, opacity: 0.18 })
    const red = new THREE.MeshBasicMaterial({ color: '#e0231c' })
    this.ring.add(new THREE.Mesh(new THREE.RingGeometry(4.2, 4.215, 128), lineMat))
    this.ring.add(new THREE.Mesh(new THREE.RingGeometry(5.6, 5.606, 128), lineMat))
    for (let i = 0; i < 72; i++) {
      const long = i % 6 === 0
      const tick = new THREE.Mesh(new THREE.PlaneGeometry(0.012, long ? 0.32 : 0.14), i === 0 ? red : lineMat)
      const a = (i / 72) * Math.PI * 2
      tick.position.set(Math.cos(a) * 4.45, 0, Math.sin(a) * 4.45)
      tick.rotation.set(-Math.PI / 2, 0, -a + Math.PI / 2)
      this.ring.add(tick)
    }
    this.ring.children.forEach((m) => { if (m.rotation.x === 0) m.rotation.x = -Math.PI / 2 })
    this.ring.position.y = 0.004
    scene.add(this.ring)
  }

  setCar(meta: CarMeta): void {
    if (this.car) {
      this.engine.scene.remove(this.car.root)
      this.car.root.traverse((o) => { const m = o as THREE.Mesh; m.geometry?.dispose() })
    }
    this.carId = meta.car_id
    this.car = new CarModel({ color: meta.color, number: meta.number, detail: 'garage' })
    this.car.heatView = 0.32
    this.car.root.traverse((o) => { if ((o as THREE.Mesh).isMesh) { o.castShadow = true } })
    this.engine.scene.add(this.car.root)
  }

  // ------------------------------------------------------------------ interação
  private pick(e: PointerEvent): string | null {
    const r = this.engine.renderer.domElement.getBoundingClientRect()
    this.mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
    this.ray.setFromCamera(this.mouse, this.engine.camera)
    const hit = this.ray.intersectObjects(this.car.pickables(), false)[0]
    return (hit?.object.userData.part as string) ?? null
  }

  private handleMove = (e: PointerEvent) => {
    const p = this.pick(e)
    if (p !== this.hoverPart) {
      this.hoverPart = p
      this.car.setHovered(p)
      this.engine.renderer.domElement.style.cursor = p ? 'pointer' : 'grab'
    }
    const r = this.engine.renderer.domElement.getBoundingClientRect()
    this.onHover(p, e.clientX - r.left, e.clientY - r.top)
  }

  private handleUp = (e: PointerEvent) => {
    if (Math.hypot(e.clientX - this.downAt.x, e.clientY - this.downAt.y) > 5) return // foi arrasto
    const p = this.pick(e)
    this.car.setSelected(p)
    this.onPick(p)
  }

  focus(part: string | null): void {
    this.car.setSelected(part)
  }

  // ------------------------------------------------------------------ loop
  private frame(dt: number, t: number): void {
    const stale = isStale()
    const tel = live.cars.get(this.carId)?.cur
    this.car.update(tel, dt, t, stale)
    const speed = !tel || stale ? 0 : tel.speed_kph / 3.6
    this.road.offset.y += (speed * dt) / 2.25
    this.ring.rotation.y += dt * 0.02

    // intro cinematográfica
    const cam = this.engine.camera
    if (this.intro < 1) {
      this.intro = Math.min(1, this.intro + dt / 2.8)
      const k = ease(this.intro)
      const a = THREE.MathUtils.lerp(-0.4, 0.62, k)
      const r = THREE.MathUtils.lerp(15, 8.2, k)
      cam.position.set(Math.sin(a) * r, THREE.MathUtils.lerp(0.6, 2.4, k), Math.cos(a) * r)
      cam.lookAt(this.controls.target)
      if (this.intro >= 1) this.controls.enabled = true
    } else {
      this.controls.autoRotate = this.autoRotate
      this.controls.autoRotateSpeed = 0.35
      this.controls.update()
    }
    this.onFrame()
  }

  anchor(part: string) {
    const o = this.car.anchors[part]
    if (!o) return null
    return this.engine.project(o.getWorldPosition(new THREE.Vector3()))
  }

  dispose(): void {
    this.controls.dispose()
    this.engine.dispose()
  }
}
