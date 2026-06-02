from abc import ABC, abstractmethod


CONTROL_LIFECYCLE_KEY = "af_control_lifecycle"
CONTROL_LIFECYCLE_DYNAMIC = "DYNAMIC"
CONTROL_LIFECYCLE_PERSISTENT = "PERSISTENT"


class ControlLifecycleStrategy(ABC):
    @abstractmethod
    def lifecycle(self):
        raise NotImplementedError

    @abstractmethod
    def should_remove_on_save(self):
        raise NotImplementedError

    @abstractmethod
    def should_remove_on_load(self):
        raise NotImplementedError

    def mark(self, obj):
        if obj is None:
            return None
        obj[CONTROL_LIFECYCLE_KEY] = self.lifecycle()
        return obj


class DynamicControlLifecycleStrategy(ControlLifecycleStrategy):
    def lifecycle(self):
        return CONTROL_LIFECYCLE_DYNAMIC

    def should_remove_on_save(self):
        return True

    def should_remove_on_load(self):
        return True


class PersistentControlLifecycleStrategy(ControlLifecycleStrategy):
    def lifecycle(self):
        return CONTROL_LIFECYCLE_PERSISTENT

    def should_remove_on_save(self):
        return False

    def should_remove_on_load(self):
        return False


_DYNAMIC_CONTROL_LIFECYCLE = DynamicControlLifecycleStrategy()
_PERSISTENT_CONTROL_LIFECYCLE = PersistentControlLifecycleStrategy()


def control_lifecycle_strategy(obj):
    if obj is not None and str(obj.get(CONTROL_LIFECYCLE_KEY, "") or "").upper() == CONTROL_LIFECYCLE_PERSISTENT:
        return _PERSISTENT_CONTROL_LIFECYCLE
    if obj is not None and bool(obj.get("af_scp_control")):
        return _PERSISTENT_CONTROL_LIFECYCLE
    return _DYNAMIC_CONTROL_LIFECYCLE


def mark_dynamic_control_object(obj):
    return _DYNAMIC_CONTROL_LIFECYCLE.mark(obj)


def mark_persistent_control_object(obj):
    return _PERSISTENT_CONTROL_LIFECYCLE.mark(obj)


def should_remove_control_object_on_save(obj):
    return bool(control_lifecycle_strategy(obj).should_remove_on_save())


def should_remove_control_object_on_load(obj):
    return bool(control_lifecycle_strategy(obj).should_remove_on_load())


def clear_control_lifecycle(obj):
    if obj is None:
        return
    if CONTROL_LIFECYCLE_KEY in obj:
        del obj[CONTROL_LIFECYCLE_KEY]
