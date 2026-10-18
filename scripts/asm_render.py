"""asm_render.py -- a picture of the assembly with connector axis markers.

Two panels (iso, top), each part flat-shaded in its own colour, every
connector drawn as an axis triad (x red, y green, z blue) with its name.
Tessellated meshes and markers share one orthographic camera, so a marker is
exactly where the connector is. Pillow only; rendered at 2x and downsampled.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

VIEWS = {"iso": ((1, -1, 1), (0, 0, 1)), "top": ((0, 0, 1), (0, 1, 0))}
AXIS_RGB = [(220, 30, 30), (20, 160, 40), (30, 70, 230)]
SS = 2                      # supersampling


def _camera(view_dir, up):
    v = np.asarray(view_dir, float)
    v /= np.linalg.norm(v)                       # towards the camera
    right = np.cross(np.asarray(up, float), v)
    right /= np.linalg.norm(right)
    upv = np.cross(v, right)
    return right, upv, v


def _meshes(solved):
    out = []
    for name, inst in solved.instances.items():
        verts, tris = solved.placed_shape(name).tessellate(0.2, 0.3)
        V = np.array([(p.X, p.Y, p.Z) for p in verts], float)
        out.append((name, V, np.asarray(tris, int), inst.color))
    return out


def _markers(solved, length):
    out = []
    for name, inst in solved.instances.items():
        for cn, f in inst.connectors.items():
            W = solved.placement(name) @ f.matrix()
            out.append((f"{name}.{cn}", W[:3, 3], [W[:3, k] * length for k in range(3)]))
    return out


def _panel(meshes, markers, view, size, font):
    right, upv, v = _camera(*VIEWS[view])
    w, h = size
    img = Image.new("RGB", size, (250, 250, 250))
    dr = ImageDraw.Draw(img)

    pts = [V for _, V, _, _ in meshes] + [np.array([o + a for a in ax] + [o])
                                          for _, o, ax in markers]
    allp = np.vstack(pts)
    u, t = allp @ right, allp @ upv
    span = max(u.max() - u.min(), t.max() - t.min(), 1e-9)
    margin = 0.08 * min(w, h)
    scale = (min(w, h) - 2 * margin) / span
    cu, ct = (u.max() + u.min()) / 2, (t.max() + t.min()) / 2

    def proj(p):
        return (w / 2 + (p @ right - cu) * scale, h / 2 - (p @ upv - ct) * scale)

    light = v + np.array([0.3, 0.2, 0.6])
    light /= np.linalg.norm(light)
    polys = []
    for _, V, T, color in meshes:
        tri = V[T]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        nn = np.linalg.norm(n, axis=1)
        keep = nn > 1e-12
        n[keep] /= nn[keep, None]
        shade = 0.35 + 0.65 * np.abs(n @ light)
        depth = tri.mean(axis=1) @ v
        base = np.array(color) * 255
        for k in np.nonzero(keep)[0]:
            c = tuple(int(x) for x in np.clip(base * shade[k] + 25, 0, 255))
            polys.append((depth[k], [proj(p) for p in tri[k]], c))
    polys.sort(key=lambda x: x[0])
    for _, poly, c in polys:
        dr.polygon(poly, fill=c, outline=c)

    for label, o, axes in markers:
        po = proj(o)
        for k, a in enumerate(axes):
            if np.linalg.norm(np.cross(a, v)) < 1e-9 * max(np.linalg.norm(a), 1):
                dr.ellipse([po[0] - 3 * SS, po[1] - 3 * SS, po[0] + 3 * SS, po[1] + 3 * SS],
                           outline=AXIS_RGB[k], width=2 * SS)    # axis points at us
                continue
            dr.line([po, proj(o + a)], fill=AXIS_RGB[k], width=2 * SS)
        dr.ellipse([po[0] - 2 * SS, po[1] - 2 * SS, po[0] + 2 * SS, po[1] + 2 * SS],
                   fill=(0, 0, 0))
        dr.text((po[0] + 4 * SS, po[1] + 2 * SS), label, fill=(20, 20, 20), font=font)
    dr.text((10 * SS, 8 * SS), view, fill=(90, 90, 90), font=font)
    return img


def _font(px):
    for name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def render(solved, path, size=(1400, 700)):
    meshes = _meshes(solved)
    allv = np.vstack([V for _, V, _, _ in meshes])
    diag = float(np.linalg.norm(allv.max(0) - allv.min(0)))
    markers = _markers(solved, 0.07 * diag)
    W, H = size[0] * SS, size[1] * SS
    font = _font(11 * SS)
    sheet = Image.new("RGB", (W, H), (250, 250, 250))
    for i, view in enumerate(VIEWS):
        sheet.paste(_panel(meshes, markers, view, (W // 2, H), font), (i * W // 2, 0))
    dr = ImageDraw.Draw(sheet)
    dr.line([(W // 2, 0), (W // 2, H)], fill=(210, 210, 210), width=SS)
    title = f"{solved.asm.name}  -  {len(solved.warnings)} warning(s)  -  x red, y green, z blue"
    dr.text((10 * SS, H - 22 * SS), title, fill=(60, 60, 60), font=font)
    sheet.resize(size, Image.LANCZOS).save(path)
