class ValidationError(Exception):
    """Input parameters or steps are invalid."""

    pass


class ConfigError(Exception):
    """Server-side qdyn.yaml configuration is missing or incomplete."""

    pass


class ResumeError(Exception):
    """Resume failed: previous task/job not found or has no output."""

    pass


class QueryError(Exception):
    """Error during querying job status or output."""

    pass
