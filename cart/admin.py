from django.contrib import admin

from .models import Cart, CartItem, CatalogProduct


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ("content_type", "object_id", "quantity")


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "session_key", "updated_at")
    search_fields = ("user__username", "user__email", "session_key")
    inlines = (CartItemInline,)


@admin.register(CatalogProduct)
class CatalogProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "catalog_key", "price", "stock", "stock_tracked", "is_active")
    list_filter = ("category", "stock_tracked", "is_active")
    search_fields = ("name", "catalog_key", "category", "merchant_name")
    list_editable = ("price", "stock", "stock_tracked", "is_active")


admin.site.register(CartItem)
