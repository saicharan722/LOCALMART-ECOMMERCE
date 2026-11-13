/* =========================================================
   LOCALMART CHECKOUT + RAZORPAY PAYMENT
========================================================= */

function getCheckoutCart() {
    if (Array.isArray(window.electronicsCheckoutCart)) {
        return window.electronicsCheckoutCart;
    }
    return [];
}

function getCheckoutRestaurantName(cart) {
    const values = (cart || []).map(item => String(item.restaurantName || item.restaurant_name || "").trim());
    const names = [...new Set(values.filter(Boolean))];
    if (names.length && values.some(name => !name)) return "multiple";
    if (names.length === 1) return names[0];
    if (names.length > 1) return "multiple";
    return "";
}

function getCheckoutCsrfToken() {
    return document.cookie
        .split(";")
        .map(value => value.trim())
        .find(value => value.startsWith("csrftoken="))
        ?.slice("csrftoken=".length) || "";
}

let checkoutMap = null, checkoutMarker = null, checkoutPin = null;
function initCheckoutDeliveryPin() {
    const address = document.getElementById("customerAddress"), mapElement = document.getElementById("checkoutDeliveryMap");
    const locate = document.getElementById("locateCheckoutAddress"), confirm = document.getElementById("confirmCheckoutPin"), note = document.getElementById("checkoutPinNote"), pay = document.getElementById("payButton");
    if (!address || !mapElement || !locate || !confirm) return;
    if (pay) pay.disabled = true;
    if (window.L) {
        checkoutMap = L.map(mapElement).setView([0, 0], 2);
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom:19,referrerPolicy:"strict-origin-when-cross-origin",attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(checkoutMap);
        checkoutMap.on("click", event => setCheckoutPin(event.latlng, "Map point selected. Confirm this as your delivery destination."));
        // Use a saved homepage location only to center the map. It is never
        // treated as a confirmed delivery pin and never replaces typed address.
        if (!address.value.trim()) {
            try {
                const saved = JSON.parse(localStorage.getItem("localmart.homeLocation") || "null");
                const lat = Number(saved?.latitude), lng = Number(saved?.longitude);
                if (Number.isFinite(lat) && lat >= -90 && lat <= 90 && Number.isFinite(lng) && lng >= -180 && lng <= 180) {
                    checkoutMap.setView([lat, lng], 13);
                    note.textContent = "Map centered on your saved location. Enter your delivery address, select the exact point, and confirm it before payment.";
                }
            } catch (_) { /* The map still works when browser storage is unavailable. */ }
        }
        setTimeout(() => checkoutMap.invalidateSize(), 150);
    } else note.textContent = "Map library could not load. Please reload this page before payment.";
    function setCheckoutPin(point, message) {
        checkoutPin = {latitude:Number(point.lat), longitude:Number(point.lng)};
        if (checkoutMarker) checkoutMarker.setLatLng([checkoutPin.latitude, checkoutPin.longitude]);
        else checkoutMarker = L.marker([checkoutPin.latitude, checkoutPin.longitude], {draggable:true}).addTo(checkoutMap);
        checkoutMarker.off("dragend").on("dragend", event => {const p=event.target.getLatLng();checkoutPin={latitude:p.lat,longitude:p.lng};note.textContent="Pin moved. Confirm the exact delivery point.";confirm.disabled=false;});
        checkoutMap.setView([checkoutPin.latitude,checkoutPin.longitude],17,{animate:true});
        note.textContent=message;confirm.disabled=false;
        if(pay)pay.disabled=true;
    }
    address.addEventListener("input",()=>{checkoutPin=null;window.LOCALMART_CHECKOUT_DELIVERY=null;confirm.disabled=true;if(pay)pay.disabled=true;note.textContent="Address changed. Locate and confirm its delivery pin again.";});
    locate.addEventListener("click",async()=>{const value=address.value.trim();if(!value){address.focus();return;}locate.disabled=true;note.textContent="Looking up delivery address…";try{const response=await fetch("/api/geocode/address/",{method:"POST",headers:{"Content-Type":"application/json","X-CSRFToken":getCheckoutCsrfToken()},credentials:"same-origin",body:JSON.stringify({address:value})});const data=await response.json();if(!response.ok)throw new Error(data.error||"Address lookup failed");setCheckoutPin({lat:data.candidate.latitude,lng:data.candidate.longitude},`Found ${data.candidate.address}. Check the point and move it to your exact entrance if needed.`);}catch(error){note.textContent=`${error.message} You can also use your GPS to center the map, then select the point on the map.`;}finally{locate.disabled=false;}});
    confirm.addEventListener("click",()=>{if(!checkoutPin||!address.value.trim())return;window.LOCALMART_CHECKOUT_DELIVERY={...checkoutPin,address:address.value.trim()};confirm.disabled=true;if(pay)pay.disabled=false;note.textContent="Delivery pin confirmed. You can now continue to payment.";});
    document.getElementById("centerCheckoutOnGps")?.addEventListener("click",()=>{if(!navigator.geolocation){note.textContent="This device does not provide GPS.";return;}navigator.geolocation.getCurrentPosition(position=>setCheckoutPin({lat:position.coords.latitude,lng:position.coords.longitude},"Current GPS shown. Confirm only if this is your delivery entrance."),()=>{note.textContent="GPS permission was denied. Locate your address or select the point on the map.";},{enableHighAccuracy:true,timeout:15000,maximumAge:30000});});
}

