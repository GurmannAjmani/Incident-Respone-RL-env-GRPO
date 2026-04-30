import random
import re
from collections import Counter, deque
from uuid import uuid4

from openenv.core.env_server.interfaces import Environment

try:
    from ..models import IncidentResponseAction, IncidentResponseObservation, IncidentResponseState
except ImportError:
    from models import IncidentResponseAction, IncidentResponseObservation, IncidentResponseState

ATTACKS  = [
    "PHISH", "BRUTEFORCE", "DRIVEBY", "RANSOM",
    "SQLI",  "RCE",        "LPE",     "SUPPLYCHAIN",
]
DEFENSES = [
    "MFA", "PATCH", "EDR", "BACKUP",
    "WAF", "LEASTPRIV", "SBOM", "ROTATEKEYS",
]

EPISODE_STEPS = 3

ATTACK_CHAINS = {
    "PHISH":      ["LPE", "RANSOM"],
    "BRUTEFORCE": ["RANSOM", "DRIVEBY"],
    "DRIVEBY":    ["RCE", "LPE"],
    "SQLI":       ["RCE", "LPE"],
    "RCE":        ["RANSOM", "SUPPLYCHAIN"],
    "LPE":        ["RANSOM", "SUPPLYCHAIN"],
    "RANSOM":     [],
    "SUPPLYCHAIN":[],
}

SCENARIOS = [
    {
        "id": "bulk_phish",
        "weakness": "PHISH",
        "hint": "Log: bulk phishing campaign detected, no clicks yet.",
        "profile": "Org: 500 users, MFA=available",
        "counter": "MFA",
    },
    {
        "id": "exec_phish",
        "weakness": "PHISH",
        "hint": "Log: CFO clicked spear-phish link, credential harvester active.",
        "profile": "Target: executive, EDR=installed, MFA=bypassed",
        "counter": "EDR",
    },
    {
        "id": "ssh_brute",
        "weakness": "BRUTEFORCE",
        "hint": "Log: many failed SSH logins from one IP, then a success.",
        "profile": "Service: ssh, rate_limits=off, MFA=available",
        "counter": "MFA",
    },
    {
        "id": "api_brute",
        "weakness": "BRUTEFORCE",
        "hint": "Log: API key rotation overdue, brute-force on API gateway.",
        "profile": "Service: REST API, MFA=not_applicable, keys=stale",
        "counter": "ROTATEKEYS",
    },
    {
        "id": "unpatched_browser",
        "weakness": "DRIVEBY",
        "hint": "Log: drive-by ad redirect chain observed on endpoints.",
        "profile": "Endpoints: outdated browser, EDR=absent",
        "counter": "PATCH",
    },
    {
        "id": "driveby_edr",
        "weakness": "DRIVEBY",
        "hint": "Log: drive-by payload dropped, C2 beacon attempting to run.",
        "profile": "Endpoints: browser patched, EDR=installed",
        "counter": "EDR",
    },
    {
        "id": "backup_gap",
        "weakness": "RANSOM",
        "hint": "Log: backups failed 3 days in a row, encryption starting.",
        "profile": "Backups: not tested, EDR=absent",
        "counter": "BACKUP",
    },
    {
        "id": "ransom_edr",
        "weakness": "RANSOM",
        "hint": "Log: ransomware binary detected in staging, not yet executed.",
        "profile": "Backups: healthy, EDR=installed",
        "counter": "EDR",
    },
]

COUNTER_FALLBACK = {
    "PHISH": "MFA",   "BRUTEFORCE": "MFA",  "DRIVEBY": "PATCH",
    "RANSOM": "BACKUP", "SQLI": "WAF",      "RCE": "PATCH",
    "LPE": "LEASTPRIV", "SUPPLYCHAIN": "SBOM",
}

def get_counter(sc: dict) -> str:
    return sc.get("counter", COUNTER_FALLBACK.get(sc["weakness"], "PATCH"))

def _summary(prefix: str, items, universe):
    c     = Counter(items)
    parts = [f"{u}={c.get(u, 0)}" for u in universe]
    return f"{prefix}({len(items)}): " + " ".join(parts)


class EpisodeState:
    """Tracks health and history within a 3-step episode."""
    def __init__(self, sc):
        self.sc         = sc
        self.health     = 1.0
        self.step       = 0
        self.history    = []    # list of (attack, defense, breached)
        self.unlocked   = []    # follow-on attacks unlocked by prior breaches

    def status(self):
        if self.health >= 0.8:   return "STABLE"
        if self.health >= 0.5:   return "DEGRADED"
        return "CRITICAL"

    def apply(self, attack, defense, breached):
        if breached:
            damage = {"RANSOM": 0.4, "RCE": 0.35, "SUPPLYCHAIN": 0.35,
                      "LPE": 0.25, "DRIVEBY": 0.25, "SQLI": 0.20,
                      "PHISH": 0.15, "BRUTEFORCE": 0.15}.get(attack, 0.2)
            self.health = max(0.0, self.health - damage)
            # Unlock follow-on attacks
            for follow in ATTACK_CHAINS.get(attack, []):
                if follow not in self.unlocked:
                    self.unlocked.append(follow)
        self.history.append((attack, defense, breached))
        self.step += 1

    def history_str(self):
        if not self.history:
            return "No prior steps."
        lines = []
        for i, (atk, df, br) in enumerate(self.history):
            outcome = "BREACHED ⚠" if br else "BLOCKED ✓"
            lines.append(f"  Step {i+1}: Attack={atk} | Defense={df} | {outcome}")
        return "\n".join(lines)


