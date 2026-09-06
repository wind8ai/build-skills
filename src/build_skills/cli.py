"""Command-line interface."""

import json
from pathlib import Path
from typing import Annotated

import typer

from build_skills.config import load_config

app = typer.Typer(no_args_is_help=True)
ConfigPath = Annotated[Path, typer.Option("--config")]


@app.command()
def doctor(config: ConfigPath, json_output: bool = typer.Option(False, "--json")) -> None:
    """Validate configuration without calling models."""
    try:
        loaded = load_config(config)
        result = {
            "status": "ready",
            "workspace": loaded.workspace,
            "providers": list(loaded.providers),
            "model_access": "not_checked",
        }
        typer.echo(json.dumps(result) if json_output else result)
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


@app.command()
def version() -> None:
    """Show the installed package version."""
    from importlib.metadata import version as package_version

    typer.echo(package_version("build-skills"))


def register_stage(name: str) -> None:
    def command(
        config: ConfigPath,
        run: str | None = typer.Option(None, "--run"),
        accept: str | None = typer.Option(None, "--accept"),
        feedback_file: Annotated[Path | None, typer.Option("--file")] = None,
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        from build_skills.workflow import Workflow
        from build_skills.workspace import WorkflowError, locked

        workflow = None
        code = 0
        try:
            loaded = load_config(config)
            if run is None and name not in {"prepare", "loop"}:
                raise ValueError("--run is required")
            workflow = Workflow(loaded, run)
            with locked(workflow.root):
                try:
                    workflow.load(create=name in {"prepare", "loop"} and run is None)
                    if name == "approve":
                        workflow.approve(accept)
                    elif name == "feedback":
                        if feedback_file is None:
                            raise ValueError("--file is required")
                        workflow.feedback(feedback_file)
                    elif name != "status":
                        getattr(workflow, name)()
                    result = workflow.status()
                except (OSError, ValueError, WorkflowError, KeyboardInterrupt) as exc:
                    code = (
                        exc.code
                        if isinstance(exc, WorkflowError)
                        else 130
                        if isinstance(exc, KeyboardInterrupt)
                        else 2
                    )
                    if workflow.state and code in {3, 4, 5, 130}:
                        workflow.state["status"] = {
                            3: "awaiting_approval",
                            4: "unmet",
                            5: "failed",
                            130: "interrupted",
                        }[code]
                        workflow.save()
                    try:
                        result = workflow.status() | {"error": str(exc)}
                    except (ValueError, OSError):
                        result = dict(workflow.state) | {"error": str(exc)}
        except (OSError, ValueError, WorkflowError) as exc:
            code = exc.code if isinstance(exc, WorkflowError) else 2
            result = {"error": str(exc), "status": "failed"}
        typer.echo(json.dumps(result) if json_output else result)
        if code:
            raise typer.Exit(code)

    app.command(name)(command)


for stage in (
    "prepare",
    "approve",
    "status",
    "loop",
    "build",
    "execute",
    "evaluate",
    "improve",
    "verify",
    "deliver",
    "feedback",
):
    register_stage(stage)