document.addEventListener("DOMContentLoaded", function () {

    initCheckoutDeliveryPin();

    /* -----------------------------------------------------
       GET ELEMENTS
    ----------------------------------------------------- */

    const checkoutItems =
        document.getElementById("checkoutItems");

    const subtotalElement =
        document.getElementById("checkoutSubtotal");

    const taxElement =
        document.getElementById("checkoutTax");

    const totalElement =
        document.getElementById("checkoutTotal");

    const payButton =
        document.getElementById("payButton");


    /* -----------------------------------------------------
       GET CART
    ----------------------------------------------------- */

    let cart = [];

    try {

        cart = getCheckoutCart();

    } catch (error) {

        console.error(
            "Cart JSON parsing error:",
            error
        );

        cart = [];
    }


    console.log(
        "Checkout cart:",
        cart
    );


    /* -----------------------------------------------------
       CHECK CART
    ----------------------------------------------------- */

    if (
        !Array.isArray(cart) ||
        cart.length === 0
    ) {

        if (checkoutItems) {

            checkoutItems.innerHTML = `
                <div class="alert alert-warning">
                    <i class="bi bi-cart-x me-2"></i>
                    Your cart is empty.
                </div>
            `;
        }

        if (payButton) {
            payButton.disabled = true;
        }

        return;
    }


    /* -----------------------------------------------------
       CALCULATE CART TOTAL
    ----------------------------------------------------- */

    let subtotal = 0;

    let html = "";


    cart.forEach(function (item) {

        const price =
            Number(item.price) || 0;

        const quantity =
            Number(item.quantity) || 1;

        const itemTotal =
            price * quantity;


        subtotal += itemTotal;


        /* -------------------------------------------------
           PRODUCT IMAGE
        ------------------------------------------------- */

        const image =
            item.image ||
            "/static/images/default-food.jpg";


        /* -------------------------------------------------
           PRODUCT NAME
        ------------------------------------------------- */

        const productName =
            item.name ||
            "Product";


        /* -------------------------------------------------
           CATEGORY
        ------------------------------------------------- */

        const category =
            item.category ||
            "";


        /* -------------------------------------------------
           RESTAURANT
        ------------------------------------------------- */

        const restaurant =
            item.restaurant_name || "";


        /* -------------------------------------------------
           PRODUCT HTML
        ------------------------------------------------- */

        html += `

            <div class="card border-0 shadow-sm mb-3">

                <div class="card-body">

                    <div class="d-flex
                                gap-3
                                align-items-center">

                        <!-- Product Image -->

                        <img
                            src="${image}"
                            alt="${productName}"
                            style="
                                width:80px;
                                height:80px;
                                object-fit:cover;
                                border-radius:10px;
                            "
                            onerror="
                                this.onerror=null;
                                this.src='/static/images/default-food.jpg';
                            "
                        >


                        <!-- Product Details -->

                        <div class="flex-grow-1">

                            <h6 class="fw-bold mb-1">
                                ${productName}
                            </h6>


                            ${
                                restaurant
                                ? `
                                    <small class="text-success">

                                        <i class="bi bi-shop me-1"></i>

                                        ${restaurant}

                                    </small>
                                `
                                : ""
                            }


                            ${
                                category
                                ? `
                                    <div class="text-muted small mt-1">

                                        ${category}

                                    </div>
                                `
                                : ""
                            }


                            <div class="mt-1">

                                ₹${price.toFixed(2)}

                                ×

                                ${quantity}

                            </div>

                        </div>


                        <!-- Item Total -->

                        <div class="text-end">

                            <strong class="text-success">

                                ₹${itemTotal.toFixed(2)}

                            </strong>

                        </div>

                    </div>

                </div>

            </div>

        `;
    });


    /* -----------------------------------------------------
       DISPLAY CART
    ----------------------------------------------------- */

    if (checkoutItems) {

        checkoutItems.innerHTML = html;

    }


    /* -----------------------------------------------------
       TAX
       5%
    ----------------------------------------------------- */

    const checkoutSummary = window.electronicsCheckoutSummary || {};
    const serverSubtotal = Number(checkoutSummary.subtotal);
    const couponDiscount = Number(checkoutSummary.coupon_discount) || 0;
    const tax = Number.isFinite(Number(checkoutSummary.tax))
        ? Number(checkoutSummary.tax)
        : subtotal * 0.05;
    const displayedSubtotal = Number.isFinite(serverSubtotal)
        ? serverSubtotal
        : subtotal;


    /* -----------------------------------------------------
       GRAND TOTAL
    ----------------------------------------------------- */

    const serverTotal = Number(checkoutSummary.total);
    const total = Number.isFinite(serverTotal)
        ? serverTotal
        : displayedSubtotal - couponDiscount + tax;


    console.log(
        "Subtotal:",
        subtotal
    );

    console.log(
        "Tax:",
        tax
    );

    console.log(
        "Total:",
        total
    );


    /* -----------------------------------------------------
       UPDATE SUMMARY
    ----------------------------------------------------- */

    if (subtotalElement) {

        subtotalElement.innerText =
            "₹" + displayedSubtotal.toFixed(2);

    }


    if (taxElement) {

        taxElement.innerText =
            "₹" + tax.toFixed(2);

    }


    if (totalElement) {

        totalElement.innerText =
            "₹" + total.toFixed(2);

    }

    const couponRow = document.getElementById("checkoutCouponRow");
    const couponDiscountElement = document.getElementById("checkoutCouponDiscount");
    const couponLabel = document.getElementById("checkoutCouponLabel");
    const couponDetails = document.getElementById("checkoutCouponDetails");
    if (couponRow) couponRow.hidden = couponDiscount <= 0;
    if (couponDiscountElement) couponDiscountElement.innerText = `−₹${couponDiscount.toFixed(2)}`;
    if (couponLabel && checkoutSummary.coupon?.code) {
        couponLabel.innerText = `Coupon (${checkoutSummary.coupon.code})`;
    }
    if (couponDetails && couponDiscount > 0) {
        const categories = checkoutSummary.coupon?.eligible_categories || [];
        const scope = categories.length
            ? `Applies to ${categories.join(", ")}`
            : "Applies to all categories";
        const eligibleSubtotal = Number(checkoutSummary.coupon?.eligible_subtotal);
        couponDetails.innerText = Number.isFinite(eligibleSubtotal)
            ? `${scope} · Eligible items ${"₹" + eligibleSubtotal.toFixed(2)}`
            : scope;
        couponDetails.hidden = false;
    }


    /* -----------------------------------------------------
       PAYMENT BUTTON
    ----------------------------------------------------- */

    if (payButton) {

        payButton.addEventListener(
            "click",
            function () {

                /* -----------------------------------------
                   ALWAYS GET FRESH CART
                ----------------------------------------- */

                let latestCart = [];

                try {

                    latestCart = getCheckoutCart();

                } catch (error) {

                    console.error(
                        "Unable to read cart:",
                        error
                    );

                    latestCart = [];

                }


                console.log(
                    "Latest cart before payment:",
                    latestCart
                );


                /* -----------------------------------------
                   CHECK LATEST CART
                ----------------------------------------- */

                if (
                    !Array.isArray(latestCart) ||
                    latestCart.length === 0
                ) {

                    alert(
                        "Your cart is empty. Please add a product first."
                    );

                    return;
                }


                /* -----------------------------------------
                   START PAYMENT
                ----------------------------------------- */

                startPayment(
                    subtotal,
                    tax,
                    total,
                    latestCart
                );

            }
        );

    }

});


