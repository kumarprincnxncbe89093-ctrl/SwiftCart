import io
import re
import unittest
from pathlib import Path

from backend.app import app


BASE_DIR = Path(__file__).resolve().parents[1]
SAMPLE_IMAGE_PATH = BASE_DIR / "frontend" / "images" / "Swiftcart_logo3.png"
PRODUCT_UPLOAD_DIR = BASE_DIR / "frontend" / "uploads" / "products"


class ProductImageUploadTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def _solve_captcha(self) -> dict:
        payload = self.client.get("/api/auth/captcha").get_json()
        prompt = payload["prompt"]
        left, right = map(int, re.findall(r"-?\d+", prompt))
        if "+" in prompt:
            answer = left + right
        elif "-" in prompt:
            answer = left - right
        else:
            answer = left * right
        return {
            "captcha_id": payload["captcha_id"],
            "captcha_answer": str(answer),
        }

    def _login(self, email: str, password: str = "123456") -> str:
        response = self.client.post(
            "/api/auth/login",
            json={
                "email": email,
                "password": password,
                **self._solve_captcha(),
            },
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        data = response.get_json()
        self.assertIsNotNone(data)
        return data["token"]

    def _cleanup_files(self, created_files: set[Path]) -> None:
        for path in created_files:
            if path.exists():
                path.unlink()

    def _uploaded_files(self) -> set[Path]:
        PRODUCT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        return {path for path in PRODUCT_UPLOAD_DIR.iterdir() if path.is_file()}

    def test_merchant_product_image_upload_succeeds(self):
        token = self._login("merchant@demo.com")
        before_files = self._uploaded_files()

        with SAMPLE_IMAGE_PATH.open("rb") as handle:
            response = self.client.post(
                "/api/merchant/uploads/product-image?user_id=13",
                headers={"Authorization": f"Bearer {token}"},
                data={"image": (handle, SAMPLE_IMAGE_PATH.name)},
            )

        created_files = self._uploaded_files() - before_files
        self.addCleanup(self._cleanup_files, created_files)

        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        data = response.get_json()
        self.assertIsNotNone(data)
        self.assertEqual(data["merchant"]["id"], 13)
        self.assertRegex(data["image"], r"^uploads/products/product-[a-f0-9]{16}\.png$")

    def test_owner_product_image_upload_succeeds(self):
        token = self._login("owner@demo.com")
        before_files = self._uploaded_files()

        with SAMPLE_IMAGE_PATH.open("rb") as handle:
            response = self.client.post(
                "/api/admin/uploads/product-image?user_id=5",
                headers={"Authorization": f"Bearer {token}"},
                data={"image": (handle, SAMPLE_IMAGE_PATH.name)},
            )

        created_files = self._uploaded_files() - before_files
        self.addCleanup(self._cleanup_files, created_files)

        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        data = response.get_json()
        self.assertIsNotNone(data)
        self.assertRegex(data["image"], r"^uploads/products/product-[a-f0-9]{16}\.png$")

    def test_owner_upload_returns_json_when_file_is_too_large(self):
        token = self._login("owner@demo.com")
        oversized_file = io.BytesIO(b"a" * (app.config["MAX_CONTENT_LENGTH"] + 1))

        response = self.client.post(
            "/api/admin/uploads/product-image?user_id=5",
            headers={"Authorization": f"Bearer {token}"},
            data={"image": (oversized_file, "too-large.png")},
        )

        self.assertEqual(response.status_code, 413, response.get_data(as_text=True))
        data = response.get_json()
        self.assertIsNotNone(data)
        self.assertEqual(data["max_upload_mb"], 10)
        self.assertIn("smaller than 10 MB", data["message"])


if __name__ == "__main__":
    unittest.main()
