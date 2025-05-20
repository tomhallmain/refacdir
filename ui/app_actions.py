from typing import Callable, Dict, Any

class AppActions:
    REQUIRED_ACTIONS = {
        "toast", "alert", "progress_text", "progress_bar_update", "progress_bar_reset",
    }
    
    def __init__(self, actions: Dict[str, Callable[..., Any]]):
        missing = self.REQUIRED_ACTIONS - set(actions.keys())
        if missing:
            raise ValueError(f"Missing required actions: {missing}")
        self._actions = actions
    
    def __getattr__(self, name):
        if name in self._actions:
            return self._actions[name]
        raise AttributeError(f"Action '{name}' not found")
