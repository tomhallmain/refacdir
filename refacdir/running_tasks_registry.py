
import asyncio
import threading


class RunningTasksRegistry:
    def __init__(self):
        self.register = {}
    def is_running(self, register_id):
        return register_id in self.register and self.register[register_id][0]
    def add(self, register_id, sleep_time, name):
        self.register[register_id] = [True, sleep_time, name]
    def remove(self, register_id):
        self.register[register_id][0] = False
    def sleep_time(self, register_id):
        if not register_id in self.register:
            raise Exception(f'No such register id: {register_id}')
        return self.register[register_id][1]
    def name(self, register_id):
        if not register_id in self.register:
            raise Exception(f'No such register id: {register_id}')
        return self.register[register_id][2]


running_tasks_registry = RunningTasksRegistry()


def start_thread(callable, use_asyncio=True, args=None):
    if use_asyncio:
        def asyncio_wrapper():
            asyncio.run(callable())
        target_func = asyncio_wrapper
    else:
        target_func = callable
    if args:
        thread = threading.Thread(target=target_func, args=args)
    else:
        thread = threading.Thread(target=target_func)
    thread.daemon = True  # Daemon threads exit when the main process does
    thread.start()

def periodic(registry_attr_name):
    def scheduler(fcn):
        async def wrapper(*args, **kwargs):
            registry_id = getattr(getattr(args[0], registry_attr_name), "registry_id")
            print(f'Started periodic task: {running_tasks_registry.name(registry_id)}')
            while True:
                if registry_id is not None and not running_tasks_registry.is_running(registry_id):
                    print(f"Ended periodic task: {running_tasks_registry.name(registry_id)}")
                    return
                # else:
                #     print(f"Registry ID: {registry_id}")
                #     print(str(running_tasks_registry.register.get(registry_id, "Not found")))
                asyncio.create_task(fcn(*args, **kwargs))
                period = running_tasks_registry.sleep_time(registry_id)
                await asyncio.sleep(period)
        return wrapper
    return scheduler

class RecurringActionConfig:
    interval_seconds = 90

    def __init__(self):
        self.registry_id = f"recurring_action"
        self.is_running = False
        running_tasks_registry.add(self.registry_id, RecurringActionConfig.interval_seconds, f"Recurring Actions")

    def set(self, is_running):
        self.is_running = is_running
        if self.is_running:
            running_tasks_registry.add(self.registry_id, RecurringActionConfig.interval_seconds, f"Recurring Actions")
        else:
            running_tasks_registry.remove(self.registry_id)

    def end(self):
        self.is_running = False
        running_tasks_registry.remove(self.registry_id)
