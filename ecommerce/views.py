from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.core.mail import send_mail
from django.core.mail import EmailMultiAlternatives
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.utils.dateparse import parse_datetime
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.urls import reverse
from django.views.decorators.http import require_http_methods
import hashlib
import logging
import uuid
import json
import re
import math
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import razorpay
from datetime import timedelta
from products.models import Product, Category
from accounts.forms import AdminProfileForm
from accounts.models import AdminProfile

from django.core.paginator import Paginator
from django.db.models import Q, Avg, Prefetch
from django.db.models import F, Sum, Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.http import Http404, HttpResponse, JsonResponse
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape as escape_xml
from collections import OrderedDict
from django.views.decorators.csrf import ensure_csrf_cookie

import requests
from django.conf import settings
from django.shortcuts import get_object_or_404, render, redirect
from rest_framework.views import APIView
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from rest_framework_simplejwt.tokens import RefreshToken

from store.models import CancellationRequest, MarketplaceCoupon, Order, OrderItem
from store.refunds import (
    CancellationWorkflowError,
    approve_order_cancellation,
    create_refund_for_approved_cancellation,
    order_can_be_cancelled,
    reject_order_cancellation,
    request_order_cancellation,
)
from tracking.services import ensure_tracking_session
from merchants.models import MerchantActivity, MerchantOrder, MerchantOrderItem, MerchantProduct, MerchantProfile, MerchantCategory, MerchantCoupon, MerchantReview, MerchantPayout, MerchantSupportTicket
from electronics.models import ElectronicsProduct, ElectronicsCategory
from cart.models import CartItem
from cart.services import (
    PRODUCT_TYPES,
    add_product_to_cart,
    get_customer_cart,
    get_applied_marketplace_coupon,
    get_inventory_product,
    marketplace_category_group,
    get_product_category,
    get_product_image,
    get_product_stock,
    merge_guest_cart,
    serialize_cart,
)
from .forms import CustomerPasswordResetRequestForm, CustomerSetPasswordForm
from .input_validation import (
    validate_address,
    validate_amount,
    validate_business_name,
    validate_email_address,
    validate_http_url,
    validate_license_identifier,
    validate_mobile_number,
    validate_person_name,
    validate_password_strength,
    validate_sku,
    validate_vehicle_identifier,
    validate_whole_number,
)

logger = logging.getLogger(__name__)


FASHION_PRODUCTS = [
    {
        "id": "urban-overshirt", "name": "Relaxed Cotton Overshirt", "brand": "Roadster",
        "category": "men", "type": "Shirts", "price": 899, "mrp": 1999, "rating": 4.4,
        "image": "https://assets.myntassets.com/w_163,c_limit,fl_progressive,dpr_2.0/assets/images/2026/JUNE/14/m0P6G8rD_a502801216244c4682db716ed6cb2802.jpg",
    },
    {
        "id": "classic-polo", "name": "Pure Cotton Polo T-shirt", "brand": "H&M",
        "category": "men", "type": "T-shirts", "price": 699, "mrp": 1299, "rating": 4.3,
        "image": "https://assets.myntassets.com/w_163,c_limit,fl_progressive,dpr_2.0/assets/images/2026/JUNE/14/RYMjxwpf_c75bb124d411422d9b7ce3cb58650c00.jpg",
    },
    {
        "id": "mens-sports-edit", "name": "Performance Sports T-shirt", "brand": "HRX",
        "category": "men", "type": "Sportswear", "price": 799, "mrp": 1599, "rating": 4.4,
        "image": "https://assets.myntassets.com/w_163,c_limit,fl_progressive,dpr_2.0/assets/images/2026/JUNE/14/oFgyKUkR_4032eec0f23b4f4abd82038a84541509.jpg",
    },
    {
        "id": "mens-lounge-edit", "name": "Relaxed Lounge Joggers", "brand": "Roadster",
        "category": "men", "type": "Loungewear", "price": 899, "mrp": 1799, "rating": 4.2,
        "image": "https://assets.myntassets.com/w_163,c_limit,fl_progressive,dpr_2.0/assets/images/2026/JUNE/14/TaRkAho2_e1da787543e54a27ae8cf3dabdb9652f.jpg",
    },
    {
        "id": "mens-ethnic-edit", "name": "Printed Casual Kurta", "brand": "Manyavar",
        "category": "men", "type": "Ethnic Wear", "price": 1299, "mrp": 2599, "rating": 4.5,
        "image": "https://assets.myntassets.com/w_163,c_limit,fl_progressive,dpr_2.0/assets/images/2026/JUNE/14/gG6vjm0y_94f74c13330c453dbf82be77578f0582.jpg",
    },
    {"id": "roadster-pure-cotton", "name": "Pure Cotton Casual Shirt", "brand": "Roadster", "category": "men", "type": "Shirts", "price": 649, "mrp": 2499, "rating": 4.2, "color": "Blue", "image": "https://images.unsplash.com/photo-1596755389378-c31d21fd1273?auto=format&fit=crop&w=700&q=85"},
    {"id": "mischief-solid", "name": "Men Solid Cotton Casual Shirt", "brand": "MISCHIEF MONKEY", "category": "men", "type": "Shirts", "price": 793, "mrp": 2088, "rating": 4.2, "color": "White", "image": "https://images.unsplash.com/photo-1603252110481-7ba873bf42ab?auto=format&fit=crop&w=700&q=85"},
    {"id": "wrogn-slim-fit", "name": "Slim Fit Casual Shirt", "brand": "WROGN", "category": "men", "type": "Shirts", "price": 1199, "mrp": 2399, "rating": 4.2, "color": "Green", "image": "https://images.unsplash.com/photo-1602810318383-e386cc2a3ccf?auto=format&fit=crop&w=700&q=85"},
    {"id": "vestirio-cotton", "name": "Men Cotton Casual Shirt", "brand": "NEW Vestirio", "category": "men", "type": "Shirts", "price": 612, "mrp": 3999, "rating": 4.6, "color": "Blue", "image": "https://images.unsplash.com/photo-1617127365659-c47fa864d8bc?auto=format&fit=crop&w=700&q=85"},
    {"id": "tigc-casual", "name": "Men Casual Shirt", "brand": "The Indian Garage Co", "category": "men", "type": "Shirts", "price": 559, "mrp": 1749, "rating": 4.3, "color": "Black", "image": "https://images.unsplash.com/photo-1598033129183-c4f50c736f10?auto=format&fit=crop&w=700&q=85"},
    {"id": "cahoot-opaque", "name": "Opaque Casual Shirt", "brand": "CAHOOT", "category": "men", "type": "Shirts", "price": 1199, "mrp": 1999, "rating": 3.9, "color": "Navy Blue", "image": "https://images.unsplash.com/photo-1626497764746-6dc36546b388?auto=format&fit=crop&w=700&q=85"},
    {"id": "roadster-cotton", "name": "Men Cotton Casual Shirt", "brand": "Roadster", "category": "men", "type": "Shirts", "price": 654, "mrp": 1599, "rating": 4.4, "color": "Grey", "image": "https://images.unsplash.com/photo-1563630423918-b58f07336ac9?auto=format&fit=crop&w=700&q=85"},
    {"id": "shirt-code-slim", "name": "Slim Fit Casual Shirt", "brand": "THE SHIRT CODE", "category": "men", "type": "Shirts", "price": 714, "mrp": 2199, "rating": 4.1, "color": "Beige", "image": "https://images.unsplash.com/photo-1596755389378-c31d21fd1273?auto=format&fit=crop&w=700&q=85"},
    {"id": "highlander-opaque", "name": "Slim Fit Opaque Casual Shirt", "brand": "HIGHLANDER", "category": "men", "type": "Shirts", "price": 449, "mrp": 1799, "rating": 4.2, "color": "Blue", "image": "https://images.unsplash.com/photo-1602810319428-01920f0d6e4d?auto=format&fit=crop&w=700&q=85"},
    {"id": "roadster-chambray", "name": "Chambray Casual Shirt", "brand": "Roadster", "category": "men", "type": "Shirts", "price": 653, "mrp": 1499, "rating": 4.2, "color": "Blue", "image": "https://images.unsplash.com/photo-1607345366928-199ea26cfe3e?auto=format&fit=crop&w=700&q=85"},
    {"id": "here-now-slim", "name": "Slim Fit Casual Shirt", "brand": "HERE&NOW", "category": "men", "type": "Shirts", "price": 786, "mrp": 1999, "rating": 4.4, "color": "White", "image": "https://images.unsplash.com/photo-1603252109303-2751441dd157?auto=format&fit=crop&w=700&q=85"},
    {"id": "mast-harbour-casual", "name": "Casual Shirt", "brand": "Mast & Harbour", "category": "men", "type": "Shirts", "price": 697, "mrp": 3999, "rating": 4.2, "color": "Green", "image": "https://images.unsplash.com/photo-1596755389378-c31d21fd1273?auto=format&fit=crop&w=700&q=85"},
    {"id": "powerlook-checked", "name": "Men Checked Casual Shirt", "brand": "Powerlook", "category": "men", "type": "Shirts", "price": 1403, "mrp": 2699, "rating": 4.2, "color": "Navy Blue", "image": "https://images.unsplash.com/photo-1598033129183-c4f50c736f10?auto=format&fit=crop&w=700&q=85"},
    {"id": "adrom-cargo", "name": "Mens Cargo Shirt Army Style", "brand": "ADRO", "category": "men", "type": "Shirts", "price": 1299, "mrp": 2499, "rating": 3.8, "color": "Green", "image": "https://images.unsplash.com/photo-1551488831-00ddcb6c6bd3?auto=format&fit=crop&w=700&q=85"},
    {"id": "kenneth-cotton", "name": "Pure Cotton Casual Shirt", "brand": "Kenneth Cole", "category": "men", "type": "Shirts", "price": 989, "mrp": 2199, "rating": 4.2, "color": "White", "image": "https://images.unsplash.com/photo-1621072156002-e2fccdc0b176?auto=format&fit=crop&w=700&q=85"},
    {
        "id": "wide-leg-denim", "name": "Wide Leg High-Rise Jeans", "brand": "ONLY",
        "category": "women", "type": "Jeans", "price": 1199, "mrp": 2499, "rating": 4.5,
        "image": "https://images.unsplash.com/photo-1541099649105-f69ad21f3246?auto=format&fit=crop&w=700&q=85",
    },
    {
        "id": "floral-dress", "name": "Printed Midi Dress", "brand": "Biba",
        "category": "women", "type": "Dresses", "price": 1499, "mrp": 2999, "rating": 4.6,
        "image": "https://images.unsplash.com/photo-1496747611176-843222e1e57c?auto=format&fit=crop&w=700&q=85",
    },
    {
        "id": "kids-hoodie", "name": "Graphic Fleece Hoodie", "brand": "Myntra",
        "category": "kids", "type": "Winterwear", "price": 799, "mrp": 1599, "rating": 4.2,
        "image": "https://images.unsplash.com/photo-1519238263530-99bdd11df2ea?auto=format&fit=crop&w=700&q=85",
    },
    {
        "id": "kids-sneaker", "name": "Colourblock Everyday Sneakers", "brand": "Puma",
        "category": "kids", "type": "Footwear", "price": 1099, "mrp": 2199, "rating": 4.4,
        "image": "https://images.unsplash.com/photo-1514989940723-e8e51635b782?auto=format&fit=crop&w=700&q=85",
    },
    {
        "id": "minimal-watch", "name": "Minimal Mesh Strap Watch", "brand": "Fossil",
        "category": "watches", "type": "Watches", "price": 2499, "mrp": 5995, "rating": 4.7,
        "image": "https://images.unsplash.com/photo-1523170335258-f5ed11844a49?auto=format&fit=crop&w=700&q=85",
    },
    {
        "id": "sport-watch", "name": "Smart Active Watch", "brand": "Noise",
        "category": "watches", "type": "Watches", "price": 1799, "mrp": 3999, "rating": 4.3,
        "image": "https://images.unsplash.com/photo-1544117519-31a4b719223d?auto=format&fit=crop&w=700&q=85",
    },
    {"id": "timex-twntg04", "name": "Men Leather Strap Analogue Watch TWNTG04SMU01", "brand": "Timex", "category": "watches", "type": "Analogue Watches", "price": 2399, "mrp": 4995, "rating": 4.3, "color": "Black", "image": "https://assets.myntassets.com/h_200%2Cw_200%2Cc_fill%2Cg_auto/h_1440%2Cq_75%2Cw_1080/v1/assets/images/30990824/2024/9/18/aca49558-e546-4ecb-8b7b-0d0297fd3fb31726646795696-Timex-Analogue-White-Dial-Men-Watch---TWNTG04SMU01-373172664-1.jpg"},
    {"id": "timex-tw0tg8010", "name": "Men White Dial Gold-Toned Analogue Watch", "brand": "Timex", "category": "watches", "type": "Analogue Watches", "price": 2999, "mrp": 5995, "rating": 4.4, "color": "Gold", "image": "https://assets.myntassets.com/h_200%2Cw_200%2Cc_fill%2Cg_auto/h_1440%2Cq_75%2Cw_1080/v1/assets/images/17697496/2023/6/26/c18e6cc9-da89-4a8d-be16-6ba79f88957c1687765095917TimexMenWhiteDialGoldTonedAnalogueWatchTW0TG80101.jpg"},
    {"id": "timex-tw00zr261e", "name": "Men Off-White Dial Analogue Watch", "brand": "Timex", "category": "watches", "type": "Analogue Watches", "price": 1799, "mrp": 3995, "rating": 4.2, "color": "Brown", "image": "https://assets.myntassets.com/w_412%2Cq_50%2C%2Cdpr_3%2Cfl_progressive%2Cf_webp/assets/images/10669924/2019/9/27/ebb99a49-823b-4791-bbc9-b58ee591c29b1569578287184-Timex-Men-Off-White-Analogue-Watch-8211569578286023-1.jpg"},
    {"id": "timex-tw000r435", "name": "Men White Dial Analogue Watch TW000R435", "brand": "Timex", "category": "watches", "type": "Analogue Watches", "price": 1999, "mrp": 3995, "rating": 4.3, "color": "Gold", "image": "https://assets.myntassets.com/w_360%2Cq_50%2C%2Cdpr_2%2Cfl_progressive%2Cf_webp/assets/images/11645576/2023/6/20/63c6bd20-fc72-4f97-afa0-1a90a01a42031687245449632TimexMenWhiteAnalogueWatch-TW000R4351.jpg"},
    {"id": "timex-tw0tg8301", "name": "Men White Dial Black Leather Analogue Watch", "brand": "Timex", "category": "watches", "type": "Analogue Watches", "price": 2499, "mrp": 4995, "rating": 4.4, "color": "Black", "image": "https://assets.myntassets.com/h_200%2Cw_200%2Cc_fill%2Cg_auto/h_1440%2Cq_100%2Cw_1080/v1/assets/images/17697758/2023/6/26/7cf1ecac-fe8d-4131-beb6-e457495242301687764825478TimexMenWhiteDialBlackLeatherTexturedStrapsAnalogueWatchTW0T1.jpg"},
    {"id": "timex-twtg80smu16", "name": "Men Textured Dial Steel Bracelet Analogue Watch", "brand": "Timex", "category": "watches", "type": "Analogue Watches", "price": 3199, "mrp": 5995, "rating": 4.5, "color": "Silver", "image": "https://assets.myntassets.com/w_360%2Cq_50%2C%2Cdpr_2%2Cfl_progressive%2Cf_webp/assets/images/22231676/2023/5/19/ac755b92-cbf3-45e1-83de-ef66d7eec6b91684471972164-Timex-Men-Silver-Toned-Brass-Embellished-Dial--Silver-Toned--1.jpg"},
    {"id": "timex-tweg165smu07", "name": "Men Brass Dial Leather Strap Analogue Watch", "brand": "Timex", "category": "watches", "type": "Analogue Watches", "price": 2299, "mrp": 4995, "rating": 4.2, "color": "Brown", "image": "https://assets.myntassets.com/assets/images/22744342/2023/6/26/e90b0f96-5f71-48a7-be52-9dc38cc1bb2a1687764921384TimexMenBrassDialLeatherStrapsAnalogueWatchTWEG165SMU071.jpg"},
    {"id": "timex-twhg53smu03", "name": "Men Leather Strap Analogue Watch TWHG53SMU03", "brand": "Timex", "category": "watches", "type": "Analogue Watches", "price": 2799, "mrp": 5495, "rating": 4.3, "color": "Black", "image": "https://assets.myntassets.com/assets/images/30828598/2024/11/4/d55ffe64-aa2d-4ea9-85ca-1185f9ecc48e1730711193513-Timex-Men-Leather-Straps-Analogue-Watch-TWHG53SMU02-14817307-1.jpg"},
    {"id": "timex-twtg73smu09", "name": "Men Gold-Tone Dial Leather Strap Watch", "brand": "Timex", "category": "watches", "type": "Analogue Watches", "price": 2499, "mrp": 4995, "rating": 4.4, "color": "Brown", "image": "https://assets.myntassets.com/w_412%2Cq_50%2C%2Cdpr_3%2Cfl_progressive%2Cf_webp/assets/images/2024/OCTOBER/8/sKGnbdAl_1afa2dfdb27a407cb2e18af4f7d756f4.jpg"},
    {"id": "timex-ti000r40900", "name": "Men Silver-Toned Analogue Watch TI000R40900", "brand": "Timex", "category": "watches", "type": "Analogue Watches", "price": 1999, "mrp": 3995, "rating": 4.2, "color": "Silver", "image": "https://assets.myntassets.com/w_360%2Cq_50%2C%2Cdpr_2%2Cfl_progressive%2Cf_webp/assets/images/217957/2022/12/29/2c9b3c0e-2e32-4dba-a4a8-44e770c448ec1672309725386-Timex-Men-Silver-Toned-Analogue-Watch---TI000R40900-82416723-1.jpg"},
    {
        "id": "red-runner", "name": "Colourblock Running Shoes", "brand": "Nike",
        "category": "footwear", "type": "Sports Shoes", "price": 2899, "mrp": 5495, "rating": 4.6, "gender": "men", "color": "Red", "sizes": [7, 8, 9, 10],
        "image": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=700&q=85",
    },
    {
        "id": "everyday-sandal", "name": "Comfort Platform Sandals", "brand": "Metro",
        "category": "footwear", "type": "Sandals", "price": 999, "mrp": 1999, "rating": 4.1, "gender": "men", "color": "Brown", "sizes": [6, 7, 8, 9, 10],
        "image": "https://images.unsplash.com/photo-1562273138-f46be4ebdf33?auto=format&fit=crop&w=700&q=85",
    },
    {"id": "puma-r78-unisex", "name": "Unisex R78 Res Colourblocked Sneakers", "brand": "Puma", "category": "footwear", "type": "Sneakers", "gender": "unisex", "sizes": [6, 7, 8, 9, 10], "price": 3299, "mrp": 6599, "rating": 4.4, "color": "White", "image": "https://assets.myntassets.com/w_360%2Cq_50%2C%2Cdpr_2%2Cfl_progressive%2Cf_webp/assets/images/2025/AUGUST/26/uEziVQyR_28d04f165dc5429b9fb2cd2198d465f1.jpg"},
    {"id": "puma-idp-white-black", "name": "Men White & Black Colourblocked IDP Sneakers", "brand": "Puma", "category": "footwear", "type": "Sneakers", "gender": "men", "sizes": [7, 8, 9, 10], "price": 2799, "mrp": 5599, "rating": 4.3, "color": "White", "image": "https://assets.myntassets.com/h_200%2Cw_200%2Cc_fill%2Cg_auto/h_1440%2Cq_100%2Cw_1080/v1/assets/images/17350726/2025/3/11/7cb4864f-3aaa-4dc6-a2aa-96aba1b1622b1741693653316-Puma-Men-White--Black-Colourblocked-IDP-Sneakers-47517416936-1.jpg"},
    {"id": "puma-mesh-colourblock", "name": "Colourblocked Mesh Sneakers", "brand": "Puma", "category": "footwear", "type": "Sneakers", "gender": "unisex", "sizes": [6, 7, 8, 9, 10], "price": 2999, "mrp": 5999, "rating": 4.2, "color": "Multi", "image": "https://assets.myntassets.com/h_200%2Cw_200%2Cc_fill%2Cg_auto/h_1440%2Cq_100%2Cw_1080/v1/assets/images/17543198/2022/3/16/5dae11c5-0a06-46f1-b986-3c8c58efb3941647429427985CasualShoes1.jpg"},
    {"id": "puma-block-sneakers", "name": "Men Colour-Block Sneakers", "brand": "Puma", "category": "footwear", "type": "Sneakers", "gender": "men", "sizes": [7, 8, 9, 10], "price": 2899, "mrp": 5799, "rating": 4.5, "color": "Multi", "image": "https://assets.myntassets.com/h_200%2Cw_200%2Cc_fill%2Cg_auto/h_1440%2Cq_100%2Cw_1080/v1/assets/images/24843934/2023/10/17/9d310884-b306-4f51-aec3-c9590fc869e61697535509508-PUMA-C-Block-Mens-Shoes-6801697535509282-1.jpg"},
    {"id": "puma-colourblocked-men", "name": "Men Colourblocked Sneakers", "brand": "Puma", "category": "footwear", "type": "Sneakers", "gender": "men", "sizes": [7, 8, 9, 10, 11], "price": 3199, "mrp": 6399, "rating": 4.4, "color": "White", "image": "https://assets.myntassets.com/h_200%2Cw_200%2Cc_fill%2Cg_auto/h_1440%2Cq_100%2Cw_1080/v1/assets/images/29441362/2024/6/3/e70ccd4b-db6e-49fb-9d82-83079af636601717416404783-Puma-Men-Colourblocked-Sneakers-5671717416404492-1.jpg"},
    {"id": "puma-cblock-green", "name": "Men C-Block Colourblocked Sneakers", "brand": "Puma", "category": "footwear", "type": "Sneakers", "gender": "men", "sizes": [7, 8, 9, 10], "price": 2999, "mrp": 5999, "rating": 4.3, "color": "Green", "image": "https://assets.myntassets.com/w_412%2Cq_50%2C%2Cdpr_3%2Cfl_progressive%2Cf_webp/assets/images/24843930/2023/10/17/8f7aeeb4-32b5-46d7-86e9-2ddbe735af001697535501180-PUMA-C-Block-Mens-Shoes-2851697535501036-1.jpg"},
    {"id": "puma-xray-astralis", "name": "X-Ray Astralis Colourblocked Lace-Up Sneakers", "brand": "Puma", "category": "footwear", "type": "Sports Shoes", "gender": "men", "sizes": [7, 8, 9, 10], "price": 3499, "mrp": 6999, "rating": 4.5, "color": "Multi", "image": "https://assets.myntassets.com/w_412%2Cq_50%2C%2Cdpr_3%2Cfl_progressive%2Cf_webp/assets/images/2025/MARCH/3/FVSDo4VS_db91d1babd6a4700840f3212682c0e5b.jpg"},
    {"id": "puma-navy-white", "name": "Men Navy Blue & White Colourblocked Sneakers", "brand": "Puma", "category": "footwear", "type": "Sneakers", "gender": "men", "sizes": [7, 8, 9, 10], "price": 2799, "mrp": 5599, "rating": 4.4, "color": "Blue", "image": "https://assets.myntassets.com/h_200%2Cw_200%2Cc_fill%2Cg_auto/h_1440%2Cq_100%2Cw_1080/v1/assets/images/17350728/2022/5/11/0f1ce8f1-6394-4785-9c67-d238acce820c1652267748897-Puma-Men-Casual-Shoes-9391652267748578-1.jpg"},
    {"id": "redtape-pu-sneakers", "name": "Men PU Sneakers", "brand": "Red Tape", "category": "footwear", "type": "Casual Shoes", "gender": "men", "sizes": [6, 7, 8, 9, 10], "price": 1499, "mrp": 5999, "rating": 4.4, "color": "White", "image": "https://assets.myntassets.com/assets/images/28132186/2024/9/26/44f5154b-e087-4b4d-9154-1b8f8b14661d1727354620484-Red-Tape-Men-PU-Sneaker-1861727354620139-1.jpg"},
    {"id": "redtape-etpu-black", "name": "Men ETPU Black Sneakers", "brand": "Red Tape", "category": "footwear", "type": "Casual Shoes", "gender": "men", "sizes": [6, 7, 8, 9, 10], "price": 1799, "mrp": 5999, "rating": 4.3, "color": "Black", "image": "https://assets.myntassets.com/assets/images/30704679/2024/10/4/4c7f5c0e-1afd-4a62-8716-0c67ed1f04a11728042013918-Red-Tape-Men-PU-ETPU-Sneakers-8671728042013393-1.jpg"},
    {"id": "redtape-mesh-sneakers", "name": "Men Textured Mesh Sneakers", "brand": "Red Tape", "category": "footwear", "type": "Casual Shoes", "gender": "men", "sizes": [6, 7, 8, 9, 10], "price": 1199, "mrp": 5999, "rating": 4.2, "color": "White", "image": "https://assets.myntassets.com/assets/images/27390440/2024/9/26/901ff874-33a6-4449-b4c7-f22b2a0a42761727354481113-Red-Tape-Men-Textured-Mesh-Sneakers-5751727354480593-1.jpg"},
    {"id": "roadster-sliders", "name": "Men Black Textured Sliders", "brand": "Roadster", "category": "footwear", "type": "Sliders", "gender": "men", "sizes": [6, 7, 8, 9, 10], "price": 549, "mrp": 2749, "rating": 4.1, "color": "Black", "image": "https://assets.myntassets.com/assets/images/24300022/2023/8/2/c5fecb5e-34a9-4ed9-be5e-52bc2db6c6e61690918638104FlipFlops1.jpg"},
    {"id": "get-glamr-aviator", "name": "Unisex Aviator Sunglasses", "brand": "Get Glamr", "category": "eyewear", "type": "Aviator Sunglasses", "gender": "unisex", "sizes": ["M"], "price": 569, "mrp": 1899, "rating": 4.2, "color": "Black", "image": "https://assets.myntassets.com/assets/images/7166151/2018/8/17/4afd83a5-508c-4d77-a8da-23320649361e1534490252127-Get-Glamr-Unisex-Aviator-Sunglasses-6721534490251993-1.jpg", "images": ["https://assets.myntassets.com/assets/images/7166151/2018/8/17/4afd83a5-508c-4d77-a8da-23320649361e1534490252127-Get-Glamr-Unisex-Aviator-Sunglasses-6721534490251993-1.jpg", "https://assets.myntassets.com/assets/images/7166151/2018/8/17/c0a08a2c-64eb-424f-a94d-d501b026d33c1534490252103-Get-Glamr-Unisex-Aviator-Sunglasses-6721534490251993-2.jpg", "https://assets.myntassets.com/assets/images/7166151/2018/8/17/4353258b-aabf-433a-95cb-ed2b8745755d1534490252080-Get-Glamr-Unisex-Aviator-Sunglasses-6721534490251993-3.jpg", "https://assets.myntassets.com/assets/images/7166151/2018/8/17/d465b32f-bfae-40e5-b865-3d6b403e47fe1534490252060-Get-Glamr-Unisex-Aviator-Sunglasses-6721534490251993-4.jpg", "https://assets.myntassets.com/assets/images/7166151/2018/8/17/c57339f6-6052-4acf-8886-bef7326d50641534490252034-Get-Glamr-Unisex-Aviator-Sunglasses-6721534490251993-5.jpg"]},
    {"id": "marc-louis-polarised", "name": "Men Brown Polarised Square Sunglasses", "brand": "MARC LOUIS", "category": "eyewear", "type": "Square Sunglasses", "gender": "men", "sizes": ["M"], "price": 1372, "mrp": 5490, "rating": 4.3, "color": "Brown", "image": "https://assets.myntassets.com/assets/images/16288322/2021/11/29/7e7ce004-16b8-4a5d-96ae-1051b059472e1638175302849MARCLOUISMenBrown1.jpg", "images": ["https://assets.myntassets.com/assets/images/16288322/2021/11/29/7e7ce004-16b8-4a5d-96ae-1051b059472e1638175302849MARCLOUISMenBrown1.jpg", "https://assets.myntassets.com/assets/images/16288322/2021/11/29/da1834a7-161f-453a-99ba-bcdf9d1e864e1638175302743MARCLOUISMenBrown2.jpg", "https://assets.myntassets.com/assets/images/16288322/2021/11/29/0bde3a73-6d1a-44a0-bf42-b444242df8461638175302857MARCLOUISMenBrown3.jpg", "https://assets.myntassets.com/assets/images/16288322/2021/11/29/5d535386-1951-4d00-9fce-af00c48acebc1638175302823MARCLOUISMenBrown4.jpg", "https://assets.myntassets.com/assets/images/16288322/2021/11/29/6dd7caed-11ad-41c9-b3f9-72fe85e3860f1638175302803MARCLOUISMenBrown5.jpg"]},
    {"id": "spiky-yellow-square", "name": "Kids Yellow Lens Square Sunglasses", "brand": "Spiky", "category": "eyewear", "type": "Square Sunglasses", "gender": "unisex", "sizes": ["S"], "price": 545, "mrp": 999, "rating": 4.1, "color": "Yellow", "image": "https://assets.myntassets.com/assets/images/productimage/2021/6/16/123df84b-21c3-4efb-bb1f-8a9475dbe91f1623843003753-1.jpg", "images": ["https://assets.myntassets.com/assets/images/productimage/2021/6/16/123df84b-21c3-4efb-bb1f-8a9475dbe91f1623843003753-1.jpg", "https://assets.myntassets.com/assets/images/productimage/2021/6/16/af9ca6d0-6590-4c35-be48-75b7881fdbee1623843003762-2.jpg", "https://assets.myntassets.com/assets/images/productimage/2021/6/16/c93c6c79-6436-433e-b826-57ff089f4ed11623843003771-3.jpg", "https://assets.myntassets.com/assets/images/productimage/2021/6/16/9ff8d5d3-ab3f-4a71-be00-e9263cf58ed41623843003781-4.jpg", "https://assets.myntassets.com/assets/images/productimage/2021/6/16/4fac2bc6-9358-4ebb-b70e-a4748cd77d9d1623843003789-5.jpg"]},
    {"id": "voyage-round-silver", "name": "Unisex Black Lens & Silver-Toned Round Sunglasses", "brand": "Voyage", "category": "eyewear", "type": "Round Sunglasses", "gender": "unisex", "sizes": ["M"], "price": 799, "mrp": 3000, "rating": 4.4, "color": "Silver", "image": "https://assets.myntassets.com/assets/images/16905012/2025/5/24/04020bd5-a154-4454-9dbc-0e240f3eb03b1748094600530-Voyage-Unisex-Black-Lens--Silver-Toned-Round-Sunglasses-with-1.jpg", "images": ["https://assets.myntassets.com/assets/images/16905012/2025/5/24/04020bd5-a154-4454-9dbc-0e240f3eb03b1748094600530-Voyage-Unisex-Black-Lens--Silver-Toned-Round-Sunglasses-with-1.jpg", "https://assets.myntassets.com/assets/images/16905012/2025/5/24/7493a780-463e-40f4-b335-f6175e9a85d31748094600417-Voyage-Unisex-Black-Lens--Silver-Toned-Round-Sunglasses-with-5.jpg", "https://assets.myntassets.com/assets/images/16905012/2025/5/24/a8729786-ba10-4caf-b5b0-57952ebed6591748094600445-Voyage-Unisex-Black-Lens--Silver-Toned-Round-Sunglasses-with-4.jpg"]},
    {"id": "voyage-square-green", "name": "Unisex Square Sunglasses 58157MG2971", "brand": "Voyage", "category": "eyewear", "type": "Square Sunglasses", "gender": "unisex", "sizes": ["L"], "price": 779, "mrp": 1800, "rating": 4.3, "color": "Green", "image": "https://assets.myntassets.com/assets/images/10748638/2023/8/25/f9a46c48-5e9e-4fd7-b51d-38f1f86de8ae1692961998340-Voyage-Unisex-Square-Sunglasses-58157MG2971-6931692961997761-2.jpg", "images": ["https://assets.myntassets.com/assets/images/10748638/2023/8/25/f9a46c48-5e9e-4fd7-b51d-38f1f86de8ae1692961998340-Voyage-Unisex-Square-Sunglasses-58157MG2971-6931692961997761-2.jpg"]},
    {"id": "eyejack-square-black", "name": "Unisex Square UV Protected Sunglasses", "brand": "Eyejack", "category": "eyewear", "type": "Square Sunglasses", "gender": "unisex", "sizes": ["M"], "price": 699, "mrp": 3000, "rating": 4.3, "color": "Black", "image": "https://assets.myntassets.com/h_200%2Cw_200%2Cc_fill%2Cg_auto/h_1440%2Cq_100%2Cw_1080/v1/assets/images/32364834/2025/1/22/63a5a4cb-1af6-4859-9f78-2b4e60aeab8c1737537836194-Eyejack-Unisex-Square-Sunglasses-with-UV-Protected-Lens-5668-1.jpg", "images": ["https://assets.myntassets.com/h_200%2Cw_200%2Cc_fill%2Cg_auto/h_1440%2Cq_100%2Cw_1080/v1/assets/images/32364834/2025/1/22/63a5a4cb-1af6-4859-9f78-2b4e60aeab8c1737537836194-Eyejack-Unisex-Square-Sunglasses-with-UV-Protected-Lens-5668-1.jpg"]},
    {"id": "voyage-black-wayfarer", "name": "Unisex Black Wayfarer Sunglasses with UV Protection", "brand": "Voyage", "category": "eyewear", "type": "Wayfarer Sunglasses", "gender": "unisex", "sizes": ["L"], "price": 849, "mrp": 3000, "rating": 4.5, "color": "Black", "image": "https://assets.myntassets.com/h_200%2Cw_200%2Cc_fill%2Cg_auto/h_1440%2Cq_100%2Cw_1080/v1/assets/images/26668196/2024/9/28/074adc0e-61a4-408a-ad93-18ec6c7e18d91727514553555-Voyage-Unisex-Black-Lens--Black-Wayfarer-Sunglasses-with-Pol-1.jpg", "images": ["https://assets.myntassets.com/h_200%2Cw_200%2Cc_fill%2Cg_auto/h_1440%2Cq_100%2Cw_1080/v1/assets/images/26668196/2024/9/28/074adc0e-61a4-408a-ad93-18ec6c7e18d91727514553555-Voyage-Unisex-Black-Lens--Black-Wayfarer-Sunglasses-with-Pol-1.jpg"]},
]


