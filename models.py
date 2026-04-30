# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Data models for the Incident Response Env Environment.

The incident_response_env environment is a simple test environment that echoes back messages.
"""

from openenv.core.env_server.types import Action, Observation, State
from pydantic import Field
from typing import Dict, Any, List, Literal, Optional


Role = Literal["attacker", "defender"]


class IncidentResponseAction(Action):
    """Action for the Duel environment - an attack or defense command."""
    command: str = Field(
        ...,
        description="Action chosen by the agent (e.g., 'ATTACK: PHISH' or 'DEFEND: MFA')",
    )
    role: Role = Field(
        "defender",
        description="Role of the agent (attacker or defender)",
    )


class IncidentResponseObservation(Observation):
    """Observation from the Duel environment - prompt for the next actor."""
    prompt: str = Field(default="", description="The text prompt presented to the agent")
    health: float = Field(default=1.0, description="Current health of the system")
    status: str = Field(default="STABLE", description="Status of the system")
    next_role: str = Field(
        default="attacker",
        description="The role that must act next (attacker, defender, or done)",
    )
    done: bool = Field(default=False, description="Whether the episode is complete")
    reward: float = Field(default=0.0, description="Reward for the last action")
    history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Turn-by-turn history: attacker/defender moves and breach outcome",
    )
    breached: Optional[bool] = Field(
        default=None,
        description="Whether the last defender resolution resulted in a breach",
    )
    damage: Optional[float] = Field(
        default=None,
        description="Damage applied to health on the last resolution (if any)",
    )
    last_attack: Optional[str] = Field(default=None, description="Last resolved attack move")
    last_defense: Optional[str] = Field(default=None, description="Last resolved defense move")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context and metrics")

class IncidentResponseState(State):
    episode_id: str = ""
    step_count: int = 0
    health: float = 1.0
    status: str = "STABLE"
    scenario_id: str = ""
    history: List[tuple] = Field(default_factory=list)

