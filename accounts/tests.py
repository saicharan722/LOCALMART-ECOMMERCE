from django.test import TestCase
from django.contrib.auth import get_user_model

from .forms import AdminProfileForm


class AdminProfileValidationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="profile-admin",
            email="admin@example.com",
            password="test-password",
        )

    def test_profile_form_rejects_non_numeric_mobile_numbers(self):
        form = AdminProfileForm(
            data={
                "first_name": "Asha",
                "last_name": "Admin",
                "email": self.user.email,
                "mobile_number": "98765abc10",
                "image_url": "",
            },
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("digits only", str(form.errors["mobile_number"]))
