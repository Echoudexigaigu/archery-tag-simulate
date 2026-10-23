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
