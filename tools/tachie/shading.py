# -*- coding: utf-8 -*-
"""Unified cel-shading primitives: one light, local scale, structural bands.

Every shadow plane is derived from the silhouette geometry instead of the
source-image luminance.  Band widths scale with the local inscribed radius of
the connected component, so narrow hair locks are not swallowed by a band
computed from the whole material bounding box.
"""
import numpy as np
from scipy.ndimage import (binary_closing, binary_dilation,
                           binary_fill_holes, distance_transform_edt,
                           gaussian_filter, label, maximum_filter)

LIGHT_PRESETS = {"upper-left": np.array([-0.70710678, -0.70710678])}


def light_vector(name="upper-left"):
    """Return the unit vector pointing from the surface toward the light."""
    if name not in LIGHT_PRESETS:
        raise ValueError(f"未知光源方向: {name}")
    return LIGHT_PRESETS[name].copy()


def ink_mask(lum, threshold=0.22, grow=2):
    """Line-art proxy used to keep luminance statistics off anti-aliased ink."""
    ink = lum < threshold
    if grow > 0:
        ink = binary_dilation(ink, iterations=int(grow))
    return ink


def local_radius(mask):
    """Per-pixel inscribed radius, propagated from the medial skeleton."""
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return np.zeros(mask.shape, dtype=np.float64)
    dist = distance_transform_edt(mask)
    peak = maximum_filter(dist, size=5, mode="nearest")
    skel = mask & (dist >= peak - 1e-6) & (dist > 0)
    if not skel.any():
        skel = mask & (dist >= float(dist.max()) - 1e-6)
    _, indices = distance_transform_edt(
        ~skel, return_distances=True, return_indices=True)
    radius = dist[indices[0], indices[1]]
    return np.maximum(radius, 1.0)


def away_side(mask, light, sigma=1.0):
    """Boolean map of the silhouette side whose outward normal faces away."""
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return np.zeros(mask.shape, dtype=bool)
    dist = distance_transform_edt(mask)
    gy, gx = np.gradient(gaussian_filter(dist, sigma))
    # The distance field grows inward, so its gradient points inward.  The
    # outward normal is -grad; the side facing away satisfies grad . L > 0.
    return (gx * light[0] + gy * light[1]) > 0


def _keep_components(mask, min_px):
    if not mask.any():
        return mask
    lab, n = label(mask)
    if n == 0:
        return mask
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    keep_ids = np.where(sizes >= max(int(min_px), 1))[0]
    keep_ids = keep_ids[keep_ids > 0]
    return np.isin(lab, keep_ids)


def directional_bands(mask, light, ratios, min_px=12):
    """Return nested (mid, deep, core) bands on the side away from the light.

    The distance field is computed on the hole-filled silhouette so that
    interior line art / eyes / buttons do not shrink the local radius and turn
    every shadow band into a hairline.
    """
    mask = np.asarray(mask, dtype=bool)
    empty = np.zeros(mask.shape, dtype=bool)
    if not mask.any():
        return empty, empty.copy(), empty.copy()
    # Interior line art and eye/mouth features split the material mask into
    # thin bands; closing 5x5 first restores the real silhouette thickness.
    solid = binary_fill_holes(binary_closing(
        mask, structure=np.ones((5, 5), dtype=bool)))
    radius = local_radius(solid)
    dist = distance_transform_edt(solid)
    away = away_side(solid, light)
    bands = []
    previous = mask
    for ratio in ratios:
        limit = np.maximum(1.0, float(ratio) * radius)
        band = mask & away & (dist <= limit)
        band = _keep_components(band, min_px) & previous
        bands.append(band)
        previous = band
    while len(bands) < 3:
        bands.append(empty.copy())
    return bands[0], bands[1], bands[2]


def field_bands(field, mask, thresholds=(0.35, 0.80), min_px=12):
    """Quantize a continuous illumination field into nested cel-shading bands."""
    mask = np.asarray(mask, dtype=bool)
    field = np.asarray(field, dtype=np.float64)
    empty = np.zeros(mask.shape, dtype=bool)
    bands = []
    previous = mask
    for threshold in thresholds:
        band = mask & (field >= float(threshold))
        band = _keep_components(band, min_px) & previous
        bands.append(band)
        previous = band
    while len(bands) < 3:
        bands.append(empty.copy())
    return bands[0], bands[1], bands[2]


def silhouette(mask):
    """Filled outline used for horizontal cross-sections."""
    return binary_fill_holes(binary_closing(
        np.asarray(mask, dtype=bool), structure=np.ones((5, 5), dtype=bool)))


def _run_shade(run, center, radius, horizontal):
    normal_x = (run - center) / radius
    shade = np.clip(horizontal * normal_x, 0.0, 1.0)
    # Smooth penumbra in the field; quantization happens only in field_bands,
    # retaining a hard umbra inside a softer mid band.
    return shade * shade * (3.0 - 2.0 * shade)


