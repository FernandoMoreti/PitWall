"""Circuito PITWALL — traçado original, fonte única para o simulador e o frontend.

A pista é uma spline Catmull-Rom fechada passando pelos pontos de controle,
reamostrada a cada 1 m. Daí saem a curvatura, o perfil de velocidade alvo
(limite de aderência lateral + aceleração/frenagem), as zonas de DRS, os
setores e a janela do pit lane.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

SCALE = 1.2
CONTROL = [
    (0, 0), (450, 0), (760, -30), (880, 60), (840, 200), (660, 260), (560, 380),
    (620, 520), (800, 560), (900, 680), (820, 820), (600, 860), (380, 760),
    (240, 800), (60, 880), (-140, 820), (-230, 640), (-120, 480), (-60, 330),
    (-200, 200), (-180, 60),
]

WIDTH = 14.0          # m
PIT_OFFSET = -18.0    # deslocamento lateral do pit lane (lado direito)
V_MAX = 93.0          # m/s (~335 km/h)
A_MECH = 14.0         # m/s² aderência mecânica
A_AERO = 30.0         # m/s² extra de downforce em Vmax
A_BRAKE = 38.0        # m/s²
DS = 1.0              # m


def _catmull_closed(points: np.ndarray, per_seg: int = 80) -> np.ndarray:
    n = len(points)
    out = []
    t = np.linspace(0, 1, per_seg, endpoint=False)[:, None]
    for i in range(n):
        p0, p1, p2, p3 = (points[(i + k - 1) % n] for k in range(4))
        a = 2 * p1
        b = p2 - p0
        c = 2 * p0 - 5 * p1 + 4 * p2 - p3
        d = -p0 + 3 * p1 - 3 * p2 + p3
        out.append(0.5 * (a + b * t + c * t ** 2 + d * t ** 3))
    return np.vstack(out)


@dataclass
class Track:
    s: np.ndarray        # distância acumulada (m)
    x: np.ndarray
    z: np.ndarray
    y: np.ndarray        # elevação (m)
    nx: np.ndarray       # normal à esquerda
    nz: np.ndarray
    k: np.ndarray        # curvatura com sinal (1/m), >0 = curva à esquerda
    v: np.ndarray        # velocidade alvo (m/s)
    length: float
    drs_zones: list[tuple[float, float]]
    sectors: list[float]
    pit_entry: float
    pit_box: float
    pit_exit: float

    def idx(self, s: float) -> int:
        return int(s / DS) % len(self.s)

    def in_drs(self, s: float) -> bool:
        return any((a <= s <= b) if a <= b else (s >= a or s <= b) for a, b in self.drs_zones)

    def sector(self, s: float) -> int:
        return 1 if s < self.sectors[1] else (2 if s < self.sectors[2] else 3)

    def to_json(self, step: int = 4) -> dict:
        sl = slice(None, None, step)
        r = lambda a: np.round(a[sl], 2).tolist()  # noqa: E731
        return {
            "length": round(self.length, 1),
            "width": WIDTH,
            "pit_offset": PIT_OFFSET,
            "step_m": step * DS,
            "s": r(self.s), "x": r(self.x), "y": r(self.y), "z": r(self.z),
            "nx": np.round(self.nx[sl], 4).tolist(), "nz": np.round(self.nz[sl], 4).tolist(),
            "k": np.round(self.k[sl], 5).tolist(),
            "v_kph": np.round(self.v[sl] * 3.6, 1).tolist(),
            "drs_zones": self.drs_zones,
            "sectors": self.sectors,
            "pit": {"entry": self.pit_entry, "box": self.pit_box, "exit": self.pit_exit},
        }


@lru_cache(maxsize=1)
def build() -> Track:
    pts = np.array(CONTROL, dtype=float) * SCALE
    dense = _catmull_closed(pts)
    seg = np.linalg.norm(np.diff(np.vstack([dense, dense[:1]]), axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    length = float(cum[-1])
    s = np.arange(0, length, DS)
    closed = np.vstack([dense, dense[:1]])
    x = np.interp(s, cum, closed[:, 0])
    z = np.interp(s, cum, closed[:, 1])

    # tangente, normal e curvatura (com wrap)
    dx = np.gradient(np.concatenate([x[-3:], x, x[:3]]))[3:-3]
    dz = np.gradient(np.concatenate([z[-3:], z, z[:3]]))[3:-3]
    heading = np.arctan2(dz, dx)
    norm = np.hypot(dx, dz)
    nx, nz = -dz / norm, dx / norm
    dh = np.diff(np.concatenate([heading, heading[:1]]))
    dh = (dh + np.pi) % (2 * np.pi) - np.pi
    kernel = np.ones(25) / 25
    k = np.convolve(np.concatenate([dh[-12:], dh, dh[:12]]), kernel, mode="same")[12:-12] / DS

    # perfil de velocidade: limite lateral, depois passes de aceleração e frenagem (2 voltas p/ fechar)
    # aderência lateral cresce com a velocidade (downforce): a_lat = A_MECH + A_AERO·(v/Vmax)²
    ak = np.abs(k) - A_AERO / V_MAX ** 2
    v = np.where(ak > 0, np.sqrt(A_MECH / np.maximum(ak, 1e-9)), V_MAX)
    v = np.minimum(V_MAX, v)
    n = len(v)
    for _ in range(2):
        for i in range(1, 2 * n):
            a, b = (i - 1) % n, i % n
            acc = 3.0 + 10.0 * (1 - v[a] / V_MAX)
            v[b] = min(v[b], np.sqrt(v[a] ** 2 + 2 * acc * DS))
        for i in range(2 * n - 2, -1, -1):
            a, b = (i + 1) % n, i % n
            v[b] = min(v[b], np.sqrt(v[a] ** 2 + 2 * A_BRAKE * DS))

    y = 6.0 * np.sin(2 * np.pi * s / length * 2 + 0.6) + 3.0 * np.sin(2 * np.pi * s / length * 5)

    # zonas de DRS: trechos quase retos com mais de 450 m
    straight = np.abs(k) < 0.0018
    zones: list[tuple[float, float, int]] = []
    i0 = int(np.argmin(straight))  # começa a varredura numa curva para não cortar a reta no wrap
    start = None
    for j in range(n + 1):
        i = (i0 + j) % n
        flag = bool(straight[i]) and j < n
        if flag and start is None:
            start = j
        elif not flag and start is not None:
            if j - start > 450:
                zones.append((float((i0 + start + 90) % n), float((i0 + j - 20) % n), j - start))
            start = None
    zones = sorted(zones, key=lambda t: -t[2])[:2]

    return Track(
        s=s, x=x, z=z, y=y, nx=nx, nz=nz, k=k, v=v, length=length,
        drs_zones=[(round(a, 1), round(b, 1)) for a, b, _ in sorted(zones)],
        sectors=[0.0, round(length / 3, 1), round(2 * length / 3, 1)],
        pit_entry=round(length - 320, 1), pit_box=60.0, pit_exit=300.0,
    )
