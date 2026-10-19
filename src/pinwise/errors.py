class PinwiseError(Exception):
    """Base class for errors that stop a pinwise command."""


class GitError(PinwiseError):
    pass


class AstGrepError(PinwiseError):
    pass


class InvalidPinError(PinwiseError):
    pass
