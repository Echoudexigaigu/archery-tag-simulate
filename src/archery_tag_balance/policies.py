"""Observation-only scripted opponents, not trained RL policies."""

from heapq import heappop, heappush
from math import hypot
import random

from .entities import Action
from .geometry import segment_box


class Navigator:
    """Direct steering with A* around the known, static bunker footprints."""

    def __init__(self, config, obstacles):
        self.config, self.obstacles = config, obstacles
        self.cell = config["policy"]["navigation_cell_m"]
        self.radius = config["physics"]["player_radius_m"] + 0.02
        self.nx = int(config["field"]["length_m"] / self.cell)
        self.ny = int(config["field"]["width_m"] / self.cell)
        self.free = {}
        for team in ("attack", "defense"):
            xmin, xmax = config["teams"][team]["move_x_bounds_m"]
            nodes = set()
            for ix in range(self.nx):
                for iy in range(self.ny):
                    x, y = self.point((ix, iy))
                    if xmin <= x <= xmax and self.radius <= x <= config["field"]["length_m"] - self.radius and self.radius <= y <= config["field"]["width_m"] - self.radius and self.clear((x, y), (x, y)):
                        nodes.add((ix, iy))
            self.free[team] = nodes

    def point(self, node):
        return ((node[0] + 0.5) * self.cell, (node[1] + 0.5) * self.cell)

    def clear(self, start, end):
        return all(segment_box((*start, 0.5), (*end, 0.5), *o.bounds(self.radius)) is None for o in self.obstacles)

    def nearest(self, point, team):
        node = (int(point[0] / self.cell), int(point[1] / self.cell))
        if node in self.free[team]:
            return node
        return min(self.free[team], key=lambda n: hypot(self.point(n)[0] - point[0], self.point(n)[1] - point[1]))

    def path(self, start, goal, team):
        if self.clear(start, goal):
            return [goal]
        begin, finish = self.nearest(start, team), self.nearest(goal, team)
        heap, costs, parent = [(0.0, begin)], {begin: 0.0}, {}
        while heap:
            _, node = heappop(heap)
            if node == finish:
                route = [node]
                while node in parent:
                    node = parent[node]
                    route.append(node)
                route.reverse()
                return [self.point(n) for n in route[1:]] or [self.point(finish)]
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                other = (node[0] + dx, node[1] + dy)
                if other not in self.free[team] or not self.clear(self.point(node), self.point(other)):
                    continue
                cost = costs[node] + hypot(dx, dy)
                if cost < costs.get(other, float("inf")):
                    costs[other], parent[other] = cost, node
                    heappush(heap, (cost + hypot(other[0] - finish[0], other[1] - finish[1]), other))
        return []


class ScriptedPolicy:
    def __init__(self, config, navigator, agent_id, seed, mirror_y=False):
        self.config, self.nav, self.id = config, navigator, agent_id
        self.index = int(agent_id.rsplit("_", 1)[1])
        self.rng, self.route, self.goal = random.Random(seed), [], None
        self.mirror_y, self.next_replan = mirror_y, 0.0
        self.jitter = self.rng.uniform(-0.35, 0.35)

    def move_to(self, position, goal, team, now):
        if self.goal is None or hypot(goal[0] - self.goal[0], goal[1] - self.goal[1]) > 0.7 or now >= self.next_replan:
            self.route = self.nav.path(position, goal, team)
            self.goal, self.next_replan = goal, now + 1.5
        while self.route and hypot(self.route[0][0] - position[0], self.route[0][1] - position[1]) < 0.25:
            self.route.pop(0)
        if not self.route:
            return (0.0, 0.0)
        dx, dy = self.route[0][0] - position[0], self.route[0][1] - position[1]
        norm = max(1e-9, hypot(dx, dy))
        scale = min(1.0, norm / (self.config["physics"]["move_speed_m_s"] * self.config["policy"]["decision_interval_s"]))
        return dx / norm * scale, dy / norm * scale

    def __call__(self, obs):
        a, c = obs["self"], self.config
        if a["status"] == "eliminated":
            return Action()
        x, y = a["position"]
        team, now = a["team"], obs["time"]
        xmin, xmax = c["teams"][team]["pickup_x_bounds_m"]
        ground = [b for b in obs["ground_arrows"] if xmin <= b["position"][0] <= xmax and not (team == "attack" and a["opening_received"] and b["opening_arrow"])]
        if a["ammo"] == 0:
            if ground:
                b = min(ground, key=lambda b: hypot(b["position"][0] - x, b["position"][1] - y))
                goal = b["position"][:2]
            elif team == "attack" and not a["opening_received"]:
                pos = c["opening"]["arrow_positions_m"][self.index % len(c["opening"]["arrow_positions_m"])]
                goal = (pos[0], c["field"]["width_m"] - pos[1] if self.mirror_y else pos[1])
            else:
                # Search only our legal pickup territory; no hidden arrow coordinates.
                slot = int(now / 3 + self.index) % 4
                gx = xmin + (xmax - xmin) * (0.3 if slot < 2 else 0.75)
                goal = (gx, c["field"]["width_m"] * (0.25 if slot % 2 == 0 else 0.75))
            move = self.move_to((x, y), goal, team, now)
            return Action(move=move, interaction="pickup")
        W = c["field"]["width_m"]
        n = c["teams"][team]["players"]
        rack_y = obs["spots"][4]["position"][1]
        side_offset = (self.index - (n - 1) / 2) * c["policy"]["lane_spacing_m"]
        if self.mirror_y:
            side_offset *= -1
        lane = max(0.8, min(W - 0.8, rack_y + side_offset + self.jitter))
        if team == "attack":
            gx = c["teams"][team]["shoot_x_bounds_m"][1] - 0.4
        else:
            gx = max(c["teams"][team]["move_x_bounds_m"][0] + 0.7, min(c["rack"]["position_xyz_m"][0] - 2.8, c["field"]["length_m"] - 1.5))
        goal = (gx, lane)
        move = self.move_to((x, y), goal, team, now)
        candidates = [b for b in obs["enemies"] if b["status"] == "active" and hypot(b["position"][0] - x, b["position"][1] - y) >= c["rules"]["min_shot_distance_m"]]
        suppress = team == "defense" or self.index < c["policy"]["attack_suppressors"]
        if suppress and candidates:
            enemy = min(candidates, key=lambda b: hypot(b["position"][0] - x, b["position"][1] - y))
            flight = hypot(enemy["position"][0] - x, enemy["position"][1] - y) / c["physics"]["arrow_speed_m_s"]
            aim = (enemy["position"][0] + enemy["velocity"][0] * flight,
                   enemy["position"][1] + enemy["velocity"][1] * flight,
                   enemy["height"] * 0.6)
            key = enemy["id"]
        elif team == "attack":
            live = [s for s in obs["spots"] if s["standing"]]
            if not live:
                return Action(move=move)
            target = live[self.index % len(live)]
            aim, key = target["position"], f"spot_{target['id']}"
        else:
            return Action(move=move, crouch=hypot(goal[0] - x, goal[1] - y) < 0.5)
        # Crouch while reloading only when physically close to a bunker.
        near_cover = any(hypot(o.center[0] - x, o.center[1] - y) < 1.3 for o in self.nav.obstacles)
        crouch = near_cover and a["reload_left"] > 0.2
        return Action(move=move, aim=aim, aim_key=key, interaction="shoot", crouch=crouch)