def _fashion_product(product_id):
    return next((product for product in FASHION_PRODUCTS if product["id"] == product_id), None)


def _fashion_catalog(request, category="all", default_discount=0, default_gender="all"):
    products = [product.copy() for product in FASHION_PRODUCTS]
    for product in products:
        product["discount"] = round((1 - product["price"] / product["mrp"]) * 100)
    category = request.GET.get("category", category).lower()
    search = request.GET.get("q", "").strip().lower()
    product_type = request.GET.get("type", "all")
    sort = request.GET.get("sort", "recommended")
    selected_brands = request.GET.getlist("brand")
    selected_colors = request.GET.getlist("color")
    min_price = request.GET.get("min_price", "")
    max_price = request.GET.get("max_price", "")
    min_discount = request.GET.get("discount", str(default_discount))
    gender = request.GET.get("gender", default_gender).lower()
    selected_sizes = request.GET.getlist("size")

    if category != "all":
        products = [product for product in products if product["category"] == category]
    if gender == "men":
        products = [product for product in products if product.get("gender", "men") in {"men", "unisex"}]
    elif gender == "women":
        products = [product for product in products if product.get("gender", "unisex") in {"women", "unisex"}]
    if selected_sizes:
        products = [product for product in products if any(str(size) in {str(s) for s in product.get("sizes", [])} for size in selected_sizes)]
    if search:
        products = [product for product in products if search in f'{product["name"]} {product["brand"]} {product["type"]}'.lower()]
    if product_type != "all":
        products = [product for product in products if product["type"] == product_type]
    if selected_brands:
        products = [product for product in products if product["brand"] in selected_brands]
    if selected_colors:
        products = [product for product in products if product.get("color") in selected_colors]
    if min_price.isdigit():
        products = [product for product in products if product["price"] >= int(min_price)]
    if max_price.isdigit():
        products = [product for product in products if product["price"] <= int(max_price)]
    if min_discount.isdigit() and int(min_discount):
        products = [product for product in products if product["discount"] >= int(min_discount)]
    if sort == "price-low":
        products.sort(key=lambda product: product["price"])
    elif sort == "price-high":
        products.sort(key=lambda product: product["price"], reverse=True)
    elif sort == "rating":
        products.sort(key=lambda product: product["rating"], reverse=True)

    available = [product for product in FASHION_PRODUCTS if category == "all" or product["category"] == category]
    types = sorted({product["type"] for product in available})
    brands = sorted({product["brand"] for product in available})
    colors = sorted({product.get("color", "Blue") for product in available})
    sizes = sorted({str(size) for product in available for size in product.get("sizes", [])})
    return products, category, product_type, sort, types, brands, colors, selected_brands, selected_colors, min_price, max_price, min_discount, gender, sizes, selected_sizes

client = razorpay.Client(
    auth=(
        settings.RAZORPAY_KEY_ID,
        settings.RAZORPAY_KEY_SECRET
    )
)


@ensure_csrf_cookie
def home(request):

    user_data = request.session.get("user") or {}
    approved_merchants = (
        MerchantProfile.objects.filter(is_approved=True, owner__is_active=True)
        .select_related("owner")
        .prefetch_related("categories")
        .annotate(average_rating=Avg("reviews__rating"))
        .order_by("shop_name")
    )

    return render(
        request,
        "index.html",
        {
            "user_data": user_data,
            "nav_user_name": user_data.get("fullname") or user_data.get("username") or "User",
            "nav_user_email": user_data.get("email", ""),
            "approved_merchants": approved_merchants,
        }
    )


@ensure_csrf_cookie
def merchant_store(request, slug):
    merchant = get_object_or_404(
        MerchantProfile.objects.select_related("owner").annotate(
            average_rating=Avg("reviews__rating")
        ),
        slug=slug,
        is_approved=True,
        owner__is_active=True,
    )
    categories = MerchantCategory.objects.filter(
        merchant=merchant,
        products__merchant=merchant,
        products__is_active=True,
        products__stock__gt=0,
    ).distinct().order_by("name")
    products = MerchantProduct.objects.filter(
        merchant=merchant,
        is_active=True,
        stock__gt=0,
    ).filter(Q(category__isnull=True) | Q(category__merchant=merchant)).select_related("category")

    search_query = request.GET.get("q", "").strip()[:100]
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query)
        )
    selected_category = request.GET.get("category", "").strip()
    if selected_category.isdigit() and categories.filter(pk=selected_category).exists():
        products = products.filter(category_id=int(selected_category))
    else:
        selected_category = ""

    basket_count = serialize_cart(get_customer_cart(request))["item_count"]
    wishlist = request.session.get("merchant_store_wishlist", [])
    wishlist_ids = [
        int(value.split(":", 1)[1])
        for value in wishlist
        if value.startswith(f"{merchant.pk}:") and value.split(":", 1)[1].isdigit()
    ]
    return render(request, "merchant-store.html", {
        "merchant": merchant,
        "products": products,
        "categories": categories,
        "search_query": search_query,
        "selected_category": selected_category,
        "merchant_cart_count": basket_count,
        "merchant_wishlist_ids": wishlist_ids,
    })


@require_http_methods(["POST"])
@ensure_csrf_cookie
def merchant_store_cart_add(request, slug, product_id):
    merchant = get_object_or_404(
        MerchantProfile,
        slug=slug,
        is_approved=True,
        owner__is_active=True,
    )
    product = get_object_or_404(
        MerchantProduct,
        pk=product_id,
        merchant=merchant,
        is_active=True,
        stock__gt=0,
    )
    cart, error, status_code = add_product_to_cart(request, "merchant", product.pk)
    if cart is None:
        return JsonResponse({"success": False, "message": error}, status=status_code)
    cart_data = serialize_cart(cart)
    return JsonResponse({
        "success": True,
        "count": cart_data["item_count"],
        "cart_count": cart_data["item_count"],
        "message": f"{product.name} added to cart successfully.",
    })


@require_http_methods(["POST"])
@ensure_csrf_cookie
def merchant_store_wishlist_toggle(request, slug, product_id):
    merchant = get_object_or_404(
        MerchantProfile,
        slug=slug,
        is_approved=True,
        owner__is_active=True,
    )
    product = get_object_or_404(
        MerchantProduct,
        pk=product_id,
        merchant=merchant,
        is_active=True,
        stock__gt=0,
    )
    wishlist = request.session.get("merchant_store_wishlist", [])
    key = f"{merchant.pk}:{product.pk}"
    if key in wishlist:
        wishlist.remove(key)
        active = False
    else:
        wishlist.append(key)
        active = True
    request.session["merchant_store_wishlist"] = wishlist
    request.session.modified = True
    return JsonResponse({"success": True, "active": active, "message": "Wishlist updated."})


def _merchant_store_checkout_lines(request):
    basket = request.session.get("merchant_store_cart", {})
    merchant_id = basket.get("merchant_id")
    item_quantities = basket.get("items", {})
    if not merchant_id or not item_quantities:
        return None, []
    merchant = MerchantProfile.objects.filter(
        pk=merchant_id,
        is_approved=True,
        owner__is_active=True,
    ).first()
    if merchant is None:
        request.session.pop("merchant_store_cart", None)
        return None, []
    ids = [int(value) for value in item_quantities if str(value).isdigit()]
    product_map = {
        str(product.pk): product
        for product in MerchantProduct.objects.filter(
            merchant=merchant,
            pk__in=ids,
            is_active=True,
            stock__gt=0,
        ).select_related("category")
    }
    lines = []
    valid_items = {}
    for product_id, raw_quantity in item_quantities.items():
        product = product_map.get(str(product_id))
        if product is None:
            continue
        try:
            quantity = min(product.stock, max(1, int(raw_quantity)))
        except (TypeError, ValueError, OverflowError):
            continue
        valid_items[str(product.pk)] = quantity
        lines.append({
            "id": f"merchant:{merchant.pk}:{product.pk}",
            "merchant_id": merchant.pk,
            "merchant_product_id": product.pk,
            "name": product.name,
            "price": float(product.price),
            "quantity": quantity,
            "image": get_product_image(product),
            "category": "Merchant Store",
            "merchant_name": merchant.shop_name,
            "restaurant_name": merchant.shop_name,
        })
    if valid_items != item_quantities:
        request.session["merchant_store_cart"] = {
            "merchant_id": merchant.pk,
            "items": valid_items,
        } if valid_items else {}
        request.session.modified = True
    return merchant, lines


def _validate_merchant_store_checkout_lines(request, cart):
    merchant_payloads = [
        item for item in cart
        if isinstance(item, dict) and item.get("merchant_product_id") is not None
    ]
    if not merchant_payloads:
        return cart, None
    basket = request.session.get("merchant_store_cart", {})
    merchant_id = basket.get("merchant_id")
    quantities = basket.get("items", {})
    if not merchant_id or not quantities:
        raise ValueError("Your merchant store cart has expired. Please add the products again.")
    submitted = {}
    try:
        for item in merchant_payloads:
            if int(item.get("merchant_id")) != int(merchant_id):
                raise ValueError("The merchant cart is invalid. Please reload checkout.")
            product_id = str(int(item["merchant_product_id"]))
            if product_id in submitted:
                raise ValueError("Duplicate merchant cart item.")
            submitted[product_id] = int(item.get("quantity", 0))
    except (TypeError, ValueError, OverflowError):
        raise ValueError("The merchant cart is invalid. Please reload checkout.")
    if submitted != {str(key): int(value) for key, value in quantities.items()}:
        raise ValueError("Your cart changed. Please reload checkout before paying.")
    merchant = MerchantProfile.objects.filter(
        pk=merchant_id,
        is_approved=True,
        owner__is_active=True,
    ).first()
    if merchant is None:
        raise ValueError("This store is no longer available for orders.")
    products = {
        str(product.pk): product
        for product in MerchantProduct.objects.filter(
            merchant=merchant,
            pk__in=[int(product_id) for product_id in submitted],
            is_active=True,
            stock__gt=0,
        )
    }
    if set(products) != set(submitted):
        raise ValueError("A product in your cart is no longer available.")
    canonical_lines = []
    for product_id, quantity in submitted.items():
        product = products[product_id]
        if quantity < 1 or quantity > product.stock:
            raise ValueError(f"Only {product.stock} of {product.name} are currently in stock.")
        canonical_lines.append({
            "id": f"merchant:{merchant.pk}:{product.pk}",
            "merchant_id": merchant.pk,
            "merchant_product_id": product.pk,
            "name": product.name,
            "price": str(product.price),
            "quantity": quantity,
            "image": get_product_image(product),
            "category": "Merchant Store",
            "merchant_name": merchant.shop_name,
            "restaurant_name": merchant.shop_name,
        })
    non_merchant_lines = [
        item for item in cart
        if not (isinstance(item, dict) and item.get("merchant_product_id") is not None)
    ]
    return non_merchant_lines + canonical_lines, merchant


