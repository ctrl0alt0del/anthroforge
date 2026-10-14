"""Composition root: detectors and direct reports share one authoritative store."""
from .listening import Listening
from .presentation import Presentation
from .reporting import Reporting
from .resolution import Resolution


class IssueSystem:
    def __init__(self, repository, coordinator):
        self.repository = repository
        self.listening = Listening(coordinator)
        self.reporting = Reporting(repository)
        self.presentation = Presentation(repository)
        self.resolution = Resolution(repository, self.listening)

    def reset(self):
        self.reporting.reset()
        self.presentation.dismissed.clear()
        self.resolution.running.clear()