class DuelEnv:
    def sample_scenario(self):
        return random.choice(SCENARIOS)

    def new_episode(self, sc):
        return EpisodeState(sc)

    def attacker_prompt(self, sc, ep: EpisodeState, defender_mem_line: str):
        unlocked_str = ""
        if ep.unlocked:
            unlocked_str = f"Unlocked follow-on attacks (from prior breach): {', '.join(ep.unlocked)}\n"
        return (
            "[RED TEAM VS BLUE TEAM — MULTI-STEP DUEL]\n"
            f"Scenario: {sc['id']} | Step: {ep.step + 1}/{EPISODE_STEPS}\n"
            f"System health: {ep.health:.0%} ({ep.status()})\n"
            f"{sc['profile']}\n"
            f"{sc['hint']}\n"
            f"{ep.history_str()}\n"
            f"{unlocked_str}"
            f"{defender_mem_line}\n\n"
            "[ROLE] You are the Attacker (RED).\n"
            "Study the health, history, and profile — adapt your attack.\n"
            "Choose exactly one attack.\n"
            f"Valid attacks: {', '.join(ATTACKS)}\n\n"
            "Format exactly (one line):\n"
            "ATTACK: <" + "|".join(ATTACKS) + ">"
        )

    def defender_prompt(self, sc, ep: EpisodeState, attacker_move: str, attacker_mem_lines: str):
        return (
            "[RED TEAM VS BLUE TEAM — MULTI-STEP DUEL]\n"
            f"Scenario: {sc['id']} | Step: {ep.step + 1}/{EPISODE_STEPS}\n"
            f"System health: {ep.health:.0%} ({ep.status()})\n"
            f"{sc['profile']}\n"
            f"{sc['hint']}\n"
            f"{ep.history_str()}\n"
            f"{attacker_mem_lines}\n"
            f"Attacker chose: {attacker_move}\n\n"
            "[ROLE] You are the Defender (BLUE).\n"
            "Read the health, history, and profile — adapt your defense.\n"
            "If health is DEGRADED/CRITICAL, prioritize recovery defenses.\n"
            "Choose exactly one defense.\n"
            f"Valid defenses: {', '.join(DEFENSES)}\n\n"
            "Format exactly (one line):\n"
            "DEFEND: <" + "|".join(DEFENSES) + ">"
        )


