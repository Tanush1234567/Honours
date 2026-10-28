"""Cell-integrated Gaussian deposition with conservative integer-litre credit.

The origin is the footprint CENTRE. The hexagon retains the old length/width
parameters. Its longitudinal/lateral density is normalised over the hexagon;
cell polygon intersections bound numerical integration of that density.
Water outside the raster is lost, not redistributed.
"""
from functools import lru_cache
import math
from shapely.geometry import Polygon, box
from scipy.integrate import quad
from scipy.special import ndtr


def footprint_polygon(heading_deg, k, height_m, ramp_m, plateau_m):
    width = k * height_m ** 1.5
    half_length = ramp_m + plateau_m / 2
    half_plateau = plateau_m / 2
    # (along-track, cross-track); world coordinates are east/north.
    points = [(-half_length, 0), (-half_plateau, width / 2),
              (half_plateau, width / 2), (half_length, 0),
              (half_plateau, -width / 2), (-half_plateau, -width / 2)]
    theta = math.radians(heading_deg)
    return Polygon([(u * math.sin(theta) + v * math.cos(theta),
                     u * math.cos(theta) - v * math.sin(theta)) for u, v in points])


def _integrated_fraction(clipped, heading, width, ramp, plateau):
    """Integrate lambda(u)*Normal(v; 0, lambda(u)/6) over a clipped cell.

    Lateral integration is analytic (normal CDF); along-track integration uses
    adaptive quadrature split at every polygon vertex and profile breakpoint.
    The footprint truncates laterally at +/-3 sigma; its normaliser includes
    that truncation. This is density, never a probability evaluated at a point.
    """
    theta = math.radians(heading)
    points = [(x * math.sin(theta) + y * math.cos(theta),
               x * math.cos(theta) - y * math.sin(theta))
              for x, y in list(clipped.exterior.coords)[:-1]]
    edges = list(zip(points, points[1:] + points[:1]))
    lo, hi = min(p[0] for p in points), max(p[0] for p in points)
    breaks = sorted(set([lo, hi] + [p[0] for p in points] +
                        [x for x in (-plateau / 2, plateau / 2) if lo < x < hi]))
    half_length = ramp + plateau / 2
    normalizer = width * (ramp + plateau) * math.erf(3 / math.sqrt(2))

    def integrand(u):
        lam = width * min(1.0, max(0.0, (half_length - abs(u)) / ramp))
        if lam <= 0:
            return 0.0
        crossings = [v1 + (u - u1) * (v2 - v1) / (u2 - u1)
                     for (u1, v1), (u2, v2) in edges
                     if u1 != u2 and min(u1, u2) <= u <= max(u1, u2)]
        if len(crossings) < 2:
            return 0.0
        sigma = lam / 6
        return lam * (ndtr(max(crossings) / sigma) - ndtr(min(crossings) / sigma))

    mass = sum(quad(integrand, a, b, epsabs=1e-9, epsrel=1e-9)[0]
               for a, b in zip(breaks, breaks[1:]) if b - a > 1e-12)
    return max(0.0, min(1.0, mass / normalizer))


@lru_cache(maxsize=64)
def _stencil(cell_x, cell_y, heading, k, height, ramp, plateau, volume):
    polygon = footprint_polygon(heading, k, height, ramp, plateau)
    minx, miny, maxx, maxy = polygon.bounds
    reach_c = math.ceil(max(abs(minx), abs(maxx)) / cell_x + 0.5)
    reach_r = math.ceil(max(abs(miny), abs(maxy)) / cell_y + 0.5)
    result = []
    for dr in range(-reach_r, reach_r + 1):
        for dc in range(-reach_c, reach_c + 1):
            x, y = dc * cell_x, -dr * cell_y
            clipped = polygon.intersection(box(x - cell_x / 2, y - cell_y / 2,
                                               x + cell_x / 2, y + cell_y / 2))
            if clipped.area <= 1e-12:
                continue
            fraction = _integrated_fraction(clipped, heading, k * height ** 1.5, ramp, plateau)
            # Round down: credited water can never exceed discharged water.
            litres = math.floor(volume * fraction)
            if litres > 0:
                result.append((dr, dc, litres))
    if sum(v for _, _, v in result) > volume:
        raise AssertionError("Deposition violates water conservation")
    return tuple(result)


def compute_drop_footprint(row, col, georef, settings):
    """Return {(affected_row, affected_col): delivered_litres}."""
    stencil = _stencil(georef["cell_size_x"], georef["cell_size_y"],
                       settings.drop_heading_deg % 360, settings.drop_k,
                       settings.drop_height_m, settings.drop_ramp_m,
                       settings.drop_plateau_m, settings.drop_volume_l)
    return {(row + dr, col + dc): litres for dr, dc, litres in stencil
            if 0 <= row + dr < georef["rows"] and 0 <= col + dc < georef["cols"]}
