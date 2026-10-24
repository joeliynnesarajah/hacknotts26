"""
PERSON 1 — Finding an item's main colors with KMeans (scikit-learn).

Only looks at visible (non-transparent) pixels, so run this AFTER background removal.
"""
from typing import List

import numpy as np
from PIL import Image
from sklearn.cluster import KMeans


def dominant_colors(img: Image.Image, k: int = 3, min_share: float = 0.12) -> List[str]:
    rgba = np.array(img.convert("RGBA").resize((120, 120)))
    pixels = rgba[rgba[..., 3] > 128][:, :3]
    if len(pixels) < k:
        return ["#808080"]

    km = KMeans(n_clusters=k, n_init=5, random_state=0).fit(pixels)
    counts = np.bincount(km.labels_, minlength=k)
    order = np.argsort(-counts)
    total = counts.sum()
    hexes = []
    for idx in order:
        if counts[idx] / total < min_share:
            continue
        r, g, b = km.cluster_centers_[idx].astype(int)
        hexes.append(f"#{r:02x}{g:02x}{b:02x}")
    return hexes or ["#808080"]
