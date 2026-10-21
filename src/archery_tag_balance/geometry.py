"""Small continuous-collision and ballistic helpers. All lengths are metres."""

from math import atan, cos, hypot, sin, sqrt


def segment_box(p, q, lo, hi):
    """Earliest fraction in [0, 1] of a segment touching an axis-aligned box."""
    enter, leave = 0.0, 1.0
    for a, b, lower, upper in zip(p, q, lo, hi):
        delta = b - a
        if abs(delta) < 1e-12:
            if a < lower or a > upper:
                return None
        else:
            t0, t1 = (lower - a) / delta, (upper - a) / delta
            if t0 > t1:
                t0, t1 = t1, t0
            enter, leave = max(enter, t0), min(leave, t1)
            if enter > leave:
                return None
    return enter


def segment_cylinder(p, q, center0, center1, radius, height):
    """Swept arrow point against a translating upright finite cylinder."""
    rx, ry = p[0] - center0[0], p[1] - center0[1]
    dx = q[0] - p[0] - (center1[0] - center0[0])
    dy = q[1] - p[1] - (center1[1] - center0[1])
    a, b, c = dx * dx + dy * dy, 2 * (rx * dx + ry * dy), rx * rx + ry * ry - radius * radius
    if a < 1e-12:
        if c > 0:
            return None
        t0, t1 = 0.0, 1.0
    else:
        disc = b * b - 4 * a * c
        if disc < 0:
            return None
        t0, t1 = max(0.0, (-b - sqrt(disc)) / (2 * a)), min(1.0, (-b + sqrt(disc)) / (2 * a))
    dz = q[2] - p[2]
    if abs(dz) < 1e-12:
        if not 0 <= p[2] <= height:
            return None
    else:
        z0, z1 = -p[2] / dz, (height - p[2]) / dz
        if z0 > z1:
            z0, z1 = z1, z0
        t0, t1 = max(t0, z0), min(t1, z1)
    return t0 if t0 <= t1 else None


def ballistic_velocity(origin, target, speed, gravity):
    """Low-angle fixed-speed trajectory, or None if the point is unreachable."""
    dx, dy, dz = (b - a for a, b in zip(origin, target))
    distance = hypot(dx, dy)
    if distance < 1e-8:
        return None
    v2 = speed * speed
    disc = v2 * v2 - gravity * (gravity * distance * distance + 2 * dz * v2)
    if disc < 0:
        return None
    pitch = atan((v2 - sqrt(disc)) / (gravity * distance))
    horizontal = speed * cos(pitch)
    return (horizontal * dx / distance, horizontal * dy / distance, speed * sin(pitch))


def lerp(p, q, fraction):
    return tuple(a + fraction * (b - a) for a, b in zip(p, q))