/* =========================================================
   START RAZORPAY PAYMENT
========================================================= */

async function startPayment(
    subtotal,
    tax,
    total,
    cart
) {
    const checkoutFields = [
        document.getElementById("customerName"),
        document.getElementById("customerEmail"),
        document.getElementById("customerPhone"),
        document.getElementById("customerAddress")
    ];
    if (window.LocalMartFormValidation
        && !window.LocalMartFormValidation.validateFields(checkoutFields)) {
        return;
    }

    /* -----------------------------------------------------
       DEBUG
    ----------------------------------------------------- */

    console.log(
        "Cart received by startPayment:",
        cart
    );


    /* -----------------------------------------------------
       CHECK CART
    ----------------------------------------------------- */

    if (
        !Array.isArray(cart) ||
        cart.length === 0
    ) {

        console.error(
            "Cart is empty:",
            cart
        );

        alert(
            "Your cart is empty. Please add a product first."
        );

        return;
    }


    console.log(
        "Cart before payment:",
        cart
    );


    /* -----------------------------------------------------
       CUSTOMER DETAILS
    ----------------------------------------------------- */

    const customerName =
        document
            .getElementById("customerName")
            ?.value
            .trim() || "";


    const customerEmail =
        document
            .getElementById("customerEmail")
            ?.value
            .trim() || "";


    const customerPhone =
        document
            .getElementById("customerPhone")
            ?.value
            .trim() || "";


    const customerAddress =
        document
            .getElementById("customerAddress")
            ?.value
            .trim() || "";

    const restaurantName = getCheckoutRestaurantName(cart);
    const deliveryPin = window.LOCALMART_CHECKOUT_DELIVERY;


    /* -----------------------------------------------------
       VALIDATE CUSTOMER DETAILS
    ----------------------------------------------------- */

    if (
        !customerName ||
        !customerEmail ||
        !customerPhone ||
        !customerAddress
    ) {

        alert(
            "Please enter all delivery details."
        );

        return;
    }

    if (!deliveryPin || deliveryPin.address !== customerAddress) {
        alert("Locate your delivery address and confirm the exact map pin before payment.");
        return;
    }
    if (restaurantName === "multiple") {
        alert("Please place separate orders for items from different restaurants.");
        return;
    }


    /* -----------------------------------------------------
       PAYMENT BUTTON
    ----------------------------------------------------- */

    const payButton =
        document.getElementById("payButton");


    if (!payButton) {

        console.error(
            "Payment button #payButton not found."
        );

        return;
    }


    /* -----------------------------------------------------
       DISABLE BUTTON
    ----------------------------------------------------- */

    payButton.disabled = true;


    payButton.innerHTML = `
        <i class="bi bi-hourglass-split me-2"></i>
        Creating Payment...
    `;


    try {

        /* -------------------------------------------------
           CREATE RAZORPAY ORDER
        ------------------------------------------------- */

        const response =
            await fetch(
                "/api/create-razorpay-order/",
                {

                    method: "POST",

                    headers: {

                        "Content-Type":
                            "application/json",

                        "X-CSRFToken":
                            getCheckoutCsrfToken()

                    },

                    credentials: "same-origin",

                    body: JSON.stringify({

    customer_name: customerName,

    customer_email: customerEmail,

    phone: customerPhone,

    address: customerAddress,

    customer_address: customerAddress,

    customer_latitude: deliveryPin.latitude,

    customer_longitude: deliveryPin.longitude,

    delivery_location_confirmed: true,

    restaurant_name: restaurantName,

    cart: cart,

    subtotal: subtotal,

    tax: tax,

    total: total
})

                }
            );


        /* -------------------------------------------------
           READ RESPONSE SAFELY
        ------------------------------------------------- */

        let data;

        try {

            data =
                await response.json();

        } catch (jsonError) {

            console.error(
                "Invalid JSON response:",
                jsonError
            );

            throw new Error(
                "Server returned an invalid response."
            );
        }


        /* -------------------------------------------------
           API ERROR
        ------------------------------------------------- */

        if (
            !response.ok ||
            !data.success
        ) {

            throw new Error(
                data.message ||
                `Unable to create Razorpay order. HTTP ${response.status}`
            );

        }


        /* -------------------------------------------------
           CHECK RAZORPAY DATA
        ------------------------------------------------- */

        if (!data.key_id) {

            throw new Error(
                "Razorpay key ID was not returned by server."
            );

        }


        if (!data.order_id) {

            throw new Error(
                "Razorpay order ID was not returned by server."
            );

        }


        if (!data.amount) {

            throw new Error(
                "Payment amount was not returned by server."
            );

        }




        /* -------------------------------------------------
           RAZORPAY OPTIONS
        ------------------------------------------------- */

        const options = {

            key:
                data.key_id,

            amount:
                data.amount,

            currency:
                data.currency || "INR",

            name:
                "LocalMart",

            description:
                "LocalMart Order",

            order_id:
                data.order_id,


            /* ---------------------------------------------
               CUSTOMER
            --------------------------------------------- */

            prefill: {

                name:
                    customerName,

                email:
                    customerEmail,

                contact:
                    customerPhone

            },


            /* ---------------------------------------------
               NOTES
            --------------------------------------------- */

            notes: {

                address:
                    customerAddress

            },


            /* ---------------------------------------------
               THEME
            --------------------------------------------- */

            theme: {

                color:
                    "#00A651"

            },


            /* ---------------------------------------------
               SUCCESS
            --------------------------------------------- */

            handler:
                async function(paymentResponse) {

                    await verifyPayment(

                        paymentResponse,

                        data.local_order_id

                    );

                },

                

            /* ---------------------------------------------
               MODAL CLOSED
            --------------------------------------------- */

            modal: {

                ondismiss:
                    function() {

                        console.log(
                            "Razorpay payment window closed."
                        );


                        payButton.disabled =
                            false;


                        payButton.innerHTML = `
                            <i class="bi bi-credit-card me-2"></i>
                            Pay Securely
                        `;

                    }

            }

        };


        /* -------------------------------------------------
           CREATE RAZORPAY INSTANCE
        ------------------------------------------------- */

        if (
            typeof Razorpay ===
            "undefined"
        ) {

            throw new Error(
                "Razorpay SDK is not loaded."
            );

        }


        const razorpay =
            new Razorpay(options);


        /* -------------------------------------------------
           PAYMENT FAILED
        ------------------------------------------------- */

        razorpay.on("payment.failed", function (response) {

    console.error(
        "========== RAZORPAY PAYMENT FAILED =========="
    );

    console.error(
        JSON.stringify(response, null, 2)
    );

    console.error(
        "Description:",
        response?.error?.description
    );

    alert(
        response?.error?.description ||
        "Payment failed. Please try another payment method."
    );

    payButton.disabled = false;

    payButton.innerHTML = `
        <i class="bi bi-credit-card me-2"></i>
        Pay Securely
    `;
});

        /* -------------------------------------------------
           OPEN RAZORPAY
        ------------------------------------------------- */

        razorpay.open();

    }


    catch(error) {

        console.error(
            "Payment error:",
            error
        );


        alert(
            error.message ||
            "Something went wrong while creating payment."
        );


        payButton.disabled =
            false;


        payButton.innerHTML = `
            <i class="bi bi-credit-card me-2"></i>
            Pay Securely
        `;

    }

}


