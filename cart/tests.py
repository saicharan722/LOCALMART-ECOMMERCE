import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from store.models import CancellationRequest, MarketplaceCoupon, Order, OrderItem, Refund
from products.models import Category, Product
from .models import Cart, CartItem, CatalogProduct
from .services import marketplace_category_group, merge_guest_cart
from store.refunds import (
    CancellationWorkflowError,
    approve_order_cancellation,
    process_refund,
    refresh_refund_status,
    reject_order_cancellation,
    request_order_cancellation,
)


class UnifiedCartTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="checkout-customer",
            email="customer@example.com",
            password="test-password",
        )
        self.product = CatalogProduct.objects.create(
            catalog_key="grocery:rice",
            name="Rice",
            category="Grocery",
            price=Decimal("12.50"),
            stock=2,
            is_active=True,
        )
        self.add_url = reverse("cart_items_api")

    def login_customer(self, client=None, user=None):
        (client or self.client).force_login(user or self.user)

    def add_product(self, client=None, product_id=None):
        client = client or self.client
        return client.post(
            self.add_url,
            data=json.dumps({
                "source": "catalog",
                "product_id": product_id or self.product.catalog_key,
            }),
            content_type="application/json",
        )

    def import_local_items(self, items):
        return self.client.post(
            reverse("cart_import_local_api"),
            data=json.dumps({"items": items}),
            content_type="application/json",
        )

    def test_checkout_logo_links_to_homepage(self):
        guest_response = self.client.get(reverse("checkout"))
        self.assertRedirects(
            guest_response,
            f'{reverse("login")}?next={reverse("checkout")}',
            fetch_redirect_response=False,
        )

        self.login_customer()
        response = self.client.get(reverse("checkout"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("index")}"')

    def test_checkout_and_payment_apis_require_authenticated_user(self):
        checkout_response = self.client.get(reverse("checkout"))
        self.assertEqual(checkout_response.status_code, 302)

        for endpoint in (
            "create_razorpay_order",
            "verify_payment",
            "create_paypal_order",
            "capture_paypal_order",
        ):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(
                    reverse(endpoint),
                    data=json.dumps({}),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 401)
                self.assertIn("log in", response.json()["message"].lower())

    def test_login_returns_authenticated_customer_to_checkout(self):
        response = self.client.get(
            reverse("login"),
            {"next": reverse("checkout")},
        )
        self.assertContains(
            response,
            f'name="next" value="{reverse("checkout")}"',
        )

        response = self.client.post(
            reverse("login"),
            {
                "email": self.user.email,
                "password": "test-password",
                "next": reverse("checkout"),
            },
        )

        self.assertRedirects(
            response,
            reverse("checkout"),
            fetch_redirect_response=False,
        )

    def test_google_login_preserves_a_safe_checkout_destination(self):
        response = self.client.get(
            reverse("google_login"),
            {"next": reverse("checkout")},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session["login_next_url"],
            reverse("checkout"),
        )

    def test_razorpay_order_creation_requires_checkout_csrf_token(self):
        client = self.client_class(enforce_csrf_checks=True)
        self.login_customer(client)
        checkout_page = client.get(reverse("checkout"))
        csrf_token = checkout_page.cookies["csrftoken"].value
        payload = json.dumps({})

        rejected = client.post(
            reverse("create_razorpay_order"),
            data=payload,
            content_type="application/json",
        )
        self.assertEqual(rejected.status_code, 403)

        accepted = client.post(
            reverse("create_razorpay_order"),
            data=payload,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(accepted.status_code, 400)
        self.assertEqual(accepted.json()["message"], "Cart is empty.")

        verification_rejected = client.post(
            reverse("verify_payment"),
            data=payload,
            content_type="application/json",
        )
        self.assertEqual(verification_rejected.status_code, 403)

    @patch("ecommerce.views.client.order.create")
    def test_razorpay_order_rejects_non_numeric_mobile_before_creating_order(self, create_order):
        self.login_customer()
        self.add_product()

        response = self.client.post(
            reverse("create_razorpay_order"),
            data=json.dumps({
                "customer_name": "Test Customer",
                "customer_email": "customer@example.com",
                "phone": "+91 98765abc",
                "customer_address": "123 Test Street",
                "customer_latitude": 12.9,
                "customer_longitude": 77.5,
                "delivery_location_confirmed": True,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("10-digit", response.json()["message"])
        self.assertFalse(Order.objects.exists())
        create_order.assert_not_called()

    def test_grocery_logo_links_to_homepage(self):
        response = self.client.get(reverse("grocery"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'class="grocery-site-logo localmart-shared-logo" href="{reverse("index")}" aria-label="LocalMart home"',
        )

    def test_food_page_navbar_keeps_cart_and_account_actions(self):
        response = self.client.get(reverse("food"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Main navigation"')
        self.assertContains(response, 'aria-label="Shopping actions"')
        self.assertContains(response, f'href="{reverse("cart")}"')
        self.assertContains(response, 'id="accountDropdown"')
        self.assertNotContains(response, 'id="foodMainNav"')
        self.assertNotContains(response, 'class="food-category-nav"')

    def test_home_appliances_navbar_has_responsive_search_and_account_menu(self):
        response = self.client.get(reverse("home_appliances"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Main navigation"')
        self.assertContains(response, 'data-bs-target="#homeAppliancesNav"')
        self.assertContains(response, 'id="homeAppliancesNav"')
        self.assertContains(response, 'aria-label="Search home appliances"')
        self.assertContains(response, 'id="accountDropdown"')
        self.assertContains(response, f'href="{reverse("my_orders")}"')
        self.assertContains(response, "My Orders")

    def test_homepage_and_home_appliances_share_the_landing_footer(self):
        for page_name in ("index", "home_appliances"):
            with self.subTest(page=page_name):
                response = self.client.get(reverse(page_name))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '<footer class="lm-landing-footer">')
                self.assertContains(response, "Shop Categories")

    def test_home_appliances_cart_add_uses_csrf_and_shows_count_after_reload(self):
        category = Category.objects.create(name="Refrigerators")
        product = Product.objects.create(
            category=category,
            name="Test Refrigerator",
            price=Decimal("100.00"),
            stock=2,
        )
        client = self.client_class(enforce_csrf_checks=True)

        page = client.get(reverse("home_appliances"))
        csrf_token = page.cookies["csrftoken"].value
        response = client.post(
            reverse("home_appliances_cart_add", args=[product.pk]),
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cart_count"], 1)

        reloaded_page = client.get(reverse("home_appliances"))
        self.assertContains(reloaded_page, 'id="cartCount">1</span>')

    def test_fashion_cart_uses_unified_cart_page(self):
        response = self.client.get(reverse("fashion_cart"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "cart.html")
        self.assertContains(response, "js/cart.js?v=category-coupons-2")
        self.assertContains(response, 'id="cartContainer"')
        self.assertContains(response, "View coupons")
        self.assertContains(response, 'id="availableCouponsModal"')
        self.assertContains(response, 'id="availableCoupons"')

    def test_empty_unified_cart_continue_shopping_links_home(self):
        response = self.client.get(reverse("cart"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-home-url="{reverse("index")}"')
        self.assertContains(response, "js/cart.js?v=category-coupons-2")
        self.assertContains(response, 'id="cartItemsColumn" class="col-12"')
        self.assertContains(
            response,
            'id="cartSummaryColumn" class="col-lg-4" hidden',
        )
        self.assertContains(response, '<div class="cart-empty">')
        self.assertContains(
            response,
            f'href="{reverse("index")}" class="btn btn-outline-success w-100 mt-3"',
        )

    def test_local_catalog_import_uses_verified_price_and_is_idempotent(self):
        item = {
            "name": "Margherita Pizza",
            "category": "Pizza",
            "price": "249",
            "image": "https://images.unsplash.com/photo-1574071318508-1cdbab80d002?w=800",
            "quantity": 2,
        }

        response = self.import_local_items([item])

        self.assertEqual(response.status_code, 200)
        imported = CatalogProduct.objects.get(name="Margherita Pizza")
        self.assertEqual(imported.price, Decimal("249.00"))
        self.assertFalse(imported.stock_tracked)
        self.assertIsNone(response.json()["items"][0]["stock"])
        cart_item = CartItem.objects.get()
        self.assertEqual(cart_item.product, imported)
        self.assertEqual(cart_item.quantity, 2)

        response = self.import_local_items([item])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CartItem.objects.get().quantity, 2)

    def test_local_catalog_import_rejects_forged_price(self):
        response = self.import_local_items([{
            "name": "Margherita Pizza",
            "category": "Pizza",
            "price": "1.00",
            "quantity": 1,
        }])

        self.assertEqual(response.status_code, 409)
        self.assertIn("could not be verified", response.json()["message"])
        self.assertFalse(CatalogProduct.objects.filter(name="Margherita Pizza").exists())
        self.assertFalse(CartItem.objects.exists())

    def test_marketplace_coupon_can_be_listed_applied_and_removed(self):
        MarketplaceCoupon.objects.create(
            code="SAVE20",
            description="Save on your marketplace order",
            discount_type="percentage",
            discount_value=Decimal("20.00"),
            minimum_order_amount=Decimal("10.00"),
            maximum_discount_amount=Decimal("2.00"),
        )
        self.add_product()
        coupon_url = reverse("cart_coupon_api")

        offers = self.client.get(coupon_url)
        self.assertEqual(offers.status_code, 200)
        listed_coupon = next(
            coupon
            for coupon in offers.json()["available_coupons"]
            if coupon["code"] == "SAVE20"
        )
        self.assertTrue(listed_coupon["eligible"])

        applied = self.client.post(
            coupon_url,
            data=json.dumps({"code": "save20"}),
            content_type="application/json",
        )
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.json()["coupon_discount"], "2.00")
        self.assertEqual(applied.json()["tax"], "0.53")
        self.assertEqual(applied.json()["total"], "11.03")

        removed = self.client.delete(coupon_url)
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()["coupon_discount"], "0.00")
        self.assertEqual(Cart.objects.get().coupon_code, "")

    def test_marketplace_coupon_rejects_unknown_expired_and_ineligible_codes(self):
        expired = MarketplaceCoupon.objects.create(
            code="OLDDEAL",
            description="An expired offer",
            discount_type="fixed",
            discount_value=Decimal("5.00"),
            expires_at=timezone.now() - timedelta(days=1),
        )
        MarketplaceCoupon.objects.create(
            code="MINIMUM",
            description="Requires a larger order",
            discount_type="fixed",
            discount_value=Decimal("5.00"),
            minimum_order_amount=Decimal("100.00"),
        )
        self.add_product()
        coupon_url = reverse("cart_coupon_api")

        for code, expected_status in (("NOTREAL", 400), (expired.code, 400), ("MINIMUM", 400)):
            with self.subTest(code=code):
                response = self.client.post(
                    coupon_url,
                    data=json.dumps({"code": code}),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, expected_status)
        self.assertEqual(Cart.objects.get().coupon_code, "")

    def test_marketplace_fixed_coupon_changes_server_cart_totals(self):
        MarketplaceCoupon.objects.create(
            code="LESS5",
            description="Take five rupees off",
            discount_type="fixed",
            discount_value=Decimal("5.00"),
        )
        self.add_product()

        response = self.client.post(
            reverse("cart_coupon_api"),
            data=json.dumps({"code": "LESS5"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["coupon_discount"], "5.00")
        self.assertEqual(response.json()["tax"], "0.38")
        self.assertEqual(response.json()["total"], "7.88")

    def test_category_coupon_minimum_and_discount_use_only_eligible_products(self):
        food_product = CatalogProduct.objects.create(
            catalog_key="food:burger",
            name="Burger",
            category="Food",
            price=Decimal("100.00"),
            stock=5,
            is_active=True,
        )
        self.add_product()
        cart = Cart.objects.get()
        CartItem.objects.create(
            cart=cart,
            content_type=ContentType.objects.get_for_model(food_product),
            object_id=food_product.pk,
            quantity=1,
        )
        coupon = MarketplaceCoupon.objects.create(
            code="GROCERY10",
            description="Save on grocery items",
            discount_type="percentage",
            discount_value=Decimal("10.00"),
            minimum_order_amount=Decimal("20.00"),
            maximum_discount_amount=Decimal("1.00"),
            eligible_categories=["Grocery"],
        )
        coupon_url = reverse("cart_coupon_api")

        rejected = self.client.post(
            coupon_url,
            data=json.dumps({"code": coupon.code}),
            content_type="application/json",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("eligible Grocery items", rejected.json()["message"])

        coupon.minimum_order_amount = Decimal("10.00")
        coupon.save(update_fields=["minimum_order_amount"])
        offers = self.client.get(coupon_url).json()["available_coupons"]
        listed_coupon = next(value for value in offers if value["code"] == coupon.code)
        self.assertTrue(listed_coupon["eligible"])
        self.assertEqual(listed_coupon["eligible_subtotal"], "12.50")
        self.assertEqual(listed_coupon["discount_amount"], "1.00")

        applied = self.client.post(
            coupon_url,
            data=json.dumps({"code": coupon.code}),
            content_type="application/json",
        )
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.json()["coupon_discount"], "1.00")
        self.assertEqual(applied.json()["total"], "117.08")

    def test_sample_coupons_cover_all_marketplace_categories(self):
        expected = {
            "FOOD10": ["Food"],
            "GROCERY5": ["Grocery"],
            "SHOPPING15": ["Shopping"],
            "ELECTRONICS10": ["Electronics"],
            "HOME10": ["Home Appliances"],
        }
        for code, categories in expected.items():
            with self.subTest(code=code):
                coupon = MarketplaceCoupon.objects.get(code=code)
                self.assertEqual(coupon.eligible_categories, categories)
                self.assertGreater(coupon.expires_at, timezone.now())

    def test_cart_product_taxonomy_maps_all_coupon_categories(self):
        examples = (
            ("Burgers", "catalog", "", "Food"),
            ("Grocery / Staples / Rice", "catalog", "", "Grocery"),
            ("Fashion", "catalog", "fashion:men:shirt", "Shopping"),
            ("Televisions", "electronics", "", "Electronics"),
            ("Mixer Grinders", "product", "", "Home Appliances"),
        )
        for category, source, catalog_key, expected in examples:
            with self.subTest(category=category):
                self.assertEqual(
                    marketplace_category_group(
                        category,
                        source=source,
                        catalog_key=catalog_key,
                    ),
                    expected,
                )

    def test_admin_can_create_and_disable_marketplace_coupons(self):
        admin = get_user_model().objects.create_superuser(
            username="coupon-admin",
            email="admin@example.com",
            password="test-password",
        )
        self.client.force_login(admin)
        session = self.client.session
        session["admin_authenticated"] = True
        session.save()

        response = self.client.post(
            reverse("admin_marketplace_coupons_api"),
            data=json.dumps({
                "code": "launch10",
                "description": "Save on a marketplace order",
                "discount_type": "percentage",
                "discount_value": "10",
                "eligible_categories": ["Grocery"],
                "minimum_order_amount": "50",
                "maximum_discount_amount": "100",
                "active": True,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        coupon = MarketplaceCoupon.objects.get(code="LAUNCH10")
        self.assertEqual(coupon.code, "LAUNCH10")
        self.assertEqual(coupon.minimum_order_amount, Decimal("50.00"))
        self.assertEqual(coupon.eligible_categories, ["Grocery"])

        response = self.client.patch(
            reverse("admin_marketplace_coupon_api", args=[coupon.pk]),
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        coupon.refresh_from_db()
        self.assertFalse(coupon.active)

        duplicate = self.client.post(
            reverse("admin_marketplace_coupons_api"),
            data=json.dumps({
                "code": "launch10",
                "description": "Duplicate marketplace offer",
                "discount_type": "fixed",
                "discount_value": "5",
            }),
            content_type="application/json",
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(MarketplaceCoupon.objects.filter(code="LAUNCH10").count(), 1)

        invalid_category = self.client.post(
            reverse("admin_marketplace_coupons_api"),
            data=json.dumps({
                "code": "INVALIDCAT",
                "description": "Invalid category offer",
                "discount_type": "fixed",
                "discount_value": "5",
                "eligible_categories": ["Other"],
            }),
            content_type="application/json",
        )
        self.assertEqual(invalid_category.status_code, 400)

        expired_coupon = self.client.post(
            reverse("admin_marketplace_coupons_api"),
            data=json.dumps({
                "code": "PASTDATE",
                "description": "Coupon with a past expiry",
                "discount_type": "fixed",
                "discount_value": "5",
                "expires_at": (timezone.now() - timedelta(days=1)).isoformat(),
            }),
            content_type="application/json",
        )
        self.assertEqual(expired_coupon.status_code, 400)
        self.assertFalse(MarketplaceCoupon.objects.filter(code="PASTDATE").exists())

    def test_admin_dashboard_exposes_marketplace_coupon_management(self):
        admin = get_user_model().objects.create_superuser(
            username="coupon-dashboard-admin",
            email="dashboard-admin@example.com",
            password="test-password",
        )
        self.client.force_login(admin)
        session = self.client.session
        session["admin_authenticated"] = True
        session.save()

        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="marketplaceCouponForm"')
        self.assertContains(response, 'id="marketplaceCouponRows"')
        self.assertContains(response, "Create marketplace-wide campaigns")

    def test_duplicate_adds_increment_quantity_and_enforce_stock(self):
        self.assertEqual(self.add_product().status_code, 200)
        response = self.add_product()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["quantity"], 2)

        response = self.add_product()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(CartItem.objects.get().quantity, 2)

    def test_catalog_cart_item_quantity_update_resolves_database_id(self):
        self.add_product()
        item = CartItem.objects.get()
        response = self.client.patch(
            reverse("cart_item_api", args=[item.pk]),
            data=json.dumps({"quantity": 2}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["subtotal"], "25.00")

    def test_fashion_add_uses_database_price_not_browser_price(self):
        fashion_product = CatalogProduct.objects.create(
            catalog_key="fashion:men:shirt-1",
            name="Database Shirt",
            category="Fashion",
            price=Decimal("40.00"),
            stock=2,
            is_active=True,
        )
        response = self.client.post(
            reverse("fashion_shopping_api"),
            data=json.dumps({
                "action": "add",
                "catalog": "men",
                "product": {
                    "id": "shirt-1",
                    "name": "Forged name",
                    "price": "0.01",
                },
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cart_count"], 1)
        self.assertEqual(CartItem.objects.get().product, fashion_product)
        self.assertEqual(CartItem.objects.get().product.price, Decimal("40.00"))

    def test_cart_is_isolated_between_users_and_guests(self):
        self.add_product()
        user = get_user_model().objects.create_user(
            username="another-customer",
            password="safe-test-password",
        )
        other_client = self.client_class()
        other_client.force_login(user)
        self.assertEqual(other_client.get(reverse("cart_count_api")).json()["count"], 0)

        self.add_product(other_client)
        self.assertEqual(Cart.objects.filter(user=user).get().items.get().quantity, 1)
        self.assertEqual(Cart.objects.filter(user__isnull=True).get().items.get().quantity, 1)

    def test_guest_cart_merges_without_exceeding_stock(self):
        self.add_product()
        session_key = self.client.session.session_key
        guest_cart = Cart.objects.get(session_key=session_key)
        guest_cart.coupon_code = "SAVE20"
        guest_cart.save(update_fields=["coupon_code"])
        user = get_user_model().objects.create_user(
            username="new-customer",
            password="safe-test-password",
        )
        user_cart = Cart.objects.create(user=user)
        CartItem.objects.create(
            cart=user_cart,
            content_type=ContentType.objects.get_for_model(self.product),
            object_id=self.product.pk,
            quantity=2,
        )

        merge_guest_cart(user, session_key)

        user_cart.refresh_from_db()
        self.assertEqual(user_cart.items.get().quantity, 2)
        self.assertEqual(user_cart.coupon_code, "SAVE20")
        self.assertFalse(Cart.objects.filter(session_key=session_key).exists())

    @patch("ecommerce.views.send_order_confirmation_email")
    @patch("ecommerce.views.ensure_tracking_session")
    @patch("ecommerce.views.client.utility.verify_payment_signature")
    def test_payment_decrements_stock_and_clears_only_purchased_quantity(
        self,
        verify_signature,
        ensure_tracking,
        send_email,
    ):
        cart = Cart.objects.create(session_key="checkout-session")
        cart_item = CartItem.objects.create(
            cart=cart,
            content_type=ContentType.objects.get_for_model(self.product),
            object_id=self.product.pk,
            quantity=2,
        )
        order = Order.objects.create(
            customer_name="Test Customer",
            customer_email="customer@example.com",
            customer_user=self.user,
            total_amount=Decimal("26.25"),
            payment_id="razorpay-order-1",
            razorpay_order_id="razorpay-order-1",
            cart=cart,
        )
        OrderItem.objects.create(
            order=order,
            name=self.product.name,
            category=self.product.category,
            price=self.product.price,
            quantity=1,
            product_content_type=ContentType.objects.get_for_model(self.product),
            product_object_id=self.product.pk,
        )
        payload = {
            "razorpay_order_id": "razorpay-order-1",
            "razorpay_payment_id": "razorpay-payment-1",
            "razorpay_signature": "test-signature",
        }
        client = self.client_class(enforce_csrf_checks=True)
        self.login_customer(client)
        csrf_token = client.get(reverse("checkout")).cookies["csrftoken"].value

        response = client.post(
            reverse("verify_payment"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        cart_item.refresh_from_db()
        self.assertEqual(self.product.stock, 1)
        self.assertEqual(cart_item.quantity, 1)
        self.assertEqual(order.__class__.objects.get(pk=order.pk).payment_status, "Paid")
        self.assertTrue(order.items.get().stock_deducted)
        verify_signature.assert_called_once()
        ensure_tracking.assert_called_once()
        send_email.assert_called_once()

        response = client.post(
            reverse("verify_payment"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)
        ensure_tracking.assert_called_once()
        send_email.assert_called_once()

    @patch("ecommerce.views.client.order.create")
    @patch("ecommerce.views.send_order_confirmation_email")
    @patch("ecommerce.views.ensure_tracking_session")
    @patch("ecommerce.views.client.utility.verify_payment_signature")
    def test_untracked_catalog_checkout_creates_and_confirms_order_without_stock_tracking(
        self,
        verify_signature,
        ensure_tracking,
        send_email,
        create_razorpay_order,
    ):
        self.login_customer()
        product = CatalogProduct.objects.create(
            catalog_key="static:untracked-product",
            name="Untracked Pizza",
            category="Food",
            price=Decimal("249.00"),
            stock=0,
            stock_tracked=False,
            is_active=True,
        )
        create_razorpay_order.return_value = {"id": "untracked-order-1"}
        self.assertEqual(self.add_product(product_id=product.catalog_key).status_code, 200)

        order_response = self.client.post(
            reverse("create_razorpay_order"),
            data=json.dumps({
                "customer_name": "Test Customer",
                "customer_email": "customer@example.com",
                "phone": "9876543210",
                "customer_address": "123 Test Street",
                "customer_latitude": 12.9,
                "customer_longitude": 77.5,
                "delivery_location_confirmed": True,
            }),
            content_type="application/json",
        )
        self.assertEqual(order_response.status_code, 200)
        self.assertEqual(order_response.json()["amount"], 26145)
        order = Order.objects.get(razorpay_order_id="untracked-order-1")
        order_item = order.items.get()
        self.assertEqual(order_item.price, product.price)
        self.assertEqual(order_item.line_total, Decimal("249.00"))
        self.assertEqual(order_item.total_tax, Decimal("12.45"))
        self.assertFalse(order_item.stock_deducted)
        self.assertEqual(order.subtotal, Decimal("249.00"))
        self.assertEqual(order.taxable_total, Decimal("249.00"))
        self.assertEqual(order.gst_total, Decimal("12.45"))
        self.assertEqual(order.cgst_total, Decimal("0.00"))
        cart_item = order.cart.items.get()

        response = self.client.post(
            reverse("verify_payment"),
            data=json.dumps({
                "razorpay_order_id": "untracked-order-1",
                "razorpay_payment_id": "untracked-payment-1",
                "razorpay_signature": "test-signature",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.stock, 0)
        self.assertEqual(Order.objects.get(pk=order.pk).order_status, "Confirmed")
        self.assertFalse(CartItem.objects.filter(pk=cart_item.pk).exists())
        create_razorpay_order.assert_called_once()
        verify_signature.assert_called_once()
        ensure_tracking.assert_called_once()
        send_email.assert_called_once()

    @patch("ecommerce.views.client.order.create")
    def test_razorpay_amount_matches_rounded_persisted_total(self, create_razorpay_order):
        self.login_customer()
        create_razorpay_order.return_value = {"id": "rounded-order-1"}
        self.assertEqual(self.add_product().status_code, 200)

        response = self.client.post(
            reverse("create_razorpay_order"),
            data=json.dumps({
                "customer_name": "Test Customer",
                "customer_email": "customer@example.com",
                "phone": "9876543210",
                "customer_address": "123 Test Street",
                "customer_latitude": 12.9,
                "customer_longitude": 77.5,
                "delivery_location_confirmed": True,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["amount"], 1313)
        order = Order.objects.get(razorpay_order_id="rounded-order-1")
        self.assertEqual(order.total_amount, Decimal("13.13"))
        self.assertEqual(order.gst_total, Decimal("0.63"))
        self.assertEqual(order.items.get().total_tax, order.gst_total)
        create_razorpay_order.assert_called_once()
        self.assertEqual(create_razorpay_order.call_args.args[0]["amount"], 1313)

    @patch("ecommerce.views.client.order.create")
    def test_razorpay_charges_and_persists_the_server_verified_coupon(
        self,
        create_razorpay_order,
    ):
        self.login_customer()
        create_razorpay_order.return_value = {"id": "coupon-order-1"}
        self.add_product()
        MarketplaceCoupon.objects.create(
            code="SAVE20",
            description="Save on your marketplace order",
            discount_type="percentage",
            discount_value=Decimal("20.00"),
            maximum_discount_amount=Decimal("2.00"),
        )
        cart = Cart.objects.get(user=self.user)
        cart.coupon_code = "SAVE20"
        cart.save(update_fields=["coupon_code"])

        response = self.client.post(
            reverse("create_razorpay_order"),
            data=json.dumps({
                "customer_name": "Test Customer",
                "customer_email": "customer@example.com",
                "phone": "9876543210",
                "customer_address": "123 Test Street",
                "customer_latitude": 12.9,
                "customer_longitude": 77.5,
                "delivery_location_confirmed": True,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["amount"], 1103)
        self.assertEqual(response.json()["coupon_discount"], 2.0)
        self.assertEqual(create_razorpay_order.call_args.args[0]["amount"], 1103)
        order = Order.objects.get(razorpay_order_id="coupon-order-1")
        order_item = order.items.get()
        self.assertEqual(order.coupon_code, "SAVE20")
        self.assertEqual(order.coupon_discount, Decimal("2.00"))
        self.assertEqual(order.subtotal, Decimal("12.50"))
        self.assertEqual(order.taxable_total, Decimal("10.50"))
        self.assertEqual(order.total_amount, Decimal("11.03"))
        self.assertEqual(order_item.coupon_discount_amount, Decimal("2.00"))
        self.assertEqual(order_item.taxable_value, Decimal("10.50"))
        self.assertEqual(order_item.total_tax, Decimal("0.53"))

    @patch("ecommerce.views.client.order.create")
    def test_category_coupon_is_allocated_only_to_matching_order_items(
        self,
        create_razorpay_order,
    ):
        self.login_customer()
        create_razorpay_order.return_value = {"id": "category-coupon-order"}
        food_product = CatalogProduct.objects.create(
            catalog_key="food:burger",
            name="Burger",
            category="Food",
            price=Decimal("100.00"),
            stock=5,
            is_active=True,
        )
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(
            cart=cart,
            content_type=ContentType.objects.get_for_model(self.product),
            object_id=self.product.pk,
            quantity=1,
        )
        CartItem.objects.create(
            cart=cart,
            content_type=ContentType.objects.get_for_model(food_product),
            object_id=food_product.pk,
            quantity=1,
        )
        MarketplaceCoupon.objects.create(
            code="GROCERY10",
            description="Save on grocery items",
            discount_type="percentage",
            discount_value=Decimal("10.00"),
            minimum_order_amount=Decimal("10.00"),
            eligible_categories=["Grocery"],
        )
        cart.coupon_code = "GROCERY10"
        cart.save(update_fields=["coupon_code"])

        response = self.client.post(
            reverse("create_razorpay_order"),
            data=json.dumps({
                "customer_name": "Test Customer",
                "customer_email": "customer@example.com",
                "phone": "9876543210",
                "customer_address": "123 Test Street",
                "customer_latitude": 12.9,
                "customer_longitude": 77.5,
                "delivery_location_confirmed": True,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["amount"], 11681)
        order = Order.objects.get(razorpay_order_id="category-coupon-order")
        order_items = {item.name: item for item in order.items.all()}
        self.assertEqual(order_items["Rice"].coupon_discount_amount, Decimal("1.25"))
        self.assertEqual(order_items["Rice"].taxable_value, Decimal("11.25"))
        self.assertEqual(order_items["Burger"].coupon_discount_amount, Decimal("0.00"))
        self.assertEqual(order_items["Burger"].taxable_value, Decimal("100.00"))

    @patch("ecommerce.views._paypal_access_token", return_value="paypal-token")
    @patch("ecommerce.views.requests.post")
    def test_paypal_uses_server_cart_and_coupon_instead_of_client_totals(
        self,
        paypal_request,
        access_token,
    ):
        self.login_customer()
        self.add_product()
        MarketplaceCoupon.objects.create(
            code="LESS5",
            description="Take five rupees off",
            discount_type="fixed",
            discount_value=Decimal("5.00"),
        )
        cart = Cart.objects.get(user=self.user)
        cart.coupon_code = "LESS5"
        cart.save(update_fields=["coupon_code"])
        paypal_request.return_value.json.return_value = {"id": "paypal-coupon-order"}

        response = self.client.post(
            reverse("create_paypal_order"),
            data=json.dumps({
                "customer_name": "Test Customer",
                "customer_email": "customer@example.com",
                "customer_phone": "9876543210",
                "customer_address": "123 Test Street",
                "cart": [{"name": "Forged item", "price": "0.01", "quantity": 1}],
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 7.88)
        self.assertEqual(response.json()["coupon_discount"], 5.0)
        order = Order.objects.get(payment_id="paypal-coupon-order")
        self.assertEqual(order.coupon_code, "LESS5")
        self.assertEqual(order.total_amount, Decimal("7.88"))
        self.assertEqual(order.items.get().name, self.product.name)
        gateway_amount = paypal_request.call_args.kwargs["json"]["purchase_units"][0]["amount"]["value"]
        expected_amount = Decimal("7.88") * Decimal(str(settings.PAYPAL_INR_TO_USD))
        self.assertEqual(gateway_amount, f"{expected_amount:.2f}")
        access_token.assert_called_once()

    @patch("ecommerce.views.client.order.create")
    @patch(
        "ecommerce.views._create_order_items",
        side_effect=RuntimeError("sensitive database detail"),
    )
    def test_persistence_failure_does_not_create_gateway_order_or_leak_details(
        self,
        create_order_items,
        create_razorpay_order,
    ):
        self.login_customer()
        self.add_product()

        response = self.client.post(
            reverse("create_razorpay_order"),
            data=json.dumps({
                "customer_name": "Test Customer",
                "customer_email": "customer@example.com",
                "phone": "9876543210",
                "customer_address": "123 Test Street",
                "customer_latitude": 12.9,
                "customer_longitude": 77.5,
                "delivery_location_confirmed": True,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("this attempt was not charged", response.json()["message"])
        self.assertNotIn("sensitive database detail", response.json()["message"])
        self.assertFalse(Order.objects.exists())
        create_order_items.assert_called_once()
        create_razorpay_order.assert_not_called()

    @patch("ecommerce.views.client.utility.verify_payment_signature")
    @patch("ecommerce.views.requests.post")
    def test_payment_callbacks_cannot_access_another_users_order(
        self,
        paypal_request,
        verify_signature,
    ):
        other_user = get_user_model().objects.create_user(
            username="other-customer",
            email="other@example.com",
            password="test-password",
        )
        razorpay_order = Order.objects.create(
            customer_name="Other Customer",
            customer_email=other_user.email,
            customer_user=other_user,
            total_amount=Decimal("10.00"),
            payment_id="other-razorpay-order",
            razorpay_order_id="other-razorpay-order",
        )
        paypal_order = Order.objects.create(
            customer_name="Other Customer",
            customer_email=other_user.email,
            customer_user=other_user,
            total_amount=Decimal("10.00"),
            payment_id="other-paypal-order",
        )
        guest_order_success = self.client.get(
            reverse("order_success"),
            {"order_id": paypal_order.pk},
        )
        self.assertEqual(guest_order_success.status_code, 302)

        self.login_customer()

        razorpay_response = self.client.post(
            reverse("verify_payment"),
            data=json.dumps({
                "razorpay_order_id": "other-razorpay-order",
                "razorpay_payment_id": "other-payment",
                "razorpay_signature": "signature",
            }),
            content_type="application/json",
        )
        paypal_response = self.client.post(
            reverse("capture_paypal_order"),
            data=json.dumps({
                "paypal_order_id": "other-paypal-order",
                "local_order_id": paypal_order.pk,
            }),
            content_type="application/json",
        )

        self.assertEqual(razorpay_response.status_code, 404)
        self.assertEqual(paypal_response.status_code, 404)
        verify_signature.assert_not_called()
        paypal_request.assert_not_called()
        razorpay_order.refresh_from_db()
        paypal_order.refresh_from_db()
        self.assertEqual(razorpay_order.payment_status, "Pending")
        self.assertEqual(paypal_order.payment_status, "Pending")
        order_success = self.client.get(
            reverse("order_success"),
            {"order_id": paypal_order.pk},
        )
        self.assertEqual(order_success.status_code, 200)
        self.assertIsNone(order_success.context["tracked_order"])


class OrderCancellationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.customer = user_model.objects.create_user(
            username="cancellation-customer",
            email="cancel@example.com",
            password="test-password",
        )
        self.reviewer = user_model.objects.create_user(
            username="refund-reviewer",
            email="reviewer@example.com",
            password="test-password",
            is_staff=True,
        )
        for codename in ("change_cancellationrequest", "change_refund"):
            self.reviewer.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label="store",
                    codename=codename,
                )
            )

    def create_order(self, **overrides):
        values = {
            "customer_name": "Cancellation Customer",
            "customer_email": self.customer.email,
            "customer_user": self.customer,
            "total_amount": Decimal("125.00"),
            "payment_amount": Decimal("125.00"),
            "payment_currency": "INR",
            "payment_method": "razorpay",
            "payment_capture_id": "pay-captured-125",
            "payment_id": "pay-captured-125",
            "razorpay_order_id": "order-125",
            "payment_status": "Paid",
            "order_status": "Confirmed",
        }
        values.update(overrides)
        return Order.objects.create(**values)

    def create_request(self, order):
        return CancellationRequest.objects.create(
            order=order,
            customer_user=self.customer,
            reason="changed_mind",
            previous_order_status=order.order_status,
        )

    def test_my_orders_and_cancellation_require_login(self):
        order = self.create_order()
        response = self.client.get(reverse("my_orders"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        status_response = self.client.get(reverse("my_order_status_updates"))
        self.assertEqual(status_response.status_code, 302)

        response = self.client.post(
            reverse("request_order_cancellation", args=[order.pk]),
            {"reason": "changed_mind"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(CancellationRequest.objects.exists())

    @patch("store.refunds.send_mail", return_value=1)
    def test_customer_request_places_eligible_order_on_hold(self, send_mail):
        self.client.force_login(self.customer)
        order = self.create_order()

        response = self.client.post(
            reverse("request_order_cancellation", args=[order.pk]),
            {"reason": "ordered_by_mistake", "details": "I selected the wrong size."},
        )

        self.assertRedirects(response, reverse("shopping_my_orders"), fetch_redirect_response=False)
        cancellation = CancellationRequest.objects.get(order=order)
        self.assertEqual(cancellation.status, "requested")
        self.assertEqual(cancellation.previous_order_status, "Confirmed")
        order.refresh_from_db()
        self.assertEqual(order.order_status, "Cancellation Requested")
        send_mail.assert_called_once()

        page = self.client.get(reverse("shopping_my_orders"))
        self.assertContains(page, "Cancellation Pending review")
        self.assertContains(page, "Your order is on hold")
        self.assertContains(page, "Refund request")
        self.assertContains(page, "Pending review")
        self.assertContains(page, "order-status-polling.js")
        self.assertContains(page, 'data-status-url="/api/my-orders/status/"')
        self.assertFalse(Refund.objects.filter(cancellation_request=cancellation).exists())
        status_response = self.client.get(reverse("my_order_status_updates"))
        status_payload = status_response.json()["orders"][0]
        self.assertEqual(
            json.loads(status_payload["snapshot"])["cancellation"]["status"],
            "requested",
        )

    def test_customer_cannot_cancel_another_users_or_shipped_order(self):
        other_user = get_user_model().objects.create_user(
            username="another-customer",
            email="another@example.com",
            password="test-password",
        )
        other_order = Order.objects.create(
            customer_name="Another Customer",
            customer_email=other_user.email,
            customer_user=other_user,
            total_amount=Decimal("30.00"),
            order_status="Confirmed",
        )
        shipped_order = self.create_order(order_status="Shipped")
        self.client.force_login(self.customer)

        other_response = self.client.post(
            reverse("request_order_cancellation", args=[other_order.pk]),
            {"reason": "changed_mind"},
        )
        shipped_response = self.client.post(
            reverse("request_order_cancellation", args=[shipped_order.pk]),
            {"reason": "changed_mind"},
        )

        self.assertEqual(other_response.status_code, 404)
        self.assertEqual(shipped_response.status_code, 302)
        self.assertFalse(CancellationRequest.objects.exists())
        shipped_order.refresh_from_db()
        self.assertEqual(shipped_order.order_status, "Shipped")

    @patch("store.refunds.send_mail", return_value=1)
    def test_rejection_restores_order_status_and_allows_a_new_request(self, send_mail):
        order = self.create_order()
        cancellation = request_order_cancellation(
            order.pk,
            self.customer,
            "changed_mind",
        )

        reject_order_cancellation(cancellation.pk, self.reviewer, "The order has entered fulfillment.")
        order.refresh_from_db()
        cancellation.refresh_from_db()

        self.assertEqual(cancellation.status, "rejected")
        self.assertEqual(
            cancellation.review_note,
            "The order has entered fulfillment.",
        )
        self.assertEqual(order.order_status, "Confirmed")
        new_request = request_order_cancellation(
            order.pk,
            self.customer,
            "other",
            "Please cancel this order.",
        )
        self.assertEqual(new_request.status, "requested")
        self.assertEqual(CancellationRequest.objects.filter(order=order).count(), 2)

    def test_only_staff_can_review_and_refunds_cannot_start_before_approval(self):
        order = self.create_order()
        cancellation = self.create_request(order)

        with self.assertRaises(CancellationWorkflowError):
            approve_order_cancellation(
                cancellation.pk,
                self.customer,
                "Approved for refund.",
            )
        with self.assertRaises(CancellationWorkflowError):
            approve_order_cancellation(cancellation.pk, self.reviewer)
        limited_reviewer = get_user_model().objects.create_user(
            username="limited-reviewer",
            password="test-password",
            is_staff=True,
        )
        with self.assertRaises(CancellationWorkflowError):
            approve_order_cancellation(
                cancellation.pk,
                limited_reviewer,
                "Approved for refund.",
            )
        refund = Refund.objects.create(
            cancellation_request=cancellation,
            payment_method="razorpay",
            amount=order.payment_amount,
            currency=order.payment_currency,
        )
        with self.assertRaises(CancellationWorkflowError):
            process_refund(refund.pk)
        refund.refresh_from_db()
        self.assertEqual(refund.status, "pending")
        self.assertEqual(cancellation.status, "requested")

    def test_admin_can_review_with_remark_and_customer_status_api_updates(self):
        order = self.create_order(payment_status="Pending", payment_capture_id="")
        cancellation = self.create_request(order)
        permission = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(CancellationRequest),
            codename="change_cancellationrequest",
        )
        self.reviewer.user_permissions.add(permission)
        self.client.force_login(self.reviewer)
        changelist_url = reverse("admin:store_cancellationrequest_changelist")

        admin_page = self.client.get(changelist_url)
        self.assertContains(admin_page, 'name="review_note"')
        response = self.client.post(changelist_url, {
            "action": "approve_cancellations",
            "_selected_action": [str(cancellation.pk)],
            "review_note": "Approved after verifying the order details.",
        })

        self.assertEqual(response.status_code, 302)
        cancellation.refresh_from_db()
        self.assertEqual(cancellation.status, "approved")
        self.assertEqual(
            cancellation.review_note,
            "Approved after verifying the order details.",
        )
        self.client.force_login(self.customer)
        status_payload = self.client.get(
            reverse("my_order_status_updates")
        ).json()["orders"][0]
        self.assertEqual(
            json.loads(status_payload["snapshot"])["cancellation"]["status"],
            "approved",
        )

    def test_admin_dashboard_shows_pending_refund_approval_controls(self):
        order = self.create_order()
        self.create_request(order)
        self.client.force_login(self.reviewer)
        session = self.client.session
        session["admin_authenticated"] = True
        session.save()

        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Approve &amp; Refund")
        self.assertContains(response, "Pending review")
        self.assertContains(response, 'data-review-action="approve"')

    @patch("store.refunds.send_mail", return_value=1)
    @patch("store.refunds.razorpay.Client")
    def test_dashboard_approve_action_starts_original_method_refund(
        self,
        razorpay_client,
        send_mail,
    ):
        order = self.create_order()
        cancellation = self.create_request(order)
        self.client.force_login(self.reviewer)
        session = self.client.session
        session["admin_authenticated"] = True
        session.save()
        razorpay_client.return_value.payment.refund.return_value = {
            "id": "dashboard-rfnd-125",
            "status": "processed",
        }

        response = self.client.post(
            reverse("admin_review_cancellation_api", args=[cancellation.pk]),
            data=json.dumps({
                "action": "approve",
                "review_note": "Approved from the dashboard.",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["refund_status"], "Completed")
        cancellation.refresh_from_db()
        refund = Refund.objects.get(cancellation_request=cancellation)
        self.assertEqual(cancellation.status, "approved")
        self.assertEqual(cancellation.review_note, "Approved from the dashboard.")
        self.assertEqual(refund.gateway_refund_id, "dashboard-rfnd-125")
        self.assertEqual(razorpay_client.return_value.payment.refund.call_args.args[0], "pay-captured-125")
        send_mail.assert_called()

    def test_dashboard_review_api_requires_staff_model_permission_and_remarks(self):
        order = self.create_order()
        cancellation = self.create_request(order)
        limited_reviewer = get_user_model().objects.create_user(
            username="dashboard-limited-reviewer",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(limited_reviewer)
        session = self.client.session
        session["admin_authenticated"] = True
        session.save()
        endpoint = reverse("admin_review_cancellation_api", args=[cancellation.pk])
        payload = {"action": "approve", "review_note": "Approved."}

        forbidden = self.client.post(
            endpoint,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.reviewer)
        session = self.client.session
        session["admin_authenticated"] = True
        session.save()
        missing_note = self.client.post(
            endpoint,
            data=json.dumps({"action": "approve", "review_note": " "}),
            content_type="application/json",
        )

        self.assertEqual(missing_note.status_code, 400)
        cancellation.refresh_from_db()
        self.assertEqual(cancellation.status, "requested")
        self.assertFalse(Refund.objects.filter(cancellation_request=cancellation).exists())

    @patch("store.refunds.send_mail", return_value=1)
    @patch("store.refunds.razorpay.Client")
    def test_approval_refunds_captured_payment_and_restores_stock(
        self,
        razorpay_client,
        send_mail,
    ):
        order = self.create_order()
        product = CatalogProduct.objects.create(
            catalog_key="grocery:cancellation-rice",
            name="Rice",
            category="Grocery",
            price=Decimal("10.00"),
            stock=3,
            is_active=True,
        )
        OrderItem.objects.create(
            order=order,
            name=product.name,
            category="Grocery",
            price=product.price,
            quantity=2,
            product_content_type=ContentType.objects.get_for_model(product),
            product_object_id=product.pk,
            stock_deducted=True,
        )
        cancellation = self.create_request(order)
        razorpay_client.return_value.payment.refund.return_value = {
            "id": "rfnd-125",
            "status": "processed",
        }

        refund = approve_order_cancellation(
            cancellation.pk,
            self.reviewer,
            "Approved after review.",
        )

        order.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual(order.order_status, "Refunded")
        self.assertEqual(order.payment_status, "Refunded")
        self.assertEqual(product.stock, 5)
        self.assertFalse(order.items.get().stock_deducted)
        self.assertEqual(refund.status, "completed")
        self.assertEqual(refund.gateway_refund_id, "rfnd-125")
        refund_call = razorpay_client.return_value.payment.refund.call_args
        self.assertEqual(refund_call.args[0], "pay-captured-125")
        self.assertEqual(refund_call.args[1]["amount"], 12500)
        self.assertIn("X-Razorpay-Idempotency-Key", refund_call.kwargs["headers"])
        send_mail.assert_called()

    @patch("store.refunds.send_mail", return_value=1)
    @patch("store.refunds.razorpay.Client")
    def test_pending_gateway_refund_can_be_refreshed_to_completed(
        self,
        razorpay_client,
        send_mail,
    ):
        order = self.create_order()
        cancellation = self.create_request(order)
        gateway = razorpay_client.return_value
        gateway.payment.refund.return_value = {"id": "rfnd-pending", "status": "pending"}
        gateway.refund.fetch.return_value = {"id": "rfnd-pending", "status": "processed"}

        refund = approve_order_cancellation(
            cancellation.pk,
            self.reviewer,
            "Approved after review.",
        )
        self.assertEqual(refund.status, "processing")

        refund = refresh_refund_status(refund.pk)
        order.refresh_from_db()
        self.assertEqual(refund.status, "completed")
        self.assertEqual(order.payment_status, "Refunded")
        self.assertEqual(order.order_status, "Refunded")

    @patch("store.refunds.send_mail", return_value=1)
    @patch("store.refunds._paypal_access_token", return_value="paypal-token")
    @patch("store.refunds.requests.post")
    def test_paypal_refund_uses_captured_payment_and_original_currency(
        self,
        paypal_post,
        access_token,
        send_mail,
    ):
        order = self.create_order(
            payment_method="paypal",
            payment_currency="USD",
            payment_amount=Decimal("1.50"),
            payment_capture_id="paypal-capture-1",
            payment_id="paypal-order-1",
            razorpay_order_id=None,
        )
        cancellation = self.create_request(order)
        response = Mock()
        response.json.return_value = {"id": "paypal-refund-1", "status": "COMPLETED"}
        paypal_post.return_value = response

        refund = approve_order_cancellation(
            cancellation.pk,
            self.reviewer,
            "Approved after review.",
        )

        self.assertEqual(refund.status, "completed")
        self.assertEqual(refund.amount, Decimal("1.50"))
        self.assertEqual(refund.currency, "USD")
        request_call = paypal_post.call_args
        self.assertIn("/captures/paypal-capture-1/refund", request_call.args[0])
        self.assertEqual(
            request_call.kwargs["json"]["amount"],
            {"value": "1.50", "currency_code": "USD"},
        )
        self.assertIn("PayPal-Request-Id", request_call.kwargs["headers"])
        access_token.assert_called_once()

    @patch("ecommerce.views.ensure_tracking_session")
    @patch("ecommerce.views.client.utility.verify_payment_signature")
    @patch("store.refunds.send_mail", return_value=1)
    @patch("store.refunds.razorpay.Client")
    def test_payment_captured_after_approved_cancellation_is_refunded(
        self,
        razorpay_client,
        send_mail,
        verify_signature,
        ensure_tracking,
    ):
        self.client.force_login(self.customer)
        order = self.create_order(
            payment_status="Pending",
            payment_method="razorpay",
            payment_amount=Decimal("125.00"),
            payment_capture_id="",
            payment_id="order-late-capture",
            razorpay_order_id="order-late-capture",
            order_status="Placed",
        )
        cancellation = request_order_cancellation(
            order.pk,
            self.customer,
            "changed_mind",
        )
        approve_order_cancellation(
            cancellation.pk,
            self.reviewer,
            "Approved after review.",
        )
        razorpay_client.return_value.payment.refund.return_value = {
            "id": "rfnd-late",
            "status": "processed",
        }

        response = self.client.post(
            reverse("verify_payment"),
            data=json.dumps({
                "razorpay_order_id": "order-late-capture",
                "razorpay_payment_id": "pay-late-capture",
                "razorpay_signature": "valid-signature",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("refund status", response.json()["message"].lower())
        order.refresh_from_db()
        cancellation.refresh_from_db()
        self.assertEqual(order.payment_status, "Refunded")
        self.assertEqual(order.order_status, "Refunded")
        self.assertEqual(order.payment_capture_id, "pay-late-capture")
        self.assertEqual(cancellation.refund.status, "completed")
        ensure_tracking.assert_not_called()
        verify_signature.assert_called_once()
