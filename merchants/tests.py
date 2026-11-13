import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from types import SimpleNamespace

from ecommerce.views import _validate_merchant_store_checkout_lines
from .models import MerchantCategory, MerchantNotification, MerchantProduct, MerchantProfile


User = get_user_model()


class PublicMerchantStoreTests(TestCase):
    def setUp(self):
        self.owner_a = User.objects.create_user(username="merchant-a", password="test-password")
        self.owner_b = User.objects.create_user(username="merchant-b", password="test-password")
        self.store_a = MerchantProfile.objects.create(
            owner=self.owner_a,
            shop_name="Ramesh General Stores",
            address="Main Road",
            is_approved=True,
        )
        self.store_b = MerchantProfile.objects.create(
            owner=self.owner_b,
            shop_name="Other Local Store",
            is_approved=True,
        )
        self.pending_owner = User.objects.create_user(username="pending-merchant", password="test-password")
        self.pending_store = MerchantProfile.objects.create(
            owner=self.pending_owner,
            shop_name="Pending Shop",
        )
        self.category_a = MerchantCategory.objects.create(merchant=self.store_a, name="Dairy")
        self.category_b = MerchantCategory.objects.create(merchant=self.store_b, name="Snacks")
        self.milk = MerchantProduct.objects.create(
            merchant=self.store_a,
            category=self.category_a,
            name="Fresh Milk",
            sku="MILK-1",
            description="Daily dairy product",
            price="52.00",
            compare_at_price="60.00",
            stock=8,
        )
        self.other_product = MerchantProduct.objects.create(
            merchant=self.store_b,
            category=self.category_b,
            name="Other Merchant Chips",
            sku="CHIPS-1",
            price="25.00",
            stock=9,
        )
        MerchantProduct.objects.create(
            merchant=self.store_a,
            name="Inactive Item",
            sku="INACTIVE-1",
            price="10.00",
            stock=9,
            is_active=False,
        )
        MerchantProduct.objects.create(
            merchant=self.store_a,
            name="Out of Stock Item",
            sku="EMPTY-1",
            price="10.00",
            stock=0,
        )

    def test_home_only_lists_approved_stores_and_uses_real_shop_url(self):
        response = self.client.get(reverse("index"))
        self.assertContains(response, "Ramesh General Stores")
        self.assertContains(response, reverse("merchant_store", args=[self.store_a.slug]))
        self.assertNotContains(response, "Pending Shop")

    def test_public_store_shows_only_own_active_in_stock_products(self):
        response = self.client.get(reverse("merchant_store", args=[self.store_a.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", response.cookies)
        self.assertContains(response, "Fresh Milk")
        self.assertNotContains(response, "Other Merchant Chips")
        self.assertNotContains(response, "Inactive Item")
        self.assertNotContains(response, "Out of Stock Item")

    def test_search_and_category_filter_stay_within_store(self):
        response = self.client.get(
            reverse("merchant_store", args=[self.store_a.slug]),
            {"q": "milk", "category": self.category_a.pk},
        )
        self.assertContains(response, "Fresh Milk")
        self.assertNotContains(response, "Other Merchant Chips")

    def test_pending_store_is_not_public_and_approval_makes_it_public(self):
        url = reverse("merchant_store", args=[self.pending_store.slug])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.pending_store.is_approved = True
        self.pending_store.save(update_fields=["is_approved"])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_cart_and_wishlist_actions_are_scoped_to_store_products(self):
        add_url = reverse("merchant_store_cart_add", args=[self.store_a.slug, self.milk.pk])
        response = self.client.post(add_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(
            self.client.post(reverse("merchant_store_cart_add", args=[self.store_a.slug, self.other_product.pk])).status_code,
            404,
        )
        wishlist_url = reverse("merchant_store_wishlist_toggle", args=[self.store_a.slug, self.milk.pk])
        self.assertTrue(self.client.post(wishlist_url).json()["active"])
        self.assertFalse(self.client.post(wishlist_url).json()["active"])

    def test_admin_delete_requires_admin_and_removes_store_catalog(self):
        delete_url = reverse("admin_delete_merchant", args=[self.store_a.pk])
        pending_delete_url = reverse("admin_delete_merchant", args=[self.pending_store.pk])
        self.assertEqual(self.client.post(delete_url).status_code, 403)

        admin_user = User.objects.create_user(
            username="delete-admin", password="test-password", is_staff=True,
        )
        self.client.force_login(admin_user)
        session = self.client.session
        session["admin_authenticated"] = True
        session.save()
        pending_response = self.client.post(pending_delete_url)
        self.assertEqual(pending_response.status_code, 400)
        self.assertTrue(MerchantProfile.objects.filter(pk=self.pending_store.pk).exists())
        response = self.client.post(delete_url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(MerchantProfile.objects.filter(pk=self.store_a.pk).exists())
        self.assertFalse(MerchantProduct.objects.filter(pk=self.milk.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.owner_a.pk).exists())
        self.assertEqual(self.client.get(reverse("merchant_store", args=[self.store_a.slug])).status_code, 404)

    def test_checkout_uses_database_price_for_merchant_items(self):
        self.client.force_login(self.owner_a)
        session = self.client.session
        session["merchant_store_cart"] = {
            "merchant_id": self.store_a.pk,
            "items": {str(self.milk.pk): 2},
        }
        session.save()
        checkout = self.client.get(reverse("checkout"))
        self.assertEqual(checkout.status_code, 200)
        cart = json.loads(checkout.context["electronics_checkout_cart"])
        merchant_line = next(item for item in cart if item.get("merchant_product_id") == self.milk.pk)
        self.assertEqual(merchant_line["price"], float(self.milk.price))
        self.assertEqual(merchant_line["quantity"], 2)

        merchant_line["price"] = 0.01
        request = SimpleNamespace(session={
            "merchant_store_cart": {
                "merchant_id": self.store_a.pk,
                "items": {str(self.milk.pk): 2},
            },
        })
        verified_cart, verified_merchant = _validate_merchant_store_checkout_lines(request, [merchant_line])
        verified_line = verified_cart[0]
        self.assertEqual(verified_merchant, self.store_a)
        self.assertEqual(verified_line["price"], str(self.milk.price))

    def test_product_creation_rejects_fractional_stock_and_excess_price_precision(self):
        self.client.force_login(self.owner_a)
        url = reverse("merchant_products_api")

        for field, value in (("price", "12.345"), ("stock", "1.5")):
            with self.subTest(field=field):
                payload = {
                    "name": "New product",
                    "sku": f"NEW-{field.upper()}",
                    "price": "12.50",
                    "stock": 1,
                }
                payload[field] = value
                response = self.client.post(
                    url,
                    data=json.dumps(payload),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(
                    MerchantProduct.objects.filter(
                        merchant=self.store_a,
                        sku=f"NEW-{field.upper()}",
                    ).exists()
                )

    def test_registration_approval_dashboard_product_and_public_store_flow(self):
        registration = self.client.post(reverse("merchant_register"), {
            "shop_name": "New Community Market",
            "owner_name": "Asha Owner",
            "email": "asha-market@example.com",
            "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
            "mobile": "9876543210",
        })
        self.assertEqual(registration.status_code, 302)
        merchant_user = User.objects.get(email="asha-market@example.com")
        merchant = MerchantProfile.objects.get(owner=merchant_user)
        self.assertFalse(merchant.is_approved)
        self.assertNotContains(self.client.get(reverse("index")), "New Community Market")

        admin_user = User.objects.create_user(
            username="store-admin", password="test-password", is_staff=True,
        )
        self.client.force_login(admin_user)
        admin_session = self.client.session
        admin_session["admin_authenticated"] = True
        admin_session.save()
        approval = self.client.post(reverse("admin_approve_merchant", args=[merchant.pk]))
        self.assertEqual(approval.status_code, 200)
        merchant.refresh_from_db()
        self.assertTrue(merchant.is_approved)
        self.assertContains(self.client.get(reverse("index")), "New Community Market")

        self.client.force_login(merchant_user)
        product_response = self.client.post(
            reverse("merchant_products_api"),
            data=json.dumps({
                "name": "Merchant Dashboard Oats",
                "sku": "OATS-NEW",
                "price": "88.00",
                "stock": 12,
            }),
            content_type="application/json",
        )
        self.assertEqual(product_response.status_code, 201)
        inventory_response = self.client.get(reverse("merchant_products_api"))
        self.assertEqual(inventory_response.status_code, 200)
        self.assertIn(
            "Merchant Dashboard Oats",
            [product["name"] for product in inventory_response.json()["products"]],
        )
        store_response = self.client.get(reverse("merchant_store", args=[merchant.slug]))
        self.assertContains(store_response, "Merchant Dashboard Oats")


class MerchantNotificationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="notification-merchant", password="test-password")
        self.merchant = MerchantProfile.objects.create(
            owner=self.owner,
            shop_name="Notification Store",
            is_approved=True,
        )
        self.other_owner = User.objects.create_user(username="other-notification-merchant", password="test-password")
        self.other_merchant = MerchantProfile.objects.create(
            owner=self.other_owner,
            shop_name="Other Notification Store",
            is_approved=True,
        )
        self.client.force_login(self.owner)
        self.api_url = reverse("merchant_notifications_api")

    def test_api_lists_only_current_merchant_notifications_and_unread_count(self):
        unread = MerchantNotification.objects.create(
            merchant=self.merchant,
            title="New order",
            message="An order is ready to review.",
        )
        read = MerchantNotification.objects.create(
            merchant=self.merchant,
            title="Payout sent",
            message="Your payout was processed.",
            is_read=True,
        )
        MerchantNotification.objects.create(
            merchant=self.other_merchant,
            title="Other store order",
            message="This notification belongs to another merchant.",
        )

        response = self.client.get(self.api_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unread_count"], 1)
        self.assertCountEqual(
            [item["id"] for item in response.json()["notifications"]],
            [unread.id, read.id],
        )

    def test_api_marks_own_notification_read_and_rejects_another_merchants(self):
        own_notification = MerchantNotification.objects.create(
            merchant=self.merchant,
            title="New order",
            message="An order is ready to review.",
        )
        other_notification = MerchantNotification.objects.create(
            merchant=self.other_merchant,
            title="Other store order",
            message="This notification belongs to another merchant.",
        )

        response = self.client.patch(
            self.api_url,
            data=json.dumps({"notification_id": own_notification.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        own_notification.refresh_from_db()
        self.assertTrue(own_notification.is_read)

        response = self.client.patch(
            self.api_url,
            data=json.dumps({"notification_id": other_notification.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        other_notification.refresh_from_db()
        self.assertFalse(other_notification.is_read)

    def test_dashboard_renders_accessible_notification_trigger_and_unread_count(self):
        MerchantNotification.objects.create(
            merchant=self.merchant,
            title="New order",
            message="An order is ready to review.",
        )
        session = self.client.session
        session["merchant_authenticated"] = True
        session.save()

        response = self.client.get(reverse("merchant_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="notificationsToggle"')
        self.assertContains(response, 'aria-label="Notifications, 1 unread"')
        self.assertContains(response, 'id="notificationsPanel"')
        for chart_id in ("miniSales", "miniOrders", "miniCustomers"):
            self.assertNotContains(response, f'id="{chart_id}"')


class MerchantProductCreationTests(TestCase):
    def test_dashboard_renders_accessible_product_edit_dialog(self):
        owner = User.objects.create_user(username="product-dialog-owner", password="test-password")
        MerchantProfile.objects.create(
            owner=owner,
            shop_name="Dialog Store",
            is_approved=True,
        )
        self.client.force_login(owner)
        session = self.client.session
        session["merchant_authenticated"] = True
        session.save()

        response = self.client.get(reverse("merchant_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="productModal" role="dialog" aria-modal="true"')
        self.assertContains(response, 'id="productModalTitle">Add product</h2>')
        self.assertContains(response, 'id="productSubmitButton" type="submit">Save product</button>')
        self.assertContains(response, 'function editProduct(id)')
        self.assertRegex(
            response.content.decode(),
            r'<a class="menu-link"\s+href="#productsPanel">\s*<i class="bi bi-box-seam"></i>\s*Products\s*</a>',
        )

    def test_product_edit_api_updates_the_fields_used_by_dashboard_form(self):
        owner = User.objects.create_user(username="product-editor", password="test-password")
        merchant = MerchantProfile.objects.create(
            owner=owner,
            shop_name="Editing Store",
            is_approved=True,
        )
        product = MerchantProduct.objects.create(
            merchant=merchant,
            name="Old Product Name",
            sku="OLD-001",
            price="20.00",
            stock=4,
        )
        self.client.force_login(owner)

        response = self.client.patch(
            reverse("merchant_product_api", args=[product.id]),
            data=json.dumps({
                "name": "Updated Product Name",
                "sku": "NEW-001",
                "price": "25.50",
                "stock": 7,
                "image": "https://example.com/product.jpg",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.name, "Updated Product Name")
        self.assertEqual(product.sku, "NEW-001")
        self.assertEqual(str(product.price), "25.50")
        self.assertEqual(product.stock, 7)
        self.assertEqual(product.image, "https://example.com/product.jpg")

        MerchantProduct.objects.create(
            merchant=merchant,
            name="Other Product",
            sku="OTHER-001",
            price="15.00",
            stock=2,
        )
        duplicate_sku = self.client.patch(
            reverse("merchant_product_api", args=[product.id]),
            data=json.dumps({"sku": "other-001"}),
            content_type="application/json",
        )
        self.assertEqual(duplicate_sku.status_code, 400)
        self.assertEqual(duplicate_sku.json()["message"], "That SKU is already in use.")
        product.refresh_from_db()
        self.assertEqual(product.sku, "NEW-001")

    def test_dashboard_csrf_token_allows_product_creation_and_inventory_refresh(self):
        owner = User.objects.create_user(username="product-owner", password="test-password")
        MerchantProfile.objects.create(
            owner=owner,
            shop_name="Product Store",
            is_approved=True,
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(owner)
        session = client.session
        session["merchant_authenticated"] = True
        session.save()

        dashboard = client.get(reverse("merchant_dashboard"))
        csrf_cookie = dashboard.cookies.get("csrftoken")
        self.assertIsNotNone(csrf_cookie)

        response = client.post(
            reverse("merchant_products_api"),
            data=json.dumps({
                "name": "Fresh Apples",
                "sku": "APPLE-001",
                "price": "75.00",
                "stock": 10,
                "image": "",
            }),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_cookie.value,
        )

        self.assertEqual(response.status_code, 201)
        inventory = client.get(reverse("merchant_products_api"), HTTP_ACCEPT="application/json")
        self.assertEqual(inventory.status_code, 200)
        self.assertEqual(inventory.json()["products"][0]["name"], "Fresh Apples")
        created_product = MerchantProduct.objects.get(merchant__owner=owner, sku="APPLE-001")
        self.assertEqual(created_product.tax_treatment, "unclassified")
        self.assertEqual(created_product.tax_classification, "unclassified")
        self.assertFalse(created_product.gst_verified)
        self.assertFalse(created_product.price_includes_gst)

        duplicate = client.post(
            reverse("merchant_products_api"),
            data=json.dumps({
                "name": "Fresh Apples",
                "sku": "apple-001",
                "price": "75.00",
                "stock": 10,
            }),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_cookie.value,
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate.json()["message"], "That SKU is already in use.")

    def test_database_integrity_conflict_returns_json_instead_of_server_error_page(self):
        owner = User.objects.create_user(username="conflict-owner", password="test-password")
        MerchantProfile.objects.create(
            owner=owner,
            shop_name="Conflict Store",
            is_approved=True,
        )
        self.client.force_login(owner)

        with patch(
            "merchants.views.MerchantProduct.objects.create",
            side_effect=IntegrityError("simulated database constraint conflict"),
        ):
            response = self.client.post(
                reverse("merchant_products_api"),
                data=json.dumps({
                    "name": "Fresh Apples",
                    "sku": "APPLE-001",
                    "price": "75.00",
                    "stock": 10,
                }),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["success"], False)
        self.assertIn("conflicts with existing data", response.json()["message"])
