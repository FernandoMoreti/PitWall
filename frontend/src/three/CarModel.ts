/**
 * Carro de F1 procedural (sem arquivos externos).
 *
 * Frente do carro em +Z, para cima em +Y, esquerda do piloto em +X.
 * Cada peça interativa tem userData.part igual ao "component" do cadastro de
 * dispositivos (tyre_FL, brake_FL, pu, fuel_cell, ers, radiator, rear_wing...).
 */
import * as THREE from 'three'
import { brakeGlow, engineHeat, ramp, tyreHeat } from './heat'
import type { Telemetry } from '../stores/telemetry'

type Detail = 'garage' | 'race'

const WHEEL_POS: Record<string, [number, number, number]> = {
  FL: [0.80, 0.36, 1.75], FR: [-0.80, 0.36, 1.75],
  RL: [0.78, 0.36, -1.85], RR: [-0.78, 0.36, -1.85],
}
const TYRE_R = 0.36
const CLONE_PARTS = new Set(['chassis', 'pu', 'radiator', 'front_wing', 'rear_wing'])
const COMPOUND: Record<string, string> = { SOFT: '#ff2a1f', MEDIUM: '#ffd02a', HARD: '#f1f4f2' }

// ------------------------------------------------------------------ geometria auxiliar
interface Station { z: number; w: number; y0: number; y1: number; x?: number; n?: number }

/** Casco "loftado" a partir de seções superelípticas ao longo de Z. */
function loft(stations: Station[], seg = 28): THREE.BufferGeometry {
  const pos: number[] = []
  const idx: number[] = []
  const ring = seg
  for (const st of stations) {
    const n = st.n ?? 3.2
    const yc = (st.y0 + st.y1) / 2, h = (st.y1 - st.y0) / 2, xc = st.x ?? 0
    for (let i = 0; i < ring; i++) {
      const a = (i / ring) * Math.PI * 2
      const c = Math.cos(a), s = Math.sin(a)
      const x = xc + st.w * Math.sign(c) * Math.abs(c) ** (2 / n)
      const y = yc + h * Math.sign(s) * Math.abs(s) ** (2 / n)
      pos.push(x, y, st.z)
    }
  }
  for (let k = 0; k < stations.length - 1; k++) {
    for (let i = 0; i < ring; i++) {
      const a = k * ring + i, b = k * ring + ((i + 1) % ring)
      const c = (k + 1) * ring + i, d = (k + 1) * ring + ((i + 1) % ring)
      idx.push(a, c, b, b, c, d)
    }
  }
  // tampas
  for (const [k, flip] of [[0, false], [stations.length - 1, true]] as const) {
    const st = stations[k]
    const center = pos.length / 3
    pos.push(st.x ?? 0, (st.y0 + st.y1) / 2, st.z)
    for (let i = 0; i < ring; i++) {
      const a = k * ring + i, b = k * ring + ((i + 1) % ring)
      if (flip) idx.push(center, a, b)
      else idx.push(center, b, a)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setIndex(idx)
  g.computeVertexNormals()
  return g
}

const UP = new THREE.Vector3(0, 1, 0)
function rod(a: THREE.Vector3, b: THREE.Vector3, r: number, mat: THREE.Material): THREE.Mesh {
  const len = a.distanceTo(b)
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 6), mat)
  m.position.copy(a).add(b).multiplyScalar(0.5)
  m.quaternion.setFromUnitVectors(UP, b.clone().sub(a).normalize())
  return m
}

function box(w: number, h: number, d: number, mat: THREE.Material, x = 0, y = 0, z = 0): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat)
  m.position.set(x, y, z)
  return m
}

function numberTexture(num: number, color: string): THREE.CanvasTexture {
  const c = document.createElement('canvas')
  c.width = 256; c.height = 128
  const g = c.getContext('2d')!
  g.fillStyle = color
  g.fillRect(0, 0, 256, 128)
  g.fillStyle = '#05070a'
  g.fillRect(0, 96, 256, 32)
  g.fillStyle = '#dfe7e0'
  g.font = '700 84px Onest, system-ui, sans-serif'
  g.textAlign = 'center'
  g.textBaseline = 'middle'
  g.fillText(String(num), 128, 52)
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  return t
}

