"""Features da IA: um único código, usado no treino (ml-worker) e na inferência ao vivo.

Entrada: matriz (n, 5) com as leituras de um equipamento em ordem de tempo, nas
colunas de SIGNALS. Saída: uma linha de features por leitura, calculada só com
as WINDOW leituras anteriores (inclusive a atual) — nunca olha para o futuro.
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

SIGNALS = ("pu_vibration", "oil_temp", "oil_pressure", "engine_temp", "rpm")
WINDOW = 30
NAMES = [f"{s}_{stat}" for s in SIGNALS for stat in ("mean", "std", "max")] + ["oil_minus_engine_mean"]


def _ffill(arr: np.ndarray) -> np.ndarray:
    """Leituras faltantes (NaN) recebem o último valor válido."""
    out = arr.astype(np.float64, copy=True)
    for j in range(out.shape[1]):
        col = out[:, j]
        mask = np.isnan(col)
        if not mask.any():
            continue
        idx = np.where(~mask, np.arange(len(col)), 0)
        np.maximum.accumulate(idx, out=idx)
        col[:] = col[idx]
        if np.isnan(col[0]):                      # começo sem valor: usa o primeiro válido
            first = np.nanmean(col) if (~np.isnan(col)).any() else 0.0
            col[np.isnan(col)] = first
    return out


def build(arr: np.ndarray) -> np.ndarray:
    """(n, 5) -> (n, len(NAMES)). Janela só com o passado."""
    x = _ffill(np.asarray(arr, dtype=np.float64))
    padded = np.pad(x, ((WINDOW - 1, 0), (0, 0)), mode="edge")      # início: repete a 1ª leitura
    win = sliding_window_view(padded, WINDOW, axis=0)               # (n, 5, WINDOW)
    mean, std, mx = win.mean(axis=2), win.std(axis=2), win.max(axis=2)
    feats = np.stack([mean, std, mx], axis=2).reshape(len(x), -1)   # ordem igual a NAMES
    delta = (x[:, 1] - x[:, 3])
    delta_mean = sliding_window_view(np.pad(delta, (WINDOW - 1, 0), mode="edge"), WINDOW).mean(axis=1)
    return np.column_stack([feats, delta_mean]).astype(np.float32)


def last_row(arr: np.ndarray) -> np.ndarray:
    """Inferência: features só da leitura mais recente (mesmo cálculo do treino)."""
    tail = np.asarray(arr, dtype=np.float64)[-WINDOW:]
    return build(tail)[-1:]
