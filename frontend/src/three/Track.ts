/**
 * Circuito 3D gerado a partir do JSON da pista servido pela API (mesma fonte do
 * simulador). Repetições (árvores, postes, arquibancadas, boxes) usam InstancedMesh.
 */
import * as THREE from 'three'
import type { TrackData } from '../services/api'

function canvasTex(w: number, h: number, draw: (g: CanvasRenderingContext2D) => void, repeat = true): THREE.CanvasTexture {
  const c = document.createElement('canvas')
  c.width = w; c.height = h
  draw(c.getContext('2d')!)
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  if (repeat) t.wrapS = t.wrapT = THREE.RepeatWrapping
  t.anisotropy = 8
  return t
}

const ELEV = 0.4     // elevação suavizada para a cena
const GROUND_Y = -4.6

export class Track {
  readonly group = new THREE.Group()
  readonly n: number
  readonly length: number
  readonly center = new THREE.Vector3()
  readonly radius: number
  readonly tvCams: THREE.Vector3[] = []
  private p: THREE.Vector3[] = []
  private nrm: THREE.Vector3[] = []

  readonly d: TrackData

  constructor(d: TrackData) {
    this.d = d
    this.n = d.s.length
    this.length = d.length
    for (let i = 0; i < this.n; i++) {
      this.p.push(new THREE.Vector3(d.x[i], d.y[i] * ELEV, d.z[i]))
      this.nrm.push(new THREE.Vector3(d.nx[i], 0, d.nz[i]))
    }
    const box = new THREE.Box3().setFromPoints(this.p)
    box.getCenter(this.center)
    this.radius = box.getSize(new THREE.Vector3()).length() / 2
    this.build()
  }

  // ------------------------------------------------------------------ consulta
  /** Posição e direção num ponto s (m) com deslocamento lateral lat (m, + = esquerda). */
  at(s: number, lat: number, outPos: THREE.Vector3, outDir: THREE.Vector3): void {
    const L = this.length
    s = ((s % L) + L) % L
    const f = s / this.d.step_m
    const i = Math.floor(f) % this.n, j = (i + 1) % this.n, t = f - Math.floor(f)
    outPos.lerpVectors(this.p[i], this.p[j], t)
    const nx = this.nrm[i].x + (this.nrm[j].x - this.nrm[i].x) * t
    const nz = this.nrm[i].z + (this.nrm[j].z - this.nrm[i].z) * t
    outPos.x += nx * lat
    outPos.z += nz * lat
    outDir.subVectors(this.p[j], this.p[i]).normalize()
  }

