"""
Endgame Voronoi assignment: hunters split across remaining prey.

Delaunay edges first; k-NN only to connect isolates.
particle.py imports VoronoiEndgame — do not import particle at module level.
"""

import math


class VoronoiEndgame:
    """
    Voronoi partition of the arena by remaining prey positions.
    Each hunter is assigned to the prey whose cell contains them (nearest site).
    Overflow hunters in overloaded cells are reassigned to under-covered prey.
    Cached and recomputed every N frames for performance.
    """
    _cache_rc = -1
    _cache_gid = None
    _prey_ids = ()
    _assignments = {}  # hunter_id -> prey particle
    _cell_load = {}    # prey_id -> count
    _imbalance = 0.0

    @classmethod
    def _prey_key(cls, prey_list):
        return tuple(sorted(getattr(q, 'id', id(q)) for q in prey_list))

    @classmethod
    def assign(cls, world, hunters, prey_list, st):
        """Return dict hunter_id -> prey particle. Uses Voronoi (nearest site) + load balance."""
        if not prey_list or not hunters:
            return {}
        n_prey0 = len(prey_list)
        interval = max(1, int(st.get('voronoi_recompute_interval', 8)))
        if n_prey0 >= 2:
            interval = min(interval, 2)
        overflow_th = max(1, int(st.get('voronoi_overflow_threshold', 3)))
        rc = getattr(world, 'runcount', 0)
        gid = getattr(world, 'gameid', None)
        pkey = cls._prey_key(prey_list)
        need = (cls._cache_rc < 0
                or rc - cls._cache_rc >= interval
                or gid != cls._cache_gid
                or pkey != cls._prey_ids)
        if not need and cls._assignments:
            # Validate cached prey still alive
            alive = {getattr(q, 'id', id(q)): q for q in prey_list}
            out = {}
            for hid, pr in cls._assignments.items():
                pid = getattr(pr, 'id', id(pr))
                if pid in alive:
                    out[hid] = alive[pid]
            if len(out) >= len(hunters) * 0.5:
                return out

        # Site positions: blend current vs predicted prey pos
        pred_b = float(st.get('clear_voronoi_predict', 0.35))
        look = float(st.get('predict_lookahead', 12.0))
        sites = []  # (prey, sx, sy)
        for pr in prey_list:
            sx, sy = pr.x, pr.y
            if pred_b > 0.01:
                px = pr.x + math.sin(pr.angle) * pr.speed * look * pred_b
                py = pr.y + (-math.cos(pr.angle)) * pr.speed * look * pred_b
                sx = pr.x * (1 - pred_b) + px * pred_b
                sy = pr.y * (1 - pred_b) + py * pred_b
            sites.append((pr, sx, sy))

        # Voronoi cell = nearest site (Euclidean)
        raw = {}  # hid -> prey
        load = {getattr(q, 'id', id(q)): 0 for q in prey_list}
        for h in hunters:
            best = None
            best_d = 1e18
            for pr, sx, sy in sites:
                d = (h.x - sx) ** 2 + (h.y - sy) ** 2
                if d < best_d:
                    best_d = d
                    best = pr
            if best is not None:
                hid = getattr(h, 'id', id(h))
                raw[hid] = best
                load[getattr(best, 'id', id(best))] += 1

        # Load-balance: overflow from heavy cells to light cells
        n_prey = len(prey_list)
        n_hunt = len(hunters)
        fair = max(1, (n_hunt + n_prey - 1) // n_prey)
        # HARD: when ≥2 prey, each cell gets at most ceil(hunters/prey) — strict split
        balance = 1.0
        slack = 0
        strict_cap = max(1, fair)
        cap = strict_cap
        if n_prey >= 2:
            # Prefer spreading: if hunters >> prey, fair share; never all on one
            cap = max(1, fair)
        cap = max(1, cap)

        # Delaunay (dual) adjacency of prey sites — overflow prefers neighbors
        use_del = float(st.get('delaunay_overflow', 1.0)) > 0.05
        adj = cls._delaunay_adj(sites, st) if use_del and len(sites) > 1 else {}

        # Sort prey by load descending
        by_load = sorted(prey_list, key=lambda q: load[getattr(q, 'id', id(q))], reverse=True)
        light = sorted(prey_list, key=lambda q: load[getattr(q, 'id', id(q))])

        # Hunters in each cell
        cells = {getattr(q, 'id', id(q)): [] for q in prey_list}
        for h in hunters:
            hid = getattr(h, 'id', id(h))
            pr = raw.get(hid)
            if pr is not None:
                cells[getattr(pr, 'id', id(pr))].append(h)

        reassigns = 0
        delaunay_peels = 0
        cross_map = 0
        for pr in by_load:
            pid = getattr(pr, 'id', id(pr))
            members = cells.get(pid, [])
            if len(members) <= cap:
                continue
            # Furthest from this prey get reassigned first
            members_sorted = sorted(members, key=lambda h: -((h.x-pr.x)**2 + (h.y-pr.y)**2))
            overflow = members_sorted[cap:]
            neighbors = adj.get(pid, [])
            for h in overflow:
                target = None
                via_delaunay = False
                # 1) Prefer lightest under-capacity Delaunay neighbor (short lateral peel)
                if neighbors:
                    best_n = None
                    best_load = 1e18
                    best_d = 1e18
                    for cand in neighbors:
                        cid = getattr(cand, 'id', id(cand))
                        if load.get(cid, 0) >= cap:
                            continue
                        ld = load.get(cid, 0)
                        d = (h.x - cand.x)**2 + (h.y - cand.y)**2
                        if ld < best_load or (ld == best_load and d < best_d):
                            best_load = ld
                            best_d = d
                            best_n = cand
                    if best_n is not None:
                        target = best_n
                        via_delaunay = True
                # 2) Global under-capacity nearest
                if target is None:
                    td = 1e18
                    for cand in light:
                        cid = getattr(cand, 'id', id(cand))
                        if load.get(cid, 0) >= cap:
                            continue
                        d = (h.x - cand.x)**2 + (h.y - cand.y)**2
                        if d < td:
                            td = d
                            target = cand
                # 3) All full — globally least loaded
                if target is None:
                    target = min(prey_list, key=lambda q: load[getattr(q, 'id', id(q))])
                hid = getattr(h, 'id', id(h))
                old = raw.get(hid)
                if old is not None:
                    oid = getattr(old, 'id', id(old))
                    load[oid] = load.get(oid, 1) - 1
                    if h in cells.get(oid, []):
                        cells[oid].remove(h)
                tid = getattr(target, 'id', id(target))
                raw[hid] = target
                load[tid] = load.get(tid, 0) + 1
                cells.setdefault(tid, []).append(h)
                reassigns += 1
                if via_delaunay:
                    delaunay_peels += 1
                else:
                    cross_map += 1

        loads = list(load.values())
        imb = 0.0
        if loads:
            mean = sum(loads) / len(loads)
            imb = max(loads) - mean if mean > 0 else 0.0

        cls._cache_rc = rc
        cls._cache_gid = gid
        cls._prey_ids = pkey
        cls._assignments = raw
        cls._cell_load = load
        cls._imbalance = imb
        cls._reassigns = reassigns
        cls._delaunay_peels = delaunay_peels
        cls._cross_map = cross_map
        cls._delaunay_edges = sum(len(v) for v in adj.values()) // 2
        # pure / fill already set inside _delaunay_adj
        return raw

    @classmethod
    def _delaunay_adj(cls, sites, st):
        """
        Hybrid dual of prey sites:
          1) Geometric Delaunay edges (midpoint shared-boundary test) first
          2) k-NN only to fix isolates / bridge disconnected components
        Never densifies an already-connected Delaunay region.
        sites: list of (prey, sx, sy)
        Returns: dict prey_id -> list of neighbor prey particles
        """
        n = len(sites)
        if n < 2:
            cls._knn_fill_edges = 0
            return {}
        k_nn = max(1, int(st.get('delaunay_k', 3)))
        pts = []
        for pr, sx, sy in sites:
            pts.append((getattr(pr, 'id', id(pr)), pr, float(sx), float(sy)))
        id_list = [t[0] for t in pts]
        pos = {t[0]: (t[2], t[3]) for t in pts}

        edges = set()  # frozenset of two ids — pure Delaunay first
        if n == 2:
            edges.add(frozenset((pts[0][0], pts[1][0])))
        else:
            for i in range(n):
                for j in range(i + 1, n):
                    id_i, _, xi, yi = pts[i]
                    id_j, _, xj, yj = pts[j]
                    mx, my = 0.5 * (xi + xj), 0.5 * (yi + yj)
                    order = []
                    for id_k, _, xk, yk in pts:
                        order.append(((mx - xk) ** 2 + (my - yk) ** 2, id_k))
                    order.sort()
                    if id_i != id_j and {order[0][1], order[1][1]} == {id_i, id_j}:
                        edges.add(frozenset((id_i, id_j)))

        # Drop any accidental self-loops / singleton frozensets
        edges = {e for e in edges if len(e) == 2}
        delaunay_n = len(edges)

        def components(edge_set):
            parent = {i: i for i in id_list}

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def union(a, b):
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra

            for e in edge_set:
                if len(e) != 2:
                    continue
                a, b = tuple(e)
                if a == b:
                    continue
                union(a, b)
            comps = {}
            for i in id_list:
                r = find(i)
                comps.setdefault(r, []).append(i)
            return list(comps.values())

        comps = components(edges)
        knn_fill = 0

        # Only fill if disconnected or isolates (degree 0)
        degree = {i: 0 for i in id_list}
        for e in edges:
            if len(e) != 2:
                continue
            a, b = tuple(e)
            if a == b:
                continue
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
        isolates = [i for i in id_list if degree[i] == 0]
        need_fill = len(comps) > 1 or len(isolates) > 0

        if need_fill:
            # Precompute all pairwise distances once
            pair_d = {}
            for i in range(n):
                for j in range(i + 1, n):
                    ai, aj = pts[i][0], pts[j][0]
                    dx = pts[i][2] - pts[j][2]
                    dy = pts[i][3] - pts[j][3]
                    pair_d[(ai, aj)] = dx * dx + dy * dy
                    pair_d[(aj, ai)] = pair_d[(ai, aj)]

            def dist(a, b):
                return pair_d.get((a, b), pair_d.get((b, a), 1e18))

            # 1) Connect each isolate to up to k_nn nearest non-self sites
            for iso in isolates:
                ranked = sorted((dist(iso, j), j) for j in id_list if j != iso)
                added = 0
                for _, j in ranked:
                    if added >= k_nn:
                        break
                    if j == iso:
                        continue
                    e = frozenset((iso, j))
                    if len(e) != 2:
                        continue
                    if e not in edges:
                        edges.add(e)
                        knn_fill += 1
                        added += 1
                        degree[iso] = degree.get(iso, 0) + 1
                        degree[j] = degree.get(j, 0) + 1

            # 2) Bridge remaining components with shortest inter-component links
            #    (Kruskal-style on component pairs, at most k_nn bridges per component)
            comps = components(edges)
            guard = 0
            while len(comps) > 1 and guard < n * k_nn:
                guard += 1
                # Shortest edge between different components
                best = None
                best_d = 1e18
                for ci in range(len(comps)):
                    for cj in range(ci + 1, len(comps)):
                        for a in comps[ci]:
                            for b in comps[cj]:
                                d = dist(a, b)
                                if d < best_d:
                                    best_d = d
                                    best = (a, b)
                if best is None:
                    break
                if best[0] == best[1]:
                    break
                e = frozenset(best)
                if len(e) != 2:
                    break
                if e not in edges:
                    edges.add(e)
                    knn_fill += 1
                    degree[best[0]] = degree.get(best[0], 0) + 1
                    degree[best[1]] = degree.get(best[1], 0) + 1
                comps = components(edges)

        cls._knn_fill_edges = knn_fill
        cls._delaunay_pure_edges = delaunay_n

        id_to_prey = {getattr(pr, 'id', id(pr)): pr for pr, _, _ in sites}
        adj = {getattr(pr, 'id', id(pr)): [] for pr, _, _ in sites}
        for e in edges:
            if len(e) != 2:
                continue
            a, b = tuple(e)
            if a == b:
                continue
            if a in id_to_prey and b in id_to_prey:
                adj[a].append(id_to_prey[b])
                adj[b].append(id_to_prey[a])
        return adj

    @classmethod
    def stats(cls):
        return {
            'voronoi_imbalance': round(cls._imbalance, 3),
            'voronoi_reassign': int(getattr(cls, '_reassigns', 0)),
            'voronoi_cells': len(cls._cell_load),
            'delaunay_peels': int(getattr(cls, '_delaunay_peels', 0)),
            'cross_map_reassigns': int(getattr(cls, '_cross_map', 0)),
            'delaunay_edges': int(getattr(cls, '_delaunay_edges', 0)),
            'delaunay_pure_edges': int(getattr(cls, '_delaunay_pure_edges', 0)),
            'knn_fill_edges': int(getattr(cls, '_knn_fill_edges', 0)),
        }
