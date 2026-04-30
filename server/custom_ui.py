"""
Custom Gradio UI for the Incident Response Env.

Replaces the default OpenEnv playground with one that:
  - Shows the legal Role choices directly in the label: "Role (attacker / defender)".
  - Binds each action to an integer 0..N-1 and shows the integer-to-command
    mapping inline (with the table re-rendering when the role flips).
  - Adds a "Run model" button that loads the GRPO checkpoint from HF and
    auto-generates the next action, with live status messages.
  - Embeds the GRPO training notebook below the playground via an iframe.
"""

from __future__ import annotations

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr

from .incident_response_env_environment import ATTACKS, DEFENSES

try:
    from .model_runner import generate_action as _model_generate_action
    _MODEL_AVAILABLE = True
except ImportError:
    _MODEL_AVAILABLE = False

_MODEL_EXECUTOR = ThreadPoolExecutor(max_workers=1)


ROLE_CHOICES: List[str] = ["attacker", "defender"]


def _action_choices(role: str) -> List[Tuple[str, int]]:
    """Return (label, value) pairs for the Action ID dropdown."""
    items = ATTACKS if role == "attacker" else DEFENSES
    prefix = "ATTACK" if role == "attacker" else "DEFEND"
    return [(f"{i}: {prefix} {name}", i) for i, name in enumerate(items)]


def _command_for(role: str, action_id: int) -> str:
    """Translate a (role, integer) pair into the env's expected command string."""
    if role == "attacker":
        return f"ATTACK: {ATTACKS[action_id]}"
    return f"DEFEND: {DEFENSES[action_id]}"


def _mapping_md(role: str) -> str:
    """Markdown table showing the active integer-to-command mapping."""
    items = ATTACKS if role == "attacker" else DEFENSES
    prefix = "ATTACK" if role == "attacker" else "DEFEND"
    rows = "\n".join(f"| **{i}** | `{prefix}: {name}` |" for i, name in enumerate(items))
    return (
        f"#### Action ID mapping for role `{role}`\n"
        f"_The integer you pick is sent as `{prefix}: <NAME>`._\n\n"
        "| ID | Command sent |\n"
        "|---:|:-------------|\n"
        f"{rows}\n"
    )


def prepare_notebook_html(notebook_path: Path, out_path: Path) -> Path:
    """
    Convert a Jupyter notebook into a self-contained HTML file.

    Tries `nbconvert` first (full Jupyter rendering, including outputs and
    syntax highlighting). Falls back to a minimal hand-rolled renderer when
    nbconvert is unavailable so the server still starts cleanly.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import nbformat
        from nbconvert import HTMLExporter

        nb = nbformat.read(str(notebook_path), as_version=4)
        exporter = HTMLExporter(template_name="lab")
        exporter.embed_images = True
        body, _ = exporter.from_notebook_node(nb)
        out_path.write_text(body, encoding="utf-8")
        return out_path
    except Exception as exc:  # pragma: no cover - fallback path
        try:
            nb = json.loads(notebook_path.read_text(encoding="utf-8"))
        except Exception as read_exc:
            out_path.write_text(
                f"<html><body><pre>Could not load notebook: {read_exc}</pre></body></html>",
                encoding="utf-8",
            )
            return out_path

        parts: List[str] = [
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>GRPO Notebook (raw)</title>"
            "<style>"
            "body{font-family:ui-sans-serif,system-ui,-apple-system;padding:1.25rem;"
            "max-width:980px;margin:0 auto;color:#0f172a;background:#fff;}"
            "h1,h2,h3{margin-top:1.5rem;}"
            "pre{background:#0f172a;color:#e2e8f0;padding:.85rem 1rem;border-radius:8px;"
            "overflow:auto;line-height:1.45;font-size:13px;}"
            "code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}"
            ".cell{margin:1.25rem 0;border-left:3px solid #e2e8f0;padding-left:.85rem;}"
            ".md{white-space:pre-wrap;}"
            ".note{background:#fef3c7;color:#78350f;padding:.6rem .8rem;border-radius:6px;"
            "margin-bottom:1rem;font-size:13px;}"
            "</style></head><body>",
            "<div class='note'>Rendered with the built-in fallback "
            f"(install <code>nbconvert</code> for full output). Reason: <code>{exc}</code></div>",
            "<h1>GRPO Training Notebook</h1>",
        ]
        for cell in nb.get("cells", []):
            src = "".join(cell.get("source", []))
            if cell.get("cell_type") == "markdown":
                parts.append(f"<div class='cell md'>{src}</div>")
            else:
                escaped = (
                    src.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                parts.append(f"<div class='cell'><pre><code>{escaped}</code></pre></div>")
        parts.append("</body></html>")
        out_path.write_text("\n".join(parts), encoding="utf-8")
        return out_path


def _strip_prompt_from_response_for_display(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove the (often very long) `observation.prompt` field from the JSON shown in
    the UI, while keeping the server response unchanged.
    """
    if not isinstance(data, dict):
        return {}
    out = dict(data)
    obs = out.get("observation")
    if isinstance(obs, dict) and "prompt" in obs:
        obs2 = dict(obs)
        obs2.pop("prompt", None)
        out["observation"] = obs2
    return out