# =========================
# USER
# =========================

def login(request):
    next_url = request.POST.get("next", request.GET.get("next", "")).strip()
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        if not email or not password:
            return render(request, "login.html", {
                "login_error": "Enter your email and password.",
                "next": next_url,
            })
        user_obj = User.objects.filter(email__iexact=email).first()
        user = authenticate(request, username=user_obj.username if user_obj else email, password=password)
        if user is None or not user.is_active:
            return render(request, "login.html", {
                "login_error": "Invalid email or password.",
                "next": next_url,
            })
        guest_session_key = request.session.session_key
        auth_login(request, user)
        merge_guest_cart(user, guest_session_key)
        request.session["user"] = {
            "id": user.id,
            "username": user.username,
            "fullname": user.first_name or user.username,
            "email": user.email.lower(),
        }
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect("index")
    return render(request, "login.html", {"next": next_url})

def logout(request):
    auth_logout(request)
    request.session.pop("user", None)
    request.session.pop("access_token", None)
    request.session.pop("refresh_token", None)
    return redirect("login")


def signup(request):
    return render(request, 'signup.html')

# =========================
# CATEGORIES
# =========================

def food(request):
    return render(request, 'food.html')


def grocery(request):
    return render(request, 'grocery.html')




def shoppingwishlist(request):
    return render(request, "shoppingwishlist.html")


# =========================================================
# SHOPPING CART
# =========================================================

def shoppingcart(request):
    return redirect("cart")




    
# =========================
# FASHION
# =========================

def fashion(request):
    return render(request, "fashion.html")


def fashion_men(request):
    return render(request, "fashion-men.html", {"fashion_page": "men"})


def fashion_women(request):
    return render(request, "fashion-women.html", {"fashion_page": "women"})


def fashion_watches(request):
    products, category, product_type, sort, types, brands, colors, selected_brands, selected_colors, min_price, max_price, min_discount, gender, sizes, selected_sizes = _fashion_catalog(request, "watches", 40)
    return render(request, "fashion-watches.html", {
        "fashion_products": products, "fashion_category": category, "selected_type": product_type,
        "selected_sort": sort, "fashion_types": types, "fashion_brands": brands, "fashion_colors": colors,
        "selected_brands": selected_brands, "selected_colors": selected_colors,
        "min_price": min_price, "max_price": max_price, "min_discount": min_discount,
        "fashion_page": "watches", "fashion_product_count": len(products), "fashion_cart_count": sum(request.session.get("fashion_cart", {}).values()),
        "fashion_wishlist_count": len(request.session.get("fashion_wishlist", [])),
    })


def fashion_footwear(request):
    products, category, product_type, sort, types, brands, colors, selected_brands, selected_colors, min_price, max_price, min_discount, gender, sizes, selected_sizes = _fashion_catalog(request, "footwear", 40, "men")
    return render(request, "fashion-footwear.html", {
        "fashion_products": products, "fashion_category": category, "selected_type": product_type,
        "selected_sort": sort, "fashion_types": types, "fashion_brands": brands, "fashion_colors": colors,
        "selected_brands": selected_brands, "selected_colors": selected_colors,
        "min_price": min_price, "max_price": max_price, "min_discount": min_discount,
        "selected_gender": gender, "fashion_sizes": sizes, "selected_sizes": selected_sizes,
        "fashion_page": "footwear", "fashion_product_count": len(products), "fashion_cart_count": sum(request.session.get("fashion_cart", {}).values()),
        "fashion_wishlist_count": len(request.session.get("fashion_wishlist", [])),
    })


def fashion_eyewear(request):
    products, category, product_type, sort, types, brands, colors, selected_brands, selected_colors, min_price, max_price, min_discount, gender, sizes, selected_sizes = _fashion_catalog(request, "eyewear", 30, "all")
    return render(request, "fashion-eyewear.html", {
        "fashion_products": products, "fashion_category": category, "selected_type": product_type,
        "selected_sort": sort, "fashion_types": types, "fashion_brands": brands, "fashion_colors": colors,
        "selected_brands": selected_brands, "selected_colors": selected_colors,
        "min_price": min_price, "max_price": max_price, "min_discount": min_discount,
        "selected_gender": gender, "fashion_sizes": sizes, "selected_sizes": selected_sizes,
        "gender_options": (("all", "All genders"), ("men", "Men"), ("women", "Women"), ("unisex", "Unisex")),
        "fashion_page": "eyewear", "fashion_product_count": len(products),
        "fashion_cart_count": sum(request.session.get("fashion_cart", {}).values()),
        "fashion_wishlist_count": len(request.session.get("fashion_wishlist", [])),
    })


def fashion_kids(request):
    return render(request, "fashion-kids.html")

def fashion_add_to_cart(request, product_id):
    cached_products = request.session.get("fashion_product_cache", {})
    product = _fashion_product(product_id) or cached_products.get(product_id)
    if not product:
        return JsonResponse({"ok": False, "error": "Product not found"}, status=404)
    catalog_key = f'fashion:{product.get("category", "fashion")}:{product.get("source_id", product_id)}'
    cart, error, status_code = add_product_to_cart(request, "catalog", catalog_key)
    if cart is None:
        return JsonResponse({"ok": False, "error": error}, status=status_code)
    if request.GET.get("next") == "cart":
        return redirect("cart")
    return JsonResponse({"ok": True, "count": serialize_cart(cart)["item_count"]})


def fashion_toggle_wishlist(request, product_id):
    cached_products = request.session.get("fashion_product_cache", {})
    product = _fashion_product(product_id) or cached_products.get(product_id)
    if not product:
        return JsonResponse({"ok": False, "error": "Product not found"}, status=404)
    product_key = str(product_id) if product_id in cached_products else f'{product.get("category", "fashion")}:{product_id}'
    wishlist = request.session.get("fashion_wishlist", [])
    if product_key in wishlist:
        wishlist.remove(product_key)
        active = False
    else:
        wishlist.append(product_key)
        active = True
    cache = request.session.get("fashion_product_cache", {})
    cache[product_key] = {**product, "id": product_key}
    request.session["fashion_product_cache"] = cache
    request.session["fashion_wishlist"] = wishlist
    return JsonResponse({"ok": True, "active": active, "count": len(wishlist)})


def fashion_shopping_api(request):
    """Bridge fashion actions to the common persistent cart."""
    if request.method == "GET":
        wishlist = request.session.get("fashion_wishlist", [])
        cart_count = serialize_cart(get_customer_cart(request))["item_count"]
        return JsonResponse({"cart_count": cart_count, "wishlist_count": len(wishlist)})
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid request"}, status=400)
    action = payload.get("action")
    catalog = str(payload.get("catalog", "fashion")).lower()
    product = payload.get("product") or {}
    raw_id = str(product.get("id", "")).strip()
    if catalog not in {"men", "women"} or not raw_id:
        return JsonResponse({"ok": False, "error": "Invalid product"}, status=400)
    key = f"fashion:{catalog}:{raw_id}"
    if action == "add":
        cart, error, status_code = add_product_to_cart(request, "catalog", key)
        if cart is None:
            return JsonResponse({"ok": False, "error": error}, status=status_code)
        return JsonResponse({
            "ok": True,
            "cart_count": serialize_cart(cart)["item_count"],
            "wishlist_count": len(request.session.get("fashion_wishlist", [])),
        })
    if action == "sync" and not payload.get("wishlisted"):
        cart_count = serialize_cart(get_customer_cart(request))["item_count"]
        return JsonResponse({
            "ok": True,
            "cart_count": cart_count,
            "wishlist_count": len(request.session.get("fashion_wishlist", [])),
        })
    cached = {
        "id": key, "source_id": raw_id, "category": catalog,
        "name": str(product.get("name", "Product"))[:180],
    }
    cache = request.session.get("fashion_product_cache", {})
    cache[key] = cached
    request.session["fashion_product_cache"] = cache
    wishlist = request.session.get("fashion_wishlist", [])
    if action == "wishlist_toggle":
        if key in wishlist:
            wishlist.remove(key)
            active = False
        else:
            wishlist.append(key)
            active = True
    elif action == "sync":
        if payload.get("wishlisted") and key not in wishlist:
            wishlist.append(key)
    else:
        return JsonResponse({"ok": False, "error": "Unknown action"}, status=400)
    request.session["fashion_wishlist"] = wishlist
    request.session.modified = True
    result = {
        "ok": True,
        "cart_count": serialize_cart(get_customer_cart(request))["item_count"],
        "wishlist_count": len(wishlist),
    }
    if action == "wishlist_toggle":
        result["active"] = active
    return JsonResponse(result)

def fashion_cart_action(request, product_id, change):
    """
    Fashion cart quantity action.

    change = 1   -> increase quantity
    change = -1  -> decrease quantity
    """

    # Get fashion cart from session
    cart = request.session.get("fashion_cart", {})

    product_id = str(product_id)
    change = int(change)

    # Current quantity
    current_quantity = int(cart.get(product_id, 0))

    # New quantity
    quantity = current_quantity + change

    # Update or remove product
    if quantity > 0:
        cart[product_id] = quantity
    else:
        cart.pop(product_id, None)

    # Save cart back to session
    request.session["fashion_cart"] = cart
    request.session.modified = True

    # Return to cart page
    return redirect("cart")




def stationery(request):
    return render(request, 'stationery.html')


def electronics(request):
    return render(request, 'electronics.html')


def home_appliances(request):
    return render(request, 'home-appliances.html')

def product_detail(request, product_id):
    product = get_object_or_404(
        Product,
        id=product_id,
    )

    return render(
        request,
        "product_detail.html",
        {"product": product},
    )


def add_to_cart(request, product_id):
    return redirect("home_appliances")

def electronics_cart(request):
    return redirect("cart")






def electronics(request):
    categories = ElectronicsCategory.objects.all().order_by("name")
    products = ElectronicsProduct.objects.all().order_by("-id")

    return render(
        request,
        "electronics.html",
        {
            "categories": categories,
            "products": products,
        }
    )









# =========================
# MERCHANT
# =========================

def merchant_login(request):
    if request.user.is_authenticated and request.session.get("merchant_authenticated") and getattr(request.user, "merchant_profile", None) and request.user.merchant_profile.is_approved:
        return redirect("merchant_dashboard")

    error = ""
    if request.method == "POST":
        # The login form submits this field as ``email``; accept ``username``
        # too so older forms and bookmarked integrations continue to work.
        login_value = request.POST.get("email", request.POST.get("username", "")).strip()
        password = request.POST.get("password", "")
        if not login_value or not password:
            return render(request, "merchant-login.html", {
                "error": "Enter your shop name/email and password.",
                "active_tab": "login",
            })
        account = User.objects.filter(
            Q(username__iexact=login_value)
            | Q(email__iexact=login_value)
        ).first()
        user = authenticate(
            request,
            username=account.username if account else login_value,
            password=password,
        )
        if user is not None:
            if not user.is_active:
                return render(request, "merchant-login.html", {
                    "error": "Your merchant account is inactive. Please contact admin.",
                    "active_tab": "login",
                })
            profile = MerchantProfile.objects.filter(owner=user).first()
            if profile is None:
                return render(request, "merchant-login.html", {
                    "error": "No merchant profile is linked to this account. Register your shop or contact admin.",
                    "active_tab": "login",
                })
            if not profile.is_approved:
                error = "Your shop registration is waiting for admin approval."
                return render(request, "merchant-login.html", {"error": error, "active_tab": "login"})
            auth_login(request, user)
            request.session["merchant_authenticated"] = True
            request.session["merchant_profile"] = {
                "shop_name": profile.shop_name,
                "owner_name": user.first_name,
                "email": user.email,
            }
            return redirect("merchant_dashboard")
        error = "Invalid shop name/email or password."

    return render(request, "merchant-login.html", {"error": error, "active_tab": "login"})


def merchant_register(request):
    if request.method != "POST":
        return render(request, "merchant-login.html", {"active_tab": "register"})

    shop_name = request.POST.get("shop_name", "").strip()
    owner_name = request.POST.get("owner_name", "").strip()
    email = request.POST.get("email", "").strip().lower()
    mobile = request.POST.get("mobile", "").strip()
    password = request.POST.get("password", "")
    confirm_password = request.POST.get("confirm_password", "")

    try:
        shop_name = validate_business_name(shop_name, label="Shop name")
        owner_name = validate_person_name(owner_name, label="Owner name", min_length=2)
        email = validate_email_address(email)
        mobile = validate_mobile_number(mobile)
        if password != confirm_password:
            raise ValidationError("Passwords do not match.")
        validate_password_strength(password)
    except ValidationError as error:
        return render(request, "merchant-login.html", {
            "error": error.messages[0],
            "active_tab": "register",
            "form": request.POST,
        }, status=400)
    if User.objects.filter(username=shop_name).exists():
        return render(request, "merchant-login.html", {"error": "That shop name is already registered.", "active_tab": "register"})
    if User.objects.filter(email__iexact=email).exists():
        return render(request, "merchant-login.html", {"error": "That email is already registered.", "active_tab": "register"})

    try:
        user = User.objects.create_user(
            username=shop_name,
            email=email,
            first_name=owner_name,
            password=password,
        )
    except IntegrityError:
        return render(request, "merchant-login.html", {
            "error": "That shop name or email is already registered.",
            "active_tab": "register",
        })
    MerchantProfile.objects.create(owner=user, shop_name=shop_name, phone=mobile)
    return redirect("/merchant/login/?registered=1")


def merchant_dashboard(request):
    if not request.user.is_authenticated or not request.session.get("merchant_authenticated") or not getattr(request.user, "merchant_profile", None) or not request.user.merchant_profile.is_approved:
        return redirect("merchant_login")
    profile, _ = MerchantProfile.objects.get_or_create(
        owner=request.user,
        defaults={"shop_name": request.user.username},
    )
    orders = profile.orders.all()
    local_orders = Order.objects.filter(merchant_profile=profile)
    products = profile.products.all()
    total_revenue = (orders.aggregate(value=Sum("total"))["value"] or Decimal("0.00")) + (local_orders.aggregate(value=Sum("total_amount"))["value"] or Decimal("0.00"))
    pending_payout = profile.payouts.filter(status="pending").aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
    order_statuses = {
        status: orders.filter(status=status).count()
        for status, _ in MerchantOrder.STATUS_CHOICES
    }
    for status, count in local_orders.values_list("order_status").annotate(count=Count("id")):
        normalized = (status or "").strip().lower()
        if normalized == "delivered":
            order_statuses["delivered"] += count
        elif normalized in {"cancelled", "refunded"}:
            order_statuses[normalized] += count
        elif normalized in {"shipped", "out for delivery", "arriving soon"}:
            order_statuses["shipped"] += count
        else:
            order_statuses["processing"] += count
    top_products = list(
        MerchantOrderItem.objects.filter(order__merchant=profile)
        .values("name")
        .annotate(sold=Sum("quantity"), revenue=Sum(F("price") * F("quantity")))
        .order_by("-sold")[:5]
    )
    for item in OrderItem.objects.filter(order__merchant_profile=profile, order__order_status__iexact="Delivered").values("name").annotate(sold=Sum("quantity"), revenue=Sum(F("price") * F("quantity"))):
        existing = next((row for row in top_products if row["name"] == item["name"]), None)
        if existing:
            existing["sold"] += item["sold"] or 0
            existing["revenue"] = (existing["revenue"] or 0) + (item["revenue"] or 0)
        else:
            top_products.append(item)
    top_products = sorted(top_products, key=lambda row: row["sold"] or 0, reverse=True)[:5]
    today = timezone.localdate()
    today_orders = orders.filter(created_at__date=today)
    today_local_orders = local_orders.filter(created_at__date=today)
    dashboard_order_rows = [{
        "id": order.id,
        "kind": "merchant",
        "number": order.order_number,
        "customer": order.customer_name,
        "email": order.customer_email,
        "items": order.items.count(),
        "total": float(order.total),
        "status": order.status.lower().replace(" ", "-"),
        "time": timezone.localtime(order.created_at).strftime("%d %b %Y, %I:%M %p"),
        "sort": order.created_at.timestamp(),
    } for order in orders]
    dashboard_order_rows.extend({
        "id": order.id,
        "kind": "local",
        "number": f"LM{order.id:05d}",
        "customer": order.customer_name,
        "email": order.customer_email,
        "items": order.items.count(),
        "total": float(order.total_amount),
        "status": (order.order_status or "Placed").lower().replace(" ", "-"),
        "time": timezone.localtime(order.created_at).strftime("%d %b %Y, %I:%M %p"),
        "sort": order.created_at.timestamp(),
    } for order in local_orders)
    dashboard_order_rows.sort(key=lambda row: row["sort"], reverse=True)
    dashboard_orders = [{key: value for key, value in row.items() if key != "sort"} for row in dashboard_order_rows[:100]]
    customer_emails = set(orders.values_list("customer_email", flat=True)) | set(local_orders.values_list("customer_email", flat=True))
    sales_by_day = {}
    for queryset, amount_field in ((orders.filter(created_at__date__gte=today - timedelta(days=6)), "total"), (local_orders.filter(created_at__date__gte=today - timedelta(days=6)), "total_amount")):
        for row in queryset.annotate(day=TruncDate("created_at")).values("day").annotate(revenue=Sum(amount_field)):
            sales_by_day[row["day"]] = sales_by_day.get(row["day"], Decimal("0")) + (row["revenue"] or Decimal("0"))
    context = {
        "merchant_profile": profile,
        "merchant_owner": request.user,
        "today": today.strftime("%d %b %Y"),
        "today_orders": today_orders.count() + today_local_orders.count(),
        "today_revenue": (today_orders.aggregate(value=Sum("total"))["value"] or Decimal("0.00")) + (today_local_orders.aggregate(value=Sum("total_amount"))["value"] or Decimal("0.00")),
        "total_revenue": total_revenue,
        "total_orders": orders.count() + local_orders.count(),
        "pending_payout": pending_payout,
        "active_listings": products.filter(is_active=True).count(),
        "low_stock_count": products.filter(stock__lte=F("low_stock_threshold"), is_active=True).count(),
        "recent_orders": dashboard_order_rows[:8],
        "merchant_products": products[:12],
        "dashboard_orders": json.dumps(dashboard_orders),
        "dashboard_products": json.dumps([
            {
                "id": product.id,
                "name": product.name,
                "price": float(product.price),
                "stock": product.stock,
                "active": product.is_active,
            }
            for product in products[:20]
        ]),
        "activities": profile.activities.all()[:8],
        "unread_notifications": profile.notifications.filter(is_read=False).count(),
        "customer_count": len(customer_emails),
        "coupon_count": profile.coupons.count(),
        "payout_balance": profile.payout_balance,
        "review_count": profile.reviews.count(),
        "ticket_count": profile.tickets.exclude(status="closed").count(),
        "order_statuses": json.dumps(order_statuses),
        "top_products": json.dumps([
            {"name": item["name"], "sold": item["sold"], "revenue": float(item["revenue"] or 0)}
            for item in top_products
        ]),
        "sales_chart": json.dumps([
            {"date": (today - timedelta(days=offset)).strftime("%d %b"), "revenue": float(sales_by_day.get(today - timedelta(days=offset), 0))}
            for offset in range(6, -1, -1)
        ]),
    }
    return render(request, "merchant-dashboard.html", context)


def merchant_logout(request):
    auth_logout(request)
    request.session.pop("merchant_authenticated", None)
    request.session.pop("merchant_profile", None)
    return redirect("merchant_login")


def cart(request):
    return render(request, "shoppingcart.html")


def wishlist(request):
    wishlist_ids = request.session.get("fashion_wishlist", [])
    cached_products = request.session.get("fashion_product_cache", {})
    wishlist_items = [product for product_id in wishlist_ids if (product := (_fashion_product(product_id) or cached_products.get(product_id)))]
    return render(request, "wishlist.html", {"fashion_items": wishlist_items})