  // ------------------------------------------------------------------ construção
  private ribbon(a: number, b: number, lift: number, mat: THREE.Material, from = 0, to = this.n, vScale = 1): THREE.Mesh {
    const pos: number[] = [], uv: number[] = [], idx: number[] = []
    let k = 0
    for (let ii = from; ii <= to; ii++) {
      const i = ((ii % this.n) + this.n) % this.n
      const p = this.p[i], n = this.nrm[i]
      const v = (ii * this.d.step_m) / vScale
      pos.push(p.x + n.x * a, p.y + lift, p.z + n.z * a, p.x + n.x * b, p.y + lift, p.z + n.z * b)
      uv.push(0, v, 1, v)
      if (ii > from) idx.push(k - 2, k - 1, k, k - 1, k + 1, k)
      k += 2
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2))
    g.setIndex(idx)
    g.computeVertexNormals()
    ;(mat as THREE.MeshStandardMaterial).side = THREE.DoubleSide
    const m = new THREE.Mesh(g, mat)
    m.receiveShadow = true
    this.group.add(m)
    return m
  }

  private wall(off: number | ((i: number) => number), height: number, mat: THREE.Material): void {
    const pos: number[] = [], idx: number[] = []
    for (let i = 0; i <= this.n; i++) {
      const p = this.p[i % this.n], n = this.nrm[i % this.n]
      const o = typeof off === 'number' ? off : off(i % this.n)
      const x = p.x + n.x * o, z = p.z + n.z * o
      pos.push(x, p.y, z, x, p.y + height, z)
      if (i) { const k = i * 2; idx.push(k - 2, k - 1, k, k - 1, k + 1, k) }
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setIndex(idx)
    g.computeVertexNormals()
    this.group.add(new THREE.Mesh(g, mat))
  }

  private idxOf(s: number): number { return Math.round(s / this.d.step_m) }

  private build(): void {
    const d = this.d
    const W = d.width / 2

    // chão
    const groundTex = canvasTex(512, 512, (g) => {
      g.fillStyle = '#080b0e'; g.fillRect(0, 0, 512, 512)
      for (let i = 0; i < 2600; i++) {
        g.fillStyle = `rgba(${40 + Math.random() * 30},${60 + Math.random() * 30},${50 + Math.random() * 25},${Math.random() * 0.12})`
        g.fillRect(Math.random() * 512, Math.random() * 512, 2, 2)
      }
      g.strokeStyle = 'rgba(223,231,224,0.035)'
      for (let i = 0; i <= 512; i += 64) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, 512); g.moveTo(0, i); g.lineTo(512, i); g.stroke() }
    })
    groundTex.repeat.set(60, 60)
    const ground = new THREE.Mesh(new THREE.CircleGeometry(this.radius * 2.6, 64),
      new THREE.MeshStandardMaterial({ map: groundTex, color: '#9aa69f', roughness: 0.95 }))
    ground.rotation.x = -Math.PI / 2
    ground.position.set(this.center.x, GROUND_Y, this.center.z)
    ground.receiveShadow = true
    this.group.add(ground)

    // asfalto
    const asphalt = canvasTex(256, 256, (g) => {
      g.fillStyle = '#262b30'; g.fillRect(0, 0, 256, 256)
      for (let i = 0; i < 9000; i++) {
        const c = 30 + Math.random() * 30
        g.fillStyle = `rgba(${c},${c + 2},${c + 4},0.5)`
        g.fillRect(Math.random() * 256, Math.random() * 256, 1.5, 1.5)
      }
      g.fillStyle = 'rgba(0,0,0,0.25)'; g.fillRect(96, 0, 64, 256) // linha de borracha
    })
    this.ribbon(-W, W, 0.02, new THREE.MeshStandardMaterial({ map: asphalt, roughness: 0.78, metalness: 0.05, emissive: '#0b0e11' }), 0, this.n, 14)

    // acostamento (terra escura) e linhas brancas
    const verge = new THREE.MeshStandardMaterial({ color: '#0f1417', roughness: 1 })
    this.ribbon(W, W + 8, -0.02, verge)
    this.ribbon(-W - 8, -W, -0.02, verge)
    const white = new THREE.MeshStandardMaterial({ color: '#dfe7e0', emissive: '#dfe7e0', emissiveIntensity: 0.35, roughness: 0.6 })
    this.ribbon(W - 0.7, W - 0.2, 0.04, white)
    this.ribbon(-W + 0.2, -W + 0.7, 0.04, white)

    // zebras nas curvas
    const kerbTex = canvasTex(64, 64, (g) => {
      g.fillStyle = '#e0231c'; g.fillRect(0, 0, 64, 32)
      g.fillStyle = '#e8ece9'; g.fillRect(0, 32, 64, 32)
    })
    const kerbMat = new THREE.MeshStandardMaterial({ map: kerbTex, roughness: 0.6, emissive: '#330806', emissiveIntensity: 0.4 })
    let start = -1
    for (let i = 0; i <= this.n; i++) {
      const curved = i < this.n && Math.abs(d.k[i]) > 0.0045
      if (curved && start < 0) start = i
      if (!curved && start >= 0) {
        if (i - start > 3) {
          this.ribbon(W, W + 1.4, 0.03, kerbMat, start - 2, i + 2, 3)
          this.ribbon(-W - 1.4, -W, 0.03, kerbMat, start - 2, i + 2, 3)
        }
        start = -1
      }
    }

    // zonas de DRS: faixa central luminosa
    const drsMat = new THREE.MeshStandardMaterial({ color: '#0b2d2e', emissive: '#29c4c9', emissiveIntensity: 1.2 })
    for (const [a, b] of d.drs_zones) {
      const ia = this.idxOf(a), ib = this.idxOf(b)
      this.ribbon(-0.12, 0.12, 0.05, drsMat, ia, ib >= ia ? ib : ib + this.n)
    }

    // linha de largada (xadrez)
    const checker = canvasTex(128, 32, (g) => {
      for (let x = 0; x < 16; x++) for (let y = 0; y < 4; y++) {
        g.fillStyle = (x + y) % 2 ? '#05070a' : '#dfe7e0'; g.fillRect(x * 8, y * 8, 8, 8)
      }
    }, false)
    this.ribbon(-W, W, 0.05, new THREE.MeshStandardMaterial({ map: checker, roughness: 0.6 }), 0, 1, d.step_m)

    // pit lane + garagens
    const pitMat = new THREE.MeshStandardMaterial({ color: '#22272c', roughness: 0.8 })
    const ie = this.idxOf(d.pit.entry), ix = this.idxOf(d.pit.exit)
    const pitFrom = ie - this.n, pitTo = ix
    this.ribbon(d.pit_offset - 4, -W - 0.5, 0.01, pitMat, pitFrom, pitTo)
    this.ribbon(-W - 0.9, -W - 0.6, 0.045, white, pitFrom, pitTo)
    const boxGeo = new THREE.BoxGeometry(1, 1, 1)
    const garages = new THREE.InstancedMesh(boxGeo, new THREE.MeshStandardMaterial({ color: '#141a1f', roughness: 0.7 }), 12)
    const garageGlow = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ color: '#dfe7e0' }), 12)
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), pos = new THREE.Vector3(), dir = new THREE.Vector3()
    for (let i = 0; i < 12; i++) {
      this.at(-60 + i * 22, d.pit_offset - 9.5, pos, dir)
      q.setFromUnitVectors(new THREE.Vector3(0, 0, 1), dir)
      m4.compose(pos.clone().setY(pos.y + 3), q, new THREE.Vector3(9, 6, 20))
      garages.setMatrixAt(i, m4)
      this.at(-60 + i * 22, d.pit_offset - 5.45, pos, dir)
      const qq = q.clone().multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), -Math.PI / 2))
      m4.compose(pos.clone().setY(pos.y + 2.2), qq, new THREE.Vector3(16, 3.2, 1))
      garageGlow.setMatrixAt(i, m4)
    }
    this.group.add(garages, garageGlow)

    // muros com faixa luminosa
    const wallMat = new THREE.MeshStandardMaterial({ color: '#11161a', roughness: 0.8, side: THREE.DoubleSide })
    this.wall(W + 9, 1.1, wallMat)
    // lado do pit: o muro abre para dar lugar ao pit lane e às garagens
    const pe = this.idxOf(d.pit.entry), px = this.idxOf(d.pit.exit), ramp = 25
    this.wall((i) => {
      const inPit = (j: number) => j >= pe || j <= px
      const distIn = inPit(i) ? Math.min(i >= pe ? i - pe : i + this.n - pe, i <= px ? px - i : this.n) : 0
      const f = Math.min(1, distIn / ramp)
      return -W - 9 + (d.pit_offset - 16 + W + 9) * f
    }, 1.1, wallMat)
    const strip = new THREE.MeshBasicMaterial({ color: '#e0231c' })
    this.ribbon(W + 8.9, W + 9.05, 1.12, strip)

    // postes de iluminação (InstancedMesh) — o "lantern" do Kage, em versão circuito noturno
    const every = Math.round(110 / d.step_m)
    const count = Math.floor(this.n / every)
    const poles = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.15, 0.2, 14, 6), new THREE.MeshStandardMaterial({ color: '#1a1f24' }), count)
    const lamps = new THREE.InstancedMesh(new THREE.BoxGeometry(2.2, 0.35, 0.8), new THREE.MeshBasicMaterial({ color: '#ffe8c8' }), count)
    for (let i = 0; i < count; i++) {
      this.at(i * every * d.step_m, W + 13, pos, dir)
      m4.makeTranslation(pos.x, pos.y + 7, pos.z)
      poles.setMatrixAt(i, m4)
      m4.makeTranslation(pos.x, pos.y + 14, pos.z)
      lamps.setMatrixAt(i, m4)
      if (i % 4 === 0) this.tvCams.push(pos.clone().setY(pos.y + 9))
    }
    this.group.add(poles, lamps)

    // arquibancadas na reta principal
    const stands = new THREE.InstancedMesh(boxGeo, new THREE.MeshStandardMaterial({ color: '#161c21', roughness: 0.9 }), 40)
    const crowdPos: number[] = []
    for (let i = 0; i < 40; i++) {
      const s = -260 + (i % 20) * 34, tier = Math.floor(i / 20)
      this.at(s, W + 26 + tier * 6, pos, dir)
      q.setFromUnitVectors(new THREE.Vector3(0, 0, 1), dir)
      m4.compose(pos.clone().setY(pos.y + 2 + tier * 4), q, new THREE.Vector3(6, 4 + tier * 8, 32))
      stands.setMatrixAt(i, m4)
      for (let c = 0; c < 40; c++) {
        crowdPos.push(pos.x + (Math.random() - 0.5) * 24 * dir.x + (Math.random() - 0.5) * 3,
          pos.y + 4.5 + tier * 8 + Math.random() * 2, pos.z + (Math.random() - 0.5) * 24 * dir.z + (Math.random() - 0.5) * 3)
      }
    }
    const crowd = new THREE.BufferGeometry()
    crowd.setAttribute('position', new THREE.Float32BufferAttribute(crowdPos, 3))
    this.group.add(stands, new THREE.Points(crowd, new THREE.PointsMaterial({ color: '#ffd9b0', size: 0.5, transparent: true, opacity: 0.7 })))

    // pórticos dos setores
    const sectorColors = ['#e0231c', '#29c4c9', '#c9a24a']
    d.sectors.forEach((s, i) => {
      const mat = new THREE.MeshBasicMaterial({ color: sectorColors[i] })
      this.at(s, 0, pos, dir)
      const gate = new THREE.Group()
      const left = new THREE.Vector3(), right = new THREE.Vector3()
      this.at(s, W + 2, left, dir); this.at(s, -W - 2, right, dir)
      for (const p of [left, right]) {
        const post = new THREE.Mesh(new THREE.BoxGeometry(0.4, 8, 0.4), new THREE.MeshStandardMaterial({ color: '#1a1f24' }))
        post.position.set(p.x, p.y + 4, p.z)
        gate.add(post)
      }
      const bar = new THREE.Mesh(new THREE.BoxGeometry(left.distanceTo(right), 0.35, 0.35), mat)
      bar.position.set(pos.x, pos.y + 8, pos.z)
      bar.lookAt(left.x, pos.y + 8, left.z)
      bar.rotateY(Math.PI / 2)
      gate.add(bar)
      this.group.add(gate)
    })

    // árvores (InstancedMesh) fora da pista
    const trees = new THREE.InstancedMesh(new THREE.ConeGeometry(4, 13, 6), new THREE.MeshStandardMaterial({ color: '#0f2019', roughness: 1, flatShading: true }), 900)
    const rng = (() => { let s = 7; return () => (s = (s * 16807) % 2147483647) / 2147483647 })()
    let placed = 0
    const probe = this.p.filter((_, i) => i % 4 === 0)
    for (let tries = 0; placed < 900 && tries < 9000; tries++) {
      const x = this.center.x + (rng() - 0.5) * this.radius * 3.2
      const z = this.center.z + (rng() - 0.5) * this.radius * 3.2
      let min = Infinity
      for (const p of probe) { const dd = (p.x - x) ** 2 + (p.z - z) ** 2; if (dd < min) min = dd }
      if (min < 70 ** 2) continue
      const sc = 0.6 + rng() * 1.1
      m4.compose(new THREE.Vector3(x, GROUND_Y + 6.5 * sc, z), new THREE.Quaternion(), new THREE.Vector3(sc, sc, sc))
      trees.setMatrixAt(placed++, m4)
    }
    trees.count = placed
    this.group.add(trees)
  }
}
