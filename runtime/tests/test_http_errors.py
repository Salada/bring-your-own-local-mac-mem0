import unittest

from fastapi import HTTPException
from mem0.exceptions import LLMError, MemoryNotFoundError, ValidationError

from http_errors import to_http_exception


class HttpErrorTest(unittest.TestCase):
    def assert_http_error(self, exc, status, detail):
        result = to_http_exception(exc)
        self.assertEqual(result.status_code, status)
        self.assertEqual(result.detail, detail)

    def test_preserves_explicit_http_errors(self):
        exc = HTTPException(status_code=400, detail="Missing 'text' or 'data'")
        self.assertIs(to_http_exception(exc), exc)

    def test_maps_not_found_to_404(self):
        self.assert_http_error(ValueError("Memory with id x not found"), 404, "Memory with id x not found")
        self.assert_http_error(
            MemoryNotFoundError("Memory not found", "MEM_404"),
            404,
            "Memory not found",
        )

    def test_maps_validation_to_400(self):
        self.assert_http_error(ValueError("Invalid filter"), 400, "Invalid filter")
        self.assert_http_error(ValidationError("Invalid input", "VALIDATION_001"), 400, "Invalid input")

    def test_reserves_5xx_for_server_failures(self):
        self.assert_http_error(LLMError("Provider unavailable"), 502, "Provider unavailable")
        self.assert_http_error(RuntimeError("unexpected implementation failure"), 500, "Internal server error")


if __name__ == "__main__":
    unittest.main()
