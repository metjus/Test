"""Kolíky a otvory na lepenie dielov: návrh polohy (numpy) a vytvorenie/aplikovanie v Blenderi."""
from __future__ import annotations

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

PIN_PROP = "smartcut_pin"


# --------------------------------------------------------------------------- návrh (čistý numpy)


def _min_dist(points: np.ndarray, others: np.ndarray) -> np.ndarray:
    out = np.empty(len(points))
    for s in range(0, len(points), 1024):
        d = np.linalg.norm(points[s : s + 1024, None, :] - others[None], axis=2)
        out[s : s + 1024] = d.min(axis=1)
    return out


def plan_pins(
    cap_pts: np.ndarray, border_pts: np.ndarray, count: int = 0, diameter: float = 0.0, length: float = 0.0, shape: str = "ROUND"
):
    """Kde dať kolíky na plochu rezu. Vráti (stredy, rozmer, dĺžka, najväčší rozmer, ktorý sa na rez zmestí).

    Rozmer je priemer (okrúhly) alebo strana (štvorcový). Ak je `diameter` zadaný, použije sa presne tak,
    ako ho používateľ chce; obmedzí sa len automatická voľba.

    Stredy sú body plochy rezu najďalej od okraja (a od seba). Priemer a dĺžka sa pri 0 zvolia podľa veľkosti plochy.
    """
    cap_pts = np.asarray(cap_pts, dtype=np.float64)
    d_border = _min_dist(cap_pts, np.asarray(border_pts, dtype=np.float64))
    r_in = float(d_border.max())  # polomer najväčšej vpísanej kružnice (približne)
    square = shape == "SQUARE"
    reach = 0.5 * (np.sqrt(2.0) if square else 1.0)  # vzdialenosť od stredu k najvzdialenejšiemu bodu kolíka / rozmer
    max_fit = max(r_in / (2.0 if square else 1.6), 0.05)  # najväčší rozmer, ktorý sa na plochu rezu zmestí
    if diameter > 0:
        dia = float(diameter)  # zadané používateľom: rešpektuj presne
    else:
        dia = min(float(np.clip(0.38 * r_in, min(1.5, 0.38 * r_in), 7.0)), max_fit)
    ln = float(length) if length > 0 else float(min(2.2 * dia, 1.4 * r_in, 12.0))
    n = count if count > 0 else (1 if r_in < 3.0 * dia else 2 if r_in < 5.0 * dia else 3)

    def candidates(margin: float):
        ok = d_border >= dia * reach + margin
        if not ok.any():
            ok = d_border >= d_border.max() * 0.999  # aspoň najlepší bod
        return np.nonzero(ok)[0]

    def farthest_pair(idx):
        """Dvojica bodov s najväčším odstupom (pri veľkom výbere sa hľadá na vzorke)."""
        sub = idx if len(idx) <= 400 else idx[:: max(1, len(idx) // 400)]
        P = cap_pts[sub]
        d = np.linalg.norm(P[:, None, :] - P[None], axis=2)
        i, j = np.unravel_index(int(d.argmax()), d.shape)
        return [int(sub[i]), int(sub[j])], float(d[i, j])

    def pick(margin: float, min_sep: float):
        pool = candidates(margin)
        if n <= 1:
            return [pool[int(d_border[pool].argmax())]]
        # pri dvoch a viacerých kolíkoch nezačínaj v strede: od neho sa druhý nemá kam vzdialiť
        pair, gap = farthest_pair(pool)
        chosen = pair if gap >= min_sep else [pool[int(d_border[pool].argmax())]]
        while len(chosen) < n:
            dist = _min_dist(cap_pts[pool], cap_pts[chosen])
            for k in np.argsort(-(dist + 0.15 * d_border[pool])):
                if dist[k] >= min_sep:
                    chosen.append(pool[k])
                    break
            else:
                break
        return chosen

    chosen = pick(0.8 * dia, 2.5 * dia)  # pohodlný odstup od okraja aj medzi kolíkmi
    if count > 0 and len(chosen) < n:
        # zadaný počet má prednosť: kolíky smú ísť bližšie k okraju aj k sebe, len sa nesmú prekrývať
        chosen = pick(0.25 * dia, 1.25 * dia)
    return cap_pts[chosen], dia, ln, max_fit


# --------------------------------------------------------------------------- meshe


def _prism(bm, size: float, size_tip: float, length: float, shape: str):
    """Hranol alebo valec od z = 0 po z = length; veľkosť dole `size`, hore `size_tip`."""
    if shape == "SQUARE":
        k = np.sqrt(2.0) / 2.0
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=4, radius1=size * k, radius2=size_tip * k, depth=length)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(np.pi / 4, 3, "Z"), verts=bm.verts)  # strany rovnobežne s osami
    else:
        bmesh.ops.create_cone(
            bm, cap_ends=True, cap_tris=False, segments=32, radius1=size / 2, radius2=size_tip / 2, depth=length
        )


