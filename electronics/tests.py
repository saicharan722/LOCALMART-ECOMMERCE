from django.test import TestCase
from django.urls import reverse


class ElectronicsWishlistTests(TestCase):
    def test_empty_wishlist_keeps_the_cta_icon_separate_from_the_heart_icon(self):
        response = self.client.get("/electronics/wishlist/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<i class="bi bi-heart wishlist-empty-icon" aria-hidden="true"></i>',
        )
        self.assertContains(response, 'class="continue-shopping"')
        self.assertContains(response, '<i class="bi bi-arrow-left"></i>')


class ElectronicsHomeNavbarTests(TestCase):
    def test_account_dropdown_contains_my_orders(self):
        response = self.client.get(reverse("electronics_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<summary class="nav-link nav-account-trigger">')
        self.assertContains(response, '<span class="nav-label">Account</span>')
        self.assertContains(
            response,
            f'<a href="{reverse("my_orders")}">',
        )
        self.assertContains(response, "<span>My Orders</span>")
