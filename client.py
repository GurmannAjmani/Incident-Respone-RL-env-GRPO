# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Incident Response Env Environment Client."""

from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

from .models import IncidentResponseAction, IncidentResponseObservation


class IncidentResponseEnv(
    EnvClient[IncidentResponseAction, IncidentResponseObservation, State]
):
    """
    Client for the Incident Response Env Environment.

    This client maintains a persistent WebSocket connection to the environment server,
    enabling efficient multi-step interactions with lower latency.
    Each client instance has its own dedicated environment session on the server.

    Example:
        >>> # Connect to a running server
        >>> with IncidentResponseEnv(base_url="http://localhost:8000") as client:
        ...     result = client.reset()
        ...     print(result.observation.echoed_message)
        ...
        ...     result = client.step(IncidentResponseAction(message="Hello!"))
        ...     print(result.observation.echoed_message)

    Example with Docker:
        >>> # Automatically start container and connect
        >>> client = IncidentResponseEnv.from_docker_image("incident_response_env-env:latest")
        >>> try:
        ...     result = client.reset()
        ...     result = client.step(IncidentResponseAction(message="Test"))
        ... finally:
        ...     client.close()
    """

    def _step_payload(self, action: IncidentResponseAction) -> Dict:
        """
        Convert IncidentResponseAction to JSON payload for step message.

        Args:
            action: IncidentResponseAction instance

        Returns:
            Dictionary representation suitable for JSON encoding
        """
        return {
            "command": action.command,
            "role": action.role,
        }

    def _parse_result(self, payload: Dict) -> StepResult[IncidentResponseObservation]:
        """
        Parse server response into StepResult[IncidentResponseObservation].

        Args:
            payload: JSON response data from server

        Returns:
            StepResult with IncidentResponseObservation
        """
        obs_data = payload.get("observation", {})
        observation = IncidentResponseObservation(
            prompt=obs_data.get("prompt", ""),
            health=obs_data.get("health", 1.0),
            status=obs_data.get("status", "STABLE"),
            next_role=obs_data.get("next_role", "attacker"),
            done=payload.get("done", False),
            reward=payload.get("reward", 0.0),
            metadata=obs_data.get("metadata", {}),
        )

        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> State:
        """
        Parse server response into State object.

        Args:
            payload: JSON response from state request

        Returns:
            State object with episode_id and step_count
        """
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )
