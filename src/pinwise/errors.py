class PinwiseError(Exception):
    """Base class for errors that stop a pinwise command."""


class GitError(PinwiseError):
    pass


class AstGrepError(PinwiseError):
    pass


class InvalidPinError(PinwiseError):
    """A pin directory or its pin.yaml is not valid. `where` is the path to report."""

    def __init__(self, message: str, *, where: str) -> None:
        super().__init__(message)
        self.where = where