def admin_login(request):
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
        return redirect("admin_dashboard")

    error = ""
    if request.method == "POST":
        login_value = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        account = User.objects.filter(
            Q(username__iexact=login_value) | Q(email__iexact=login_value)
        ).first()
        user = authenticate(
            request,
            username=account.username if account else login_value,
            password=password,
        )
        if user is not None and user.is_active and (user.is_staff or user.is_superuser):
            auth_login(request, user)
            request.session["admin_authenticated"] = True
            return redirect("admin_dashboard")
        error = "Invalid administrator credentials or insufficient permissions."

    return render(request, "admin-login.html", {"error": error})


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def admin_forgot_password(request):
    form = CustomerPasswordResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip()
        if _password_reset_request_allowed(request, email, "admin"):
            admins = User.objects.filter(
                Q(is_staff=True) | Q(is_superuser=True),
                email__iexact=email,
                is_active=True,
            ).distinct()
            for user in admins:
                uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                reset_path = reverse(
                    "admin_reset_password",
                    kwargs={"uidb64": uidb64, "token": token},
                )
                reset_url = request.build_absolute_uri(reset_path)
                if not settings.DEBUG and reset_url.startswith("http://"):
                    reset_url = "https://" + reset_url[len("http://"):]
                context = {
                    "user_name": user.get_short_name() or user.username,
                    "reset_url": reset_url,
                    "expires_minutes": max(1, settings.PASSWORD_RESET_TIMEOUT // 60),
                }
                message = EmailMultiAlternatives(
                    subject="LocalMart Admin Password Reset",
                    body=render_to_string("emails/admin-password-reset.txt", context),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[user.email],
                )
                message.attach_alternative(
                    render_to_string("emails/admin-password-reset.html", context),
                    "text/html",
                )
                try:
                    message.send(fail_silently=False)
                except Exception:
                    logger.exception("Admin password-reset email could not be sent")
        return render(request, "admin-password-reset-sent.html", {
            "message": "If an administrator account exists with that email address, a password reset link has been sent.",
        })
    return render(request, "admin-forgot-password.html", {"form": form})


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def admin_reset_password(request, uidb64, token):
    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=user_id, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    valid_link = bool(
        user
        and (user.is_staff or user.is_superuser)
        and default_token_generator.check_token(user, token)
    )
    if not valid_link:
        return render(request, "admin-reset-password.html", {
            "valid_link": False,
            "error_message": "This password reset link is invalid or has expired. Request a new link to continue.",
        }, status=400)

    form = CustomerSetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return render(request, "admin-password-reset-success.html")
    return render(request, "admin-reset-password.html", {
        "valid_link": True,
        "form": form,
    })


def admin_dashboard(request):
    if not request.user.is_authenticated or not (
        request.user.is_staff or request.user.is_superuser
    ) or not request.session.get("admin_authenticated"):
        return redirect("admin_login")
    admin_profile, _ = AdminProfile.objects.get_or_create(user=request.user)
    orders = Order.objects.all().order_by("-created_at")
    merchant_orders = MerchantOrder.objects.all().order_by("-created_at")
    cancellation_requests = (
        CancellationRequest.objects.select_related("order", "refund")
        .order_by("-created_at")[:30]
    )
    admin_cancellation_requests = []
    for cancellation in cancellation_requests:
        refund = getattr(cancellation, "refund", None)
        if refund:
            refund_status = refund.get_status_display()
            refund_amount = refund.amount
            refund_currency = refund.currency
        elif cancellation.status == "requested" and cancellation.order.payment_status.casefold() == "paid":
            refund_status = "Pending review"
            refund_amount = cancellation.order.payment_amount or cancellation.order.total_amount
            refund_currency = cancellation.order.payment_currency or "INR"
        elif cancellation.status == "rejected":
            refund_status = "Not approved"
            refund_amount = cancellation.order.payment_amount or cancellation.order.total_amount
            refund_currency = cancellation.order.payment_currency or "INR"
        else:
            refund_status = "No captured payment"
            refund_amount = cancellation.order.payment_amount or cancellation.order.total_amount
            refund_currency = cancellation.order.payment_currency or "INR"
        admin_cancellation_requests.append({
            "id": cancellation.pk,
            "order": f"ORD-{cancellation.order_id}",
            "customer": cancellation.order.customer_name,
            "reason": cancellation.get_reason_display(),
            "details": cancellation.reason_details,
            "status": cancellation.get_status_display(),
            "status_code": cancellation.status,
            "refund_status": refund_status,
            "amount": str(refund_amount),
            "currency": refund_currency,
            "payment_method": cancellation.order.get_payment_method_display(),
            "date": timezone.localtime(cancellation.created_at).strftime("%d %b %Y, %I:%M %p"),
            "review_note": cancellation.review_note,
        })
    revenue = orders.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    revenue += merchant_orders.aggregate(total=Sum("total"))["total"] or Decimal("0.00")
    customer_count = orders.values("customer_email").distinct().count()
    customer_count += merchant_orders.values("customer_email").distinct().count()
    today = timezone.localdate()
    chart_days = [today - timedelta(days=offset) for offset in range(364, -1, -1)]
    daily_sales = {}
    for row in orders.filter(created_at__date__gte=chart_days[0]).annotate(day=TruncDate("created_at")).values("day").annotate(value=Sum("total_amount")):
        daily_sales[row["day"]] = daily_sales.get(row["day"], Decimal("0")) + (row["value"] or Decimal("0"))
    for row in merchant_orders.filter(created_at__date__gte=chart_days[0]).annotate(day=TruncDate("created_at")).values("day").annotate(value=Sum("total")):
        daily_sales[row["day"]] = daily_sales.get(row["day"], Decimal("0")) + (row["value"] or Decimal("0"))
    product_sales = {}
    for item in OrderItem.objects.values("name", "category").annotate(sold=Sum("quantity"), revenue=Sum(F("price") * F("quantity"))).order_by("-sold")[:10]:
        product_sales[item["name"]] = {"name": item["name"], "category": item["category"], "sold": item["sold"], "revenue": item["revenue"] or 0}
    for item in MerchantOrderItem.objects.values("name").annotate(sold=Sum("quantity"), revenue=Sum(F("price") * F("quantity"))).order_by("-sold")[:10]:
        row = product_sales.setdefault(item["name"], {"name": item["name"], "category": "Merchant product", "sold": 0, "revenue": Decimal("0")})
        row["sold"] += item["sold"] or 0
        row["revenue"] += item["revenue"] or Decimal("0")
    activity_items = []
    for order in orders.order_by("-created_at")[:4]:
        activity_items.append({"sort": order.created_at.timestamp(), "icon": "blue", "title": "Order received", "detail": f"Order ORD-{order.id} · {order.customer_name}", "date": order.created_at.strftime("%d %b, %I:%M %p")})
    for profile in MerchantProfile.objects.select_related("owner").order_by("-created_at")[:4]:
        activity_items.append({"sort": profile.created_at.timestamp(), "icon": "purple", "title": "Merchant application", "detail": f"{profile.shop_name} · {'Approved' if profile.is_approved else 'Awaiting review'}", "date": profile.created_at.strftime("%d %b, %I:%M %p")})
    for activity in MerchantActivity.objects.select_related("merchant").order_by("-created_at")[:4]:
        activity_items.append({"sort": activity.created_at.timestamp(), "icon": "green", "title": activity.merchant.shop_name, "detail": activity.message, "date": activity.created_at.strftime("%d %b, %I:%M %p")})
    activity_items = sorted(activity_items, key=lambda item: item["sort"], reverse=True)[:6]
    for item in activity_items: item.pop("sort", None)
    recent_orders = [
        {
            "id": f"ORD-{order.id}",
            "customer": order.customer_name,
            "date": order.created_at.strftime("%d %b %Y, %I:%M %p"),
            "status": order.order_status.lower(),
            "amount": float(order.total_amount),
            "sort": order.created_at.timestamp(),
        }
        for order in orders[:10]
    ] + [
        {
            "id": order.order_number,
            "customer": order.customer_name,
            "date": order.created_at.strftime("%d %b %Y, %I:%M %p"),
            "status": order.status,
            "amount": float(order.total),
            "sort": order.created_at.timestamp(),
        }
        for order in merchant_orders[:10]
    ]
    recent_orders.sort(key=lambda item: item["sort"], reverse=True)
    for item in recent_orders: item.pop("sort", None)
    context = {
        "admin_user": request.user,
        "admin_profile": admin_profile,
        "admin_profile_data": json.dumps({
            "first_name": request.user.first_name,
            "last_name": request.user.last_name,
            "email": request.user.email,
            "username": request.user.username,
            "mobile_number": admin_profile.mobile_number,
            "image_url": admin_profile.image_url,
            "role": "Super Admin" if request.user.is_superuser else "Administrator",
            "date_joined": request.user.date_joined.strftime("%b %d, %Y") if request.user.date_joined else "Not available",
            "last_login": request.user.last_login.strftime("%b %d, %Y %I:%M %p") if request.user.last_login else "Never",
            "is_active": request.user.is_active,
            "avatar_initial": (request.user.get_full_name() or request.user.username)[:1].upper(),
        }),
        "admin_today": today.strftime("%d %b %Y"),
        "admin_revenue": revenue,
        "admin_order_count": orders.count() + merchant_orders.count(),
        "admin_customer_count": customer_count,
        "admin_merchant_count": MerchantProfile.objects.filter(is_approved=True, owner__is_active=True).count(),
        "admin_pending_merchants": MerchantProfile.objects.filter(is_approved=False).count(),
        "admin_sales_chart": json.dumps([{"date": day.isoformat(), "label": day.strftime("%d %b"), "revenue": float(daily_sales.get(day, 0))} for day in chart_days]),
        "admin_top_products": json.dumps([{**item, "revenue": float(item["revenue"])} for item in sorted(product_sales.values(), key=lambda x: x["sold"], reverse=True)[:5]]),
        "admin_activity": json.dumps(activity_items),
        "admin_categories": Category.objects.count() + ElectronicsCategory.objects.count(),
        "admin_merchant_data": json.dumps([
            {
                "id": profile.id,
                "shop_name": profile.shop_name,
                "email": profile.owner.email,
                "is_approved": profile.is_approved,
            }
            for profile in MerchantProfile.objects.select_related("owner").order_by("shop_name")
        ]),
        "admin_recent_orders": json.dumps(recent_orders[:10]),
        "admin_cancellation_requests": json.dumps(admin_cancellation_requests),
        "admin_can_review_cancellations": request.user.has_perm("store.change_cancellationrequest"),
        "admin_product_count": Product.objects.count() + ElectronicsProduct.objects.count() + MerchantProduct.objects.count() + len(_admin_static_product_catalog()) + len(FASHION_PRODUCTS),
        "admin_category_count": Category.objects.count() + ElectronicsCategory.objects.count(),
    }
    return render(request, "admin.html", context)


def admin_logout(request):
    auth_logout(request)
    request.session.pop("admin_authenticated", None)
    return redirect("admin_login")


def _admin_api_allowed(request):
    return bool(request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser) and request.session.get("admin_authenticated"))


@require_http_methods(["POST"])
def admin_review_cancellation_api(request, cancellation_id):
    if not _admin_api_allowed(request) or not request.user.is_active:
        return JsonResponse(
            {"success": False, "message": "Administrator access required."},
            status=403,
        )
    if not request.user.has_perm("store.change_cancellationrequest"):
        return JsonResponse(
            {"success": False, "message": "You do not have permission to review cancellation requests."},
            status=403,
        )
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"success": False, "message": "Invalid JSON request."},
            status=400,
        )
    if not isinstance(data, dict):
        return JsonResponse(
            {"success": False, "message": "Invalid review request."},
            status=400,
        )
    action = data.get("action")
    review_note = data.get("review_note")
    if action not in {"approve", "reject"}:
        return JsonResponse(
            {"success": False, "message": "Choose approve or reject."},
            status=400,
        )
    if not isinstance(review_note, str) or not review_note.strip():
        return JsonResponse(
            {"success": False, "message": "Enter review remarks before submitting."},
            status=400,
        )
    if len(review_note.strip()) > 500:
        return JsonResponse(
            {"success": False, "message": "Review remarks must be 500 characters or fewer."},
            status=400,
        )

    refund = None
    try:
        if action == "approve":
            refund = approve_order_cancellation(
                cancellation_id,
                request.user,
                review_note,
            )
            cancellation = CancellationRequest.objects.get(pk=cancellation_id)
            refund_status = refund.get_status_display() if refund else "No captured payment"
        else:
            cancellation = reject_order_cancellation(
                cancellation_id,
                request.user,
                review_note,
            )
            refund_status = "Not approved"
    except CancellationRequest.DoesNotExist:
        return JsonResponse(
            {"success": False, "message": "Cancellation request not found."},
            status=404,
        )
    except CancellationWorkflowError as error:
        return JsonResponse(
            {"success": False, "message": str(error)},
            status=409,
        )

    return JsonResponse({
        "success": True,
        "status": cancellation.get_status_display(),
        "status_code": cancellation.status,
        "review_note": cancellation.review_note,
        "refund_status": refund_status,
        "message": (
            "Request approved. The refund is being processed through the original payment method."
            if action == "approve" and refund
            else "Request approved. No captured payment requires a refund."
            if action == "approve"
            else "Request rejected. The customer has been notified."
        ),
    })


@require_http_methods(["POST"])
def admin_profile_update(request):
    if not _admin_api_allowed(request):
        return JsonResponse({"success": False, "message": "Administrator access required."}, status=403)
    profile, _ = AdminProfile.objects.get_or_create(user=request.user)
    form = AdminProfileForm(request.POST, instance=profile, user=request.user)
    if not form.is_valid():
        return JsonResponse({"success": False, "errors": form.errors.get_json_data()}, status=400)
    profile = form.save()
    full_name = request.user.get_full_name()
    return JsonResponse({
        "success": True,
        "message": "Profile updated successfully.",
        "profile": {
            "first_name": request.user.first_name,
            "last_name": request.user.last_name,
            "full_name": full_name,
            "email": request.user.email,
            "username": request.user.username,
            "mobile_number": profile.mobile_number,
            "image_url": profile.image_url,
            "role": "Super Admin" if request.user.is_superuser else "Administrator",
            "avatar_initial": (full_name or request.user.username)[:1].upper(),
        },
    })


def _admin_json(request):
    if not _admin_api_allowed(request):
        return JsonResponse({"success": False, "message": "Administrator access required."}, status=403)
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def admin_merchant_approvals_api(request):
    if request.method != "GET" or not _admin_api_allowed(request):
        return JsonResponse({"success": False, "message": "Administrator access required."}, status=403)
    merchants = list(
        MerchantProfile.objects.select_related("owner").order_by("shop_name").values(
            "id", "shop_name", "owner__email", "is_approved",
        )
    )
    return JsonResponse({
        "success": True,
        "pending_count": sum(not merchant["is_approved"] for merchant in merchants),
        "merchants": [{
            "id": merchant["id"],
            "shop_name": merchant["shop_name"],
            "email": merchant["owner__email"],
            "is_approved": merchant["is_approved"],
        } for merchant in merchants],
    })


@lru_cache(maxsize=1)
def _admin_static_product_catalog():
    catalog_path = Path(__file__).with_name("admin_catalog.json")
    try:
        with catalog_path.open(encoding="utf-8") as catalog_file:
            return json.load(catalog_file)
    except (OSError, json.JSONDecodeError):
        return []


def _admin_product_group(category):
    return marketplace_category_group(category)


def admin_products_api(request, product_id=None):
    if not _admin_api_allowed(request):
        return JsonResponse({"success": False, "message": "Administrator access required."}, status=403)
    if request.method == "GET":
        qs = Product.objects.select_related("category").all()
        if product_id:
            qs = qs.filter(id=product_id)
        products = [
            {**row, "kind": "store", "category": row["category__name"], "group": _admin_product_group(row["category__name"])}
            for row in qs.values("id", "name", "brand", "price", "stock", "image", "category_id", "category__name")
        ]
        if product_id:
            return JsonResponse({"success": True, "products": products})

        for item in ElectronicsProduct.objects.select_related("category").values("id", "name", "brand", "price", "stock", "image", "category__name"):
            products.append({**item, "kind": "electronics", "category": f"Electronics / {item['category__name']}", "group": "Electronics", "stock": item["stock"]})

        seen = {(str(p["name"]).strip().casefold(), str(p.get("price", "")).strip()) for p in products}
        static_products = []
        for item in _admin_static_product_catalog():
            name = str(item.get("name", "")).strip()
            raw_price = str(item.get("price", ""))
            numeric_price = re.sub(r"[^0-9.]", "", raw_price.replace(",", ""))
            key = (name.casefold(), numeric_price)
            if not name or key in seen:
                continue
            seen.add(key)
            static_products.append({
                "id": f"static-{len(static_products) + 1}", "kind": "static",
                "name": name, "brand": item.get("brand", ""),
                "price": numeric_price or raw_price, "stock": item.get("stock"),
                "image": item.get("image", ""), "category": item.get("category", "Other"),
                "group": _admin_product_group(item.get("category")),
            })
        for item in FASHION_PRODUCTS:
            name = str(item.get("name", "")).strip()
            raw_price = str(item.get("price", ""))
            numeric_price = re.sub(r"[^0-9.]", "", raw_price.replace(",", ""))
            key = (name.casefold(), numeric_price)
            if not name or key in seen:
                continue
            seen.add(key)
            static_products.append({"id": f"fashion-{len(static_products) + 1}", "kind": "static", "name": name,
                "brand": item.get("brand", ""), "price": numeric_price or raw_price, "stock": None,
                "image": item.get("image", ""), "category": f"Shopping / {str(item.get('category', 'Fashion')).title()}", "group": "Shopping"})
        products.extend(static_products)
        return JsonResponse({"success": True, "products": products})
    data = _admin_json(request)
    if data is None:
        return JsonResponse({"success": False, "message": "Invalid JSON."}, status=400)
    if request.method == "POST" and product_id is None:
        try:
            category_id = validate_whole_number(
                data.get("category_id"),
                label="Category",
                minimum=1,
            )
            category = Category.objects.filter(id=category_id).first()
            if category is None:
                raise ValidationError("Choose a valid product category.")
            name = validate_business_name(
                data.get("name", ""),
                label="Product name",
                max_length=255,
            )
            brand = validate_business_name(
                data.get("brand", ""),
                label="Brand",
                max_length=150,
                required=False,
            )
            price = validate_amount(
                data.get("price", ""),
                label="Price",
                allow_zero=True,
                max_value=Decimal("99999999.99"),
            )
            stock = validate_whole_number(
                data.get("stock", 0),
                label="Stock",
                maximum=2147483647,
            )
            image = validate_http_url(data.get("image", ""))
            product = Product.objects.create(
                category=category,
                name=name,
                brand=brand,
                price=price,
                stock=stock,
                image=image,
            )
        except (ValueError, TypeError, InvalidOperation, ValidationError) as error:
            message = error.messages[0] if isinstance(error, ValidationError) else "Provide a valid category, product name, price, stock, and image URL."
            return JsonResponse({"success": False, "message": message}, status=400)
        return JsonResponse({"success": True, "product_id": product.id}, status=201)
    if not product_id:
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)
    product = get_object_or_404(Product, id=product_id)
    if request.method == "DELETE":
        product.delete()
        return JsonResponse({"success": True})
    if request.method not in ("PATCH", "PUT"):
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)
    try:
        if "category_id" in data:
            category_id = validate_whole_number(data["category_id"], label="Category", minimum=1)
            category = Category.objects.filter(id=category_id).first()
            if category is None:
                raise ValidationError("Choose a valid product category.")
            product.category = category
        if "name" in data:
            product.name = validate_business_name(data["name"], label="Product name", max_length=255)
        if "brand" in data:
            product.brand = validate_business_name(data["brand"], label="Brand", max_length=150, required=False)
        if "image" in data:
            product.image = validate_http_url(data["image"])
        if "price" in data:
            product.price = validate_amount(data["price"], label="Price", allow_zero=True, max_value=Decimal("99999999.99"))
        if "stock" in data:
            product.stock = validate_whole_number(data["stock"], label="Stock", maximum=2147483647)
        product.save()
    except (ValueError, TypeError, InvalidOperation, ValidationError) as error:
        message = error.messages[0] if isinstance(error, ValidationError) else "Enter valid product details."
        return JsonResponse({"success": False, "message": message}, status=400)
    return JsonResponse({"success": True})


def admin_merchant_products_api(request, product_id=None):
    if not _admin_api_allowed(request): return JsonResponse({"success": False, "message": "Administrator access required."}, status=403)
    qs = MerchantProduct.objects.select_related("merchant", "category").all()
    if request.method == "GET":
        if product_id: qs = qs.filter(id=product_id)
        return JsonResponse({"success": True, "products": list(qs.values("id", "name", "sku", "merchant__shop_name", "category__name", "price", "stock", "is_active"))})
    if not product_id: return JsonResponse({"success": False, "message": "Product ID required."}, status=400)
    product = get_object_or_404(MerchantProduct, id=product_id)
    if request.method == "DELETE": product.delete(); return JsonResponse({"success": True})
    if request.method not in ("PATCH", "PUT"): return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)
    data = _admin_json(request)
    if data is None: return JsonResponse({"success": False, "message": "Invalid JSON."}, status=400)
    if not isinstance(data.get("is_active"), bool): return JsonResponse({"success": False, "message": "is_active must be true or false."}, status=400)
    product.is_active = data["is_active"]
    product.save(update_fields=["is_active", "updated_at"])
    return JsonResponse({"success": True})


def admin_categories_api(request, category_id=None):
    if not _admin_api_allowed(request):
        return JsonResponse({"success": False, "message": "Administrator access required."}, status=403)
    if request.method == "GET":
        qs = Category.objects.all()
        if category_id: qs = qs.filter(id=category_id)
        return JsonResponse({"success": True, "categories": list(qs.values("id", "name"))})
    data = _admin_json(request)
    if data is None: return JsonResponse({"success": False, "message": "Invalid JSON."}, status=400)
    if request.method == "POST" and category_id is None:
        try:
            name = validate_business_name(data.get("name", ""), label="Category name", max_length=150)
        except ValidationError as error:
            return JsonResponse({"success": False, "message": error.messages[0]}, status=400)
        category, created = Category.objects.get_or_create(name=name)
        return JsonResponse({"success": True, "category_id": category.id}, status=201 if created else 200)
    if not category_id: return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)
    category = get_object_or_404(Category, id=category_id)
    if request.method == "DELETE":
        if category.products.exists(): return JsonResponse({"success": False, "message": "Move or delete this category’s products first."}, status=400)
        category.delete(); return JsonResponse({"success": True})
    if request.method not in ("PATCH", "PUT"): return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)
    try:
        name = validate_business_name(data.get("name", ""), label="Category name", max_length=150)
    except ValidationError as error:
        return JsonResponse({"success": False, "message": error.messages[0]}, status=400)
    category.name = name
    try: category.save()
    except IntegrityError: return JsonResponse({"success": False, "message": "That category already exists."}, status=400)
    return JsonResponse({"success": True})


def admin_customers_api(request):
    if request.method != "GET" or not _admin_api_allowed(request):
        return JsonResponse({"success": False, "message": "Administrator access required."}, status=403)
    orders = list(Order.objects.values("customer_email", "customer_name").annotate(order_count=Count("id"), spent=Sum("total_amount")))
    merchant_orders = list(MerchantOrder.objects.values("customer_email", "customer_name").annotate(order_count=Count("id"), spent=Sum("total")))
    customer_map = {}
    for row in orders + merchant_orders:
        customer = customer_map.setdefault(row["customer_email"], {"email": row["customer_email"], "name": row["customer_name"], "orders": 0, "spent": Decimal("0")})
        customer["orders"] += row["order_count"]
        customer["spent"] += row["spent"] or Decimal("0")
    return JsonResponse({"success": True, "customers": [{**c, "spent": str(c["spent"])} for c in customer_map.values()]})