class IncidentResponseEnvironment(Environment):
    """
    OpenEnv wrapper for the DuelEnv cyber warfare environment.
    Supports alternating steps between attacker and defender.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self):
        """Initialize the incident_response_env environment."""
        self._state = IncidentResponseState(episode_id=str(uuid4()), step_count=0)
        self.env = DuelEnv()
        self.sc = None
        self.ep = None
        
        # Memory variables (instance-level to support concurrency)
        MEMORY_WINDOW = 10
        self.recent_attacks = deque(maxlen=MEMORY_WINDOW)
        self.recent_defenses = deque(maxlen=MEMORY_WINDOW)
        self.recent_breaches = deque(maxlen=MEMORY_WINDOW)
        
        self.last_attacker_move = ""

    def reset(self) -> IncidentResponseObservation:
        self._state = IncidentResponseState(episode_id=str(uuid4()), step_count=0)
        self.sc = self.env.sample_scenario()
        self.ep = self.env.new_episode(self.sc)
        self.last_attacker_move = ""
        
        self._state.health = self.ep.health
        self._state.status = self.ep.status()
        self._state.scenario_id = self.sc["id"]
        
        defender_mem_line = self._attacker_memory_line()
        prompt = self.env.attacker_prompt(self.sc, self.ep, defender_mem_line)

        return IncidentResponseObservation(
            prompt=prompt,
            health=self.ep.health,
            status=self.ep.status(),
            next_role="attacker",
            done=False,
            reward=0.0,
            history=[],
            breached=None,
            damage=None,
            last_attack=None,
            last_defense=None,
            metadata={"scenario": self.sc["id"], "step": self.ep.step},
        )

    def _history_payload(self):
        if not self.ep or not getattr(self.ep, "history", None):
            return []
        out = []
        for i, (atk, df, br) in enumerate(self.ep.history):
            out.append(
                {
                    "turn": i + 1,
                    "attacker": atk,
                    "defender": df,
                    "breached": bool(br),
                }
            )
        return out

    def _attacker_memory_line(self):
        return _summary("Defender_recent", list(self.recent_defenses), DEFENSES)

    def _defender_memory_lines(self):
        return (
            _summary("Attacker_recent", list(self.recent_attacks),  ATTACKS)
            + "\n"
            + _summary("Recent_breaches", list(self.recent_breaches), ATTACKS)
        )

    def _parse_attack(self, text: str):
        m = re.search(r"ATTACK:\s*([A-Za-z]+)", text, re.IGNORECASE)
        return m.group(1).upper() if m else "INVALID"

    def _parse_defense(self, text: str):
        m = re.search(r"DEFEND:\s*([A-Za-z]+)", text, re.IGNORECASE)
        return m.group(1).upper() if m else "INVALID"

    def _outcome_breached(self, sc, attacker_move: str, defender_move: str, ep: EpisodeState) -> bool:
        if not sc:
            return False
        is_weakness = (attacker_move == sc["weakness"])
        is_followon = (attacker_move in ep.unlocked)
        
        if not is_weakness and not is_followon:
            return False
            
        if is_followon and not is_weakness:
            correct = COUNTER_FALLBACK.get(attacker_move, "PATCH")
        else:
            correct = get_counter(sc)
            
        return defender_move != correct

    def step(self, action: IncidentResponseAction) -> IncidentResponseObservation:
        self._state.step_count += 1

        # If a client calls /step before /reset, initialize an episode so the env
        # never crashes with None episode/scenario state.
        if self.sc is None or self.ep is None:
            obs = self.reset()
            # Tell the caller what happened, but keep the same response shape.
            obs.metadata = {**(obs.metadata or {}), "auto_reset": True}
            return obs
        
        if action.role == "attacker":
            # Save attacker move and prompt defender
            self.last_attacker_move = self._parse_attack(action.command)
            
            attacker_mem_lines = self._defender_memory_lines()
            prompt = self.env.defender_prompt(self.sc, self.ep, self.last_attacker_move, attacker_mem_lines)
            
            # For attacker, we might provide a partial reward or wait till the end of the round.
            # In GRPO, rewards are computed externally based on the outcomes. Here we just return 0.
            return IncidentResponseObservation(
                prompt=prompt,
                health=self.ep.health,
                status=self.ep.status(),
                next_role="defender",
                done=False,
                reward=0.0,
                history=self._history_payload(),
                breached=None,
                damage=None,
                last_attack=None,
                last_defense=None,
                metadata={
                    "scenario": self.sc["id"],
                    "step": self.ep.step,
                    "pending_attack": self.last_attacker_move,
                },
            )
            
        elif action.role == "defender":
            # Defender can't act before an attacker move has been recorded.
            if not self.last_attacker_move:
                defender_mem_line = self._attacker_memory_line()
                prompt = self.env.attacker_prompt(self.sc, self.ep, defender_mem_line)
                return IncidentResponseObservation(
                    prompt=prompt,
                    health=self.ep.health,
                    status=self.ep.status(),
                    next_role="attacker",
                    done=False,
                    reward=0.0,
                    metadata={
                        "scenario": self.sc["id"],
                        "step": self.ep.step,
                        "error": "defender_step_without_attacker_move",
                    },
                )
            defender_move = self._parse_defense(action.command)
            breached = self._outcome_breached(self.sc, self.last_attacker_move, defender_move, self.ep)
            
            # Apply to episode state
            prev_health = self.ep.health
            self.ep.apply(self.last_attacker_move, defender_move, breached)
            damage = round(prev_health - self.ep.health, 4)
            
            # Update memory
            if self.last_attacker_move in ATTACKS:
                self.recent_attacks.append(self.last_attacker_move)
                if breached:
                    self.recent_breaches.append(self.last_attacker_move)
            if defender_move in DEFENSES:
                self.recent_defenses.append(defender_move)
                
            self._state.health = self.ep.health
            self._state.status = self.ep.status()
            
            done = (self.ep.step >= EPISODE_STEPS)
            
            if done:
                prompt = "Episode Complete."
                next_role = "done"
            else:
                defender_mem_line = self._attacker_memory_line()
                prompt = self.env.attacker_prompt(self.sc, self.ep, defender_mem_line)
                next_role = "attacker"
            
            # When a breach happens, reflect it explicitly in the observation status.
            # (The underlying episode status still exists via health thresholds.)
            obs_status = f"BREACHED(-{damage})" if breached and damage > 0 else self.ep.status()
                
            return IncidentResponseObservation(
                prompt=prompt,
                health=self.ep.health,
                status=obs_status,
                next_role=next_role,
                done=done,
                reward=0.0, # Handled externally by reward functions in RL script
                history=self._history_payload(),
                breached=breached,
                damage=(damage if breached and damage > 0 else None),
                last_attack=self.last_attacker_move,
                last_defense=defender_move,
                metadata={"scenario": self.sc["id"], "step": self.ep.step},
            )

        # Invalid role
        return IncidentResponseObservation(
            prompt="Invalid role. Must be 'attacker' or 'defender'.",
            health=self.ep.health,
            status=self.ep.status(),
            next_role="attacker",
            done=True,
            reward=0.0
        )

    @property
    def state(self) -> IncidentResponseState:
        """
        Get the current environment state.
        """
        return self._state
