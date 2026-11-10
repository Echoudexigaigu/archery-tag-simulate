"""Physical entities; policy decisions are kept separate from proficiency."""

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    ACTIVE = "active"
    INVINCIBLE = "invincible"
    ELIMINATED = "eliminated"


@dataclass(frozen=True)
class Action:
    move: tuple = (0.0, 0.0)
    aim: tuple | None = None  # world x,y,z; no target tracking by the arrow
    aim_key: str | None = None
    interaction: str = "none"  # none / pickup / shoot / catch
    crouch: bool = False
    evasion_kind: str | None = None
    evade_key: tuple | None = None


@dataclass
class Agent:
    id: str
    team: str
    eta: float
    position: tuple
    spawn: tuple
    lives: int | None
    velocity: tuple = (0.0, 0.0)
    status: Status = Status.ACTIVE
    inventory: list = field(default_factory=list)
    has_bow: bool = True
    reload_left: float = 0.0
    aim_elapsed: float = 0.0
    aim_key: str | None = None
    respawn_at: float | None = None
    protected_until: float = 0.0
    catch_left: float = 0.0
    catch_cooldown: float = 0.0
    opening_received: bool = False
    pickup_elapsed: float = 0.0
    crouched: bool = False
    center_visited: bool = False
    shoot_unlocked: bool = True
    dodge_ready_at: float = 0.0
    stamina: float = 1.0
    movement_dodge_ready_at: float = 0.0
    evasion_until: float = 0.0
    evasion_kind: str | None = None
    evade_key: tuple | None = None
    human_profile: dict = field(default_factory=dict)
    human_aim_s: float = 1.0
    pickup_required_s: float = 0.65
    last_move_at: float = -100.0
    last_shot_at: float = -100.0
    role: str = ""
    steady_aim_s: float = 0.0
    steady_aim_key: str | None = None


@dataclass
class Arrow:
    id: int
    position: tuple
    state: str = "ground"  # ground / carried / flying
    velocity: tuple = (0.0, 0.0, 0.0)
    carrier: str | None = None
    shooter: str | None = None
    flight_left: float = 0.0
    opening_arrow: bool = False
    opening_owner: str | None = None
    released_at: float = 0.0
    evaded_agents: set = field(default_factory=set)
    planned_flight_s: float = 0.0
    landing_origin: tuple | None = None
    settling_elapsed: float = 0.0
    settling_duration: float = 0.0
    settling_heading: tuple = (0.0, 0.0)
    settling_distance: float = 0.0
    settling_curve: float = 0.0
    settling_hops: int = 0
    settling_height: float = 0.0


@dataclass(frozen=True)
class Obstacle:
    id: str
    center: tuple
    size: tuple

    def bounds(self, margin=0.0):
        x, y = self.center
        sx, sy, sz = self.size
        return ((x - sx / 2 - margin, y - sy / 2 - margin, -margin),
                (x + sx / 2 + margin, y + sy / 2 + margin, sz + margin))


@dataclass
class TargetRack:
    position: tuple
    size: tuple
    offsets: list
    radius: float
    standing: list = field(default_factory=lambda: [True] * 5)

    def spot(self, index):
        horizontal, vertical = self.offsets[index]
        x, y, z = self.position
        return x, y + horizontal, z + vertical