def _shell(bm, size: float, size_tip: float, z0: float, z1: float, shape: str):
    """Pridá do bmeshu hranol/valec od z0 po z1; šírka dole `size`, hore `size_tip`."""
    tmp = bmesh.new()
    _prism(tmp, size, size_tip, z1 - z0, shape)
    bmesh.ops.translate(tmp, vec=(0, 0, (z0 + z1) / 2.0), verts=tmp.verts)
    me = bpy.data.meshes.new("tmp_shell")
    tmp.to_mesh(me)
    tmp.free()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)


def peg_width_at(z: float, size: float, length: float, base: float, taper: float) -> float:
    """Šírka kolíka vo výške z (kolík je zrezaný ihlan od -base po +length)."""
    t = (z + base) / max(length + base, 1e-9)
    return size + (size * taper - size) * t


def peg_span(length: float, base: float):
    """Kolík siaha od -base (vo vnútri svojho dielu) po +length (do druhého dielu)."""
    return -base, length


def hole_span(length: float, size: float, clearance: float):
    """Otvor je o kúsok hlbší, aby kolík nedosadol skôr, než sa stretnú plochy rezu."""
    return 0.0, length + max(2.0 * clearance, 0.08 * size)


def peg_mesh(name: str, size: float, length: float, base: float, taper: float, shape: str):
    bm = bmesh.new()
    z0, z1 = peg_span(length, base)
    _shell(bm, size, size * taper, z0, z1, shape)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def hole_mesh(name: str, size: float, length: float, base: float, taper: float, shape: str, clearance: float):
    """Otvor kopíruje skosenie kolíka: o `clearance` širší na každej strane po celej dĺžke."""
    bm = bmesh.new()
    z0, z1 = hole_span(length, size, clearance)
    k = 2.0 * clearance
    lo = z0 - size  # kúsok pod rovinu rezu, aby rez prešiel povrchom
    _shell(bm, peg_width_at(lo, size, length, base, taper) + k, peg_width_at(z1, size, length, base, taper) + k, lo, z1, shape)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def preview_mesh(name: str, size: float, length: float, base: float, taper: float, shape: str, clearance: float):
    """Náhľad: kolík a okolo neho obrys diery, aby bola vôľa aj skosenie vidieť naraz."""
    bm = bmesh.new()
    pz0, pz1 = peg_span(length, base)
    _shell(bm, size, size * taper, pz0, pz1, shape)
    hz0, hz1 = hole_span(length, size, clearance)
    k = 2.0 * clearance
    if k > 1e-9:
        _shell(bm, peg_width_at(hz0, size, length, base, taper) + k, peg_width_at(hz1, size, length, base, taper) + k, hz0, hz1, shape)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def _major_direction(cap_pts: np.ndarray, normal: np.ndarray) -> np.ndarray:
    """Smer najdlhšieho rozmeru plochy rezu (kolmý na normálu). Pri takmer okrúhlej ploche pevný smer, nie náhodný."""
    n = normal / np.linalg.norm(normal)
    ref = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = ref - n * (ref @ n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    xy = np.stack([(cap_pts - cap_pts.mean(axis=0)) @ u, (cap_pts - cap_pts.mean(axis=0)) @ v], axis=1)
    w, vec = np.linalg.eigh(np.cov(xy.T))
    if w[1] < 1.15 * w[0]:
        return u  # takmer okrúhla plocha
    d = vec[:, 1]
    return u * d[0] + v * d[1]


def _frame(axis: Vector, major: Vector) -> Matrix:
    """Os Z = smer kolíka, os X = najdlhší rozmer plochy rezu."""
    z = axis.normalized()
    x = (major - z * major.dot(z))
    if x.length < 1e-9:
        x = z.orthogonal()
    x.normalize()
    y = z.cross(x)
    m = Matrix((x, y, z)).transposed()
    return m.to_4x4()


# --------------------------------------------------------------------------- dáta o reze


def _world_coords(obj) -> np.ndarray:
    n = len(obj.data.vertices)
    co = np.empty(n * 3)
    obj.data.vertices.foreach_get("co", co)
    m = np.array(obj.matrix_world)
    return co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]