def _nearest_long_run(rows, y, run, min_len=12, span=8):
    """Parameters of the closest long run overlapping the given short run."""
    for distance in range(1, span + 1):
        for row in (y - distance, y + distance):
            candidates = rows.get(row)
            if not candidates:
                continue
            for other in candidates:
                if len(other) < min_len:
                    continue
                if other[-1] < run[0] or other[0] > run[-1]:
                    continue
                center = 0.5 * (other[0] + other[-1])
                radius = max(0.5 * (other[-1] - other[0]), 1.0)
                return center, radius
    return None


def cylindrical_field(mask, light):
    """Continuous right/left cylindrical shading from horizontal cross-sections.

    Each horizontal run is a separate cylinder cross-section.  Consequently
    two legs or a sleeve and a torso receive their own back-lit band instead of
    sharing one bounding-box-wide outline shadow.  Interior material holes do
    not reset the cross-section, preserving a continuous field from chest to
    waist and from thigh to calf.
    """
    mask = np.asarray(mask, dtype=bool)
    field = np.zeros(mask.shape, dtype=np.float64)
    if not mask.any():
        return field
    solid = silhouette(mask)
    lab, count = label(solid)
    horizontal = 1.0 if float(light[0]) < 0 else -1.0
    rows = {}
    for component_id in range(1, count + 1):
        component = lab == component_id
        for y in np.unique(np.where(component)[0]):
            xs = np.flatnonzero(component[y])
            if not len(xs):
                continue
            splits = np.flatnonzero(np.diff(xs) > 1) + 1
            rows.setdefault(int(y), []).extend(np.split(xs, splits))
    for y, runs in rows.items():
        for run in runs:
            if len(run) <= 2:
                field[y, run] = 0.5
                continue
            if len(run) < 12:
                # A silhouette sliver cannot carry a stable normal: inherit the
                # nearest long section so a garment seam never reads as a
                # lighting break (v10.2 ③).
                donor = _nearest_long_run(rows, y, run)
                if donor is not None:
                    field[y, run] = _run_shade(
                        run, donor[0], donor[1], horizontal)
                    continue
            center = 0.5 * (run[0] + run[-1])
            radius = max(0.5 * (run[-1] - run[0]), 1.0)
            field[y, run] = _run_shade(run, center, radius, horizontal)
    return field


def continuous_bands(mask, light, thresholds=(0.35, 0.80), min_px=12):
    """Cylindrical body-space bands, clipped to the garment/skin silhouette."""
    field = cylindrical_field(mask, light)
    return field_bands(field, mask, thresholds, min_px=min_px)


def ellipsoid_field(mask, cx, cy, rx, ry, light, terminator=0.40):
    """Return a continuous back-lit field on an ellipsoidal body protrusion.

    The surface normal includes the viewer-facing Z component.  Increasing
    ``terminator`` with bust size moves the shadow boundary toward the lobe
    centre, so a larger protrusion produces a genuinely larger shadow rather
    than a thicker outline.
    """
    mask = np.asarray(mask, dtype=bool)
    field = np.zeros(mask.shape, dtype=np.float64)
    if not mask.any() or rx <= 0 or ry <= 0:
        return field
    yy, xx = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
    nx = (xx - float(cx)) / float(rx)
    ny = (yy - float(cy)) / float(ry)
    radius2 = nx * nx + ny * ny
    lobe = mask & (radius2 <= 1.0)
    if not lobe.any():
        return field
    nz = np.sqrt(np.clip(1.0 - radius2, 0.0, 1.0))
    light3 = np.array([light[0], light[1], 0.9], dtype=np.float64)
    light3 /= np.linalg.norm(light3)
    illumination = nx * light3[0] + ny * light3[1] + nz * light3[2]
    field[lobe] = np.clip(float(terminator) - illumination[lobe], 0.0, 1.0)
    return field


def cast_shadow(source, receiver, light, depth):
    """Project an occluder along the light direction onto a receiver."""
    source = np.asarray(source, dtype=bool)
    receiver = np.asarray(receiver, dtype=bool)
    if not source.any() or not receiver.any():
        return np.zeros(source.shape, dtype=bool)
    dx = int(round(-float(light[0]) * float(depth)))
    dy = int(round(-float(light[1]) * float(depth)))
    if dx == 0 and dy == 0:
        return np.zeros(source.shape, dtype=bool)
    shifted = np.zeros_like(source)
    h, w = source.shape
    ys0, ys1 = max(0, dy), min(h, h + dy)
    xs0, xs1 = max(0, dx), min(w, w + dx)
    shifted[ys0:ys1, xs0:xs1] = source[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return shifted & receiver & ~source
