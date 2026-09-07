class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}

    def payload(self, correlation_id):
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "correlationId": correlation_id,
            }
        }