def admin_orders_api(request):
    if not _admin_api_allowed(request):
        return JsonResponse({"success": False, "message": "Administrator access required."}, status=403)
    if request.method == "GET":
        rows = [{"kind": "store", "id": o.id, "number": f"ORD-{o.id}", "customer": o.customer_name, "date": o.created_at.strftime("%d %b %Y, %I:%M %p"), "sort": o.created_at.timestamp(), "status": o.order_status, "amount": str(o.total_amount)} for o in Order.objects.all().order_by("-created_at")]
        rows += [{"kind": "merchant", "id": o.id, "number": o.order_number, "customer": o.customer_name, "date": o.created_at.strftime("%d %b %Y, %I:%M %p"), "sort": o.created_at.timestamp(), "status": o.status, "amount": str(o.total)} for o in MerchantOrder.objects.all().order_by("-created_at")]
        rows.sort(key=lambda row: row["sort"], reverse=True)
        for row in rows: row.pop("sort", None)
        return JsonResponse({"success": True, "orders": rows})
    if request.method not in ("PATCH", "PUT"):
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)
    data = _admin_json(request)
    if data is None: return JsonResponse({"success": False, "message": "Invalid JSON."}, status=400)
    kind, status_value = data.get("kind"), str(data.get("status", "")).strip()
    allowed = ["Placed", "Processing", "Shipped", "Delivered"] if kind == "store" else ["Pending", "Confirmed", "Processing", "Packed", "Shipped", "Out for Delivery", "Delivered", "Cancelled", "Returned"]
    normalized = {v.lower(): v for v in allowed}.get(status_value.lower())
    if not normalized: return JsonResponse({"success": False, "message": "Invalid order status."}, status=400)
    order_model = Order if kind == "store" else MerchantOrder if kind == "merchant" else None
    if order_model is None: return JsonResponse({"success": False, "message": "Invalid order type."}, status=400)
    order = get_object_or_404(order_model, id=data.get("id"))
    field = "order_status" if kind == "store" else "status"
    if kind == "store" and order.order_status.casefold() == "cancellation requested":
        return JsonResponse({
            "success": False,
            "message": "This order is on hold for a cancellation review.",
        }, status=409)
    if kind == "store" and order.order_status.casefold() in {"cancelled", "refunded"}:
        return JsonResponse({
            "success": False,
            "message": "Cancelled or refunded orders cannot be changed through order status updates.",
        }, status=409)
    setattr(order, field, normalized)
    order.save(update_fields=[field])
    return JsonResponse({"success": True})


def admin_coupons_api(request, coupon_id=None):
    if not _admin_api_allowed(request): return JsonResponse({"success": False, "message": "Administrator access required."}, status=403)
    if request.method == "GET":
        qs = MerchantCoupon.objects.select_related("merchant").all()
        if coupon_id: qs = qs.filter(id=coupon_id)
        return JsonResponse({"success": True, "coupons": list(qs.values("id", "code", "merchant__shop_name", "percentage", "fixed_amount", "active", "expires_at"))})
    if not coupon_id: return JsonResponse({"success": False, "message": "Coupon ID required."}, status=400)
    coupon = get_object_or_404(MerchantCoupon, id=coupon_id)
    if request.method == "DELETE": coupon.delete(); return JsonResponse({"success": True})
    if request.method not in ("PATCH", "PUT"): return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)
    data = _admin_json(request)
    if data is None: return JsonResponse({"success": False, "message": "Invalid JSON."}, status=400)
    if "active" in data:
        if not isinstance(data["active"], bool): return JsonResponse({"success": False, "message": "Active must be true or false."}, status=400)
        coupon.active = data["active"]
    try:
        if "percentage" in data:
            coupon.percentage = validate_whole_number(
                data["percentage"],
                label="Percentage discount",
                maximum=100,
            )
        if "fixed_amount" in data:
            coupon.fixed_amount = validate_amount(
                data["fixed_amount"],
                label="Fixed discount",
                allow_zero=True,
                max_value=Decimal("9999999999.99"),
            )
    except (ValueError, TypeError, InvalidOperation, ValidationError) as error:
        message = error.messages[0] if isinstance(error, ValidationError) else "Enter a valid coupon discount."
        return JsonResponse({"success": False, "message": message}, status=400)
    coupon.save(); return JsonResponse({"success": True})


def admin_marketplace_coupons_api(request, coupon_id=None):
    if not _admin_api_allowed(request):
        return JsonResponse({"success": False, "message": "Administrator access required."}, status=403)
    if request.method == "GET":
        coupons = MarketplaceCoupon.objects.all()
        if coupon_id is not None:
            coupons = coupons.filter(id=coupon_id)
        return JsonResponse({
            "success": True,
            "coupons": list(coupons.values(
                "id",
                "code",
                "description",
                "discount_type",
                "discount_value",
                "minimum_order_amount",
                "maximum_discount_amount",
                "eligible_categories",
                "active",
                "expires_at",
            )),
        })

    data = _admin_json(request)
    if data is None:
        return JsonResponse({"success": False, "message": "Invalid JSON."}, status=400)
    if request.method == "POST" and coupon_id is None:
        coupon = MarketplaceCoupon()
    elif coupon_id is not None and request.method in ("PATCH", "PUT", "DELETE"):
        coupon = get_object_or_404(MarketplaceCoupon, pk=coupon_id)
        if request.method == "DELETE":
            coupon.delete()
            return JsonResponse({"success": True})
    else:
        return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)

    try:
        if "code" in data or request.method == "POST":
            code = data.get("code", "")
            if not isinstance(code, str):
                raise ValidationError("Enter a valid coupon code.")
            code = code.strip().upper()
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,39}", code):
                raise ValidationError("Coupon codes must be 2-40 letters, numbers, hyphens, or underscores.")
            if MarketplaceCoupon.objects.filter(code__iexact=code).exclude(pk=coupon.pk).exists():
                raise ValidationError("That coupon code already exists.")
            coupon.code = code

        if "description" in data or request.method == "POST":
            description = data.get("description", "")
            if not isinstance(description, str):
                raise ValidationError("Enter a valid coupon description.")
            description = description.strip()
            if not 5 <= len(description) <= 280:
                raise ValidationError("Coupon descriptions must be between 5 and 280 characters.")
            coupon.description = description

        if "discount_type" in data or request.method == "POST":
            discount_type = data.get("discount_type", "")
            if discount_type not in {"percentage", "fixed"}:
                raise ValidationError("Choose percentage or fixed amount.")
            coupon.discount_type = discount_type

        if "discount_value" in data or request.method == "POST":
            maximum = Decimal("100") if data.get("discount_type", coupon.discount_type) == "percentage" else Decimal("9999999999.99")
            coupon.discount_value = validate_amount(
                data.get("discount_value"),
                label="Discount",
                max_value=maximum,
            )

        if "minimum_order_amount" in data or request.method == "POST":
            coupon.minimum_order_amount = validate_amount(
                data.get("minimum_order_amount", "0"),
                label="Minimum order amount",
                allow_zero=True,
                max_value=Decimal("9999999999.99"),
            )

        if "maximum_discount_amount" in data or request.method == "POST":
            value = data.get("maximum_discount_amount", "")
            coupon.maximum_discount_amount = (
                None
                if value in ("", None)
                else validate_amount(
                    value,
                    label="Maximum discount",
                    max_value=Decimal("9999999999.99"),
                )
            )

        if "eligible_categories" in data or request.method == "POST":
            categories = data.get("eligible_categories", [])
            allowed_categories = {
                value for value, _label in MarketplaceCoupon.MARKETPLACE_CATEGORIES
            }
            if (
                not isinstance(categories, list)
                or any(not isinstance(category, str) or category not in allowed_categories for category in categories)
            ):
                raise ValidationError("Choose valid marketplace categories.")
            coupon.eligible_categories = list(dict.fromkeys(categories))

        if "expires_at" in data or request.method == "POST":
            raw_expiry = data.get("expires_at", "")
            if raw_expiry in ("", None):
                coupon.expires_at = None
            elif isinstance(raw_expiry, str):
                expires_at = parse_datetime(raw_expiry)
                if expires_at is None:
                    raise ValidationError("Enter a valid coupon expiration date.")
                coupon.expires_at = (
                    timezone.make_aware(expires_at)
                    if timezone.is_naive(expires_at)
                    else expires_at
                )
                if coupon.expires_at <= timezone.now():
                    raise ValidationError("Coupon expiration must be in the future.")
            else:
                raise ValidationError("Enter a valid coupon expiration date.")

        if "active" in data:
            if not isinstance(data["active"], bool):
                raise ValidationError("Coupon status must be true or false.")
            coupon.active = data["active"]
        elif request.method == "POST":
            coupon.active = True
        if coupon.discount_type == "percentage" and coupon.discount_value > Decimal("100"):
            raise ValidationError("Percentage discounts cannot exceed 100%.")
        if coupon.discount_value <= 0:
            raise ValidationError("Discount must be greater than zero.")
    except (ValidationError, TypeError, ValueError, InvalidOperation) as error:
        message = error.messages[0] if isinstance(error, ValidationError) else "Enter valid coupon details."
        return JsonResponse({"success": False, "message": message}, status=400)

    try:
        coupon.save()
    except IntegrityError:
        return JsonResponse({"success": False, "message": "That coupon code already exists."}, status=400)
    return JsonResponse({"success": True, "coupon_id": coupon.pk}, status=201 if request.method == "POST" else 200)


def admin_reviews_api(request, review_id=None):
    if not _admin_api_allowed(request): return JsonResponse({"success": False, "message": "Administrator access required."}, status=403)
    if request.method == "GET":
        qs = MerchantReview.objects.select_related("merchant", "product").all()
        if review_id: qs = qs.filter(id=review_id)
        return JsonResponse({"success": True, "reviews": list(qs.values("id", "merchant__shop_name", "product__name", "customer_name", "rating", "comment", "reply", "created_at"))})
    if request.method not in ("PATCH", "PUT"): return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)
    data = _admin_json(request)
    if data is None: return JsonResponse({"success": False, "message": "Invalid JSON."}, status=400)
    review = get_object_or_404(MerchantReview, id=review_id)
    reply = data.get("reply", "")
    if not isinstance(reply, str) or len(reply) > 5000:
        return JsonResponse({"success": False, "message": "Review replies must be text with no more than 5,000 characters."}, status=400)
    review.reply = reply.strip()
    review.save(update_fields=["reply"]); return JsonResponse({"success": True})


def admin_payouts_api(request, payout_id=None):
    if not _admin_api_allowed(request): return JsonResponse({"success": False, "message": "Administrator access required."}, status=403)
    if request.method == "GET":
        qs = MerchantPayout.objects.select_related("merchant").all()
        if payout_id: qs = qs.filter(id=payout_id)
        return JsonResponse({"success": True, "payouts": list(qs.values("id", "merchant__shop_name", "amount", "status", "reference", "created_at"))})
    if request.method not in ("PATCH", "PUT"): return JsonResponse({"success": False, "message": "Method not allowed."}, status=405)
    data = _admin_json(request)
    if data is None: return JsonResponse({"success": False, "message": "Invalid JSON."}, status=400)
    payout = get_object_or_404(MerchantPayout, id=payout_id)
    status_value = data.get("status", "")
    if not isinstance(status_value, str):
        return JsonResponse({"success": False, "message": "Choose a valid payout status."}, status=400)
    status_value = status_value.lower()
    if status_value not in {"pending", "paid", "failed"}: return JsonResponse({"success": False, "message": "Invalid payout status."}, status=400)
    payout.status = status_value
    if "reference" in data:
        reference = data["reference"]
        if not isinstance(reference, str) or len(reference) > 120:
            return JsonResponse({"success": False, "message": "Payout reference must be text with no more than 120 characters."}, status=400)
        payout.reference = reference.strip()
    payout.save(update_fields=["status", "reference"]); return JsonResponse({"success": True})


def admin_approve_merchant(request, merchant_id):
    if request.method != "POST" or not _admin_api_allowed(request):
        return JsonResponse({"success": False, "message": "Admin permission required."}, status=403)
    profile = get_object_or_404(MerchantProfile, id=merchant_id)
    profile.is_approved = True
    profile.approved_at = timezone.now()
    profile.save(update_fields=["is_approved", "approved_at"])
    return JsonResponse({"success": True, "merchant_id": profile.id})


def admin_delete_merchant(request, merchant_id):
    if request.method != "POST" or not _admin_api_allowed(request):
        return JsonResponse({"success": False, "message": "Admin permission required."}, status=403)
    profile = get_object_or_404(MerchantProfile, pk=merchant_id)
    if not profile.is_approved:
        return JsonResponse({"success": False, "message": "Only approved merchant stores can be deleted here."}, status=400)
    deleted_name = profile.shop_name
    profile.delete()
    return JsonResponse({"success": True, "merchant_id": merchant_id, "shop_name": deleted_name})


def admin_export_report(request):
    if not _admin_api_allowed(request):
        return redirect("admin_login")
    section = request.GET.get("section", "overview")
    if section not in {"overview", "orders", "merchants"}:
        return JsonResponse({"success": False, "message": "Unknown report section."}, status=400)

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    body_style = styles["BodyText"]
    body_style.fontSize = 7
    body_style.leading = 9

    def cell(value):
        text = str(value if value is not None else "")
        safe_text = escape_xml(text.encode("ascii", "replace").decode("ascii"))
        return Paragraph(safe_text, body_style)

    report = BytesIO()
    document = SimpleDocTemplate(
        report,
        pagesize=landscape(A4),
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30,
        title=f"LocalMart {section.title()} Report",
    )
    content = [
        Paragraph(f"LocalMart {section.title()} Report", title_style),
        Paragraph(f"Generated {timezone.localtime().strftime('%d %b %Y, %I:%M %p')}", body_style),
        Spacer(1, 14),
    ]
    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
    ])

    if section in {"overview", "orders"}:
        content.append(Paragraph("Orders", styles["Heading2"]))
        order_rows = [[cell(value) for value in ("Order", "Customer", "Email", "Status", "Amount", "Date")]]
        for order in Order.objects.all().order_by("-created_at"):
            order_rows.append([cell(value) for value in (
                f"ORD-{order.id}", order.customer_name, order.customer_email,
                order.order_status, f"INR {order.total_amount:.2f}",
                timezone.localtime(order.created_at).strftime("%d %b %Y, %I:%M %p"),
            )])
        for order in MerchantOrder.objects.all().order_by("-created_at"):
            order_rows.append([cell(value) for value in (
                order.order_number, order.customer_name, order.customer_email,
                order.status, f"INR {order.total:.2f}",
                timezone.localtime(order.created_at).strftime("%d %b %Y, %I:%M %p"),
            )])
        content.append(Table(order_rows, colWidths=[75, 125, 175, 90, 75, 145], repeatRows=1, style=table_style))

    if section in {"overview", "merchants"}:
        if section == "overview":
            content.extend([Spacer(1, 18)])
        content.append(Paragraph("Merchants", styles["Heading2"]))
        merchant_rows = [[cell(value) for value in ("Store", "Owner email", "Phone", "Status", "Payout balance", "Registered")]]
        for merchant in MerchantProfile.objects.select_related("owner").order_by("shop_name"):
            merchant_rows.append([cell(value) for value in (
                merchant.shop_name, merchant.owner.email, merchant.phone,
                "Approved" if merchant.is_approved else "Pending",
                f"{merchant.currency} {merchant.payout_balance:.2f}",
                timezone.localtime(merchant.created_at).strftime("%d %b %Y, %I:%M %p"),
            )])
        content.append(Table(merchant_rows, colWidths=[140, 175, 100, 85, 105, 145], repeatRows=1, style=table_style))

    document.build(content)
    response = HttpResponse(report.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="localmart-{section}-report.pdf"'
    return response


CUSTOMER_RESET_GENERIC_MESSAGE = (
    "If an account exists with that email address, a password reset link has been sent."
)


def _password_reset_request_allowed(request, email, scope):
    """Rate-limit password-reset requests without placing emails in cache keys."""
    ip = request.META.get("REMOTE_ADDR", "unknown")
    email_hash = hashlib.sha256(email.casefold().encode("utf-8")).hexdigest()
    ip_hash = hashlib.sha256(ip.encode("utf-8")).hexdigest()
    try:
        outcomes = []
        for key, limit in (
            (f"{scope}-reset:email:{email_hash}", 3),
            (f"{scope}-reset:ip:{ip_hash}", 10),
        ):
            if cache.add(key, 1, timeout=3600):
                outcomes.append(True)
            else:
                outcomes.append(cache.incr(key) <= limit)
        return all(outcomes)
    except Exception:
        logger.warning("Customer password-reset rate-limit cache unavailable")
        return True


def _customer_reset_users(email):
    """Only customer accounts use this flow; merchant and admin accounts have separate login flows."""
    return User.objects.filter(
        email__iexact=email,
        is_active=True,
        is_staff=False,
        is_superuser=False,
    ).exclude(merchant_profile__isnull=False).distinct()


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def forgot_password(request):
    form = CustomerPasswordResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip()
        if _password_reset_request_allowed(request, email, "customer"):
            for user in _customer_reset_users(email):
                uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                reset_path = reverse(
                    "user_reset_password",
                    kwargs={"uidb64": uidb64, "token": token},
                )
                reset_url = request.build_absolute_uri(reset_path)
                if not settings.DEBUG and reset_url.startswith("http://"):
                    reset_url = "https://" + reset_url[len("http://"):]
                context = {
                    "user_name": user.first_name or user.username,
                    "reset_url": reset_url,
                    "expires_minutes": max(1, settings.PASSWORD_RESET_TIMEOUT // 60),
                }
                text_body = render_to_string("emails/user-password-reset.txt", context)
                html_body = render_to_string("emails/user-password-reset.html", context)
                message = EmailMultiAlternatives(
                    subject="LocalMart Password Reset",
                    body=text_body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[user.email],
                )
                message.attach_alternative(html_body, "text/html")
                try:
                    message.send(fail_silently=False)
                except Exception:
                    logger.exception("Customer password-reset email could not be sent")
        return render(request, "user-password-reset-sent.html", {
            "message": CUSTOMER_RESET_GENERIC_MESSAGE,
        })
    return render(request, "user-forgot-password.html", {"form": form})


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def user_reset_password(request, uidb64, token):
    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=user_id, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    valid_link = bool(
        user
        and not user.is_staff
        and not user.is_superuser
        and not hasattr(user, "merchant_profile")
        and default_token_generator.check_token(user, token)
    )
    if not valid_link:
        return render(request, "user-reset-password.html", {
            "valid_link": False,
            "error_message": "This password reset link is invalid or has expired. Request a new link to continue.",
        }, status=400)

    form = CustomerSetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return render(request, "user-password-reset-success.html")
    return render(request, "user-reset-password.html", {
        "valid_link": True,
        "form": form,
    })


def _customer_order_owner_filter(user):
    owner_filter = Q(customer_user=user)
    if user.email:
        owner_filter |= Q(
            customer_user__isnull=True,
            customer_email__iexact=user.email,
        )
    return owner_filter


def _order_status_snapshot(order):
    cancellation = order.latest_cancellation
    refund = getattr(cancellation, "refund", None) if cancellation else None
    snapshot = {
        "order_status": order.order_status,
        "payment_status": order.payment_status,
        "cancellation": (
            {
                "status": cancellation.status,
                "review_note": cancellation.review_note,
                "updated_at": cancellation.updated_at.isoformat(),
            }
            if cancellation
            else None
        ),
        "refund": (
            {
                "status": refund.status,
                "failure_reason": refund.failure_reason,
                "gateway_refund_id": refund.gateway_refund_id,
                "updated_at": refund.updated_at.isoformat(),
            }
            if refund
            else None
        ),
    }
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"))


def _customer_order_list(user):
    orders = list(
        Order.objects.filter(_customer_order_owner_filter(user))
        .prefetch_related(
            "items",
            Prefetch(
                "cancellation_requests",
                queryset=CancellationRequest.objects.select_related("refund").order_by("-created_at"),
            ),
        )
        .order_by("-created_at")
    )
    for order in orders:
        cancellation_history = list(order.cancellation_requests.all())
        order.latest_cancellation = cancellation_history[0] if cancellation_history else None
        order.status_snapshot = _order_status_snapshot(order)
        order.refund_review_pending = (
            order.latest_cancellation is not None
            and order.latest_cancellation.status == "requested"
            and order.payment_status.casefold() == "paid"
        )
        order.can_request_cancellation = (
            order_can_be_cancelled(order)
            and (
                order.latest_cancellation is None
                or order.latest_cancellation.status == "rejected"
            )
        )
    return orders


@login_required(login_url="login")
@require_http_methods(["GET"])
def my_order_status_updates(request):
    orders = (
        Order.objects.filter(_customer_order_owner_filter(request.user))
        .prefetch_related(
            Prefetch(
                "cancellation_requests",
                queryset=CancellationRequest.objects.select_related("refund").order_by("-created_at"),
            ),
        )
        .order_by("-created_at")
    )
    updates = []
    for order in orders:
        cancellation_history = list(order.cancellation_requests.all())
        order.latest_cancellation = cancellation_history[0] if cancellation_history else None
        updates.append({
            "id": order.pk,
            "snapshot": _order_status_snapshot(order),
        })
    return JsonResponse(
        {"orders": updates},
        headers={"Cache-Control": "no-store"},
    )


@login_required(login_url="login")
def orders(request):
    return render(
        request,
        "shoppingmy-orders.html",
        {
            "orders": _customer_order_list(request.user),
            "cancellation_reason_choices": CancellationRequest.REASON_CHOICES,
        },
    )


@login_required(login_url="login")
def shopping_my_orders(request):
    return render(
        request,
        "shoppingmy-orders.html",
        {
            "orders": _customer_order_list(request.user),
            "cancellation_reason_choices": CancellationRequest.REASON_CHOICES,
        },
    )


@login_required(login_url="login")
@require_http_methods(["POST"])
def request_order_cancellation_view(request, order_id):
    try:
        request_order_cancellation(
            order_id=order_id,
            user=request.user,
            reason=request.POST.get("reason", ""),
            details=request.POST.get("details", ""),
        )
    except Order.DoesNotExist:
        raise Http404("Order not found.")
    except CancellationWorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request,
            "Your order is on hold while LocalMart reviews your cancellation request.",
        )
    return redirect("shopping_my_orders")

def restaurant_menu(request, id):
    return render(request, "restaurant_menu.html")

class SignupAPIView(APIView):

    def post(self, request):

        try:
            full_name = validate_person_name(
                str(request.data.get("full_name") or ""),
                label="Full name",
                min_length=3,
            )
            email = validate_email_address(request.data.get("email"))
            mobile = validate_mobile_number(request.data.get("mobile"))
            password = request.data.get("password", "")
            confirm_password = request.data.get("confirm_password", "")
            if not isinstance(password, str) or not password:
                raise ValidationError("Password is required.")
            if password != confirm_password:
                raise ValidationError("Passwords do not match.")
            validate_password_strength(password)
        except ValidationError as error:
            return Response(
                {"error": error.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate required fields
        # Check existing email
        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {"error": "An account with this email already exists."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check username
        username = email.split("@")[0]

        if User.objects.filter(username=username).exists():
            username = f"{username}_{mobile[-4:]}"

        # Create Django user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=full_name
        )

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "message": "Account created successfully.",
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "fullname": full_name,
                    "email": user.email,
                    "mobile": mobile
                }
            },
            status=status.HTTP_201_CREATED
        )





