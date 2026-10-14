"""Registered detectors own their domains; this dispatcher owns no issue types."""


class Listening:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    def register(self, listener):
        self.coordinator.register(listener)
        return lambda: self.unregister(listener.name)

    def unregister(self, name):
        self.coordinator.factories.pop(name, None)
        for key in tuple(self.coordinator.jobs):
            if isinstance(key, tuple) and len(key) == 2 and key[0] == name:
                self.coordinator.cancel(key)
        for scope, provider in tuple(self.coordinator.repository.provider_states):
            if provider == name:
                self.coordinator.repository.state(scope, "CANCELLED", provider=name)

    def notify(self, event, context=None):
        self.coordinator.on_action(event, context)

    def recheck(self, provider=None, context=None):
        selected = self.coordinator.factories
        if provider is not None and provider not in selected:
            raise ValueError("The issue's detector is unavailable")
        for name, listener in tuple(selected.items()):
            if provider is None or name == provider:
                listener.check_all(context)

    def schedule(self, provider, scope, builder, delay=.15):
        return self.coordinator.enqueue((provider, scope), builder, delay)
