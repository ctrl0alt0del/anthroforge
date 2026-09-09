"""Expected authoring failures, separate from programming errors."""


class AuthoringError(ValueError):
    def __init__(self, code, message="", pointer="", related=()):
        super().__init__(message or code.replace("_", " ").capitalize())
        self.code, self.pointer, self.related = code, pointer, tuple(related)

    def diagnostic(self):
        return dict(code=self.code, severity="error", document_pointer=self.pointer,
                    message=str(self), related_ids=list(self.related))


def require(condition, code, message="", pointer=""):
    if not condition:
        raise AuthoringError(code, message, pointer)
