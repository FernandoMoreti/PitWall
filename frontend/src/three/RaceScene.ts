/** Cena da corrida: circuito + carros posicionados somente pela telemetria do WebSocket. */
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { Engine } from './Engine'
import { CarModel } from './CarModel'
import { Track } from './Track'
import { isStale, live, type Telemetry } from '../stores/telemetry'
import { TEAM_COLOR } from '../stores/insights'
import type { TrackData } from '../services/api'

export type CamMode = 'aerial' | 'chase' | 'tv'

interface RaceCar {
  model: CarModel
  marker: THREE.Sprite
  s: number
  lat: number
  init: boolean
}

function markerTexture(num: number, code: string, color: string): THREE.CanvasTexture {
  const c = document.createElement('canvas')
  c.width = 256; c.height = 96
  const g = c.getContext('2d')!
  g.fillStyle = 'rgba(5,7,10,0.82)'
  g.fillRect(0, 10, 256, 60)
  g.fillStyle = color
  g.fillRect(0, 10, 10, 60)
  g.fillStyle = '#dfe7e0'
  g.font = '700 38px Onest, system-ui, sans-serif'
  g.textBaseline = 'middle'
  g.fillText(String(num), 24, 41)
  g.font = '500 24px Onest, system-ui, sans-serif'
  g.fillStyle = '#aab4ad'
  g.fillText(code, 92, 42)
  g.fillStyle = color
  g.beginPath(); g.moveTo(118, 70); g.lineTo(138, 70); g.lineTo(128, 92); g.fill()
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  return t
}

export class RaceScene {
  readonly engine: Engine
  readonly track: Track
  readonly controls: OrbitControls
  readonly cars = new Map<string, RaceCar>()
  mode: CamMode = 'aerial'
  selected = 'PW16'
  onSelect: (id: string) => void = () => {}
  onFrame: () => void = () => {}
  private ray = new THREE.Raycaster()
  private halo: THREE.Mesh
  private tvIndex = 0
  private intro = 0
  private tmpP = new THREE.Vector3()
  private tmpD = new THREE.Vector3()
  private downAt = { x: 0, y: 0 }

  constructor(host: HTMLElement, data: TrackData) {
    this.engine = new Engine(host, { fov: 38, near: 0.5, far: 9000, bloom: 0.75, threshold: 0.85 })
    const { scene, camera } = this.engine
    scene.background = new THREE.Color('#05070a')
    scene.fog = new THREE.FogExp2('#05070a', 0.00016)
    scene.environmentIntensity = 0.35
    scene.add(new THREE.HemisphereLight('#9fb4c8', '#0a0e12', 1.1))
    const moon = new THREE.DirectionalLight('#cfdcff', 1.1)
    moon.position.set(-600, 900, 400)
    scene.add(moon)

    this.track = new Track(data)
    scene.add(this.track.group)

    this.halo = new THREE.Mesh(new THREE.RingGeometry(4.2, 5, 48), new THREE.MeshBasicMaterial({ color: '#e0231c', transparent: true, opacity: 0.85, side: THREE.DoubleSide }))
    this.halo.rotation.x = -Math.PI / 2
    scene.add(this.halo)

    this.controls = new OrbitControls(camera, this.engine.renderer.domElement)
    this.controls.target.copy(this.track.center)
    this.controls.enableDamping = true
    this.controls.maxPolarAngle = Math.PI * 0.46
    this.controls.minDistance = 60
    this.controls.maxDistance = this.track.radius * 3
    this.controls.enabled = false
    camera.position.set(this.track.center.x + this.track.radius * 0.15, this.track.radius * 1.75, this.track.center.z + this.track.radius * 1.3)
    camera.lookAt(this.track.center)

    const el = this.engine.renderer.domElement
    el.addEventListener('pointerdown', (e) => { this.downAt = { x: e.clientX, y: e.clientY } })
    el.addEventListener('pointerup', (e) => {
      if (Math.hypot(e.clientX - this.downAt.x, e.clientY - this.downAt.y) < 5) this.pick(e)
    })

    this.engine.onFrame((dt, t) => this.frame(dt, t))
  }

  private ensureCar(t: Telemetry): RaceCar {
    let rc = this.cars.get(t.car_id)
    if (rc) return rc
    const color = TEAM_COLOR[t.team] ?? '#dfe7e0'
    const model = new CarModel({ color, number: t.number, detail: 'race' })
    model.heatView = 0.25
    model.root.scale.setScalar(1.25)   // um pouco maior para ler na vista aérea
    const marker = new THREE.Sprite(new THREE.SpriteMaterial({ map: markerTexture(t.number, t.car_id, color), depthTest: false, transparent: true, sizeAttenuation: false }))
    marker.scale.set(0.085, 0.032, 1)
    marker.center.set(0.5, 0)
    marker.renderOrder = 10
    marker.userData.carId = t.car_id
    model.root.userData.carId = t.car_id
    this.engine.scene.add(model.root, marker)
    rc = { model, marker, s: t.lap_dist, lat: t.lat, init: false }
    this.cars.set(t.car_id, rc)
    return rc
  }