/* =========================================================
   VERIFY RAZORPAY PAYMENT
========================================================= */

async function verifyPayment(
    paymentResponse,
    localOrderId
) {

    console.log(
        "Starting payment verification..."
    );


    try {

        /* -------------------------------------------------
           VERIFY PAYMENT
        ------------------------------------------------- */

        const response =
            await fetch(
                "/api/verify-payment/",
                {

                    method: "POST",

                    headers: {

                        "Content-Type":
                            "application/json",

                        "X-CSRFToken":
                            getCheckoutCsrfToken()

                    },

                    credentials: "same-origin",

                    body: JSON.stringify({

                        razorpay_payment_id:
                            paymentResponse
                                .razorpay_payment_id,

                        razorpay_order_id:
                            paymentResponse
                                .razorpay_order_id,

                        razorpay_signature:
                            paymentResponse
                                .razorpay_signature,

                        customer_address:
                            document.getElementById("customerAddress")?.value.trim() || "",

                        local_order_id:
                            localOrderId

                    })

                }
            );


        /* -------------------------------------------------
           READ RESPONSE
        ------------------------------------------------- */

        let data;

        try {

            data =
                await response.json();

        } catch (jsonError) {

            throw new Error(
                "Invalid payment verification response."
            );

        }


        /* -------------------------------------------------
           VERIFY ERROR
        ------------------------------------------------- */

        if (
            !response.ok ||
            !data.success
        ) {

            throw new Error(
                data.message ||
                "Payment verification failed."
            );

        }


        /* -------------------------------------------------
           PAYMENT SUCCESS
        ------------------------------------------------- */

        console.log(
            "Payment verified successfully."
        );


        /* -------------------------------------------------
           CLEAR CART
        ------------------------------------------------- */

        [
            "cart",
            "localmartFashionCart",
            "localmartFashionMenCart"
        ].forEach(key => localStorage.removeItem(key));

        localStorage.removeItem("localmartCart");
        localStorage.removeItem("localmartWishlist");


        /* -------------------------------------------------
           SAVE ORDER ID
        ------------------------------------------------- */

        if (localOrderId) {

            localStorage.setItem(
                "lastOrderId",
                localOrderId
            );

        }


        /* -------------------------------------------------
           REDIRECT
        ------------------------------------------------- */

        window.location.href = localOrderId ? `/order/${encodeURIComponent(localOrderId)}/track/` : "/order-success/";

    }


    catch(error) {

        console.error(
            "Payment verification error:",
            error
        );


        alert(
            error.message ||
            "Payment verification failed. Please contact support."
        );

    }

}