def cap_info(part, partner):
    """Plocha rezu, ktorá patrí k dvojici dielov. Vráti (body plochy, body hranice, priemerná vonkajšia normála)."""
    me = part.data
    attr = me.attributes.get("smartcut_cap")
    if attr is None:
        return None
    cap = np.zeros(len(me.polygons), dtype=np.int64)
    attr.data.foreach_get("value", cap)
    cap = cap.astype(bool)
    co = _world_coords(part)
    partner_cap_keys = set()
    pme = partner.data
    pattr = pme.attributes.get("smartcut_cap")
    if pattr is not None:
        pcap = np.zeros(len(pme.polygons), dtype=np.int64)
        pattr.data.foreach_get("value", pcap)
        pco = _world_coords(partner)
        for poly in pme.polygons:
            if pcap[poly.index]:
                partner_cap_keys.update(tuple(np.round(pco[i], 5)) for i in poly.vertices)
    in_cap, in_surface = set(), set()
    normal = np.zeros(3)
    m3 = np.array(part.matrix_world)[:3, :3]
    for poly in me.polygons:
        if not cap[poly.index]:
            in_surface.update(poly.vertices)
            continue
        if partner_cap_keys and not all(tuple(np.round(co[i], 5)) in partner_cap_keys for i in poly.vertices):
            in_surface.update(poly.vertices)
            continue  # plocha iného rezu
        in_cap.update(poly.vertices)
        normal += (m3 @ np.array(poly.normal)) * poly.area
    if not in_cap:
        return None
    cap_ids = sorted(in_cap)
    border_ids = sorted(in_cap & in_surface)
    if not border_ids:
        return None
    n = np.linalg.norm(normal)
    if n < 1e-12:
        return None
    return co[cap_ids], co[border_ids], normal / n


# --------------------------------------------------------------------------- vytvorenie


def _base_depth(cap_pts: np.ndarray, center: np.ndarray, normal: np.ndarray, size: float) -> float:
    """Ako hlboko do dielu siaha základňa kolíka: o zakrivenie plochy rezu pod kolíkom a rezervu, najviac 1,2 šírky.
    Základňa musí prekryť teleso dielu, ale nesmie prerážať na druhú stranu."""
    near = np.linalg.norm(cap_pts - center, axis=1) <= 1.5 * size
    z = (cap_pts[near] - center) @ normal if near.any() else np.zeros(1)
    sag = float(np.ptp(z))
    return float(np.clip(1.3 * sag + 0.4 * size, 0.6 * size, 1.2 * size))


def auto_length(size: float, r_in: float) -> float:
    return float(min(2.2 * size, 1.4 * r_in, 12.0))


def refresh_previews(size: float, taper: float, clearance: float) -> int:
    """Prekreslí náhľady podľa aktuálnych hodnôt. Mení len mesh, takže poloha a posun ostanú."""
    n = 0
    for pin in [o for o in bpy.data.objects if o.get(PIN_PROP)]:
        shape = pin.get("smartcut_pin_shape", "SQUARE")
        r_in = float(pin.get("smartcut_pin_rin", size))
        old_size = float(pin.get("smartcut_pin_size", size)) or size
        base = float(pin.get("smartcut_pin_base", size)) * (size / old_size)  # základňa rastie s kolíkom
        ln = auto_length(size, r_in)
        old = pin.data
        pin.data = preview_mesh(pin.name, size, ln, base, taper, shape, clearance)
        if old.users == 0:
            bpy.data.meshes.remove(old)
        pin["smartcut_pin_size"] = size
        pin["smartcut_pin_length"] = ln
        pin["smartcut_pin_base"] = base
        pin["smartcut_pin_taper"] = taper
        n += 1
    return n


def flip_pins(pins) -> int:
    """Prehodí stranu: kolík prejde na druhý diel a diera na ten, kde bol. Poloha ostáva."""
    n = 0
    for pin in pins:
        a, b = pin.get("smartcut_pin_part"), pin.get("smartcut_pin_other")
        if not a or not b:
            continue
        pin["smartcut_pin_part"], pin["smartcut_pin_other"] = b, a
        pin.matrix_world = pin.matrix_world @ Matrix.Rotation(np.pi, 4, "X")  # otočí smer kolíka
        n += 1
    return n


def remove_preview_pins(part, partner):
    """Zmaže náhľadové kolíky, ktoré patria tejto dvojici dielov."""
    names = {part.name, partner.name}
    for ob in [o for o in bpy.data.objects if o.get(PIN_PROP)]:
        if {ob.get("smartcut_pin_part"), ob.get("smartcut_pin_other")} == names:
            me = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if me.users == 0:
                bpy.data.meshes.remove(me)


