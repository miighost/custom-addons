class ApiError(Exception):
    """A refusal the app should show, e.g. a wallet too low or a declined card.

    Raised anywhere under an API call, it rolls back everything the call wrote
    and answers {"error": code, **details} with HTTP 200 - the same shape as
    every other business refusal, so the app branches on `error`.
    """

    def __init__(self, code, **details):
        super().__init__(code)
        self.code = code
        self.details = details