def build_custom_ui(
    web_manager: Any,
    metadata: Optional[Any],
    quick_start_md: Optional[str],
    notebook_iframe_url: str,
) -> gr.Blocks:
    """Build the full /web Gradio app: playground + embedded GRPO notebook."""
    title = getattr(metadata, "name", None) or "Incident Response Env"
    readme_content = getattr(metadata, "readme_content", None) if metadata else None
    display_title = f"OpenEnv Agentic Environment: {title}"
    project_readme_path = Path(__file__).resolve().parent.parent / "README.md"
    project_readme_md = (
        project_readme_path.read_text(encoding="utf-8")
        if project_readme_path.exists()
        else ""
    )
    if project_readme_md.startswith("---"):
        project_readme_md = re.sub(
            r"^---\s*\n.*?\n---\s*\n",
            "",
            project_readme_md,
            count=1,
            flags=re.DOTALL,
        )
    project_readme_md = re.sub(
        r"(!\[[^\]]*\]\()(?!https?://|/)([^)]+)(\))",
        lambda m: f"{m.group(1)}/{m.group(2).lstrip('./')}{m.group(3)}",
        project_readme_md,
    )

    async def reset_env():
        try:
            data = await web_manager.reset_environment()
            obs = data.get("observation", {}) or {}
            next_role = obs.get("next_role", "attacker")
            health = obs.get("health", 1.0)
            status_text = obs.get("status", "STABLE")

            role_value = next_role if next_role in ROLE_CHOICES else "attacker"
            new_choices = _action_choices(role_value)
            # User requested: never show the prompt in the UI.
            obs_md = ""
            return (
                gr.update(value=role_value),
                gr.update(
                    choices=new_choices,
                    value=new_choices[0][1] if new_choices else None,
                    label=f"Action ID (0..{len(new_choices) - 1})",
                ),
                _mapping_md(role_value),
                obs_md,
                json.dumps(_strip_prompt_from_response_for_display(data), indent=2),
                f"Reset OK | health={health:.0%} | status={status_text} | next_role={role_value}",
            )
        except Exception as exc:
            return (
                gr.update(),
                gr.update(),
                gr.update(),
                "",
                "",
                f"Error during reset: {exc}",
            )

    async def step_env(role: str, action_id: Optional[int]):
        try:
            # If the user clicks Step before any Reset, the underlying env session
            # has no episode state yet. Auto-reset once to avoid None-state errors.
            try:
                if getattr(web_manager, "episode_state", None) is not None and (
                    web_manager.episode_state.current_observation is None
                ):
                    await web_manager.reset_environment()
            except Exception:
                # If we can't read/reset episode_state for any reason, keep going
                # and let the environment raise a more specific error.
                pass

            if role not in ROLE_CHOICES:
                return (gr.update(), gr.update(), gr.update(), "", "", "Pick a role first.")
            if action_id is None:
                return (gr.update(), gr.update(), gr.update(), "", "", "Pick an Action ID first.")

            ai = int(action_id)
            universe = ATTACKS if role == "attacker" else DEFENSES
            if not 0 <= ai < len(universe):
                return (
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    "",
                    "",
                    f"Invalid Action ID for `{role}` (must be 0..{len(universe) - 1}).",
                )

            command = _command_for(role, ai)
            data = await web_manager.step_environment({"command": command, "role": role})
            obs = data.get("observation", {}) or {}
            next_role = obs.get("next_role", role)
            health = obs.get("health", 1.0)
            status_text = obs.get("status", "STABLE")
            done = bool(obs.get("done", False))
            meta = obs.get("metadata", {}) or {}

            role_value = next_role if next_role in ROLE_CHOICES else role
            new_choices = _action_choices(role_value)
            done_md = " Episode complete — click Reset." if done else ""
            breached = meta.get("breached")
            breach_part = f" | breached={breached}" if breached is not None else ""

            # User requested: never show the prompt in the UI.
            obs_md = ""
            return (
                gr.update(value=role_value),
                gr.update(
                    choices=new_choices,
                    value=new_choices[0][1] if new_choices else None,
                    label=f"Action ID (0..{len(new_choices) - 1})",
                ),
                _mapping_md(role_value),
                obs_md,
                json.dumps(_strip_prompt_from_response_for_display(data), indent=2),
                f"Step OK | health={health:.0%} | status={status_text}{breach_part} | next_role={next_role}.{done_md}",
            )
        except Exception as exc:
            return (
                gr.update(),
                gr.update(),
                gr.update(),
                "",
                "",
                f"Error during step: {exc}",
            )

    def get_state_sync():
        try:
            return json.dumps(web_manager.get_state(), indent=2)
        except Exception as exc:
            return f"Error: {exc}"

    def on_role_change(role: str):
        new_choices = _action_choices(role)
        return (
            gr.update(
                choices=new_choices,
                value=new_choices[0][1] if new_choices else None,
                label=f"Action ID (0..{len(new_choices) - 1})",
            ),
            _mapping_md(role),
        )

    async def run_model(role: str):
        """
        Load the GRPO checkpoint for the current role and auto-generate an action,
        then step the environment with the result.
        """
        _blank = (gr.update(), gr.update(), gr.update(), "", "", "")

        if not _MODEL_AVAILABLE:
            return (*_blank[:5], "transformers/torch not installed — cannot run model.")

        if role not in ROLE_CHOICES:
            return (*_blank[:5], "Select a role first.")

        # Ensure an episode is active
        try:
            current_obs = (
                web_manager.episode_state.current_observation
                if web_manager.episode_state and web_manager.episode_state.current_observation
                else None
            )
        except Exception:
            current_obs = None

        if current_obs is None:
            await web_manager.reset_environment()
            try:
                current_obs = web_manager.episode_state.current_observation
            except Exception:
                current_obs = {}

        prompt = (current_obs or {}).get("prompt", "") if isinstance(current_obs, dict) else ""

        if not prompt:
            return (*_blank[:5], "No prompt yet — click Reset first.")

        status_msgs: List[str] = []

        def _status_cb(msg: str):
            status_msgs.append(msg)

        loop = asyncio.get_event_loop()
        try:
            command = await loop.run_in_executor(
                _MODEL_EXECUTOR,
                lambda: _model_generate_action(role, prompt, _status_cb),
            )
        except Exception as exc:
            return (*_blank[:5], f"Model error: {exc}")

        all_status = " → ".join(status_msgs)

        if not command:
            return (*_blank[:5], f"Model produced no valid action. {all_status}")

        try:
            data = await web_manager.step_environment({"command": command, "role": role})
        except Exception as exc:
            return (*_blank[:5], f"Step error after model action: {exc}")

        obs         = data.get("observation", {}) or {}
        next_role   = obs.get("next_role", role)
        health      = obs.get("health", 1.0)
        status_text = obs.get("status", "STABLE")
        done        = bool(obs.get("done", False))
        role_value  = next_role if next_role in ROLE_CHOICES else role
        new_choices = _action_choices(role_value)
        done_note   = " Episode complete — click Reset." if done else ""

        return (
            gr.update(value=role_value),
            gr.update(choices=new_choices, value=new_choices[0][1] if new_choices else None,
                      label=f"Action ID (0..{len(new_choices) - 1})"),
            _mapping_md(role_value),
            "",
            json.dumps(_strip_prompt_from_response_for_display(data), indent=2),
            f"Model → {command} | health={health:.0%} | {status_text} | next={next_role}.{done_note}",
        )

    initial_role = "attacker"
    initial_choices = _action_choices(initial_role)

    with gr.Blocks(title=display_title) as demo:
        gr.HTML(
            """
<style>
  .oe_sidebar {
    position: fixed;
    left: 14px;
    top: 14px;
    width: 210px;
    z-index: 9999;
    background: #ffffff;
    border: 2px solid #111827;
    border-radius: 12px;
    padding: 14px 12px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.18);
  }
  .oe_sidebar_title {
    font-weight: 700;
    margin: 0 0 4px 0;
    font-size: 12px;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: #111827;
  }
  .oe_sidebar_subtitle {
    margin: 0 0 10px 0;
    font-size: 11px;
    color: #6b7280;
    font-style: italic;
  }
  .oe_sidebar a {
    display: block;
    padding: 9px 12px;
    margin: 6px 0;
    border-radius: 8px;
    color: #111827;
    text-decoration: none;
    font-size: 13px;
    font-weight: 600;
    background: #f3f4f6;
    border: 1px solid #111827;
    transition: background .15s, transform .05s, color .15s;
  }
  .oe_sidebar a:hover { background: #e5e7eb; color: #000000; }
  .oe_sidebar a:active { transform: translateY(1px); }
  @media (min-width: 1100px) { .col-left { margin-left: 240px; } }
  .oe_readme_wrap {
    max-width: 1100px;
    margin: 0 auto 16px auto;
    padding: 14px 16px;
    border: 2px solid #111827;
    border-radius: 12px;
    background: #ffffff;
    box-shadow: 0 10px 40px rgba(0,0,0,0.10);
  }
  .oe_readme_title {
    font-weight: 700;
    margin: 0 0 10px 0;
    font-size: 14px;
    color: #111827;
  }
  .oe_readme_scroll {
    max-height: 340px;
    overflow-y: auto;
    padding-right: 6px;
  }
</style>
<nav class="oe_sidebar">
  <div class="oe_sidebar_title">Jump to</div>
  <div class="oe_sidebar_subtitle">(in order on this page)</div>
  <a href="javascript:void(0)" onclick="document.getElementById('readme_md').scrollIntoView({behavior:'smooth'})">README.md</a>
  <a href="javascript:void(0)" onclick="document.getElementById('interactive_playground').scrollIntoView({behavior:'smooth'})">Interactive Playground</a>
  <a href="javascript:void(0)" onclick="document.getElementById('grpo_training_notebook').scrollIntoView({behavior:'smooth'})">GRPO Training Notebook</a>
</nav>
"""
        )

        gr.HTML('<div id="readme_md"></div>')
        if project_readme_md:
            gr.HTML("<div class='oe_readme_wrap'><div class='oe_readme_title'>README.md</div><div class='oe_readme_scroll'>")
            gr.Markdown(project_readme_md)
            gr.HTML("</div></div>")

        gr.HTML('<div id="interactive_playground"></div>')
        with gr.Row():
            with gr.Column(scale=1, elem_classes="col-left"):
                # Replace the default Quick Start section with the integer binding table,
                # so users can always see how Action IDs map to commands.
                mapping_md = gr.Markdown(_mapping_md(initial_role))
                if readme_content:
                    with gr.Accordion("README", open=False):
                        gr.Markdown(readme_content)

            with gr.Column(scale=2, elem_classes="col-right"):
                gr.Markdown(f"# Playground — {title}\nClick **Reset** to start a new episode.")

                role_dd = gr.Dropdown(
                    choices=ROLE_CHOICES,
                    value=initial_role,
                    label="Role (attacker / defender)",
                    info="Whose turn it is. Reset will set this automatically based on the env.",
                    allow_custom_value=False,
                )
                action_dd = gr.Dropdown(
                    choices=initial_choices,
                    value=initial_choices[0][1],
                    label=f"Action ID (0..{len(initial_choices) - 1})",
                    info="Integer index into the role's action universe (see mapping below).",
                    allow_custom_value=False,
                )
                gr.Markdown("*Action ID mapping is shown on the left.*")

                with gr.Row():
                    step_btn  = gr.Button("Step", variant="primary")
                    reset_btn = gr.Button("Reset", variant="secondary")
                    state_btn = gr.Button("Get state", variant="secondary")
                    model_btn = gr.Button("Run model (takes 15-25s)", variant="stop")

                status_box = gr.Textbox(label="Status", interactive=False)

                # Prompt is intentionally hidden; keep a placeholder for spacing
                # and to keep the same output wiring for click handlers.
                obs_md = gr.Markdown(value="")
                raw_json = gr.Code(
                    label="Raw JSON response",
                    language="json",
                    interactive=False,
                )

        # Notebook embed directly under the interactive playground, but full width.
        gr.HTML(
            f'''<div id="grpo_training_notebook" style="margin-top:32px;">
  <div style="font-size:1.1rem;font-weight:600;padding:8px 0 12px 0;">GRPO Training Notebook</div>
  <style>
    #grpo_nb_frame_wrap {{
      width: 100vw;
      position: relative;
      left: 50%;
      transform: translateX(-50%);
      box-sizing: border-box;
      overflow-x: hidden;
    }}
    #grpo_nb_frame_wrap iframe {{
      width: 100vw;
      height: 960px;
      border: none;
      display: block;
    }}
  </style>
  <div id="grpo_nb_frame_wrap">
    <iframe src="{notebook_iframe_url}"></iframe>
  </div>
</div>'''
        )

        role_dd.change(on_role_change, inputs=role_dd, outputs=[action_dd, mapping_md])

        reset_btn.click(
            fn=reset_env,
            outputs=[role_dd, action_dd, mapping_md, obs_md, raw_json, status_box],
        )
        step_btn.click(
            fn=step_env,
            inputs=[role_dd, action_dd],
            outputs=[role_dd, action_dd, mapping_md, obs_md, raw_json, status_box],
        )
        model_btn.click(
            fn=run_model,
            inputs=[role_dd],
            outputs=[role_dd, action_dd, mapping_md, obs_md, raw_json, status_box],
        )
        state_btn.click(fn=get_state_sync, outputs=[raw_json])

    return demo
