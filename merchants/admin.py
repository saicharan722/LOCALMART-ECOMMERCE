from django.contrib import admin
from .models import (
	MerchantActivity,
	MerchantCategory,
	MerchantCoupon,
	MerchantNotification,
	MerchantOrder,
	MerchantOrderItem,
	MerchantPayout,
	MerchantProduct,
	MerchantProductVariant,
	MerchantProfile,
	MerchantReview,
	MerchantSupportTicket,
)


admin.site.register([
	MerchantProfile,
	MerchantCategory,
	MerchantProduct,
	MerchantProductVariant,
	MerchantOrder,
	MerchantOrderItem,
	MerchantCoupon,
	MerchantPayout,
	MerchantReview,
	MerchantSupportTicket,
	MerchantNotification,
	MerchantActivity,
])