  private pick(e: PointerEvent): void {
    const r = this.engine.renderer.domElement.getBoundingClientRect()
    const m = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
    this.ray.setFromCamera(m, this.engine.camera)
    const objs: THREE.Object3D[] = []
    for (const c of this.cars.values()) objs.push(c.marker, c.model.root)
    const hit = this.ray.intersectObjects(objs, true)[0]
    let o: THREE.Object3D | null = hit?.object ?? null
    while (o && !o.userData.carId) o = o.parent
    if (o) { this.selected = o.userData.carId; this.onSelect(this.selected) }
  }

  setMode(mode: CamMode): void {
    this.mode = mode
    this.controls.enabled = mode === 'aerial' && this.intro >= 1
    if (mode !== 'tv') { this.engine.camera.fov = 38; this.engine.camera.updateProjectionMatrix() }
    if (mode === 'aerial') {
      const sel = this.cars.get(this.selected)
      this.controls.target.copy(sel ? sel.model.root.position : this.track.center)
    }
  }

  private frame(dt: number, time: number): void {
    const stale = isStale()
    const L = this.track.length
    const now = performance.now()

    for (const [id, c] of live.cars) {
      const t = c.cur
      const rc = this.ensureCar(t)
      if (!rc.init) { rc.s = t.lap_dist; rc.lat = t.lat; rc.init = true }
      if (!stale) {
        // extrapola com a velocidade e corrige suavemente para a última leitura
        const v = t.speed_kph / 3.6
        rc.s += v * dt
        const target = t.lap_dist + v * Math.min(0.25, (now - c.recvAt) / 1000)
        let err = target - rc.s
        if (err > L / 2) err -= L
        if (err < -L / 2) err += L
        if (Math.abs(err) > 150) rc.s = target
        else rc.s += err * Math.min(1, dt * 3)
        rc.s = ((rc.s % L) + L) % L
        rc.lat += (t.lat - rc.lat) * Math.min(1, dt * 3)
      }
      this.track.at(rc.s, rc.lat, this.tmpP, this.tmpD)
      const root = rc.model.root
      root.position.copy(this.tmpP).setY(this.tmpP.y + 0.02)
      root.lookAt(this.tmpP.x + this.tmpD.x, this.tmpP.y + this.tmpD.y + 0.02, this.tmpP.z + this.tmpD.z)
      rc.model.update(t, dt, time, stale)
      rc.marker.position.copy(root.position).setY(root.position.y + 4.5)
      rc.marker.material.opacity = id === this.selected ? 1 : 0.8
      const k = this.engine.camera.fov / 38
      rc.marker.scale.set(0.085 * k, 0.032 * k, 1)
      if (id === this.selected) {
        this.halo.position.copy(root.position).setY(root.position.y + 0.06)
        ;(this.halo.material as THREE.MeshBasicMaterial).opacity = 0.55 + Math.sin(time * 4) * 0.25
      }
    }

    this.updateCamera(dt)
    this.onFrame()
  }

  private updateCamera(dt: number): void {
    const cam = this.engine.camera
    const sel = this.cars.get(this.selected)
    if (this.intro < 1) {
      this.intro = Math.min(1, this.intro + dt / 3.2)
      if (this.intro >= 1) this.controls.enabled = this.mode === 'aerial'
    }
    if (this.mode === 'aerial' || !sel) {
      this.controls.autoRotate = true
      this.controls.autoRotateSpeed = 0.18
      this.controls.update()
      return
    }
    const p = sel.model.root.position
    this.track.at(sel.s, sel.lat, this.tmpP, this.tmpD)
    if (this.mode === 'chase') {
      const desired = p.clone().addScaledVector(this.tmpD, -9.5).add(new THREE.Vector3(0, 3.1, 0))
      cam.position.lerp(desired, 1 - Math.exp(-dt * 4))
      cam.lookAt(p.clone().addScaledVector(this.tmpD, 8).add(new THREE.Vector3(0, 1, 0)))
    } else {
      // câmera de TV: poste mais próximo à frente, com zoom de teleobjetiva
      const cams = this.track.tvCams
      let best = this.tvIndex, bd = Infinity
      for (let i = 0; i < cams.length; i++) {
        const d = cams[i].distanceTo(p)
        const ahead = cams[i].clone().sub(p).dot(this.tmpD) > -60
        if (ahead && d < bd) { bd = d; best = i }
      }
      if (best !== this.tvIndex && cams[this.tvIndex].distanceTo(p) > 260) this.tvIndex = best
      cam.position.lerp(cams[this.tvIndex], 1 - Math.exp(-dt * 6))
      const dist = cam.position.distanceTo(p)
      cam.fov = THREE.MathUtils.clamp(THREE.MathUtils.radToDeg(2 * Math.atan(9 / dist)), 4, 45)
      cam.updateProjectionMatrix()
      cam.lookAt(p)
    }
  }

  dispose(): void {
    this.controls.dispose()
    this.engine.dispose()
  }
}