class LoginAPIView(APIView):

    permission_classes = [AllowAny]

    def post(self, request):

        email = request.data.get("email", "").strip().lower()
        password = request.data.get("password", "")

        if not email or not password:

            return Response(
                {
                    "error": "Email and password are required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ==========================================
        # FIND USER
        # ==========================================

        user_obj = User.objects.filter(
            email__iexact=email,
            is_active=True,
        ).order_by("id").first()

        if user_obj is None:
            return Response(
                {"error": "Invalid email or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # ==========================================
        # AUTHENTICATE
        # ==========================================

        user = authenticate(
            username=user_obj.username,
            password=password
        )

        if user is None:

            return Response(
                {
                    "error": "Invalid email or password."
                },
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Create the regular Django auth session too, so protected pages and
        # session-based account features recognize this API login.
        auth_login(request, user)

        # ==========================================
        # JWT TOKENS
        # ==========================================

        refresh = RefreshToken.for_user(user)

        access_token = str(
            refresh.access_token
        )

        refresh_token = str(
            refresh
        )

        # ==========================================
        # SAVE USER IN SESSION
        # ==========================================

        request.session["access_token"] = access_token

        request.session["refresh_token"] = refresh_token

        request.session["user"] = {

            "id": user.id,

            "username": user.username,

            "fullname": (
                user.first_name
                or user.username
            ),

            "email": user.email.lower(),

        }

        request.session.modified = True

        print("========================================")
        print("LOGIN SUCCESSFUL")
        print("USER ID:", user.id)
        print("USER EMAIL:", user.email)
        print("SESSION USER:", request.session.get("user"))
        print("========================================")

        # ==========================================
        # RESPONSE
        # ==========================================

        return Response(
            {
                "message": "Login successful.",

                "user": {

                    "id": user.id,

                    "username":
                        user.username,

                    "fullname":
                        user.first_name
                        or user.username,

                    "email":
                        user.email,

                },

                "access":
                    access_token,

                "refresh":
                    refresh_token,

            },
            status=status.HTTP_200_OK
        )









@api_view(['POST'])
def api_signup(request):

    try:
        username = validate_person_name(
            str(request.data.get("username") or ""),
            label="Full name",
            min_length=3,
        )
        email = validate_email_address(request.data.get("email"))
        mobile = validate_mobile_number(request.data.get("mobile"))
        password = request.data.get("password", "")
        confirm_password = request.data.get("confirm_password", "")
        if not isinstance(password, str) or not password:
            raise ValidationError("Password is required.")
        if not confirm_password:
            raise ValidationError("Confirm password is required.")
        if password != confirm_password:
            raise ValidationError("Passwords do not match.")
        validate_password_strength(password)
    except ValidationError as error:
        return Response(
            {"error": error.messages[0]},
            status=status.HTTP_400_BAD_REQUEST,
        )


    # ==============================
    # REQUIRED FIELD VALIDATION
    # ==============================

    if not username:
        return Response(
            {
                'error': 'Full name is required.'
            },
            status=status.HTTP_400_BAD_REQUEST
        )


    if not email:
        return Response(
            {
                'error': 'Email is required.'
            },
            status=status.HTTP_400_BAD_REQUEST
        )


    if not password:
        return Response(
            {
                'error': 'Password is required.'
            },
            status=status.HTTP_400_BAD_REQUEST
        )


    if not confirm_password:
        return Response(
            {
                'error': 'Confirm password is required.'
            },
            status=status.HTTP_400_BAD_REQUEST
        )


    # ==============================
    # PASSWORD MATCH
    # ==============================

    if password != confirm_password:

        return Response(
            {
                'error': 'Passwords do not match.'
            },
            status=status.HTTP_400_BAD_REQUEST
        )


    # ==============================
    # CHECK EMAIL
    # ==============================

    if User.objects.filter(email__iexact=email).exists():

        return Response(
            {
                'error': 'Email already registered.'
            },
            status=status.HTTP_400_BAD_REQUEST
        )


    # ==============================
    # CREATE UNIQUE USERNAME
    # ==============================

    base_username = username.replace(
        ' ',
        '_'
    ).lower()

    final_username = base_username

    counter = 1


    while User.objects.filter(
        username=final_username
    ).exists():

        final_username = (
            f"{base_username}{counter}"
        )

        counter += 1


    # ==============================
    # CREATE USER
    # ==============================

    user = User.objects.create_user(

        username=final_username,

        email=email,

        password=password

    )


    # ==============================
    # JWT TOKENS
    # ==============================

    refresh = RefreshToken.for_user(user)

    access_token = str(
        refresh.access_token
    )


    # ==============================
    # RESPONSE
    # ==============================

    return Response(

        {
            'message':
                'Account created successfully.',

            'access':
                access_token,

            'refresh':
                str(refresh),

            'user': {

                'id':
                    user.id,

                'username':
                    user.username,

                'email':
                    user.email,

                'mobile':
                    mobile

            }

        },

        status=status.HTTP_201_CREATED

    )






# ==========================================
# GOOGLE LOGIN
# ==========================================

def google_login(request):
    next_url = request.GET.get("next", "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        request.session["login_next_url"] = next_url

    google_auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }

    from urllib.parse import urlencode

    url = (
        google_auth_url
        + "?"
        + urlencode(params)
    )

    return redirect(url)


# ==========================================
# GOOGLE CALLBACK
# ==========================================

def google_callback(request):

    code = request.GET.get("code")

    if not code:

        return redirect(
            "/login/?error=google_login_failed"
        )


    next_url = request.session.pop("login_next_url", "")

    # ==========================================
    # EXCHANGE CODE FOR GOOGLE ACCESS TOKEN
    # ==========================================

    token_response = requests.post(

        "https://oauth2.googleapis.com/token",

        data={

            "code": code,

            "client_id":
                settings.GOOGLE_CLIENT_ID,

            "client_secret":
                settings.GOOGLE_CLIENT_SECRET,

            "redirect_uri":
                settings.GOOGLE_REDIRECT_URI,

            "grant_type":
                "authorization_code",

        }

    )


    token_data = token_response.json()


    if "access_token" not in token_data:

        return redirect(
            "/login/?error=google_token_failed"
        )


    google_access_token = (
        token_data["access_token"]
    )


    # ==========================================
    # GET GOOGLE USER INFORMATION
    # ==========================================

    user_response = requests.get(

        "https://www.googleapis.com/oauth2/v2/userinfo",

        headers={

            "Authorization":
                f"Bearer {google_access_token}"

        }

    )


    google_user = user_response.json()


    google_id = google_user.get(
        "id"
    )

    email = (google_user.get("email") or "").strip().lower()

    full_name = google_user.get(
        "name",
        ""
    )

    first_name = google_user.get(
        "given_name",
        ""
    )


    if not email:

        return redirect(
            "/login/?error=google_email_missing"
        )


    # ==========================================
    # FIND EXISTING USER
    # ==========================================

    # Duplicate emails can exist in older LocalMart data. Prefer the oldest
    # active matching account deterministically; never create another account
    # just because the email already exists more than once.
    user = User.objects.filter(
        email__iexact=email,
        is_active=True,
    ).order_by("id").first()

    if user is None:
        if User.objects.filter(email__iexact=email).exists():
            return redirect("/login/?error=google_account_disabled")

        # ==========================================
        # CREATE NEW USER
        # ==========================================

        base_username = (
            email.split("@")[0]
        )

        username = base_username

        counter = 1


        while User.objects.filter(
            username=username
        ).exists():

            username = (
                f"{base_username}{counter}"
            )

            counter += 1


        user = User.objects.create_user(

            username=username,

            email=email,

            first_name=first_name,

            password=None

        )


        user.set_unusable_password()

        user.save()


    # Establish the same Django authenticated session as email/password login.
    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    # ==========================================
    # GENERATE JWT TOKENS
    # ==========================================

    refresh = RefreshToken.for_user(
        user
    )

    access_token = str(
        refresh.access_token
    )

    refresh_token = str(
        refresh
    )


    # ==========================================
    # SAVE DATA IN SESSION
    # ==========================================

    request.session[
        "access_token"
    ] = access_token

    request.session[
        "refresh_token"
    ] = refresh_token

    request.session[
        "user"
    ] = {

        "id":
            user.id,

        "username":
            user.username,

        "fullname":
            full_name
            or first_name
            or user.first_name
            or user.username,

        "email":
            (user.email or email).strip().lower(),

    }


    # ==========================================
    # REDIRECT TO HOME
    # ==========================================

    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)

    return redirect(
        "index"
    )



def _import_legacy_merchant_cart(request):
    legacy_cart = request.session.get("merchant_store_cart", {})
    merchant_id = legacy_cart.get("merchant_id")
    item_quantities = legacy_cart.get("items", {})
    if not merchant_id or not item_quantities:
        return

    merchant = MerchantProfile.objects.filter(
        pk=merchant_id,
        is_approved=True,
        owner__is_active=True,
    ).first()
    if merchant is None:
        raise ValueError("This merchant cart is no longer available.")

    validated_items = []
    for product_id, raw_quantity in item_quantities.items():
        try:
            product_id = int(product_id)
            quantity = int(raw_quantity)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("The saved merchant cart contains invalid products.")
        product = MerchantProduct.objects.filter(
            pk=product_id,
            merchant=merchant,
            is_active=True,
        ).first()
        if product is None or quantity < 1 or quantity > product.stock:
            raise ValueError("A saved merchant cart product is no longer available.")
        validated_items.append((product.pk, quantity))

    with transaction.atomic():
        for product_id, quantity in validated_items:
            cart, error, _ = add_product_to_cart(
                request,
                "merchant",
                product_id,
                quantity,
            )
            if cart is None:
                raise ValueError(error)

    request.session.pop("merchant_store_cart", None)
    request.session.modified = True


@login_required(login_url="login")
@ensure_csrf_cookie
def checkout(request):
    try:
        _import_legacy_merchant_cart(request)
    except ValueError as error:
        logger.warning("Unable to import a saved merchant cart: %s", error)
    cart = serialize_cart(get_customer_cart(request))
    checkout_items = [
        {**item, "price": float(item["price"])}
        for item in cart["items"]
    ]
    user_data = request.session.get("user") or {}
    checkout_customer_name = user_data.get("fullname") or user_data.get("username", "")
    checkout_customer_email = user_data.get("email", "")

    return render(
        request,
        "checkout.html",
        {
            "razorpay_key_id": settings.RAZORPAY_KEY_ID,
            "electronics_checkout_cart": json.dumps(checkout_items),
            "checkout_summary": json.dumps({
                key: cart[key]
                for key in ("subtotal", "coupon", "coupon_discount", "tax", "total")
            }),
            "checkout_customer_name": checkout_customer_name,
            "checkout_customer_email": checkout_customer_email,
        }
    )


def _checkout_authentication_error(request):
    if request.user.is_authenticated:
        return None
    return JsonResponse({
        "success": False,
        "message": "Please log in before placing an order or making a payment.",
        "login_url": f"{reverse('login')}?next={reverse('checkout')}",
    }, status=401)





def _verified_checkout_cart_lines(customer_cart):
    cart = []
    cart_merchant_ids = set()
    merchant_products = {}
    cart_lines = customer_cart.items.select_related("content_type").order_by("id")

    for line in cart_lines:
        source = next(
            (key for key, model in PRODUCT_TYPES.items() if model._meta.model_name == line.content_type.model),
            None,
        )
        product = get_inventory_product(source, line.object_id) if source else None
        stock = get_product_stock(product) if product is not None else None
        if product is None or (stock is not None and stock < line.quantity):
            raise ValueError(
                f"{getattr(product, 'name', 'A cart product')} is no longer available in the requested quantity."
            )
        if source == "merchant":
            cart_merchant_ids.add(product.merchant_id)
            merchant_products[product.merchant_id] = product.merchant
        cart_item = {
            "id": product.pk,
            "item_id": line.pk,
            "source": source,
            "content_type": line.content_type,
            "name": product.name,
            "category": get_product_category(product),
            "marketplace_category": marketplace_category_group(
                get_product_category(product),
                source=source,
                catalog_key=getattr(product, "catalog_key", ""),
            ),
            "price": str(product.discounted_price if isinstance(product, ElectronicsProduct) else product.price),
            "quantity": line.quantity,
            "image": get_product_image(product),
        }
        if source == "merchant":
            cart_item.update({
                "merchant_id": product.merchant_id,
                "merchant_product_id": product.pk,
                "merchant_name": product.merchant.shop_name,
                "restaurant_name": product.merchant.shop_name,
            })
        cart.append(cart_item)

    cart_merchant = (
        merchant_products[next(iter(cart_merchant_ids))]
        if cart and all(line["source"] == "merchant" for line in cart) and len(cart_merchant_ids) == 1
        else None
    )
    return cart, cart_merchant


def _checkout_totals(cart_model, subtotal):
    coupon = get_applied_marketplace_coupon(cart_model, subtotal)
    if coupon and not coupon["eligible"]:
        raise ValueError("The applied coupon is no longer eligible. Remove it from your cart and try again.")
    coupon_discount = Decimal(coupon["discount_amount"]) if coupon else Decimal("0.00")
    taxable_subtotal = subtotal - coupon_discount
    tax = (taxable_subtotal * Decimal("0.05")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    total = taxable_subtotal + tax
    return coupon, coupon_discount, taxable_subtotal, tax, total


def _create_order_items(
    order,
    cart,
    subtotal,
    tax,
    coupon_discount=Decimal("0.00"),
    eligible_categories=None,
):
    remaining_tax = tax
    remaining_discount = coupon_discount
    taxable_subtotal = subtotal - coupon_discount
    eligible_categories = set(eligible_categories or [])
    discountable_items = [
        item
        for item in cart
        if not eligible_categories or item.get("marketplace_category") in eligible_categories
    ]
    discountable_subtotal = sum(
        (
            Decimal(str(item.get("price", 0))) * int(item.get("quantity", 1))
            for item in discountable_items
        ),
        Decimal("0.00"),
    )
    last_discountable_index = max(
        (
            index
            for index, item in enumerate(cart)
            if not eligible_categories or item.get("marketplace_category") in eligible_categories
        ),
        default=None,
    )
    for index, item in enumerate(cart):
        price = Decimal(str(item.get("price", 0)))
        quantity = int(item.get("quantity", 1))
        line_total = (price * quantity).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        discountable = (
            not eligible_categories
            or item.get("marketplace_category") in eligible_categories
        )
        if not discountable:
            line_discount = Decimal("0.00")
        elif index == last_discountable_index:
            line_discount = remaining_discount
        elif discountable_subtotal:
            line_discount = min(
                remaining_discount,
                (coupon_discount * line_total / discountable_subtotal).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                ),
            )
        else:
            line_discount = Decimal("0.00")
        remaining_discount -= line_discount
        line_taxable = line_total - line_discount
        if index == len(cart) - 1:
            line_tax = remaining_tax
        elif taxable_subtotal:
            line_tax = min(
                remaining_tax,
                (tax * line_taxable / taxable_subtotal).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                ),
            )
        else:
            line_tax = Decimal("0.00")
        remaining_tax -= line_tax
        raw_product_id = item.get("id")
        product_id = (
            int(raw_product_id)
            if not isinstance(raw_product_id, bool) and str(raw_product_id or "").isdigit()
            else None
        )
        content_type = item.get("content_type")
        if not isinstance(content_type, ContentType):
            product_id = None
            content_type = None

        OrderItem.objects.create(
            order=order,
            name=item.get("name", "Product"),
            category=item.get("category", ""),
            price=price,
            quantity=quantity,
            image=item.get("image", ""),
            product_content_type=content_type,
            product_object_id=product_id,
            line_total=line_total,
            original_line_amount=line_total,
            taxable_value=line_taxable,
            total_tax=line_tax,
            gst_rate=Decimal("5.00"),
            tax_treatment="exclusive",
            price_includes_gst=False,
            catalog_source=str(item.get("source") or "")[:30],
            source_product_id=str(raw_product_id or "")[:180],
            coupon_discount_amount=line_discount,
        )


def create_razorpay_order(request):
    authentication_error = _checkout_authentication_error(request)
    if authentication_error:
        return authentication_error

    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "message": "Only POST requests are allowed."
        }, status=405)

    try:

        # ==========================================
        # READ FRONTEND DATA
        # ==========================================

        data = json.loads(request.body)

        _import_legacy_merchant_cart(request)
        customer_cart = get_customer_cart(request)
        cart_payload = serialize_cart(customer_cart)
        if not cart_payload["items"]:
            return JsonResponse({
                "success": False,
                "message": "Cart is empty."
            }, status=400)

        try:
            cart, cart_merchant = _verified_checkout_cart_lines(customer_cart)
        except ValueError as error:
            return JsonResponse({"success": False, "message": str(error)}, status=409)

        # ==========================================
        # CUSTOMER INFORMATION
        # ==========================================

        customer_name = data.get("customer_name", "")
        customer_email = data.get("customer_email", "")
        customer_phone = data.get("phone") or data.get("customer_phone", "")
        customer_address = data.get("customer_address", "")
        restaurant_name = str(data.get("restaurant_name", "")).strip()[:180]
        if cart_merchant:
            merchant_profile = cart_merchant
            restaurant_name = cart_merchant.shop_name
        else:
            merchant_matches = MerchantProfile.objects.filter(is_approved=True, shop_name__iexact=restaurant_name) if restaurant_name else MerchantProfile.objects.none()
            merchant_profile = merchant_matches.first() if merchant_matches.count() == 1 else None
        raw_lat, raw_lng = data.get("customer_latitude"), data.get("customer_longitude")
        try:
            delivery_lat = float(raw_lat) if raw_lat is not None else None
            delivery_lng = float(raw_lng) if raw_lng is not None else None
            if (isinstance(raw_lat, bool) or isinstance(raw_lng, bool)
                    or (delivery_lat is None) != (delivery_lng is None)
                    or (delivery_lat is not None and (not math.isfinite(delivery_lat) or not -90 <= delivery_lat <= 90))
                    or (delivery_lng is not None and (not math.isfinite(delivery_lng) or not -180 <= delivery_lng <= 180))):
                raise ValueError
        except (TypeError, ValueError):
            return JsonResponse({"success": False, "message": "Confirm a valid delivery pin on the map."}, status=400)
        delivery_confirmed = data.get("delivery_location_confirmed") is True and delivery_lat is not None
        if not delivery_confirmed:
            return JsonResponse({"success": False, "message": "Confirm your delivery location on the map before payment."}, status=400)

        # ==========================================
        # SESSION USER FALLBACK
        # Only use session email if frontend
        # did NOT send customer email
        # ==========================================

        user_data = request.session.get("user")

        if user_data:
            if customer_name in (None, ""):
                customer_name = user_data.get("fullname") or user_data.get("username", "")
            if customer_email in (None, ""):
                customer_email = user_data.get("email", "")

        try:
            if customer_name in (None, ""):
                raise ValidationError("Customer name is required.")
            if not customer_address:
                raise ValidationError("Delivery address is required.")
            customer_name = validate_person_name(
                customer_name,
                label="Customer name",
                max_length=150,
            )
            customer_email = validate_email_address(customer_email)
            customer_phone = validate_mobile_number(customer_phone)
            customer_address = validate_address(customer_address)
        except ValidationError as error:
            return JsonResponse({
                "success": False,
                "message": error.messages[0],
            }, status=400)

        # ==========================================
        # DEFAULT CUSTOMER NAME
        # ==========================================

        # ==========================================
        # EMAIL REQUIRED
        # ==========================================

        if not customer_email:
            return JsonResponse({
                "success": False,
                "message": "Customer email is required."
            }, status=400)

        # ==========================================
        # FINAL CUSTOMER DETAILS DEBUG
        # ==========================================

        # ==========================================
        # CALCULATE TOTAL
        # ==========================================

        subtotal = Decimal("0.00")

        for item in cart:

            price = Decimal(
                str(item.get("price", 0))
            )

            quantity = int(
                item.get("quantity", 1)
            )

            if price <= 0:
                return JsonResponse({
                    "success": False,
                    "message": (
                        f"Invalid price for "
                        f"{item.get('name', 'Product')}"
                    )
                }, status=400)

            if quantity <= 0:
                return JsonResponse({
                    "success": False,
                    "message": (
                        f"Invalid quantity for "
                        f"{item.get('name', 'Product')}"
                    )
                }, status=400)

            subtotal += price * quantity

        subtotal = subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # ==========================================
        # 5% TAX
        # ==========================================

        try:
            coupon, coupon_discount, taxable_subtotal, tax, total = _checkout_totals(
                customer_cart,
                subtotal,
            )
        except ValueError as error:
            return JsonResponse({"success": False, "message": str(error)}, status=409)

        # ==========================================
        # CONVERT INR TO PAISE
        # ==========================================

        amount = int(
            total * Decimal("100")
        )

        # ==========================================
        # CREATE RAZORPAY ORDER
        # ==========================================

        import time

        receipt_id = (
            "localmart_"
            + str(int(time.time()))
            + "_"
            + uuid.uuid4().hex[:6]
        )

        with transaction.atomic():
            local_order = Order.objects.create(
                customer_name=customer_name,
                customer_email=customer_email,
                customer_user=request.user if request.user.is_authenticated else None,
                cart=customer_cart,
                delivery_address=customer_address,
                customer_latitude=delivery_lat,
                customer_longitude=delivery_lng,
                delivery_latitude=delivery_lat,
                delivery_longitude=delivery_lng,
                delivery_location_confirmed=delivery_confirmed,
                restaurant_name=restaurant_name,
                merchant_profile=merchant_profile,
                subtotal=subtotal,
                taxable_total=taxable_subtotal,
                gst_total=tax,
                cgst_total=Decimal("0.00"),
                sgst_total=Decimal("0.00"),
                igst_total=Decimal("0.00"),
                discount_total=coupon_discount,
                coupon_discount=coupon_discount,
                coupon_code=coupon["code"] if coupon else "",
                total_amount=total,
                payment_method="razorpay",
                payment_currency="INR",
                payment_amount=total,
                payment_status="Pending",
                order_status="Placed",
            )
            _create_order_items(
                local_order,
                cart,
                subtotal,
                tax,
                coupon_discount,
                coupon["eligible_categories"] if coupon else [],
            )

            razorpay_order = client.order.create({
                "amount": amount,
                "currency": "INR",
                "receipt": receipt_id,
                "payment_capture": 1
            })
            razorpay_order_id = razorpay_order.get("id")
            if not razorpay_order_id:
                raise ValueError("Razorpay did not return an order ID.")

            local_order.payment_id = razorpay_order_id
            local_order.razorpay_order_id = razorpay_order_id
            local_order.save(update_fields=["payment_id", "razorpay_order_id"])

        logger.info("Razorpay checkout order created successfully.")

        # ==========================================
        # RESPONSE
        # ==========================================

        return JsonResponse({

            "success": True,

            "key_id":
                settings.RAZORPAY_KEY_ID,

            "amount":
                amount,

            "currency":
                "INR",

            "order_id":
                razorpay_order_id,

            "local_order_id":
                local_order.id,

            "customer_email":
                local_order.customer_email,

            "subtotal":
                float(subtotal),

            "tax":
                float(tax),

            "total":
                float(total),

            "coupon_discount":
                float(coupon_discount),

            "coupon_code":
                coupon["code"] if coupon else ""
        })

    # ==============================================
    # INVALID JSON
    # ==============================================

    except json.JSONDecodeError:

        return JsonResponse({
            "success": False,
            "message": "Invalid JSON request."
        }, status=400)

    # ==============================================
    # OTHER ERRORS
    # ==============================================

    except Exception as error:
        logger.error(
            "Razorpay checkout order creation failed (%s).",
            type(error).__name__,
        )
        return JsonResponse({
            "success": False,
            "message": "We could not start the payment. Please retry; this attempt was not charged."
        }, status=502)


# ==============================================
# ORDER SUCCESS
# ==============================================

@login_required(login_url="login")
def order_success(request):
    orders = Order.objects.filter(
        Q(customer_user=request.user)
        | Q(
            customer_user__isnull=True,
            customer_email__iexact=request.user.email,
        ),
        payment_status__iexact="Paid",
    ).exclude(order_status__in=["Cancelled", "Refunded", "Cancellation Requested"])
    order_id = request.GET.get("order_id")
    order = orders.filter(pk=order_id).first() if order_id and order_id.isdigit() else orders.order_by("-created_at").first()
    if order is None and order_id and order_id.isdigit():
        cancelled_order = Order.objects.filter(
            Q(customer_user=request.user)
            | Q(
                customer_user__isnull=True,
                customer_email__iexact=request.user.email,
            ),
            pk=order_id,
            payment_status__iexact="Paid",
            order_status__in=["Cancellation Requested", "Cancelled", "Refunded"],
        ).first()
        if cancelled_order:
            return redirect("shopping_my_orders")
    if order:
        ensure_tracking_session(order)
    return render(
        request,
        "order-success.html",
        {"tracked_order": order}
    )


def send_order_confirmation_email(order):

    items = order.items.all()

    subtotal = Decimal("0.00")

    item_lines = []

    for item in items:

        item_total = item.price * item.quantity

        subtotal += item_total

        item_lines.append(
            f"""
Product       : {item.name}
Category      : {item.category}
Quantity      : {item.quantity}
Price         : Rs. {item.price:.2f}
Amount        : Rs. {item_total:.2f}
"""
        )

    items_text = "\n----------------------------------------\n".join(
        item_lines
    )

    subtotal = order.subtotal or subtotal
    coupon_discount = order.coupon_discount or Decimal("0.00")
    tax = order.gst_total or (subtotal * Decimal("0.05"))
    total = order.total_amount or (subtotal - coupon_discount + tax)

    message = f"""
LOCALMART
ORDER CONFIRMATION
========================================

Hello {order.customer_name},

Thank you for shopping with LocalMart!

Your payment has been successfully completed
and your order has been confirmed.

========================================
ORDER DETAILS
========================================

Order ID       : #{order.id}

Order Date     : {order.created_at.strftime('%d %b %Y, %I:%M %p')}

Customer Name  : {order.customer_name}

Customer Email : {order.customer_email}

Order Status   : {order.order_status}

Payment Status : {order.payment_status}


Payment ID     : {order.payment_id}

========================================
ORDER ITEMS
========================================

{items_text}


========================================
BILL SUMMARY
========================================

Subtotal       : Rs. {subtotal:.2f}

Coupon discount: Rs. {coupon_discount:.2f}

Tax (5%)       : Rs. {tax:.2f}

----------------------------------------
TOTAL PAID     : Rs. {total:.2f}
----------------------------------------


========================================
PAYMENT DETAILS
========================================

Payment Status : PAID

Payment ID     : {order.payment_id}

Order ID       : #{order.id}


========================================

Thank you for ordering with LocalMart!

Your order has been successfully confirmed.

Regards,
LocalMart Team

This is an automated confirmation email.
"""

    print("========================================")
    print("SENDING ORDER CONFIRMATION EMAIL")
    print("TO:", order.customer_email)
    print("ORDER:", order.id)
    print("========================================")

    result = send_mail(

        subject=f"LocalMart Order Confirmation - #{order.id}",

        message=message,

        from_email=settings.DEFAULT_FROM_EMAIL,

        recipient_list=[
            order.customer_email
        ],

        fail_silently=False
    )

    print(
        "EMAIL SEND RESULT:",
        result
    )

def _paypal_base_url():
    return "https://api-m.paypal.com" if settings.PAYPAL_MODE == "live" else "https://api-m.sandbox.paypal.com"


def _paypal_access_token():
    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        raise ValueError("PayPal credentials are not configured.")
    response = requests.post(
        f"{_paypal_base_url()}/v1/oauth2/token",
        auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
        headers={"Accept": "application/json"},
        data={"grant_type": "client_credentials"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _paypal_checkout_details(request, data):
    if not isinstance(data, dict):
        raise ValueError("Enter valid checkout details.")
    _import_legacy_merchant_cart(request)
    customer_cart = get_customer_cart(request)
    if not customer_cart.items.exists():
        raise ValueError("Cart is empty.")
    cart, cart_merchant = _verified_checkout_cart_lines(customer_cart)
    user_data = request.session.get("user") or {}
    customer_name = data.get("customer_name", "")
    customer_email = data.get("customer_email", "")
    if customer_name in (None, ""):
        customer_name = user_data.get("fullname", "")
    if customer_email in (None, ""):
        customer_email = user_data.get("email", "")
    customer_phone = data.get("customer_phone") or data.get("phone") or ""
    customer_address = data.get("customer_address", "")
    try:
        if customer_name in (None, ""):
            raise ValidationError("Customer name is required.")
        if not customer_address:
            raise ValidationError("Delivery address is required.")
        customer_name = validate_person_name(customer_name, label="Customer name", max_length=150)
        customer_email = validate_email_address(customer_email)
        validate_mobile_number(customer_phone)
        validate_address(customer_address)
    except ValidationError as error:
        raise ValueError(error.messages[0]) from None
    subtotal = Decimal("0.00")
    for item in cart:
        price = Decimal(str(item.get("price", 0)))
        quantity = int(item.get("quantity", 1))
        if price <= 0 or quantity <= 0:
            raise ValueError(f"Invalid cart item: {item.get('name', 'Product')}")
        subtotal += price * quantity
    subtotal = subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    coupon, coupon_discount, taxable_subtotal, tax, total = _checkout_totals(
        customer_cart,
        subtotal,
    )
    return {
        "cart": cart,
        "cart_model": customer_cart,
        "cart_merchant": cart_merchant,
        "customer_name": customer_name,
        "customer_email": customer_email,
        "customer_address": customer_address,
        "subtotal": subtotal,
        "taxable_subtotal": taxable_subtotal,
        "tax": tax,
        "total": total,
        "coupon": coupon,
        "coupon_discount": coupon_discount,
    }


def create_paypal_order(request):
    authentication_error = _checkout_authentication_error(request)
    if authentication_error:
        return authentication_error
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Only POST requests are allowed."}, status=405)
    try:
        data = json.loads(request.body)
        checkout = _paypal_checkout_details(request, data)
        cart = checkout["cart"]
        customer_name = checkout["customer_name"]
        customer_email = checkout["customer_email"]
        subtotal = checkout["subtotal"]
        taxable_subtotal = checkout["taxable_subtotal"]
        tax = checkout["tax"]
        total = checkout["total"]
        coupon = checkout["coupon"]
        coupon_discount = checkout["coupon_discount"]
        cart_merchant = checkout["cart_merchant"]
        paypal_amount = (
            total * Decimal(str(settings.PAYPAL_INR_TO_USD))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        access_token = _paypal_access_token()
        response = requests.post(
            f"{_paypal_base_url()}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Prefer": "return=representation"},
            json={"intent": "CAPTURE", "purchase_units": [{"reference_id": "localmart-order", "amount": {"currency_code": settings.PAYPAL_CURRENCY, "value": f"{paypal_amount:.2f}"}}]},
            timeout=20,
        )
        response.raise_for_status()
        paypal_order_id = response.json().get("id")
        if not paypal_order_id:
            raise ValueError("PayPal did not return an order ID.")
        restaurant_name = str(data.get("restaurant_name", "")).strip()[:180]
        if cart_merchant:
            merchant_profile = cart_merchant
            restaurant_name = cart_merchant.shop_name
        else:
            merchant_matches = MerchantProfile.objects.filter(is_approved=True, shop_name__iexact=restaurant_name) if restaurant_name else MerchantProfile.objects.none()
            merchant_profile = merchant_matches.first() if merchant_matches.count() == 1 else None
        local_order = Order.objects.create(
            customer_name=customer_name,
            customer_email=customer_email,
            customer_user=request.user if request.user.is_authenticated else None,
            cart=checkout["cart_model"],
            delivery_address=checkout["customer_address"],
            restaurant_name=restaurant_name,
            merchant_profile=merchant_profile,
            subtotal=subtotal,
            taxable_total=taxable_subtotal,
            gst_total=tax,
            cgst_total=Decimal("0.00"),
            sgst_total=Decimal("0.00"),
            igst_total=Decimal("0.00"),
            discount_total=coupon_discount,
            coupon_discount=coupon_discount,
            coupon_code=coupon["code"] if coupon else "",
            total_amount=total,
            payment_method="paypal",
            payment_currency=settings.PAYPAL_CURRENCY,
            payment_amount=paypal_amount,
            payment_id=paypal_order_id,
            payment_status="Pending",
            order_status="Placed",
        )
        _create_order_items(
            local_order,
            cart,
            subtotal,
            tax,
            coupon_discount,
            coupon["eligible_categories"] if coupon else [],
        )
        return JsonResponse({
            "success": True,
            "paypal_order_id": paypal_order_id,
            "local_order_id": local_order.id,
            "subtotal": float(subtotal),
            "coupon_discount": float(coupon_discount),
            "coupon_code": coupon["code"] if coupon else "",
            "tax": float(tax),
            "total": float(total),
        })
    except (json.JSONDecodeError, ValueError) as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)
    except requests.RequestException:
        return JsonResponse({"success": False, "message": "PayPal is unavailable. Please try again."}, status=502)


def capture_paypal_order(request):
    authentication_error = _checkout_authentication_error(request)
    if authentication_error:
        return authentication_error
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Only POST requests are allowed."}, status=405)
    try:
        data = json.loads(request.body)
        paypal_order_id = data.get("paypal_order_id")
        if not paypal_order_id:
            raise ValueError("PayPal order ID is required.")
        order = Order.objects.filter(
            payment_id=paypal_order_id,
            customer_user=request.user,
        ).first()
        if order is None:
            return JsonResponse({"success": False, "message": "Local order not found."}, status=404)
        local_order_id = data.get("local_order_id")
        if local_order_id is not None and str(order.pk) != str(local_order_id):
            return JsonResponse({"success": False, "message": "Local order not found."}, status=404)
        if order.payment_status.casefold() in {"paid", "refunded"}:
            if order.payment_status.casefold() == "paid" and order.order_status.casefold() not in {
                "cancellation requested",
                "cancelled",
                "refunded",
            }:
                ensure_tracking_session(order)
            return JsonResponse({
                "success": True,
                "payment_id": paypal_order_id,
                "order_id": order.id,
                "email": order.customer_email,
            })
        access_token = _paypal_access_token()
        response = requests.post(f"{_paypal_base_url()}/v2/checkout/orders/{paypal_order_id}/capture", headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Prefer": "return=representation"}, timeout=20)
        capture_data = response.json()
        if not response.ok or capture_data.get("status") != "COMPLETED":
            return JsonResponse({"success": False, "message": "PayPal payment was not completed."}, status=400)
        capture_id = next(
            (
                capture.get("id")
                for purchase_unit in capture_data.get("purchase_units", [])
                for capture in purchase_unit.get("payments", {}).get("captures", [])
                if capture.get("id")
            ),
            "",
        )
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            cancellation_request = (
                CancellationRequest.objects.select_for_update()
                .filter(order=order, status="requested")
                .first()
            )
            approved_cancellation = CancellationRequest.objects.filter(
                order=order,
                status="approved",
            ).exists()
            cancellation_hold = (
                bool(cancellation_request)
                or approved_cancellation
                or order.order_status.casefold() in {
                    "cancellation requested",
                    "cancelled",
                    "refunded",
                }
            )
            order.payment_status = "Paid"
            order.payment_capture_id = capture_id
            update_fields = ["payment_status", "payment_capture_id"]
            if not cancellation_hold:
                order.order_status = "Confirmed"
                update_fields.append("order_status")
            elif cancellation_request and cancellation_request.previous_order_status.casefold() == "placed":
                cancellation_request.previous_order_status = "Confirmed"
                cancellation_request.save(update_fields=["previous_order_status", "updated_at"])
            order.save(update_fields=update_fields)
        request.session.pop("merchant_store_cart", None)
        request.session.modified = True

        if cancellation_hold:
            refund = create_refund_for_approved_cancellation(order.pk)
            message = (
                f"Payment was captured after cancellation approval. Refund status: {refund.get_status_display()}."
                if refund
                else "Payment was captured while your cancellation request is under review. The order remains on hold."
            )
            return JsonResponse({
                "success": True,
                "message": message,
                "payment_id": paypal_order_id,
                "order_id": order.id,
                "email": order.customer_email,
            })

        if order.payment_status == "Paid":
            try:
                send_order_confirmation_email(order)
            except Exception as error:
                logger.warning(
                    "Order confirmation email failed (%s).",
                    type(error).__name__,
                )
        ensure_tracking_session(order)
        return JsonResponse({"success": True, "payment_id": paypal_order_id, "order_id": order.id, "email": order.customer_email})
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "message": "Local order not found."}, status=404)
    except (json.JSONDecodeError, ValueError) as error:
        return JsonResponse({"success": False, "message": str(error)}, status=400)
    except requests.RequestException:
        return JsonResponse({"success": False, "message": "PayPal is unavailable. Please try again."}, status=502)


def verify_payment(request):
    authentication_error = _checkout_authentication_error(request)
    if authentication_error:
        return authentication_error

    if request.method != "POST":

        return JsonResponse({

            "success": False,

            "message":
                "Only POST requests are allowed."

        }, status=405)


    try:

        data = json.loads(
            request.body
        )


        razorpay_order_id = data.get(
            "razorpay_order_id"
        )

        razorpay_payment_id = data.get(
            "razorpay_payment_id"
        )

        razorpay_signature = data.get(
            "razorpay_signature"
        )

        local_order_id = data.get(
            "local_order_id"
        )


        # -----------------------------------------
        # VALIDATE PAYMENT DATA
        # -----------------------------------------

        if (
            not razorpay_order_id
            or not razorpay_payment_id
            or not razorpay_signature
        ):

            return JsonResponse({

                "success": False,

                "message":
                    "Payment details are missing."

            }, status=400)

        order = Order.objects.filter(
            Q(razorpay_order_id=razorpay_order_id)
            | Q(payment_id=razorpay_order_id),
            customer_user=request.user,
        ).first()
        if order is None:
            return JsonResponse({
                "success": False,
                "message": "Local order not found.",
            }, status=404)

        # -----------------------------------------
        # VERIFY RAZORPAY SIGNATURE
        # -----------------------------------------

        client.utility.verify_payment_signature({

            "razorpay_order_id":
                razorpay_order_id,

            "razorpay_payment_id":
                razorpay_payment_id,

            "razorpay_signature":
                razorpay_signature

        })


        # -----------------------------------------
        # GET LOCAL ORDER
        # -----------------------------------------

        inventory_problem = None
        already_processed = False
        cancellation_hold = False
        with transaction.atomic():
            order = Order.objects.select_for_update().filter(
                Q(razorpay_order_id=razorpay_order_id)
                | Q(payment_id=razorpay_order_id),
                customer_user=request.user,
            ).first()
            if order is None:
                return JsonResponse({
                    "success": False,
                    "message": "Local order not found.",
                }, status=404)

            if order.payment_status.casefold() in {"paid", "refunded"}:
                already_processed = True
            else:
                cancellation_request = (
                    CancellationRequest.objects.select_for_update()
                    .filter(order=order, status="requested")
                    .first()
                )
                cancellation_hold = bool(cancellation_request) or (
                    order.order_status.casefold()
                    in {"cancellation requested", "cancelled", "refunded"}
                )
                order_items = list(
                    order.items.select_related("product_content_type").order_by(
                        "product_content_type_id", "product_object_id", "id"
                    )
                )
                inventory = []
                if not cancellation_hold:
                    for order_item in order_items:
                        content_type = order_item.product_content_type
                        source = next(
                            (
                                key
                                for key, model in PRODUCT_TYPES.items()
                                if content_type and model._meta.model_name == content_type.model
                            ),
                            None,
                        )
                        product = (
                            get_inventory_product(source, order_item.product_object_id, lock=True)
                            if source and order_item.product_object_id
                            else None
                        )
                        stock = get_product_stock(product) if product is not None else None
                        if product is None or (stock is not None and stock < order_item.quantity):
                            inventory_problem = (
                                f"{order_item.name} is no longer available in the requested quantity."
                            )
                            break
                        inventory.append((product, order_item))

                order.payment_id = razorpay_payment_id
                order.payment_capture_id = razorpay_payment_id
                order.payment_status = "Paid"
                update_fields = [
                    "payment_id",
                    "payment_capture_id",
                    "payment_status",
                ]
                if not cancellation_hold:
                    order.order_status = "Confirmed" if inventory_problem is None else "Stock Review"
                    update_fields.append("order_status")
                elif cancellation_request and cancellation_request.previous_order_status.casefold() == "placed":
                    cancellation_request.previous_order_status = "Confirmed"
                    cancellation_request.save(update_fields=["previous_order_status", "updated_at"])
                order.save(update_fields=update_fields)

                if not cancellation_hold and inventory_problem is None:
                    for product, order_item in inventory:
                        if get_product_stock(product) is None or order_item.stock_deducted:
                            continue
                        product.stock -= order_item.quantity
                        product.save(update_fields=["stock"])
                        order_item.stock_deducted = True
                        order_item.save(update_fields=["stock_deducted"])

                if (cancellation_hold or inventory_problem is None) and order.cart_id:
                    for order_item in order_items:
                        cart_item = CartItem.objects.select_for_update().filter(
                            cart_id=order.cart_id,
                            content_type=order_item.product_content_type,
                            object_id=order_item.product_object_id,
                        ).first()
                        if cart_item is None:
                            continue
                        remaining_quantity = cart_item.quantity - order_item.quantity
                        if remaining_quantity > 0:
                            cart_item.quantity = remaining_quantity
                            cart_item.save(update_fields=["quantity"])
                        else:
                            cart_item.delete()

        if already_processed:
            return JsonResponse({
                "success": True,
                "message": "Payment was already verified.",
                "payment_id": razorpay_payment_id,
                "order_id": order.id,
                "email": order.customer_email,
            })

        if cancellation_hold:
            refund = create_refund_for_approved_cancellation(order.pk)
            message = (
                f"Payment was received after cancellation approval. Refund status: {refund.get_status_display()}."
                if refund
                else "Payment was verified while your cancellation request is under review. The order remains on hold."
            )
            return JsonResponse({
                "success": True,
                "message": message,
                "payment_id": razorpay_payment_id,
                "order_id": order.id,
                "email": order.customer_email,
            })

        if inventory_problem:
            logger.error(
                "Payment %s for order %s succeeded but inventory needs review: %s",
                razorpay_payment_id,
                order.id,
                inventory_problem,
            )
            return JsonResponse({
                "success": True,
                "message": "Payment received. The order needs stock review before confirmation.",
                "payment_id": razorpay_payment_id,
                "order_id": order.id,
                "email": order.customer_email,
            })

        ensure_tracking_session(order)


        # -----------------------------------------
        # SEND ORDER EMAIL
        # -----------------------------------------

        email_sent = False

        try:

            if not order.customer_email:

                logger.info("Order confirmation email skipped because no address is set.")

            else:

                send_order_confirmation_email(
                    order
                )

                email_sent = True

        except Exception as email_error:
            logger.warning(
                "Order confirmation email failed (%s).",
                type(email_error).__name__,
            )


        # -----------------------------------------
        # RETURN SUCCESS
        # -----------------------------------------

        return JsonResponse({

            "success": True,

            "message":
                "Payment verified and order confirmed successfully.",

            "payment_id":
                razorpay_payment_id,

            "order_id":
                order.id,

            "email":
                order.customer_email,

            "email_sent":
                email_sent

        })


    # -----------------------------------------
    # RAZORPAY SIGNATURE ERROR
    # -----------------------------------------

    except razorpay.errors.SignatureVerificationError:

        return JsonResponse({

            "success": False,

            "message":
                "Payment signature verification failed."

        }, status=400)


    # -----------------------------------------
    # OTHER ERRORS
    # -----------------------------------------

    except Exception as error:
        logger.error(
            "Razorpay payment verification failed (%s).",
            type(error).__name__,
        )

        return JsonResponse({

            "success": False,

            "message":
                "Payment could not be verified automatically. Do not retry payment; contact support."

        }, status=502)

        

def download_order_pdf(request, order_id):

    print("PDF FUNCTION CALLED:", order_id)

    # Get logged-in user
    user_data = request.session.get("user")

    if not user_data:
        return redirect("login")

    customer_email = user_data.get("email")

    # Get order
    order = (
        Order.objects
        .filter(
            id=order_id,
            customer_email=customer_email
        )
        .prefetch_related("items")
        .first()
    )

    if not order:
        return HttpResponse(
            "Order not found",
            status=404
        )

    # Create PDF response
    response = HttpResponse(
        content_type="application/pdf"
    )

    response["Content-Disposition"] = (
        f'attachment; filename="Order_{order.id}.pdf"'
    )

    # Create PDF
    pdf = canvas.Canvas(
        response,
        pagesize=A4
    )

    width, height = A4

    y = height - 50

    # --------------------------------
    # HEADER
    # --------------------------------

    pdf.setFont(
        "Helvetica-Bold",
        22
    )

    pdf.drawString(
        50,
        y,
        "LocalMart"
    )

    y -= 30

    pdf.setFont(
        "Helvetica",
        12
    )

    pdf.drawString(
        50,
        y,
        "Order Invoice"
    )

    y -= 35

    # --------------------------------
    # ORDER DETAILS
    # --------------------------------

    pdf.setFont(
        "Helvetica-Bold",
        11
    )

    pdf.drawString(
        50,
        y,
        f"Order #{order.id}"
    )

    y -= 20

    pdf.setFont(
        "Helvetica",
        10
    )

    pdf.drawString(
        50,
        y,
        f"Customer: {order.customer_name}"
    )

    y -= 18

    pdf.drawString(
        50,
        y,
        f"Email: {order.customer_email}"
    )

    y -= 18

    pdf.drawString(
        50,
        y,
        f"Date: {order.created_at.strftime('%d %b %Y, %I:%M %p')}"
    )

    y -= 18

    pdf.drawString(
        50,
        y,
        f"Payment: {order.payment_status}"
    )

    y -= 18

    pdf.drawString(
        50,
        y,
        f"Order Status: {order.order_status}"
    )

    y -= 35

    # --------------------------------
    # ITEMS HEADER
    # --------------------------------

    pdf.setFont(
        "Helvetica-Bold",
        11
    )

    pdf.drawString(
        50,
        y,
        "Item"
    )

    pdf.drawString(
        300,
        y,
        "Qty"
    )

    pdf.drawString(
        360,
        y,
        "Price"
    )

    pdf.drawString(
        460,
        y,
        "Amount"
    )

    y -= 15

    pdf.line(
        50,
        y,
        550,
        y
    )

    y -= 20

    # --------------------------------
    # ORDER ITEMS
    # --------------------------------

    pdf.setFont(
        "Helvetica",
        10
    )

    for item in order.items.all():

        item_total = (
            item.price * item.quantity
        )

        pdf.drawString(
            50,
            y,
            item.name[:35]
        )

        pdf.drawString(
            300,
            y,
            str(item.quantity)
        )

        pdf.drawString(
            360,
            y,
            f"Rs. {item.price}"
        )

        pdf.drawString(
            460,
            y,
            f"Rs. {item_total}"
        )

        y -= 22

        if y < 80:

            pdf.showPage()

            y = height - 50

            pdf.setFont(
                "Helvetica",
                10
            )

    # --------------------------------
    # TOTAL
    # --------------------------------

    y -= 10

    pdf.line(
        50,
        y,
        550,
        y
    )

    y -= 30

    pdf.setFont(
        "Helvetica-Bold",
        14
    )

    pdf.drawRightString(
        550,
        y,
        f"Total Paid: Rs. {order.total_amount}"
    )

    y -= 35

    pdf.setFont(
        "Helvetica",
        10
    )

    pdf.drawString(
        50,
        y,
        "Thank you for ordering with LocalMart!"
    )

    # --------------------------------
    # SAVE PDF
    # --------------------------------

    pdf.showPage()

    pdf.save()

    # --------------------------------
    # VERY IMPORTANT
    # --------------------------------

    return response






def grocery_home(request):

    return render(
        request,
        "grocery.html"
    )


def fruits_vegetables(request):

    return render(
        request,
        "fruits-vegetables.html"
    )


def dairy_bread_eggs(request):

    return render(
        request,
        "dairy-bread-eggs.html"
    )


def atta_rice_oil_dals(request):
    return render(request, "atta-rice-oil-dals.html")


def meats_fish_eggs(request):

    return render(
        request,
        "meats-fish-eggs.html"
    )


def masala_dry_fruits_more(request):

    return render(
        request,
        "masala-dry-fruits-more.html"
    )


def breakfast_sauces(request):

    return render(
        request,
        "breakfast-sauces.html"
    )





def tea_coffee(request):

    return render(
        request,
        "tea-coffee-more.html"
    )


def ice_cream_tubs(request):
    return render(request, "ice-cream-tubs.html")


def frozen_food(request):

    return render(
        request,
        "frozen-food.html"
    )


def sweet_cravings(request):

    return render(
        request,
        "sweet-cravings.html"
    )


def cold_drinks(request):
    return render(request, "drinks-juices.html")


def munchies(request):

    return render(
        request,
        "munchies.html"
    )


def biscuits(request):

    return render(
        request,
        "biscuits.html"
    )








def grocery_cart(request):
    return redirect("cart")


@ensure_csrf_cookie
def grocery_checkout(request):
    return redirect("checkout")









def grocery_orders(request):
    """
    Grocery-specific My Orders page.

    Food orders remain on:
        /my-orders/

    Grocery orders appear on:
        /grocery/orders/
    """

    user_data = request.session.get("user")

    # -------------------------------------------------
    # LOGIN CHECK
    # -------------------------------------------------

    if not user_data:
        return redirect("login")

    customer_email = (
        user_data.get("email", "")
        .strip()
        .lower()
    )

    customer_name = (
        user_data.get("fullname")
        or user_data.get("full_name")
        or user_data.get("name")
        or user_data.get("username")
        or "Customer"
    )

    if not customer_email:
        return redirect("login")

    # -------------------------------------------------
    # GROCERY KEYWORDS
    # -------------------------------------------------

    grocery_keywords = [
        # Fruits
        "fruit",
        "fruits",
        "apple",
        "banana",
        "orange",
        "mango",
        "grape",
        "watermelon",
        "papaya",
        "pineapple",
        "pomegranate",
        "guava",

        # Vegetables
        "vegetable",
        "vegetables",
        "tomato",
        "potato",
        "onion",
        "carrot",
        "cucumber",
        "capsicum",
        "spinach",
        "brinjal",
        "cauliflower",
        "broccoli",

        # Dairy
        "dairy",
        "milk",
        "curd",
        "yogurt",
        "paneer",
        "butter",
        "cheese",
        "cream",
        "lassi",

        # Bread / Eggs
        "bread",
        "bun",
        "eggs",
        "egg",

        # Atta / Rice / Dal
        "atta",
        "flour",
        "rice",
        "basmati",
        "dal",
        "dals",
        "pulse",
        "pulses",
        "toor",
        "moong",
        "urad",
        "chana",

        # Oil / Ghee
        "oil",
        "sunflower oil",
        "mustard oil",
        "rice bran oil",
        "coconut oil",
        "ghee",

        # Masala
        "masala",
        "spice",
        "spices",
        "turmeric",
        "chilli powder",
        "pepper",
        "cumin",
        "cardamom",
        "cinnamon",

        # Dry Fruits / Seeds
        "dry fruit",
        "dry fruits",
        "nuts",
        "almond",
        "cashew",
        "walnut",
        "pistachio",
        "raisins",
        "dates",
        "seeds",
        "pumpkin seeds",
        "sunflower seeds",
        "chia seeds",

        # Breakfast
        "breakfast",
        "muesli",
        "oats",
        "cereal",
        "corn flakes",
        "honey",
        "jam",
        "spread",
        "peanut butter",

        # Sauces
        "ketchup",
        "sauce",
        "sauces",
        "mayonnaise",

        # Packaged food
        "packaged",
        "packaged food",
        "noodles",
        "vermicelli",
        "pasta",
        "soup",
        "ready to eat",
        "ready-to-eat",
        "papad",
        "papads",
        "pickle",
        "pickles",
        "chutney",
        "baking",
        "baking mix",

        # Snacks
        "munchies",
        "snack",
        "snacks",
        "biscuit",
        "biscuits",
        "cookie",
        "cookies",
        "chips",
        "namkeen",

        # Sweets / Chocolate
        "chocolate",
        "chocolates",
        "sweet",
        "sweets",
        "dessert",
        "desserts",

        # Beverages
        "beverage",
        "beverages",
        "drink",
        "drinks",
        "juice",
        "juices",
        "tea",
        "coffee",

        # Ice cream / Frozen
        "ice cream",
        "icecream",
        "frozen",

        # Personal care
        "personal care",
        "shampoo",
        "soap",
        "toothpaste",
        "toothbrush",
        "face wash",
        "body wash",

        # Cleaning / Household
        "cleaning",
        "cleaner",
        "detergent",
        "dishwash",
        "dish washer",
        "floor cleaner",
        "household",
    ]

    # -------------------------------------------------
    # CHECK WHETHER ITEM IS GROCERY
    # -------------------------------------------------

    def is_grocery_item(item):

        category = (
            str(item.category or "")
            .strip()
            .lower()
        )

        name = (
            str(item.name or "")
            .strip()
            .lower()
        )

        searchable_text = f"{category} {name}"

        return any(
            keyword in searchable_text
            for keyword in grocery_keywords
        )

    # -------------------------------------------------
    # GET USER ORDERS
    # -------------------------------------------------

    all_orders = (
        Order.objects
        .filter(
            customer_email__iexact=customer_email
        )
        .prefetch_related("items")
        .order_by("-created_at")
    )

    prepared_orders = []

    total_items_purchased = 0

    # -------------------------------------------------
    # CATEGORY ICONS
    # -------------------------------------------------

    category_icons = {

        "Fruits & Vegetables":
            "bi-basket2",

        "Dairy, Bread & Eggs":
            "bi-cup-straw",

        "Atta, Rice, Oil & Dals":
            "bi-bag",

        "Masala, Dry Fruits & More":
            "bi-stars",

        "Breakfast & Sauces":
            "bi-egg-fried",

        "Tea, Coffee & More":
            "bi-cup-hot",

        "Ice Creams & More":
            "bi-snow2",

        "Sweet Cravings":
            "bi-gift",

        "Cold Drinks & Juices":
            "bi-cup",

        "Munchies":
            "bi-cookie",

        "Packaged Food":
            "bi-box-seam",

        "Personal Care":
            "bi-person",

        "Cleaning":
            "bi-droplet",
    }

    # -------------------------------------------------
    # PROCESS ORDERS
    # -------------------------------------------------

    for order in all_orders:

        all_items = list(
            order.items.all()
        )

        # ONLY GROCERY ITEMS
        grocery_items = [
            item
            for item in all_items
            if is_grocery_item(item)
        ]

        # IMPORTANT:
        # If this order contains no Grocery products,
        # completely hide it from Grocery My Orders.

        if not grocery_items:
            continue

        # -------------------------------------------------
        # CATEGORY GROUPING
        # -------------------------------------------------

        category_groups = OrderedDict()

        for item in grocery_items:

            category = (
                item.category.strip()
                if item.category
                else "Grocery"
            )

            if category not in category_groups:
                category_groups[category] = []

            # Item subtotal
            try:

                item.subtotal = (
                    float(item.price)
                    * int(item.quantity)
                )

            except (
                TypeError,
                ValueError
            ):

                item.subtotal = 0

            # Category icon
            item.category_icon = (
                category_icons.get(
                    category,
                    "bi-bag-check"
                )
            )

            category_groups[
                category
            ].append(item)

            # Total quantity
            try:

                total_items_purchased += int(
                    item.quantity
                )

            except (
                TypeError,
                ValueError
            ):

                pass

        # -------------------------------------------------
        # ORDER STATUS
        # -------------------------------------------------

        order_status = (
            order.order_status
            or "Placed"
        )

        status_class = (
            order_status
            .strip()
            .lower()
            .replace(" ", "-")
        )

        # -------------------------------------------------
        # PAYMENT STATUS
        # -------------------------------------------------

        payment_status = (
            order.payment_status
            or "Pending"
        )

        payment_class = (
            payment_status
            .strip()
            .lower()
            .replace(" ", "-")
        )

        # -------------------------------------------------
        # ITEM COUNT
        # -------------------------------------------------

        order_item_count = 0

        for item in grocery_items:

            try:

                order_item_count += int(
                    item.quantity
                )

            except (
                TypeError,
                ValueError
            ):

                pass

        # -------------------------------------------------
        # CATEGORY GROUPS FOR TEMPLATE
        # -------------------------------------------------

        order.category_groups = [

            {
                "name": category_name,

                "icon": category_icons.get(
                    category_name,
                    "bi-bag-check"
                ),

                "items": items,
            }

            for (
                category_name,
                items
            )
            in category_groups.items()
        ]

        # -------------------------------------------------
        # TEMPLATE VALUES
        # -------------------------------------------------

        order.order_status_display = (
            order_status
        )

        order.status_class = (
            status_class
        )

        order.payment_status_display = (
            payment_status
        )

        order.payment_class = (
            payment_class
        )

        order.item_count = (
            order_item_count
        )

        prepared_orders.append(order)

    # -------------------------------------------------
    # SUMMARY
    # -------------------------------------------------

    total_orders = len(
        prepared_orders
    )

    last_order = (
        prepared_orders[0]
        if prepared_orders
        else None
    )

    # -------------------------------------------------
    # CONTEXT
    # -------------------------------------------------

    context = {

        "orders":
            prepared_orders,

        "customer_name":
            customer_name,

        "customer_email":
            customer_email,

        "total_orders":
            total_orders,

        "total_items_purchased":
            total_items_purchased,

        "last_order":
            last_order,
    }

    # -------------------------------------------------
    # GROCERY TEMPLATE
    # -------------------------------------------------

    return render(
        request,
        "groceryorders.html",
        context
    )




def grocery_wishlist(request):
    return render(
        request,
        "grocerywishlist.html"
    )






@ensure_csrf_cookie
def home_appliances(request):

    # =====================================================
    # HOME APPLIANCE CATEGORIES
    # =====================================================

    appliance_category_names = [
        "Refrigerators",
        "Washing Machines",
        "Air Conditioners",
        "Televisions",
        "Microwave Ovens",
        "Mixer Grinders",
        "Air Fryers",
        "Fans",
        "Vacuum Cleaners",
        "Water Purifiers",
        "Geysers",
        "Dishwashers",
        "Induction Cooktops",
        "Kitchen Chimneys",
    ]

    # =====================================================
    # BASE PRODUCTS
    # =====================================================

    products = (
        Product.objects
        .filter(
            category__name__in=appliance_category_names
        )
        .select_related("category")
    )

    # =====================================================
    # SEARCH
    # =====================================================

    search = request.GET.get(
        "q",
        ""
    ).strip()

    if search:
        products = products.filter(
            Q(name__icontains=search)
            |
            Q(brand__icontains=search)
            |
            Q(category__name__icontains=search)
        )

    # =====================================================
    # CATEGORY
    # =====================================================

    selected_category = request.GET.get(
        "category",
        ""
    ).strip()

    if selected_category:
        products = products.filter(
            category__name=selected_category
        )

    # =====================================================
    # BRAND
    # =====================================================

    selected_brand = request.GET.get(
        "brand",
        ""
    ).strip()

    if selected_brand:
        products = products.filter(
            brand=selected_brand
        )

    # =====================================================
    # MIN PRICE
    # =====================================================

    min_price = request.GET.get(
        "min_price",
        ""
    ).strip()

    if min_price:
        try:
            products = products.filter(
                price__gte=float(min_price)
            )
        except (ValueError, TypeError):
            min_price = ""

    # =====================================================
    # MAX PRICE
    # =====================================================

    max_price = request.GET.get(
        "max_price",
        ""
    ).strip()

    if max_price:
        try:
            products = products.filter(
                price__lte=float(max_price)
            )
        except (ValueError, TypeError):
            max_price = ""

    # =====================================================
    # RATING
    # =====================================================

    rating = request.GET.get(
        "rating",
        ""
    ).strip()

    if rating:
        try:
            products = products.filter(
                rating__gte=float(rating)
            )
        except (ValueError, TypeError):
            rating = ""

    # =====================================================
    # STOCK
    # =====================================================

    in_stock = request.GET.get(
        "in_stock",
        ""
    ) == "1"

    if in_stock:
        products = products.filter(
            stock__gt=0
        )

    # =====================================================
    # DISCOUNT
    # =====================================================

    discount_only = request.GET.get(
        "discount",
        ""
    ) == "1"

    if discount_only:
        products = products.filter(
            discount__gt=0
        )

    # =====================================================
    # SORT
    # =====================================================

    selected_sort = request.GET.get(
        "sort",
        "popular"
    )

    if selected_sort == "price-low":

        products = products.order_by(
            "price"
        )

    elif selected_sort == "price-high":

        products = products.order_by(
            "-price"
        )

    elif selected_sort == "rating":

        products = products.order_by(
            "-rating"
        )

    elif selected_sort == "name":

        products = products.order_by(
            "name"
        )

    else:

        products = products.order_by(
            "-rating",
            "-discount"
        )

    # =====================================================
    # PRODUCT COUNT
    # =====================================================

    product_count = products.count()

    # =====================================================
    # PAGINATION
    # =====================================================

    paginator = Paginator(
        products,
        20
    )

    page_number = request.GET.get(
        "page"
    )

    page_obj = paginator.get_page(
        page_number
    )

    # =====================================================
    # CATEGORIES FOR SIDEBAR
    # =====================================================

    categories = (
        Category.objects
        .filter(
            name__in=appliance_category_names
        )
        .order_by("name")
    )

    # =====================================================
    # BRANDS FOR SIDEBAR
    # =====================================================

    brands = (
        Product.objects
        .filter(
            category__name__in=appliance_category_names
        )
        .exclude(
            brand__isnull=True
        )
        .exclude(
            brand=""
        )
        .values_list(
            "brand",
            flat=True
        )
        .distinct()
        .order_by("brand")
    )

    # =====================================================
    # PAGINATION FILTER QUERY
    # =====================================================

    query_params = request.GET.copy()

    query_params.pop(
        "page",
        None
    )

    filter_query = query_params.urlencode()

    # =====================================================
    # CONTEXT
    # =====================================================

    context = {
        "products": page_obj,

        "page_obj": page_obj,

        "product_count": product_count,

        "categories": categories,

        "brands": brands,

        "selected_category": selected_category,

        "selected_brand": selected_brand,

        "selected_sort": selected_sort,

        "min_price": min_price,

        "max_price": max_price,

        "rating": rating,

        "in_stock": in_stock,

        "discount_only": discount_only,

        "filter_query": filter_query,

        "search": search,

        "cart_count": serialize_cart(get_customer_cart(request))["item_count"],

        "wishlist_ids": request.session.get("home_appliances_wishlist", []),
    }

    # =====================================================
    # RENDER
    # =====================================================

    return render(
        request,
        "home-appliances.html",
        context
    )


def _home_appliance_product(product_id):
    return get_object_or_404(
        Product,
        id=product_id,
        category__name__in=[
            "Refrigerators", "Washing Machines", "Air Conditioners",
            "Televisions", "Microwave Ovens", "Mixer Grinders",
            "Air Fryers", "Fans", "Vacuum Cleaners", "Water Purifiers",
            "Geysers", "Dishwashers", "Induction Cooktops", "Kitchen Chimneys",
        ],
    )


def home_appliances_cart(request):
    return redirect("cart")


def home_appliances_cart_add(request, product_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST request required."}, status=405)
    _home_appliance_product(product_id)
    cart, error, status_code = add_product_to_cart(request, "product", product_id)
    if cart is None:
        return JsonResponse({"success": False, "message": error}, status=status_code)
    return JsonResponse({
        "success": True,
        "quantity": cart.items.filter(
            content_type=ContentType.objects.get_for_model(Product),
            object_id=product_id,
        ).values_list("quantity", flat=True).first(),
        "cart_count": serialize_cart(cart)["item_count"],
        "message": "Product added to cart successfully.",
    })


def home_appliances_cart_update(request, product_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST request required."}, status=405)
    product = _home_appliance_product(product_id)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = request.POST
    cart = get_customer_cart(request)
    item = CartItem.objects.filter(
        cart=cart,
        content_type=ContentType.objects.get_for_model(Product),
        object_id=product.pk,
    ).first()
    if item is None:
        return JsonResponse({"success": False, "message": "Cart item not found."}, status=404)
    action = data.get("action")
    if action == "remove":
        item.delete()
        quantity = 0
    elif action in ("increase", "decrease"):
        quantity = item.quantity + (1 if action == "increase" else -1)
        if quantity < 1:
            return JsonResponse({"success": False, "message": "Quantity cannot be less than one."}, status=400)
        if quantity > product.stock:
            return JsonResponse({"success": False, "message": f"Only {product.stock} item(s) are available."}, status=409)
        item.quantity = quantity
        item.save(update_fields=["quantity"])
    else:
        return JsonResponse({"success": False, "message": "Invalid cart action."}, status=400)
    return JsonResponse({
        "success": True,
        "quantity": quantity,
        "cart_count": serialize_cart(cart)["item_count"],
    })


def home_appliances_wishlist(request):
    wishlist = request.session.get("home_appliances_wishlist", [])
    products = Product.objects.filter(id__in=[int(product_id) for product_id in wishlist if str(product_id).isdigit()])
    return render(request, "home-appliances-wishlist.html", {
        "wishlist_products": products,
        "wishlist_count": products.count(),
        "cart_count": sum(int(quantity) for quantity in request.session.get("home_appliances_cart", {}).values()),
    })


def home_appliances_wishlist_toggle(request, product_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST request required."}, status=405)
    product = _home_appliance_product(product_id)
    wishlist = request.session.get("home_appliances_wishlist", [])
    key = str(product.id)
    if key in wishlist:
        wishlist.remove(key)
        added = False
    else:
        wishlist.append(key)
        added = True
    request.session["home_appliances_wishlist"] = wishlist
    request.session.modified = True
    return JsonResponse({"success": True, "added": added, "wishlist_count": len(wishlist)})
