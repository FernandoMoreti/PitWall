import * as THREE from 'three'

/** Rampa térmica: frio (azul) → janela ideal (verde) → quente (âmbar) → crítico (vermelho). */
const STOPS: [number, THREE.Color][] = [
  [0.0, new THREE.Color('#2f6dff')],
  [0.35, new THREE.Color('#29c4c9')],
  [0.5, new THREE.Color('#4fd18b')],
  [0.72, new THREE.Color('#f2b33d')],
  [1.0, new THREE.Color('#ff2a1f')],
]

export function ramp(x: number, out = new THREE.Color()): THREE.Color {
  const v = Math.min(1, Math.max(0, x))
  for (let i = 1; i < STOPS.length; i++) {
    const [b, cb] = STOPS[i]
    const [a, ca] = STOPS[i - 1]
    if (v <= b) return out.copy(ca).lerp(cb, (v - a) / (b - a))
  }
  return out.copy(STOPS[STOPS.length - 1][1])
}

export const norm = (v: number, lo: number, hi: number) => (v - lo) / (hi - lo)

/** Temperatura do pneu: 60 °C = 0, 95 °C ≈ ideal, 130 °C = 1 */
export const tyreHeat = (c: number) => norm(c, 60, 130)
/** Motor: 80 °C = 0, ~100 = ideal, 125 = 1 */
export const engineHeat = (c: number) => norm(c, 75, 125)

/** Brilho incandescente do disco de freio (corpo negro simplificado). */
export function brakeGlow(c: number, out = new THREE.Color()): { color: THREE.Color; intensity: number } {
  const x = Math.min(1, Math.max(0, (c - 420) / 650))
  out.setRGB(1, 0.25 + 0.5 * x * x, 0.05 + 0.2 * x * x * x)
  return { color: out, intensity: x * x * 3 }
}
