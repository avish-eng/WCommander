from __future__ import annotations

from dataclasses import dataclass

from multipane_commander.config.load import load_config, save_config
from multipane_commander.config.model import AppConfig
from multipane_commander.state.model import AppState
from multipane_commander.state.store import load_state, save_state


@dataclass(slots=True)
class AppContext:
    config: AppConfig
    state: AppState


def build_app_context() -> AppContext:
    return AppContext(
        config=load_config(),
        state=load_state(),
    )


def persist_app_context(context: AppContext) -> None:
    save_config(context.config)
    save_state(context.state)