def add_pins(part, partner, count=0, diameter=0.0, length=0.0, alternate=False, shape="SQUARE", taper=0.9, clearance=0.0):
    """Vytvorí náhľadové kolíky (obyčajné objekty, ktoré sa dajú presúvať). Vráti zoznam objektov."""
    info = cap_info(part, partner)
    if info is None:
        raise ValueError("No cut surface found between these parts.")
    cap_pts, border_pts, normal = info
    centers, size, ln, max_fit = plan_pins(cap_pts, border_pts, count, diameter, length, shape)
    r_in = float(_min_dist(cap_pts, border_pts).max())
    major = Vector(_major_direction(cap_pts, normal))
    pins = []
    for i, c in enumerate(centers):
        on_part, other = (part, partner) if (not alternate or i % 2 == 0) else (partner, part)
        axis = Vector(normal) if on_part is part else Vector(-normal)  # kolík smeruje z dielu von, k druhému dielu
        base = _base_depth(cap_pts, c, normal, size)
        me = preview_mesh(f"Peg{i + 1}", size, ln, base, taper, shape, clearance)
        ob = bpy.data.objects.new(f"Peg{i + 1}", me)
        ob.matrix_world = Matrix.Translation(Vector(c)) @ _frame(axis, major)
        ob.display_type = "WIRE"  # drôtový obrys, model pod ním ostane viditeľný
        ob.show_in_front = True  # a kolík je vidieť aj cez model (X-ray)
        ob.color = (1.0, 0.55, 0.05, 1.0)
        ob[PIN_PROP] = 1
        ob["smartcut_pin_part"] = on_part.name
        ob["smartcut_pin_other"] = other.name
        ob["smartcut_pin_size"] = size
        ob["smartcut_pin_length"] = ln
        ob["smartcut_pin_shape"] = shape
        ob["smartcut_pin_base"] = base
        ob["smartcut_pin_taper"] = taper
        ob["smartcut_pin_rin"] = r_in
        for coll in part.users_collection:
            coll.objects.link(ob)
        pins.append(ob)
    return pins, {"size": size, "length": ln, "max_fit": max_fit, "placed": len(centers), "requested": count}


# --------------------------------------------------------------------------- aplikovanie


def _boolean(obj, operand, operation: str):
    mod = obj.modifiers.new("smartcut_bool", "BOOLEAN")
    mod.operation = operation
    mod.object = operand
    mod.solver = "EXACT"
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    new = bpy.data.meshes.new_from_object(ev)
    obj.modifiers.remove(mod)
    old = obj.data
    obj.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
    new.name = obj.name


def apply_pins(pins, clearance: float = 0.05) -> int:
    """Kolík sa pridá k dielu, na ktorom je, a do druhého sa vyreže otvor s rovnakým skosením a vôľou `clearance`."""
    done = 0
    for pin in list(pins):
        part = bpy.data.objects.get(pin.get("smartcut_pin_part", ""))
        other = bpy.data.objects.get(pin.get("smartcut_pin_other", ""))
        if part is None or other is None:
            continue
        sx = (abs(pin.scale.x) + abs(pin.scale.y)) / 2.0
        size = float(pin["smartcut_pin_size"]) * sx
        length = float(pin["smartcut_pin_length"]) * abs(pin.scale.z)
        base = float(pin.get("smartcut_pin_base", size)) * abs(pin.scale.z)
        taper = float(pin.get("smartcut_pin_taper", 1.0))
        shape = pin.get("smartcut_pin_shape", "SQUARE")
        frame = pin.matrix_world @ Matrix.Diagonal(
            (1 / max(abs(pin.scale.x), 1e-9), 1 / max(abs(pin.scale.y), 1e-9), 1 / max(abs(pin.scale.z), 1e-9), 1.0)
        )
        peg = bpy.data.objects.new("peg_tmp", peg_mesh("peg_tmp", size, length, base, taper, shape))
        sock = bpy.data.objects.new("socket_tmp", hole_mesh("socket_tmp", size, length, base, taper, shape, clearance))
        peg.matrix_world = frame
        sock.matrix_world = frame
        for coll in part.users_collection:
            coll.objects.link(peg)
        for coll in other.users_collection:
            coll.objects.link(sock)
        _boolean(part, peg, "UNION")
        _boolean(other, sock, "DIFFERENCE")
        bpy.data.objects.remove(peg, do_unlink=True)
        bpy.data.objects.remove(sock, do_unlink=True)
        done += 1
    for pin in pins:
        if pin.name in bpy.data.objects:
            me = pin.data
            bpy.data.objects.remove(pin, do_unlink=True)
            if me.users == 0:
                bpy.data.meshes.remove(me)
    return done
