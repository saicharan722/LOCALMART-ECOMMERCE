(() => {
    if (window.localmartBackToTopInitialized) return;
    window.localmartBackToTopInitialized = true;

    const initialize = () => {
        const hasFloatingCart = Boolean(document.querySelector(".floating-cart"));
        const button = document.createElement("button");
        button.type = "button";
        button.className = "lm-back-to-top";
        button.setAttribute("aria-label", "Back to top");
        button.setAttribute("aria-hidden", "true");
        button.tabIndex = -1;
        button.title = "Back to top";
        if (hasFloatingCart) {
            button.classList.add("lm-back-to-top--above-floating-cart");
        }
        button.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
                <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round"></path>
            </svg>`;
        document.body.appendChild(button);

        const updateVisibility = () => {
            const isVisible = window.scrollY > 240;
            button.classList.toggle("is-visible", isVisible);
            button.setAttribute("aria-hidden", String(!isVisible));
            button.tabIndex = isVisible ? 0 : -1;
        };

        window.addEventListener("scroll", updateVisibility, { passive: true });
        button.addEventListener("click", () => {
            const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches
                ? "auto"
                : "smooth";
            window.scrollTo({ top: 0, behavior });
        });
        updateVisibility();
    };

    const stylesheetUrl = document.currentScript?.dataset.stylesheetUrl;
    if (!stylesheetUrl) {
        initialize();
        return;
    }

    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = stylesheetUrl;
    stylesheet.dataset.localmartBackToTop = "true";
    stylesheet.addEventListener("load", initialize, { once: true });
    stylesheet.addEventListener("error", () => {
        console.error("Unable to load the Back to Top stylesheet.");
    }, { once: true });
    document.head.appendChild(stylesheet);
})();
