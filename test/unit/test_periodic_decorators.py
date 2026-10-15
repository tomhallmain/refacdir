"""The periodic decorators keep the decorated function's identity.

A compiled build takes a different path through PySide6's signal handling,
where every decorated method named ``wrapper`` made connected actions all run
the last one connected; ``functools.wraps`` fixed it.
"""

from refacdir.running_tasks_registry import periodic
from refacdir.utils.utils import Utils


def test_registry_periodic_keeps_the_name():
    class Owner:
        @periodic("recurring")
        async def run_recurring(self):
            pass

    assert Owner.run_recurring.__name__ == "run_recurring"
    assert Owner.run_recurring.__qualname__.endswith("Owner.run_recurring")


def test_utils_periodic_keeps_the_name():
    @Utils.periodic(5)
    async def poll():
        pass

    assert poll.__name__ == "poll"