// ------------------------------------------------------------------ o carro
export class CarModel {
  readonly root = new THREE.Group()       // posição no mundo
  readonly body = new THREE.Group()       // treme com a vibração
  readonly parts = new Map<string, THREE.Mesh[]>()
  readonly anchors: Record<string, THREE.Object3D> = {}
  private wheels: Record<string, { spin: THREE.Group; steer: THREE.Group; tyreMat: THREE.MeshStandardMaterial; disc: THREE.MeshStandardMaterial; arc: THREE.Mesh; arcWear: number }> = {}
  private shells: THREE.Mesh[] = []
  private internals = new THREE.Group()
  private puMats: THREE.MeshStandardMaterial[] = []
  private radiatorMats: THREE.MeshStandardMaterial[] = []
  private drsFlap = new THREE.Group()
  private louvers: THREE.Mesh[] = []
  private exhaust!: THREE.MeshStandardMaterial
  private rainLight!: THREE.MeshStandardMaterial
  private fuelLevel?: THREE.Mesh
  private ersMat?: THREE.MeshStandardMaterial
  private hovered: string | null = null
  private selected: string | null = null
  private xray = false
  private drsAngle = -0.85
  private louverAngle = 0
  heatView = 0.45     // intensidade do mapa térmico nas peças

  constructor(opts: { color: string; accent?: string; number: number; detail: Detail }) {
    const detail = opts.detail
    this.root.add(this.body)

    const paint = new THREE.MeshPhysicalMaterial({ color: opts.color, metalness: 0.35, roughness: 0.32, clearcoat: 1, clearcoatRoughness: 0.18 })
    const accent = new THREE.MeshPhysicalMaterial({ color: opts.accent ?? '#9aa39d', metalness: 0.3, roughness: 0.5, clearcoat: 0.3 })
    const carbon = new THREE.MeshStandardMaterial({ color: '#0d1013', metalness: 0.35, roughness: 0.5 })
    const dark = new THREE.MeshStandardMaterial({ color: '#05070a', metalness: 0.1, roughness: 0.7 })
    const metal = new THREE.MeshStandardMaterial({ color: '#8a9096', metalness: 0.9, roughness: 0.3 })
    const susp = new THREE.MeshStandardMaterial({ color: '#16191c', metalness: 0.6, roughness: 0.4 })

    // ---- monocoque + nariz (chassis) e capa do motor (pu)
    const front: Station[] = [
      { z: 2.78, w: 0.07, y0: 0.17, y1: 0.25 }, { z: 2.45, w: 0.13, y0: 0.15, y1: 0.34 },
      { z: 2.0, w: 0.18, y0: 0.13, y1: 0.44 }, { z: 1.5, w: 0.24, y0: 0.12, y1: 0.55 },
      { z: 1.0, w: 0.30, y0: 0.1, y1: 0.62 }, { z: 0.4, w: 0.36, y0: 0.1, y1: 0.64 },
      { z: -0.2, w: 0.4, y0: 0.1, y1: 0.7 },
    ]
    const rear: Station[] = [
      { z: -0.2, w: 0.4, y0: 0.1, y1: 0.7 }, { z: -0.6, w: 0.34, y0: 0.1, y1: 0.97, n: 2.6 },
      { z: -1.2, w: 0.27, y0: 0.12, y1: 0.8, n: 2.6 }, { z: -1.8, w: 0.18, y0: 0.15, y1: 0.58 },
      { z: -2.3, w: 0.12, y0: 0.18, y1: 0.4 }, { z: -2.62, w: 0.07, y0: 0.22, y1: 0.32 },
    ]
    const chassis = new THREE.Mesh(loft(front), paint)
    const cover = new THREE.Mesh(loft(rear), paint.clone())
    this.addPart('chassis', chassis)
    this.addPart('pu', cover)
    this.shells.push(chassis, cover)

    // abertura do cockpit + capacete
    const cockpit = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.24, 0.04, 24), dark)
    cockpit.scale.set(1, 1, 1.9)
    cockpit.position.set(0, 0.64, 0.42)
    this.body.add(cockpit)
    const helmet = new THREE.Mesh(new THREE.SphereGeometry(0.13, 24, 16), accent)
    helmet.position.set(0, 0.74, 0.18)
    this.body.add(helmet)
    const visor = new THREE.Mesh(new THREE.SphereGeometry(0.131, 24, 8, -0.9, 1.8, 1.25, 0.45), dark)
    visor.position.copy(helmet.position)
    this.body.add(visor)

    // barbatana com o número
    const fin = new THREE.Shape()
    fin.moveTo(0.65, 0.95); fin.lineTo(2.35, 0.62); fin.lineTo(2.35, 0.4); fin.lineTo(0.8, 0.7); fin.closePath()
    const finGeo = new THREE.ExtrudeGeometry(fin, { depth: 0.014, bevelEnabled: false })
    finGeo.rotateY(Math.PI / 2)
    finGeo.translate(-0.007, 0, 0)
    const finMesh = new THREE.Mesh(finGeo, paint.clone())
    this.addPart('pu', finMesh)
    this.shells.push(finMesh)
    const numTex = numberTexture(opts.number, opts.color)
    for (const side of [1, -1]) {
      const decal = new THREE.Mesh(new THREE.PlaneGeometry(0.42, 0.21), new THREE.MeshStandardMaterial({ map: numTex, roughness: 0.5 }))
      decal.position.set(0.0085 * side, 0.68, -1.45)
      decal.rotation.y = side * Math.PI / 2
      this.body.add(decal)
    }

    // ---- sidepods (radiadores)
    for (const side of [1, -1]) {
      const pod = new THREE.Mesh(loft([
        { z: 0.72, w: 0.1, y0: 0.22, y1: 0.52, x: side * 0.6 }, { z: 0.45, w: 0.24, y0: 0.15, y1: 0.62, x: side * 0.58 },
        { z: -0.2, w: 0.26, y0: 0.13, y1: 0.58, x: side * 0.56 }, { z: -0.8, w: 0.2, y0: 0.13, y1: 0.45, x: side * 0.5 },
        { z: -1.4, w: 0.1, y0: 0.14, y1: 0.3, x: side * 0.42 }, { z: -1.72, w: 0.04, y0: 0.15, y1: 0.22, x: side * 0.38 },
      ], 24), paint.clone())
      this.addPart('radiator', pod)
      this.shells.push(pod)
      const inlet = new THREE.Mesh(new THREE.PlaneGeometry(0.17, 0.26), dark)
      inlet.position.set(side * 0.6, 0.37, 0.73)
      this.body.add(inlet)
      // aletas de resfriamento (abrem com o atuador "cooling")
      for (let i = 0; i < 4; i++) {
        const l = box(0.2, 0.012, 0.07, carbon, side * 0.55, 0.585 - i * 0.012, -0.35 - i * 0.12)
        l.userData.part = 'radiator'
        this.louvers.push(l)
        this.body.add(l)
      }
    }

    // ---- assoalho
    const floor = new THREE.Shape()
    floor.moveTo(0.3, 1.55); floor.lineTo(0.62, 1.2); floor.lineTo(0.88, 0.6); floor.lineTo(0.9, -1.3)
    floor.lineTo(0.62, -2.15); floor.lineTo(-0.62, -2.15); floor.lineTo(-0.9, -1.3); floor.lineTo(-0.88, 0.6)
    floor.lineTo(-0.62, 1.2); floor.lineTo(-0.3, 1.55); floor.closePath()
    const floorGeo = new THREE.ExtrudeGeometry(floor, { depth: 0.035, bevelEnabled: false })
    floorGeo.rotateX(Math.PI / 2)
    floorGeo.translate(0, 0.085, 0)
    const floorMesh = new THREE.Mesh(floorGeo, carbon)
    this.body.add(floorMesh)
    this.body.add(box(0.5, 0.02, 3.4, new THREE.MeshStandardMaterial({ color: '#c9a24a', roughness: 0.6 }), 0, 0.04, -0.3)) // prancha

    // ---- asa dianteira
    const fwing: THREE.Mesh[] = []
    const elems = [[0.0, 0.11, 0.3, 0.0], [0.05, 0.15, 0.2, -0.18], [0.1, 0.19, 0.14, -0.34]]
    elems.forEach(([dz, y, d, rx], i) => {
      const m = box(1.86, 0.018, d, i === 0 ? accent : paint, 0, y, 2.68 - dz)
      m.rotation.x = rx
      fwing.push(m)
    })
    for (const side of [1, -1]) {
      fwing.push(box(0.02, 0.22, 0.55, carbon, side * 0.94, 0.17, 2.62))
      fwing.push(rod(new THREE.Vector3(side * 0.06, 0.2, 2.45), new THREE.Vector3(side * 0.06, 0.12, 2.6), 0.015, carbon))
    }
    fwing.forEach((m) => this.addPart('front_wing', m))

    // ---- asa traseira + DRS
    const rwing: THREE.Mesh[] = []
    const main = box(1.0, 0.03, 0.34, paint, 0, 0.82, -2.78)
    main.rotation.x = -0.12
    rwing.push(main)
    const flap = box(1.0, 0.02, 0.2, accent, 0, 0, 0.1)
    this.drsFlap.add(flap)
    this.drsFlap.position.set(0, 0.93, -2.9)
    this.drsFlap.rotation.x = -0.85
    this.body.add(this.drsFlap)
    flap.userData.part = 'rear_wing'
    this.parts.set('rear_wing', [flap])
    for (const side of [1, -1]) rwing.push(box(0.02, 0.5, 0.62, carbon, side * 0.51, 0.72, -2.8))
    rwing.push(box(0.92, 0.025, 0.18, carbon, 0, 0.42, -2.62))   // beam wing
    rwing.push(box(0.04, 0.5, 0.12, carbon, 0, 0.6, -2.7))       // pilone
    rwing.forEach((m) => this.addPart('rear_wing', m))
    this.rainLight = new THREE.MeshStandardMaterial({ color: '#300', emissive: '#ff1a10', emissiveIntensity: 0 })
    this.body.add(box(0.1, 0.05, 0.02, this.rainLight, 0, 0.36, -2.73))
    this.exhaust = new THREE.MeshStandardMaterial({ color: '#222', emissive: '#ff6a2a', emissiveIntensity: 0, metalness: 0.8, roughness: 0.3 })
    const ex = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.055, 0.14, 16, 1, true), this.exhaust)
    ex.rotation.x = Math.PI / 2
    ex.position.set(0, 0.47, -2.62)
    this.body.add(ex)

    // ---- halo e espelhos
    const haloMat = new THREE.MeshStandardMaterial({ color: '#1a1e22', metalness: 0.7, roughness: 0.35 })
    const halo = new THREE.TubeGeometry(new THREE.CatmullRomCurve3([
      new THREE.Vector3(0.33, 0.66, -0.15), new THREE.Vector3(0.3, 0.87, 0.22), new THREE.Vector3(0, 0.92, 0.55),
      new THREE.Vector3(-0.3, 0.87, 0.22), new THREE.Vector3(-0.33, 0.66, -0.15)]), 40, 0.026, 8)
    this.addPart('chassis', new THREE.Mesh(halo, haloMat))
    this.addPart('chassis', rod(new THREE.Vector3(0, 0.92, 0.55), new THREE.Vector3(0, 0.63, 0.86), 0.022, haloMat))
    for (const side of [1, -1]) {
      this.body.add(rod(new THREE.Vector3(side * 0.3, 0.64, 0.62), new THREE.Vector3(side * 0.5, 0.72, 0.6), 0.01, carbon))
      this.body.add(box(0.13, 0.06, 0.03, paint, side * 0.54, 0.73, 0.6))
    }

    // ---- rodas, freios e suspensão (as hastes começam e terminam exatamente nos pontos de fixação)
    for (const [w, [x, y, z]] of Object.entries(WHEEL_POS)) this.buildWheel(w, x, y, z, w[0] === 'F' ? 0.3 : 0.4, metal, carbon, susp)

    // ---- componentes internos (visíveis no modo raio-X da garagem)
    if (detail === 'garage') this.buildInternals()

    // âncoras para as linhas-guia dos cards
    const anchor = (name: string, x: number, y: number, z: number) => {
      const o = new THREE.Object3D()
      o.position.set(x, y, z)
      this.body.add(o)
      this.anchors[name] = o
    }
    for (const [w, [x, y, z]] of Object.entries(WHEEL_POS)) anchor(`tyre_${w}`, x + Math.sign(x) * 0.18, y + 0.1, z)
    anchor('pu', 0, 0.85, -1.1)
    anchor('fuel_cell', 0, 0.6, -0.25)
    anchor('ers', 0, 0.2, -0.25)
    anchor('radiator', 0.62, 0.55, -0.2)
    anchor('rear_wing', 0, 1.0, -2.85)
    anchor('front_wing', 0.6, 0.2, 2.7)
    anchor('chassis', 0, 0.95, 0.4)
  }

  private addPart(part: string, mesh: THREE.Mesh, parent: THREE.Object3D = this.body): void {
    mesh.userData.part = part
    // material próprio por peça, para o destaque de hover não "vazar" para outras peças
    if (CLONE_PARTS.has(part) && parent === this.body) mesh.material = (mesh.material as THREE.Material).clone()
    if (!this.parts.has(part)) this.parts.set(part, [])
    this.parts.get(part)!.push(mesh)
    parent.add(mesh)
  }

  private buildWheel(w: string, x: number, y: number, z: number, width: number, metal: THREE.Material,
                     carbon: THREE.Material, susp: THREE.Material): void {
    const steer = new THREE.Group()
    steer.position.set(x, y, z)
    this.body.add(steer)
    const spin = new THREE.Group()
    steer.add(spin)
    const side = Math.sign(x)

    const hw = width / 2
    const prof = [
      [0.245, -hw], [0.31, -hw], [0.345, -hw + 0.02], [TYRE_R, -hw + 0.06],
      [TYRE_R, hw - 0.06], [0.345, hw - 0.02], [0.31, hw], [0.245, hw],
    ].map(([r, a]) => new THREE.Vector2(r, a))
    const tyreGeo = new THREE.LatheGeometry(prof, 48)
    tyreGeo.rotateZ(Math.PI / 2)
    const tyreMat = new THREE.MeshStandardMaterial({ color: '#141414', roughness: 0.85, metalness: 0, emissive: '#000' })
    const tyre = new THREE.Mesh(tyreGeo, tyreMat)
    this.addPart(`tyre_${w}`, tyre, spin)

    const rim = new THREE.Mesh(new THREE.CylinderGeometry(0.245, 0.245, width * 0.86, 32, 1, true), metal)
    rim.rotation.z = Math.PI / 2
    this.addPart(`tyre_${w}`, rim, spin)
    const cover = new THREE.Mesh(new THREE.CircleGeometry(0.244, 32), new THREE.MeshStandardMaterial({ color: '#101316', metalness: 0.6, roughness: 0.35 }))
    cover.rotation.y = side * Math.PI / 2
    cover.position.x = side * hw * 0.86
    this.addPart(`tyre_${w}`, cover, spin)
    // raios (para enxergar a rotação)
    for (let i = 0; i < 5; i++) {
      const s = box(0.005, 0.035, 0.42, metal, side * (hw * 0.86 + 0.004), 0, 0)
      s.rotation.x = (i / 5) * Math.PI
      spin.add(s)
    }
    // arco do composto no flanco: encurta conforme o desgaste
    const arc = new THREE.Mesh(new THREE.RingGeometry(0.295, 0.318, 48, 1, 0, Math.PI * 2),
      new THREE.MeshStandardMaterial({ color: '#fff', emissive: '#fff', emissiveIntensity: 0.25, side: THREE.DoubleSide }))
    arc.rotation.y = side * Math.PI / 2
    arc.position.x = side * (hw + 0.002)
    spin.add(arc)

    // disco de freio (não gira visualmente com a roda; fica no cubo)
    const disc = new THREE.MeshStandardMaterial({ color: '#2a2422', metalness: 0.5, roughness: 0.6, emissive: '#000' })
    const discMesh = new THREE.Mesh(new THREE.CylinderGeometry(0.165, 0.165, 0.032, 32), disc)
    discMesh.rotation.z = Math.PI / 2
    discMesh.position.x = -side * (hw * 0.4)
    this.addPart(`brake_${w}`, discMesh, steer)
    const duct = box(0.06, 0.16, 0.18, carbon, -side * (hw + 0.04), 0.0, 0)
    this.addPart(`brake_${w}`, duct, steer)

    // suspensão: braços triangulares superior/inferior e push-rod
    const hub = new THREE.Vector3(x - side * (hw + 0.06), y, z)
    const cx = side * 0.22
    const front = w[0] === 'F'
    const uA = new THREE.Vector3(cx, front ? 0.48 : 0.42, z + 0.28), uB = new THREE.Vector3(cx, front ? 0.48 : 0.42, z - 0.22)
    const lA = new THREE.Vector3(cx, 0.17, z + 0.32), lB = new THREE.Vector3(cx, 0.17, z - 0.3)
    const hubU = hub.clone().add(new THREE.Vector3(0, 0.12, 0)), hubL = hub.clone().add(new THREE.Vector3(0, -0.12, 0))
    for (const [a, b] of [[uA, hubU], [uB, hubU], [lA, hubL], [lB, hubL], [new THREE.Vector3(cx, 0.55, z - 0.05), hubL]] as const) {
      this.body.add(rod(a, b, 0.012, susp))
    }
    this.wheels[w] = { spin, steer, tyreMat, disc, arc, arcWear: -1 }
  }

  private buildInternals(): void {
    const g = this.internals
    g.visible = false
    this.body.add(g)
    const mk = (color: string, emissive = '#000') => new THREE.MeshStandardMaterial({ color, emissive, metalness: 0.6, roughness: 0.35 })

    // Power Unit: bloco V6 + turbo + MGU
    const block = mk('#3a3f44')
    this.puMats.push(block)
    const blk = box(0.42, 0.3, 0.8, block, 0, 0.36, -1.15)
    this.addPart('pu', blk, g)
    for (const side of [1, -1]) {
      for (let i = 0; i < 3; i++) {
        const cm = mk('#4a5056')
        this.puMats.push(cm)
        const c = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.22, 16), cm)
        c.position.set(side * 0.16, 0.56, -0.9 - i * 0.24)
        c.rotation.z = side * 0.5
        this.addPart('pu', c, g)
      }
    }
    const turbo = mk('#5b5f63')
    this.puMats.push(turbo)
    const turboMesh = new THREE.Mesh(new THREE.SphereGeometry(0.11, 20, 14), turbo)
    turboMesh.position.set(0, 0.45, -1.7)
    this.addPart('pu', turboMesh, g)

    // célula de combustível com nível
    const tankMat = new THREE.MeshPhysicalMaterial({ color: '#c9a24a', transparent: true, opacity: 0.18, roughness: 0.2, transmission: 0.3 })
    const tank = box(0.56, 0.42, 0.48, tankMat, 0, 0.36, -0.25)
    this.addPart('fuel_cell', tank, g)
    this.fuelLevel = box(0.52, 0.38, 0.44, new THREE.MeshStandardMaterial({ color: '#c9a24a', emissive: '#c9a24a', emissiveIntensity: 0.6 }), 0, 0.17, -0.25)
    this.fuelLevel.geometry.translate(0, 0.19, 0)
    this.addPart('fuel_cell', this.fuelLevel, g)

    // bateria do ERS
    this.ersMat = new THREE.MeshStandardMaterial({ color: '#0b2730', emissive: '#29c4c9', emissiveIntensity: 0.6 })
    this.addPart('ers', box(0.36, 0.08, 0.5, this.ersMat, 0, 0.13, -0.25), g)

    // radiadores
    for (const side of [1, -1]) {
      const rm = mk('#2c3136')
      this.radiatorMats.push(rm)
      const r = box(0.05, 0.36, 0.55, rm, side * 0.56, 0.36, 0.1)
      r.rotation.z = side * 0.35
      this.addPart('radiator', r, g)
    }
  }

  // ------------------------------------------------------------------ interação
  setXray(on: boolean): void {
    this.xray = on
    this.internals.visible = on
    for (const m of this.shells) {
      const mat = m.material as THREE.MeshPhysicalMaterial
      mat.transparent = on
      mat.opacity = on ? 0.13 : 1
      mat.depthWrite = !on
      mat.needsUpdate = true
    }
  }

  setHovered(p: string | null): void { this.hovered = p }
  setSelected(p: string | null): void { this.selected = p }

  /** Meshes clicáveis (no raio-X, as carenagens deixam de capturar o clique). */
  pickables(): THREE.Object3D[] {
    const out: THREE.Object3D[] = []
    this.root.traverse((o) => {
      if (!(o as THREE.Mesh).isMesh || !o.userData.part || !o.visible) return
      if (this.xray && this.shells.includes(o as THREE.Mesh)) return
      let p: THREE.Object3D | null = o
      while (p) { if (!p.visible) return; p = p.parent }
      out.push(o)
    })
    return out
  }

  private glow(part: string): number {
    return part === this.selected ? 0.55 : part === this.hovered ? 0.3 : 0
  }

  // ------------------------------------------------------------------ atualização por quadro
  private tmp = new THREE.Color()
  private tmp2 = new THREE.Color()

  update(t: Telemetry | undefined, dt: number, time: number, stale: boolean): void {
    const speed = !t || stale ? 0 : t.speed_kph / 3.6
    const hv = this.heatView

    for (const [w, wh] of Object.entries(this.wheels)) {
      wh.spin.rotation.x += (speed / TYRE_R) * dt
      if (!t || stale) {
        wh.tyreMat.emissive.setRGB(0, 0, 0)
        wh.disc.emissive.setRGB(0, 0, 0)
        continue
      }
      ramp(tyreHeat(t[`tyre_temp_${w}`]), this.tmp)
      wh.tyreMat.emissive.copy(this.tmp).multiplyScalar(hv)
      const gl = this.glow(`tyre_${w}`)
      if (gl) wh.tyreMat.emissive.lerp(this.tmp2.set('#ffffff'), gl * 0.5)
      const b = brakeGlow(t[`brake_temp_${w}`], this.tmp)
      wh.disc.emissive.copy(b.color)
      wh.disc.emissiveIntensity = b.intensity + this.glow(`brake_${w}`) * 2
      // arco do composto
      const wear = Math.round(t[`tyre_wear_${w}`])
      if (wear !== wh.arcWear) {
        wh.arcWear = wear
        wh.arc.geometry.dispose()
        wh.arc.geometry = new THREE.RingGeometry(0.295, 0.318, 48, 1, Math.PI / 2, Math.PI * 2 * Math.max(0.01, 1 - wear / 100))
        const mat = wh.arc.material as THREE.MeshStandardMaterial
        mat.color.set(COMPOUND[t.tyre_compound] ?? '#fff')
        mat.emissive.set(COMPOUND[t.tyre_compound] ?? '#fff')
      }
    }

    // PU: calor e vibração
    const heat = t && !stale ? engineHeat(t.engine_temp) : 0
    ramp(heat, this.tmp)
    for (const m of this.puMats) {
      m.emissive.copy(this.tmp).multiplyScalar(0.25 + heat * 0.9)
      if (this.glow('pu')) m.emissive.lerp(this.tmp2.set('#fff'), this.glow('pu') * 0.4)
    }
    for (const m of this.radiatorMats) m.emissive.copy(this.tmp).multiplyScalar(0.2 + heat * 0.6)
    const vib = t && !stale ? Math.max(0, t.pu_vibration - 0.95) : 0
    const amp = Math.min(0.03, vib * vib * 0.004 + vib * 0.0015)
    this.body.position.set((Math.random() - 0.5) * amp, (Math.random() - 0.5) * amp, (Math.random() - 0.5) * amp * 0.5)

    // carenagens: destaque de hover/seleção
    for (const [part, meshes] of this.parts) {
      const g = this.glow(part)
      for (const m of meshes) {
        if (!this.shells.includes(m) && part !== 'front_wing' && part !== 'rear_wing' && part !== 'chassis') continue
        const mat = m.material as THREE.MeshStandardMaterial
        if (!mat.emissive) continue
        if (part === 'pu' && t && !stale && this.shells.includes(m)) {
          mat.emissive.copy(this.tmp.set('#ff4a1c')).multiplyScalar(Math.max(0, heat - 0.75) * hv * 1.4)
        } else mat.emissive.setRGB(0, 0, 0)
        if (g) mat.emissive.lerp(this.tmp2.set('#ffffff'), g * 0.35)
      }
    }

    // DRS e aletas de resfriamento (atuadores animados)
    this.drsAngle += ((t && !stale && t.drs ? -0.12 : -0.85) - this.drsAngle) * Math.min(1, dt * 8)
    this.drsFlap.rotation.x = this.drsAngle
    this.louverAngle += ((t && !stale && t.cooling ? 0.75 : 0) - this.louverAngle) * Math.min(1, dt * 4)
    for (const l of this.louvers) l.rotation.x = this.louverAngle
    for (const m of this.radiatorMats) if (t?.cooling) m.emissive.lerp(this.tmp2.set('#4aa8ff'), 0.35)

    // escape e luz de chuva (pisca em regeneração / lift-and-coast)
    this.exhaust.emissiveIntensity = t && !stale ? (t.rpm / 12000) * (0.6 + t.throttle * 2.2) : 0
    const blink = t && !stale && (t.ers_mode === 'HARVEST' || t.cooling) ? (Math.sin(time * 14) > 0 ? 4 : 0.2) : 0
    this.rainLight.emissiveIntensity = blink

    // internos
    if (this.fuelLevel && t) this.fuelLevel.scale.y = Math.max(0.02, t.fuel_kg / 110)
    if (this.ersMat && t) {
      this.ersMat.emissiveIntensity = 0.15 + (t.ers_soc / 100) * 1.4 + this.glow('ers') * 2
    }
  }
}
