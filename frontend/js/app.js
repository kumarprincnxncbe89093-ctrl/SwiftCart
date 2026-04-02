const DEFAULT_ADMIN_EXPANDED_SECTIONS = {
  products: false,
  users: false,
  codes: false,
  bankOffers: false,
  orders: false,
  reviews: false,
  linked: false,
  chats: false,
  changes: false,
  tables: false,
  "panel:finance": true,
  "panel:category": true,
  "panel:bankOffers": true,
  "panel:products": true,
  "panel:users": true,
  "panel:codes": true,
  "panel:orders": true,
  "panel:reviews": true,
  "panel:linked": true,
  "panel:changes": true,
  "panel:chats": true,
  "panel:database": true
};

const state = {
  home: null,
  currentProduct: null,
  productMap: new Map(),
  registerOtpVerified: false,
  loginOtpSessionId: null,
  loginOtpAccounts: [],
  recoveryOtpSessionId: null,
  recoveryOtpAccounts: [],
  activeCategory: "",
  wishlistIds: new Set(),
  chatbotMessages: [],
  chatResetTimer: null,
  chatbotSetOpen: null,
  adminExpandedSections: { ...DEFAULT_ADMIN_EXPANDED_SECTIONS }
};
const HOME_CACHE_KEY = "swiftcart-home-cache-v1";

function setStatus(node, message, tone = "neutral") {
  if (!node) return;
  node.textContent = message;
  node.dataset.state = tone;
}

function getPageStatusNode(page = document.body.dataset.page || "") {
  const statusIdByPage = {
    account: "profileUpdateStatus",
    admin: "adminStatus",
    cart: "cartCheckoutStatus",
    home: "catalogMessage",
    login: "loginStatus",
    merchant: "merchantStatus",
    orders: "ordersStatus",
    payment: "paymentStatus",
    register: "registerStatus",
    wishlist: "wishlistStatus"
  };
  return document.getElementById(statusIdByPage[page] || "pageStatus");
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function sanitizeUrl(value, fallback = "#") {
  const raw = String(value || "").trim();
  if (!raw) return fallback;

  const lowered = raw.toLowerCase();
  if (lowered.startsWith("javascript:") || lowered.startsWith("vbscript:")) {
    return fallback;
  }
  if (lowered.startsWith("data:") && !lowered.startsWith("data:image/")) {
    return fallback;
  }
  if (
    lowered.startsWith("https://")
    || lowered.startsWith("http://")
    || lowered.startsWith("blob:")
    || lowered.startsWith("data:image/")
    || raw.startsWith("/")
    || raw.startsWith("./")
    || raw.startsWith("../")
    || /^[a-zA-Z0-9][a-zA-Z0-9/_?.%=&+#:-]*$/.test(raw)
  ) {
    return raw;
  }
  return fallback;
}

function buildProductHref(slug) {
  const normalizedSlug = String(slug || "").trim();
  return normalizedSlug ? `product.html?slug=${encodeURIComponent(normalizedSlug)}` : "product.html";
}

function normalizeHomePayload(payload = {}) {
  return {
    hero: {
      title: payload?.hero?.title || "SwiftCart Marketplace",
      subtitle: payload?.hero?.subtitle || "Discover fashion, footwear, and accessories with richer product data and real checkout flows.",
      highlight: payload?.hero?.highlight || "Daily deals and premium selections updated from the catalog.",
    },
    categories: Array.isArray(payload?.categories) ? payload.categories : [],
    featured_products: Array.isArray(payload?.featured_products) ? payload.featured_products : [],
    deal_of_the_day: Array.isArray(payload?.deal_of_the_day) ? payload.deal_of_the_day : [],
    imported_products: Array.isArray(payload?.imported_products) ? payload.imported_products : [],
    new_arrivals: Array.isArray(payload?.new_arrivals) ? payload.new_arrivals : [],
  };
}

function buildEmptyAdminDashboard(user = null) {
  const fallbackName = [user?.first_name, user?.last_name].filter(Boolean).join(" ").trim() || user?.full_name || user?.email || "Owner";
  return {
    owner: {
      full_name: fallbackName,
      email: user?.email || "Owner account",
      unique_code: user?.unique_code || "",
      created_at: user?.created_at || null
    },
    totals: {
      categories: 0,
      products: 0,
      in_stock_products: 0,
      out_of_stock_products: 0,
      low_stock_products: 0,
      featured_products: 0,
      users: 0,
      orders: 0,
      wishlist_items: 0,
      reviews: 0,
      revenue: 0,
      cancelled_orders: 0,
      chat_messages: 0
    },
    inventory: {
      seller_listed_products: 0,
      platform_managed_products: 0,
      discounted_products: 0
    },
    growth: {
      users_last_7_days: 0,
      users_last_30_days: 0,
      orders_last_7_days: 0,
      orders_last_30_days: 0,
      revenue_last_7_days: 0,
      revenue_last_30_days: 0,
      merchant_accounts: 0
    },
    order_activity: [],
    hourly_activity: [],
    finance_series: [],
    order_series: [],
    cancelled_series: [],
    category_performance: [],
    bank_offers: [],
    active_category_discounts: [],
    users: [],
    orders: [],
    reviews: [],
    linked_mobile_accounts: [],
    chat_messages: [],
    user_change_logs: []
  };
}

function normalizeAdminDashboardPayload(payload = {}, user = null) {
  const fallback = buildEmptyAdminDashboard(user);
  return {
    ...fallback,
    ...(payload || {}),
    owner: { ...fallback.owner, ...(payload?.owner || {}) },
    totals: { ...fallback.totals, ...(payload?.totals || {}) },
    inventory: { ...fallback.inventory, ...(payload?.inventory || {}) },
    growth: { ...fallback.growth, ...(payload?.growth || {}) },
    order_activity: Array.isArray(payload?.order_activity) ? payload.order_activity : fallback.order_activity,
    hourly_activity: Array.isArray(payload?.hourly_activity) ? payload.hourly_activity : fallback.hourly_activity,
    finance_series: Array.isArray(payload?.finance_series) ? payload.finance_series : fallback.finance_series,
    order_series: Array.isArray(payload?.order_series) ? payload.order_series : fallback.order_series,
    cancelled_series: Array.isArray(payload?.cancelled_series) ? payload.cancelled_series : fallback.cancelled_series,
    category_performance: Array.isArray(payload?.category_performance) ? payload.category_performance : fallback.category_performance,
    bank_offers: Array.isArray(payload?.bank_offers) ? payload.bank_offers : fallback.bank_offers,
    active_category_discounts: Array.isArray(payload?.active_category_discounts) ? payload.active_category_discounts : fallback.active_category_discounts,
    users: Array.isArray(payload?.users) ? payload.users : fallback.users,
    orders: Array.isArray(payload?.orders) ? payload.orders : fallback.orders,
    reviews: Array.isArray(payload?.reviews) ? payload.reviews : fallback.reviews,
    linked_mobile_accounts: Array.isArray(payload?.linked_mobile_accounts) ? payload.linked_mobile_accounts : fallback.linked_mobile_accounts,
    chat_messages: Array.isArray(payload?.chat_messages) ? payload.chat_messages : fallback.chat_messages,
    user_change_logs: Array.isArray(payload?.user_change_logs) ? payload.user_change_logs : fallback.user_change_logs
  };
}

function normalizeAdminCatalogPayload(payload = {}) {
  return {
    owner: payload?.owner || null,
    products: Array.isArray(payload?.products) ? payload.products : [],
    categories: Array.isArray(payload?.categories) ? payload.categories : []
  };
}

function normalizeAdminDbOverview(payload = {}) {
  return {
    owner: payload?.owner || null,
    database_path: String(payload?.database_path || "Unavailable"),
    tables: Array.isArray(payload?.tables) ? payload.tables : []
  };
}

function hasAnyHomeProducts(payload) {
  return [
    payload?.featured_products,
    payload?.deal_of_the_day,
    payload?.imported_products,
    payload?.new_arrivals,
  ].some((items) => Array.isArray(items) && items.length > 0);
}

function cacheHomePayload(payload) {
  try {
    localStorage.setItem(HOME_CACHE_KEY, JSON.stringify(normalizeHomePayload(payload)));
  } catch {
    // Ignore localStorage write failures.
  }
}

function getCachedHomePayload() {
  try {
    const raw = localStorage.getItem(HOME_CACHE_KEY);
    return raw ? normalizeHomePayload(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

function dedupeProductsById(products = []) {
  return Array.from(new Map((products || []).filter(Boolean).map((item) => [item.id, item])).values());
}

function buildFallbackHomePayload(categories = [], products = []) {
  const catalog = dedupeProductsById(products);
  const newest = [...catalog].sort((left, right) => {
    const rightTime = new Date(right?.created_at || 0).getTime();
    const leftTime = new Date(left?.created_at || 0).getTime();
    return rightTime - leftTime;
  });
  return normalizeHomePayload({
    categories,
    featured_products: catalog.filter((item) => item?.featured).slice(0, 8),
    deal_of_the_day: catalog
      .filter((item) => item?.deal_of_the_day || Number(item?.original_price || 0) > Number(item?.price || 0))
      .slice(0, 6),
    imported_products: catalog.filter((item) => item?.category?.slug === "research-picks").slice(0, 12),
    new_arrivals: newest.slice(0, 10),
    hero: {
      title: "SwiftCart Marketplace",
      subtitle: "Discover fashion, footwear, and accessories with richer product data, offers, and real checkout flows.",
      highlight: "Daily deals and premium selections inspired by modern marketplace experiences.",
    },
  });
}

function guardProtectedPage(page) {
  const rules = {
    account: (user) => Boolean(user),
    merchant: (user) => isMerchantUser(user),
    admin: (user) => isOwnerUser(user),
    orders: (user) => Boolean(user),
    wishlist: (user) => Boolean(user),
    payment: (user) => Boolean(user)
  };

  const canAccess = rules[page];
  if (!canAccess) return true;

  const verify = () => {
    const user = getStoredUser();
    if (canAccess(user)) return true;
    document.body.style.display = "none";
    redirectToPage("Login.html");
    return false;
  };

  window.addEventListener("pageshow", verify);
  window.addEventListener("popstate", verify);
  return verify();
}

function isOwnerUser(user) {
  return Boolean(user && user.is_owner);
}

function isMerchantUser(user) {
  return Boolean(user && ["merchant", "seller"].includes(user.account_type));
}

function buildOwnerQuery(user) {
  return `?user_id=${encodeURIComponent(user.id)}`;
}

function isSectionExpanded(key) {
  return Boolean(state.adminExpandedSections?.[key]);
}

function setSectionExpanded(key, value) {
  if (!state.adminExpandedSections) state.adminExpandedSections = {};
  state.adminExpandedSections[key] = Boolean(value);
}

function renderStars(rating) {
  const safeRating = Math.max(0, Math.min(5, Number(rating) || 0));
  const percentage = `${(safeRating / 5) * 100}%`;
  return `
    <span class="star-rating" aria-label="${safeRating.toFixed(1)} out of 5 stars">
      <span class="star-track">★★★★★</span>
      <span class="star-fill" style="width:${percentage}">★★★★★</span>
    </span>
  `;
}

function getVisibleDiscountPercent(product) {
  const price = Number(product?.price || 0);
  const originalPrice = Number(product?.original_price || 0);
  const storedPercent = Number(product?.discount_percent || 0);
  if (originalPrice > price && originalPrice > 0) {
    return Math.max(0, Math.round(((originalPrice - price) / originalPrice) * 100));
  }
  return storedPercent > 0 ? storedPercent : 0;
}

function hasVisibleDiscount(product) {
  const price = Number(product?.price || 0);
  const originalPrice = Number(product?.original_price || 0);
  return originalPrice > price && getVisibleDiscountPercent(product) > 0;
}

function buildPriceMetaMarkup(product) {
  if (!hasVisibleDiscount(product)) {
    return "";
  }
  return `
    <small class="strike-copy">${formatPrice(product.original_price)}</small>
    <small class="offer-chip">${getVisibleDiscountPercent(product)}% off</small>
  `;
}

function isProductOutOfStock(product) {
  return Number(product?.stock || 0) <= 0 || product?.stock_status_key === "out_of_stock";
}

function buildStockStatusMarkup(product, options = {}) {
  const stock = Number(product?.stock || 0);
  const status = String(product?.stock_status || (stock <= 0 ? "Out of Stock" : stock <= 5 ? "Low Stock" : "In Stock"));
  const key = String(product?.stock_status_key || (stock <= 0 ? "out_of_stock" : stock <= 5 ? "low_stock" : "in_stock"));
  const compact = Boolean(options.compact);
  const toneClass = key === "out_of_stock" ? "is-danger" : key === "low_stock" ? "is-warning" : "is-success";
  const countCopy = stock > 0 && !compact ? ` · ${stock} left` : "";
  return `<span class="inventory-pill ${toneClass}">${escapeHtml(status)}${escapeHtml(countCopy)}</span>`;
}

function calculateCartSummary(items = []) {
  const normalizedItems = Array.isArray(items) ? items : [];
  const subtotal = normalizedItems.reduce((sum, item) => sum + (Number(item.price || 0) * Number(item.quantity || 0)), 0);
  const originalSubtotal = normalizedItems.reduce((sum, item) => sum + (Number(item.original_price || item.price || 0) * Number(item.quantity || 0)), 0);
  const savings = Math.max(0, originalSubtotal - subtotal);
  const unavailableItems = normalizedItems.filter((item) => isProductOutOfStock(item) || Number(item.quantity || 0) > Number(item.stock || 0));
  return {
    itemCount: normalizedItems.reduce((sum, item) => sum + Number(item.quantity || 0), 0),
    uniqueItems: normalizedItems.length,
    subtotal,
    originalSubtotal,
    savings,
    unavailableItems,
  };
}

function showPaymentProcessingOverlay(message = "Processing your payment and reserving stock.") {
  const existing = document.getElementById("paymentProcessingOverlay");
  if (existing) existing.remove();
  const overlay = document.createElement("div");
  overlay.id = "paymentProcessingOverlay";
  overlay.className = "payment-processing-overlay";
  overlay.innerHTML = `
    <div class="payment-processing-card">
      <div class="payment-spinner-wrap">
        <div class="payment-spinner"></div>
        <div class="payment-spinner-core"></div>
      </div>
      <div class="payment-progress-dots"><span></span><span></span><span></span></div>
      <h3>Finalising Your Order</h3>
      <p>${escapeHtml(message)}</p>
    </div>
  `;
  document.body.appendChild(overlay);
  return overlay;
}

function toTitleCase(value) {
  return String(value || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function toSentenceCase(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) return "";
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

function normalizePhoneInput(value) {
  const raw = String(value || "").trim();
  const digits = raw.replace(/\D/g, "");
  if (!digits) return "";
  if (digits.length === 10) return `+91${digits}`;
  if (digits.length === 12 && digits.startsWith("91")) return `+${digits}`;
  if (digits.length === 13 && raw.startsWith("+")) return raw;
  return raw.startsWith("+") ? raw : `+${digits}`;
}

function formatPhoneDisplay(value) {
  const normalized = normalizePhoneInput(value);
  return normalized || String(value || "").trim();
}

function sortAddresses(addresses = []) {
  return [...(addresses || [])].sort((left, right) => {
    if (Boolean(left.is_default) !== Boolean(right.is_default)) {
      return left.is_default ? -1 : 1;
    }
    return String(left.label || "").localeCompare(String(right.label || ""));
  });
}

function getDefaultAddress(user) {
  const addresses = sortAddresses(user?.addresses || []);
  return addresses.find((item) => item.is_default) || addresses[0] || user?.address || null;
}

function formatAddressSummary(address) {
  if (!address) return "";
  return [address.street, address.city, address.state, address.pincode].filter(Boolean).join(", ");
}

function fillAddressFields(address, mapping) {
  if (!mapping) return;
  Object.entries(mapping).forEach(([key, selector]) => {
    const node = typeof selector === "string" ? document.querySelector(selector) : selector;
    if (node) node.value = address?.[key] || "";
  });
}

function autoCapitalizeField(field, mode = "sentence") {
  if (!field || typeof field.value !== "string") return;
  const nextValue = mode === "title" ? toTitleCase(field.value) : toSentenceCase(field.value);
  if (nextValue) field.value = nextValue;
}

function bindAutoCapitalization(fields, mode = "sentence") {
  fields.filter(Boolean).forEach((field) => {
    if (field.dataset.autoCapitalizedBound === "true") return;
    field.dataset.autoCapitalizedBound = "true";
    field.addEventListener("blur", () => autoCapitalizeField(field, mode));
  });
}

function startCooldown(button, seconds, onTick) {
  let remaining = seconds;
  button.disabled = true;
  onTick(remaining);
  const timer = setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      clearInterval(timer);
      button.disabled = false;
      onTick(0);
      return;
    }
    onTick(remaining);
  }, 1000);
}

function updateCartCount() {
  const count = getCart().reduce((sum, item) => sum + item.quantity, 0);
  document.querySelectorAll("[data-cart-count]").forEach((node) => {
    node.textContent = count;
  });
}

function firstNonEmptyText(...values) {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text) return text;
  }
  return "";
}

function mergedProfileData(storedUser, remoteProfile) {
  const firstName = firstNonEmptyText(remoteProfile?.first_name, storedUser?.first_name);
  const lastName = firstNonEmptyText(remoteProfile?.last_name, storedUser?.last_name);
  const fullName = firstNonEmptyText(
    remoteProfile?.full_name,
    [firstName, lastName].filter(Boolean).join(" "),
    storedUser?.full_name
  );

  return {
    ...(storedUser || {}),
    ...(remoteProfile || {}),
    first_name: firstName,
    last_name: lastName,
    full_name: fullName,
    email: firstNonEmptyText(remoteProfile?.email, storedUser?.email),
    mobile: firstNonEmptyText(remoteProfile?.mobile, storedUser?.mobile),
    unique_code: firstNonEmptyText(remoteProfile?.unique_code, storedUser?.unique_code),
    profile_image: firstNonEmptyText(remoteProfile?.profile_image, storedUser?.profile_image),
    created_at: firstNonEmptyText(remoteProfile?.created_at, storedUser?.created_at),
    addresses: Array.isArray(remoteProfile?.addresses)
      ? remoteProfile.addresses
      : Array.isArray(storedUser?.addresses)
        ? storedUser.addresses
        : [],
    address: remoteProfile?.address || storedUser?.address || null,
  };
}

function setImageSourceWithFallback(node, src, fallbackSrc = "images/swift.png") {
  if (!(node instanceof HTMLImageElement)) return;
  node.onerror = () => {
    node.onerror = null;
    node.src = fallbackSrc;
  };
  node.src = src || fallbackSrc;
}

function buildUserAvatarMarkup(user) {
  if (!user) {
    return `<i class="fa-regular fa-circle-user"></i>`;
  }
  if (user?.profile_image) {
    const photoPrefs = user?.id ? loadProfilePhotoPrefs(user.id) : {};
    const zoom = Number(photoPrefs.zoom) || 1;
    const focus = Number(photoPrefs.focus) || 50;
    return `<img class="account-avatar-image" src="${escapeHtml(sanitizeUrl(user.profile_image, "images/swift.png"))}" alt="${escapeHtml(user.full_name || user.first_name || "User")}" style="--profile-zoom:${zoom}; --profile-focus:${focus}%;" onerror="this.onerror=null;this.src='images/swift.png';">`;
  }

  const seed = String(user?.first_name || user?.full_name || "U").trim().charAt(0).toUpperCase();
  return `<span class="account-avatar-fallback">${escapeHtml(seed || "U")}</span>`;
}

function syncUserUi() {
  const user = getStoredUser();
  const page = document.body.dataset.page || "";
  const hasPageLogout = Boolean(document.getElementById("adminLogoutButton") || document.getElementById("logoutButton"));
  const allowInjectedLogout = new Set(["home", "product"]).has(page) && !hasPageLogout;
  const allowSignupCta = new Set(["home", "product"]).has(page);
  document.querySelectorAll("[data-user-name]").forEach((node) => {
    node.textContent = user ? user.first_name : "Sign in";
  });
  document.querySelectorAll("[data-user-email]").forEach((node) => {
    node.textContent = user ? user.email : "Login to your account";
  });

  document.querySelectorAll(".nav-signin").forEach((node) => {
    const link = node.closest("a.icon");
    const greeting = node.querySelector("[data-user-name]");
    const meta = node.querySelector(".nav-second");
    if (greeting) greeting.textContent = user ? user.first_name : "Sign in";
    if (meta) meta.textContent = user ? "My Account" : "Login";
    if (link) link.href = user ? "Account_Details.html" : "Login.html";
  });

  document.querySelectorAll(".navbar").forEach((navbar) => {
    const existingLogout = navbar.querySelector(".nav-logout-button");
    const existingSignup = navbar.querySelector(".nav-signup-button");
    if (user && allowInjectedLogout) {
      if (!existingLogout) {
        const logoutButton = document.createElement("button");
        logoutButton.type = "button";
        logoutButton.className = "nav-logout-button";
        logoutButton.textContent = "Logout";
        logoutButton.addEventListener("click", () => logoutCurrentUser());
        navbar.appendChild(logoutButton);
      }
      if (existingSignup) {
        existingSignup.remove();
      }
    } else if (existingLogout) {
      existingLogout.remove();
    }
    if (!user && allowSignupCta && !existingSignup) {
      const signupLink = document.createElement("a");
      signupLink.href = "Account_Creation.html";
      signupLink.className = "nav-signup-button";
      signupLink.textContent = "Create Account";
      navbar.appendChild(signupLink);
    } else if (user && existingSignup) {
      existingSignup.remove();
    }
  });

  document.querySelectorAll(".account-user").forEach((node) => {
    const link = node.closest("a.icon");
    node.innerHTML = buildUserAvatarMarkup(user);
    node.classList.toggle("is-logged-in", Boolean(user));
    if (link) link.href = user ? "Account_Details.html" : "Login.html";
  });
}

async function loadWishlistIds() {
  const user = getStoredUser();
  if (!user) {
    state.wishlistIds = new Set();
    return state.wishlistIds;
  }

  try {
    const wishlist = await apiFetch(`/users/${user.id}/wishlist`);
    state.wishlistIds = new Set(wishlist.map((item) => item.id));
  } catch (error) {
    state.wishlistIds = new Set();
    console.warn("SwiftCart wishlist sync skipped:", error);
  }
  return state.wishlistIds;
}

function buildProductCard(product) {
  const productHref = buildProductHref(product.slug);
  const productImage = sanitizeUrl(product.image, "images/swift.png");
  const wishlistBadge = state.wishlistIds.has(product.id) ? "<span class=\"wishlist-badge\">Saved</span>" : "";
  return `
    <article class="product-card">
      <div class="product-tag">${escapeHtml(product.tag)}</div>
      ${wishlistBadge}
      <a href="${escapeHtml(productHref)}" class="product-image-link" aria-label="View details for ${escapeHtml(product.name)}">
        <img src="${escapeHtml(productImage)}" alt="${escapeHtml(product.name)}">
      </a>
      <h3><a href="${escapeHtml(productHref)}" class="product-title-link">${escapeHtml(product.name)}</a></h3>
      <p class="product-copy">${escapeHtml(product.description)}</p>
      <div class="product-meta">
        <span class="rating-chip">${renderStars(product.rating)}<strong class="rating-value">${product.rating.toFixed(1)}</strong></span>
        <span>${escapeHtml(String(product.reviews_count))} reviews</span>
      </div>
      <div class="product-stock-row">${buildStockStatusMarkup(product, { compact: true })}</div>
      <div class="product-footer">
        <div>
          <strong>${formatPrice(product.price)}</strong>
          ${buildPriceMetaMarkup(product)}
        </div>
        <a href="${escapeHtml(productHref)}" class="product-link">View Details</a>
      </div>
    </article>
  `;
}

function renderProductCollection(containerId, products) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const items = Array.isArray(products) ? products : [];
  container.dataset.empty = items.length ? "false" : "true";
  container.innerHTML = items.map((product) => buildProductCard(product)).join("");
  const emptyState = document.getElementById("notFound");
  if (containerId === "productGrid" && emptyState) {
    emptyState.hidden = items.length > 0;
    emptyState.style.display = items.length > 0 ? "none" : "grid";
  }
}

function toggleCatalogSection(containerId, hasItems) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const head = container.previousElementSibling;
  const visible = Boolean(hasItems);
  container.hidden = !visible;
  if (head?.classList?.contains("section-head")) {
    head.hidden = !visible;
  }
}

function renderDatabaseTable(container, columns, rows) {
  if (!container) return;
  if (!columns.length) {
    container.innerHTML = "<p class=\"empty-copy\">No data to show.</p>";
    return;
  }

  container.innerHTML = `
    <table class="db-table">
      <thead>
        <tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr>
      </thead>
      <tbody>
        ${
          rows.length
            ? rows
                .map(
                  (row) => `
                    <tr>${columns
                      .map((column) => `<td class="db-cell">${escapeHtml(row[column] ?? "")}</td>`)
                      .join("")}</tr>
                  `
                )
                .join("")
            : `<tr><td colspan="${columns.length}" class="db-cell">No rows found.</td></tr>`
        }
      </tbody>
    </table>
  `;
}

function getChatStorageKey() {
  const user = getStoredUser();
  return user ? `swiftcart-chat-history:${user.id}` : "swiftcart-chat-history:guest";
}

function getChatClosedAtKey() {
  const user = getStoredUser();
  return user ? `swiftcart-chat-closed-at:${user.id}` : "swiftcart-chat-closed-at:guest";
}

function clearChatHistory() {
  state.chatbotMessages = [];
  sessionStorage.removeItem(getChatStorageKey());
  sessionStorage.removeItem(getChatClosedAtKey());
}

function loadChatHistory() {
  try {
    const closedAt = Number(sessionStorage.getItem(getChatClosedAtKey()) || 0);
    if (closedAt && Date.now() - closedAt >= 5 * 60 * 1000) {
      clearChatHistory();
      return [];
    }
    return JSON.parse(sessionStorage.getItem(getChatStorageKey()) || "[]");
  } catch {
    return [];
  }
}

function saveChatHistory(messages) {
  state.chatbotMessages = messages;
  sessionStorage.setItem(getChatStorageKey(), JSON.stringify(messages));
  sessionStorage.removeItem(getChatClosedAtKey());
}

function ensureChatWelcomeMessage() {
  if (state.chatbotMessages.length) return;
  const user = getStoredUser();
  const name = user?.first_name ? toTitleCase(user.first_name) : "there";
  saveChatHistory([
    {
      role: "assistant",
      text: `Hi ${name}, I’m SwiftCart AI. Tell me what you want to buy, your budget, or where you want delivery, and I’ll guide you step by step like a shopping assistant.`,
      quick_actions: ["Show top deals", "Track my order", "Recommend products"]
    }
  ]);
}

function openChatbot(force = true) {
  if (typeof state.chatbotSetOpen === "function") {
    state.chatbotSetOpen(force);
  }
}

function decorateSharedFooters() {
  document.querySelectorAll(".footer").forEach((footer) => {
    footer.innerHTML = `
      <div class="footer-top footer-top-rich">
        <div class="footer-col">
          <h4>SHOP SMART</h4>
          <p>Curated products with real ratings</p>
          <p>Track orders and delivery progress</p>
          <p>Wishlist, reviews, and AI shopping help</p>
        </div>
        <div class="footer-col">
          <h4>CUSTOMER CARE</h4>
          <p>Payments and checkout support</p>
          <p>Cancellation and returns</p>
          <p>Secure account and OTP access</p>
        </div>
        <div class="footer-col">
          <h4>SELL ON SWIFTCART</h4>
          <p>Merchant onboarding</p>
          <p>Product listing controls</p>
          <p>Marketplace visibility</p>
        </div>
        <div class="footer-col">
          <h4>DISCOVER</h4>
          <p>Fashion and accessories</p>
          <p>Curated marketplace collection</p>
          <p>Deals, trends, and fresh arrivals</p>
        </div>
        <div class="footer-col border-left">
          <h4>SWIFTCART HQ</h4>
          <p>Bengaluru, Karnataka, India</p>
          <p>Customer-first marketplace experience</p>
          <p>Secure shopping for buyers and merchants</p>
        </div>
        <div class="footer-col footer-highlight">
          <h4>WHY SWIFTCART</h4>
          <p>Fast product discovery</p>
          <p>Verified identity and account tracking</p>
          <p>Owner-grade analytics and control tools</p>
        </div>
      </div>
      <div class="footer-bottom footer-bottom-rich">
        <div><i class="fa-solid fa-store"></i><span>Marketplace Ready</span></div>
        <div><i class="fa-solid fa-shield-heart"></i><span>Secure Access</span></div>
        <div><i class="fa-solid fa-truck-fast"></i><span>Tracked Delivery</span></div>
        <div><i class="fa-solid fa-headset"></i><span>Support Center</span></div>
        <div><i class="fa-solid fa-sparkles"></i><span>SwiftCart AI</span></div>
        <div><span>© 2026 SwiftCart.com</span></div>
      </div>
    `;
  });
}

function buildChatProductCard(product) {
  return `
    <a class="chatbot-product-card" href="product.html?slug=${product.slug}">
      <img src="${product.image}" alt="${escapeHtml(product.name)}">
      <div>
        <strong>${escapeHtml(product.name)}</strong>
        <div class="chatbot-rating-row">${renderStars(product.rating)}<span>${product.rating.toFixed(1)}</span></div>
        <small>${formatPrice(product.price)}</small>
      </div>
    </a>
  `;
}

function renderChatMessages() {
  const body = document.getElementById("chatbotMessages");
  if (!body) return;
  body.innerHTML = state.chatbotMessages.map((item) => `
    <article class="chatbot-message ${item.role}">
      <div class="chatbot-bubble">
        <p>${escapeHtml(item.text)}</p>
        ${item.products?.length ? `<div class="chatbot-product-list">${item.products.map((product) => buildChatProductCard(product)).join("")}</div>` : ""}
        ${item.quick_actions?.length ? `<div class="chatbot-quick-actions">${item.quick_actions.map((action) => `<button type="button" class="chatbot-chip" data-chat-prompt="${escapeHtml(action)}">${escapeHtml(action)}</button>`).join("")}</div>` : ""}
      </div>
    </article>
  `).join("");
  body.querySelectorAll("[data-chat-prompt]").forEach((button) => {
    button.onclick = async (event) => {
      event.preventDefault();
      event.stopPropagation();
      openChatbot(true);
      await sendChatMessage(button.dataset.chatPrompt || "");
      document.getElementById("chatbotInput")?.focus();
    };
  });
  body.scrollTop = body.scrollHeight;
}

function pushChatMessage(role, text, extras = {}) {
  const next = [...state.chatbotMessages, { role, text, ...extras }];
  saveChatHistory(next);
  renderChatMessages();
}

async function sendChatMessage(rawMessage) {
  const input = document.getElementById("chatbotInput");
  const sendButton = document.getElementById("chatbotSendButton");
  const message = String(rawMessage || input?.value || "").trim();
  if (!message) return;

  pushChatMessage("user", message);
  openChatbot(true);
  if (input) input.value = "";
  if (sendButton) sendButton.disabled = true;
  if (sendButton) sendButton.textContent = "Thinking...";

  try {
    const user = getStoredUser();
    const response = await apiFetch("/chatbot/message", {
      method: "POST",
      body: JSON.stringify({
        message,
        user_id: user?.id || null,
        current_product_id: state.currentProduct?.id || null,
        cart_items: getCart(),
        page: document.body.dataset.page || "",
        history: state.chatbotMessages.slice(-6).map((entry) => ({
          role: entry.role,
          text: entry.text
        }))
      })
    });
    pushChatMessage("assistant", response.reply, {
      products: response.products || [],
      quick_actions: response.quick_actions || []
    });
    openChatbot(true);
  } catch (error) {
    pushChatMessage("assistant", error.message || "I could not answer that right now.");
    openChatbot(true);
  } finally {
    if (sendButton) {
      sendButton.disabled = false;
      sendButton.textContent = "Send";
    }
  }
}

function initChatbotWidget() {
  const blockedPages = new Set(["admin", "merchant", "login", "register"]);
  const page = document.body.dataset.page;
  const user = getStoredUser();
  if (blockedPages.has(page) || !user) return;
  document.querySelector(".chatbot-shell")?.remove();

  const wrapper = document.createElement("div");
  wrapper.className = "chatbot-shell";
  wrapper.innerHTML = `
    <button id="chatbotToggle" class="chatbot-toggle" type="button" aria-label="Open SwiftCart AI" aria-expanded="false">
      <i class="fa-solid fa-comments"></i>
    </button>
    <section id="chatbotPanel" class="chatbot-panel" hidden>
      <div class="chatbot-header">
        <div>
          <strong>SwiftCart AI</strong>
          <small>Shopping help, product picks, and order tracking</small>
        </div>
        <button id="chatbotClose" class="chatbot-close-button" type="button" aria-label="Close SwiftCart AI">
          <i class="fa-solid fa-xmark"></i>
        </button>
      </div>
      <div id="chatbotMessages" class="chatbot-messages"></div>
      <form id="chatbotForm" class="chatbot-form" autocomplete="off">
        <textarea id="chatbotInput" name="swiftcart_assistant_message" rows="1" placeholder="Ask about deals, products, delivery, or your saved address" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" data-lpignore="true"></textarea>
        <button id="chatbotSendButton" class="btn" type="submit">Send</button>
      </form>
    </section>
  `;
  document.body.appendChild(wrapper);

  state.chatbotMessages = loadChatHistory();
  ensureChatWelcomeMessage();
  renderChatMessages();

  const panel = document.getElementById("chatbotPanel");
  const toggle = document.getElementById("chatbotToggle");
  let isOpen = false;
  const shouldOpenOnLoad = ["home", "product", "cart", "orders", "wishlist", "account"].includes(page) && state.chatbotMessages.length <= 1;
  const setOpenState = (open) => {
    if (!panel || !toggle) return;
    isOpen = Boolean(open);
    panel.hidden = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.setAttribute("aria-label", open ? "Close SwiftCart AI" : "Open SwiftCart AI");
    toggle.classList.toggle("active", open);
    wrapper.classList.toggle("open", open);
    if (!open) {
      sessionStorage.setItem(getChatClosedAtKey(), String(Date.now()));
      if (state.chatResetTimer) window.clearTimeout(state.chatResetTimer);
      state.chatResetTimer = window.setTimeout(() => {
        clearChatHistory();
        ensureChatWelcomeMessage();
        renderChatMessages();
      }, 5 * 60 * 1000);
    } else {
      sessionStorage.removeItem(getChatClosedAtKey());
      if (state.chatResetTimer) {
        window.clearTimeout(state.chatResetTimer);
        state.chatResetTimer = null;
      }
      ensureChatWelcomeMessage();
      renderChatMessages();
    }
  };
  state.chatbotSetOpen = setOpenState;
  toggle?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    setOpenState(!isOpen);
  });
  document.getElementById("chatbotClose")?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    setOpenState(false);
  });
  document.addEventListener("click", (event) => {
    if (!isOpen) return;
    if (wrapper.contains(event.target)) return;
    setOpenState(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && isOpen) {
      setOpenState(false);
    }
  });
  document.getElementById("chatbotForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await sendChatMessage();
  });

  const input = document.getElementById("chatbotInput");
  input?.addEventListener("keydown", async (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      await sendChatMessage();
    }
  });
  input?.addEventListener("focus", () => setOpenState(true));
  if (shouldOpenOnLoad && page === "home") {
    setOpenState(false);
  }
}

function formatOrderStageDate(value) {
  if (!value) return "Pending";
  return new Date(value).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short"
  });
}

function formatCompactDateTime(value) {
  if (!value) return "Not available yet";
  return new Date(value).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit"
  });
}

function formatRemainingDuration(value) {
  if (!value) return "No timer";
  const diff = new Date(value).getTime() - Date.now();
  if (diff <= 0) return "Expired";
  const totalMinutes = Math.ceil(diff / 60000);
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return `${days}d ${hours}h left`;
  if (hours > 0) return `${hours}h ${minutes}m left`;
  return `${minutes}m left`;
}

function renderOrderTimeline(order) {
  const timeline = order.delivery_tracking?.timeline || [];
  return `
    <div class="order-timeline">
      ${timeline.map((step) => `
        <div class="order-step${step.completed ? " completed" : ""}${step.active ? " active" : ""}">
          <span class="order-step-dot"></span>
          <div>
            <strong>${escapeHtml(step.label)}</strong>
            <small>${formatOrderStageDate(step.timestamp)}</small>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function getOrderDeliveryCopy(order) {
  if (order.status === "Cancelled") {
    return `Cancelled on ${formatCompactDateTime(order.canceled_at)}`;
  }
  if (order.status === "Partially Cancelled") {
    return "Some products in this order were cancelled. Remaining products continue on the active delivery route.";
  }
  return `Estimated delivery by ${new Date(order.delivery_tracking.estimated_delivery_date).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "long",
    year: "numeric"
  })} · ${order.delivery_tracking.estimated_delivery_days} day route`;
}

function renderOrderLineItem(order, item) {
  const itemStatus = item.status || order.status;
  const canCancel = !["Cancelled", "Delivered"].includes(itemStatus) && order.status !== "Cancelled";
  const statusClass = itemStatus === "Cancelled"
    ? "is-cancelled"
    : itemStatus === "Partially Cancelled"
      ? "is-partial"
      : "";

  return `
    <article class="order-line-item${itemStatus === "Cancelled" ? " is-cancelled" : ""}">
      <img class="order-line-media" src="${escapeHtml(sanitizeUrl(item.image, "images/swift.png"))}" alt="${escapeHtml(item.name)}">
      <div class="order-line-copy">
        <div class="order-line-top">
          <div>
            <a class="order-line-link" href="product.html?slug=${encodeURIComponent(item.slug)}">${escapeHtml(item.name)}</a>
            <p class="order-line-meta">Qty ${item.quantity} · ${formatPrice(item.unit_price)} each · Line total ${formatPrice(item.line_total)}</p>
          </div>
          <span class="order-status-pill ${statusClass}">${escapeHtml(itemStatus)}</span>
        </div>
        ${item.cancel_reason ? `<p class="order-cancel-note"><strong>Cancellation reason:</strong> ${escapeHtml(item.cancel_reason)}</p>` : ""}
        <div class="inline-actions order-line-actions">
          <a class="ghost-button" href="product.html?slug=${encodeURIComponent(item.slug)}">View Product</a>
        </div>
        ${
          canCancel
            ? `
              <form class="order-cancel-form order-item-cancel-form" data-order-id="${order.id}" data-order-item-id="${item.order_item_id}">
                <textarea name="reason" rows="3" placeholder="Tell us why you want to cancel this product. Minimum 10 words." required></textarea>
                <div class="inline-actions">
                  <small>Minimum 10 words are required for cancellation.</small>
                  <button class="ghost-button" type="submit">Cancel This Product</button>
                </div>
                <p class="status-copy order-cancel-status"></p>
              </form>
            `
            : ""
        }
      </div>
    </article>
  `;
}

function renderAnalyticsBars(entries, getLabel, getValue, getMeta) {
  if (!entries.length) {
    return "<p class=\"empty-copy\">No analytics data yet.</p>";
  }
  const maxValue = Math.max(...entries.map((entry) => getValue(entry)), 1);
  return entries.map((entry) => {
    const value = getValue(entry);
    const width = Math.max((value / maxValue) * 100, value > 0 ? 8 : 0);
    return `
      <article class="analytics-bar-card">
        <div class="analytics-bar-top">
          <strong>${escapeHtml(getLabel(entry))}</strong>
          <span>${escapeHtml(getMeta(entry))}</span>
        </div>
        <div class="analytics-bar-track">
          <div class="analytics-bar-fill" style="width:${width}%"></div>
        </div>
      </article>
    `;
  }).join("");
}

function renderLineChart(title, points, color, formatter = (value) => String(value)) {
  if (!points?.length) {
    return `<article class="line-chart-card"><div class="section-head"><div><p class="eyebrow">${escapeHtml(title)}</p><h3>No data yet</h3></div></div></article>`;
  }
  const width = 640;
  const height = 220;
  const paddingX = 24;
  const paddingTop = 20;
  const paddingBottom = 36;
  const maxValue = Math.max(...points.map((point) => Number(point.value) || 0), 1);
  const stepX = points.length > 1 ? (width - paddingX * 2) / (points.length - 1) : 0;
  const toY = (value) => {
    const usable = height - paddingTop - paddingBottom;
    return paddingTop + usable - ((Number(value) || 0) / maxValue) * usable;
  };
  const coords = points.map((point, index) => ({
    x: paddingX + index * stepX,
    y: toY(point.value),
    label: point.label,
    value: Number(point.value) || 0,
  }));
  const polyline = coords.map((point) => `${point.x},${point.y}`).join(" ");
  const area = `${paddingX},${height - paddingBottom} ${polyline} ${width - paddingX},${height - paddingBottom}`;

  return `
    <article class="line-chart-card">
      <div class="section-head compact-head">
        <div>
          <p class="eyebrow">${escapeHtml(title)}</p>
          <h3>${formatter(points.at(-1)?.value || 0)}</h3>
        </div>
      </div>
      <svg viewBox="0 0 ${width} ${height}" class="line-chart-svg" role="img" aria-label="${escapeHtml(title)} trend chart">
        <polygon class="line-chart-area" points="${area}" style="fill:${color}; opacity:0.14;"></polygon>
        <polyline class="line-chart-path" points="${polyline}" style="--chart-color:${color};"></polyline>
        ${coords.map((point) => `
          <g>
            <circle cx="${point.x}" cy="${point.y}" r="4" class="line-chart-dot" style="--chart-color:${color};"></circle>
            <title>${escapeHtml(point.label)}: ${escapeHtml(formatter(point.value))}</title>
          </g>
        `).join("")}
        ${coords.map((point) => `<text x="${point.x}" y="${height - 10}" text-anchor="middle" class="line-chart-label">${escapeHtml(point.label)}</text>`).join("")}
      </svg>
    </article>
  `;
}

function buildAdminChatGroups(messages) {
  const groups = new Map();
  const chronologicalMessages = [...(messages || [])]
    .filter((message) => message && message.message)
    .reverse();

  chronologicalMessages.forEach((chat) => {
    const createdAt = chat.created_at || new Date().toISOString();
    const dayKey = String(createdAt).slice(0, 10);
    const userKey = chat.user?.id ? `user:${chat.user.id}` : "guest";
    const pageKey = chat.page || "general";
    const groupKey = `${userKey}|${pageKey}|${dayKey}`;

    if (!groups.has(groupKey)) {
      groups.set(groupKey, {
        key: groupKey,
        user: chat.user || null,
        page: pageKey,
        intent: chat.intent || "general",
        created_at: createdAt,
        messages: []
      });
    }

    const group = groups.get(groupKey);
    group.messages.push(chat);
    if (new Date(createdAt).getTime() > new Date(group.created_at).getTime()) {
      group.created_at = createdAt;
    }
  });

  return Array.from(groups.values()).sort(
    (left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
  );
}

function bindDisclosureButton(buttonId, panelId, key, openLabel = "Show Details", closeLabel = "Hide Details") {
  const button = document.getElementById(buttonId);
  const panel = document.getElementById(panelId);
  if (!button || !panel) return;
  const isOpen = Boolean(state.adminExpandedSections?.[`panel:${key}`]);
  panel.hidden = !isOpen;
  button.textContent = isOpen ? closeLabel : openLabel;
  button.onclick = () => {
    const next = !Boolean(state.adminExpandedSections?.[`panel:${key}`]);
    setSectionExpanded(`panel:${key}`, next);
    panel.hidden = !next;
    button.textContent = next ? closeLabel : openLabel;
  };
}

function formatDateTime(value) {
  return new Date(value).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit"
  });
}

function renderCategories(categories) {
  const container = document.getElementById("categoryRail");
  if (!container) return;

  container.innerHTML = categories
    .map(
      (category) => `
        <button class="category-pill" type="button" data-category="${escapeHtml(category.slug)}">
          <strong>${escapeHtml(category.name)}</strong>
          <span>${escapeHtml(category.banner_title)}</span>
        </button>
      `
    )
    .join("");

  container.querySelectorAll("[data-category]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.activeCategory = button.dataset.category;
      await runCatalogSearch();
      setStatus(document.getElementById("catalogMessage"), `Showing ${button.textContent.trim()} picks.`, "success");
    });
  });
}

function renderImportedProducts(products) {
  renderProductCollection("researchGrid", products);
  toggleCatalogSection("researchGrid", Array.isArray(products) && products.length > 0);
}

async function runCatalogSearch() {
  const searchInput = document.getElementById("catalogSearch");
  const sortSelect = document.getElementById("catalogSort");
  const minPrice = document.getElementById("catalogMinPrice");
  const maxPrice = document.getElementById("catalogMaxPrice");
  const inStock = document.getElementById("catalogInStock");
  const messageNode = document.getElementById("catalogMessage");
  const notFoundNode = document.getElementById("notFound");
  const searchTerm = searchInput?.value.trim() || "";
  const effectiveCategory = searchTerm ? "" : state.activeCategory;

  const params = new URLSearchParams();
  if (searchTerm) params.set("q", searchTerm);
  if (effectiveCategory) params.set("category", effectiveCategory);
  if (sortSelect?.value) params.set("sort", sortSelect.value);
  if (minPrice?.value) params.set("min_price", minPrice.value);
  if (maxPrice?.value) params.set("max_price", maxPrice.value);
  if (inStock?.checked) params.set("in_stock", "true");

  const queryString = params.toString();
  const result = await apiFetch(`/products${queryString ? `?${queryString}` : ""}`);
  renderProductCollection("productGrid", result);
  if (notFoundNode) {
    notFoundNode.hidden = result.length > 0;
    notFoundNode.style.display = result.length > 0 ? "none" : "grid";
  }
  setStatus(
    messageNode,
    queryString ? `Showing ${result.length} matching products.` : "Showing featured products.",
    result.length ? "success" : "error"
  );
}

window.handleCatalogSearch = runCatalogSearch;

async function renderHomePage() {
  await loadWishlistIds();
  const catalogMessageNode = document.getElementById("catalogMessage");
  let payload = null;
  let loadMessage = "";
  let usedFallback = false;

  try {
    payload = normalizeHomePayload(await apiFetch("/home"));
  } catch (error) {
    loadMessage = error.message || "Live catalog is temporarily unavailable.";
  }

  if (!payload || !hasAnyHomeProducts(payload)) {
    try {
      const [categories, products] = await Promise.all([
        apiFetch("/categories").catch(() => []),
        apiFetch("/products?sort=rating").catch(() => []),
      ]);
      const fallbackPayload = buildFallbackHomePayload(categories, products);
      if (hasAnyHomeProducts(fallbackPayload)) {
        payload = fallbackPayload;
        usedFallback = true;
      }
    } catch {
      // Keep trying the next fallback.
    }
  }

  if ((!payload || !hasAnyHomeProducts(payload))) {
    const cachedPayload = getCachedHomePayload();
    if (cachedPayload && hasAnyHomeProducts(cachedPayload)) {
      payload = cachedPayload;
      usedFallback = true;
      if (!loadMessage) {
        loadMessage = "Showing the last available catalog snapshot while the live refresh completes.";
      }
    }
  }

  payload = normalizeHomePayload(payload || {});
  if (hasAnyHomeProducts(payload)) {
    cacheHomePayload(payload);
  }
  state.home = payload;
  payload.featured_products.forEach((item) => state.productMap.set(item.id, item));
  payload.deal_of_the_day.forEach((item) => state.productMap.set(item.id, item));
  payload.new_arrivals.forEach((item) => state.productMap.set(item.id, item));
  payload.imported_products.forEach((item) => state.productMap.set(item.id, item));

  const heroTitle = document.getElementById("heroTitle");
  const heroSubtitle = document.getElementById("heroSubtitle");
  const heroHighlight = document.getElementById("heroHighlight");
  const marketplaceStats = document.getElementById("marketplaceStats");
  const marketplaceHighlights = document.getElementById("marketplaceHighlights");
  if (heroTitle) heroTitle.textContent = payload.hero.title;
  if (heroSubtitle) heroSubtitle.textContent = payload.hero.subtitle;
  if (heroHighlight) heroHighlight.textContent = payload.hero.highlight;

  const allShowcaseProducts = [
    ...(payload.featured_products || []),
    ...(payload.deal_of_the_day || []),
    ...(payload.new_arrivals || []),
    ...(payload.imported_products || [])
  ];
  const uniqueProducts = Array.from(new Map(allShowcaseProducts.map((item) => [item.id, item])).values());
  const inStockShowcaseCount = uniqueProducts.filter((item) => !isProductOutOfStock(item)).length;
  const discountedShowcaseCount = uniqueProducts.filter((item) => hasVisibleDiscount(item)).length;
  const topRatedShowcaseCount = uniqueProducts.filter((item) => Number(item.rating || 0) >= 4.2).length;
  if (marketplaceStats) {
    marketplaceStats.innerHTML = [
      { label: "Live Categories", value: payload.categories?.length || 0 },
      { label: "Featured Listings", value: payload.featured_products?.length || 0 },
      { label: "In Stock Now", value: inStockShowcaseCount },
      { label: "Active Deals", value: discountedShowcaseCount },
    ].map((entry) => `
      <article class="marketplace-stat-card">
        <strong>${entry.value}</strong>
        <span>${entry.label}</span>
      </article>
    `).join("");
  }
  if (marketplaceHighlights) {
    const topCategories = (payload.categories || []).slice(0, 3);
    marketplaceHighlights.innerHTML = [
      {
        title: "Fast Discovery",
        copy: `${topRatedShowcaseCount} highly rated listings are ready to browse with richer product detail and reviews.`,
      },
      {
        title: "Fresh Deals",
        copy: `${discountedShowcaseCount} products are currently showing deal pricing instead of flat static catalog prices.`,
      },
      {
        title: "Marketplace Depth",
        copy: topCategories.length
          ? `Top active departments include ${topCategories.map((item) => item.name).join(", ")}.`
          : "The catalog is ready to scale across multiple departments.",
      }
    ].map((entry) => `
      <article class="marketplace-highlight-card">
        <strong>${escapeHtml(entry.title)}</strong>
        <p>${escapeHtml(entry.copy)}</p>
      </article>
    `).join("");
  }

  renderCategories(payload.categories);
  renderImportedProducts(payload.imported_products || []);
  renderProductCollection("dealGrid", payload.deal_of_the_day);
  toggleCatalogSection("dealGrid", Array.isArray(payload.deal_of_the_day) && payload.deal_of_the_day.length > 0);
  renderProductCollection("productGrid", payload.featured_products);
  renderProductCollection("arrivalGrid", payload.new_arrivals);
  toggleCatalogSection("arrivalGrid", Array.isArray(payload.new_arrivals) && payload.new_arrivals.length > 0);

  const searchInput = document.getElementById("catalogSearch");
  const searchForm = document.getElementById("catalogSearchForm");
  const suggestionNode = document.getElementById("catalogSearchSuggestions");
  const resetButton = document.getElementById("catalogResetButton");
  const sortSelect = document.getElementById("catalogSort");
  const applyFiltersButton = document.getElementById("catalogApplyFilters");
  const quickFilterButtons = document.querySelectorAll("#catalogQuickFilters .filter-chip");
  const searchableProducts = [
    ...(payload.featured_products || []),
    ...(payload.deal_of_the_day || []),
    ...(payload.new_arrivals || []),
    ...(payload.imported_products || [])
  ];
  const suggestionIndex = [];
  const seenSuggestionKeys = new Set();

  searchableProducts.forEach((product) => {
    const key = `product:${product.slug}`;
    if (seenSuggestionKeys.has(key)) return;
    seenSuggestionKeys.add(key);
    suggestionIndex.push({
      type: "Product",
      title: product.name,
      subtitle: `${product.category?.name || product.tag || "Marketplace listing"} · ${formatPrice(product.price)}`,
      value: product.name,
    });
  });
  (payload.categories || []).forEach((category) => {
    const key = `category:${category.slug}`;
    if (seenSuggestionKeys.has(key)) return;
    seenSuggestionKeys.add(key);
    suggestionIndex.push({
      type: "Category",
      title: category.name,
      subtitle: category.description || category.banner_title || "Browse a curated category collection",
      value: category.name,
    });
  });

  function hideSearchSuggestions() {
    if (!suggestionNode) return;
    suggestionNode.hidden = true;
    suggestionNode.innerHTML = "";
    if (searchInput) searchInput.setAttribute("aria-expanded", "false");
  }

  function showSearchSuggestions() {
    if (!suggestionNode || !searchInput) return;
    const query = searchInput.value.trim().toLowerCase();
    if (!query) {
      hideSearchSuggestions();
      return;
    }
    const suggestions = suggestionIndex
      .filter((item) => item.title.toLowerCase().includes(query) || item.subtitle.toLowerCase().includes(query))
      .slice(0, 6);

    if (!suggestions.length) {
      suggestionNode.hidden = false;
      suggestionNode.innerHTML = `<div class="search-suggestion-empty">No close matches yet. Try a product name, a category, or a simpler keyword.</div>`;
      searchInput.setAttribute("aria-expanded", "true");
      return;
    }

    suggestionNode.hidden = false;
    suggestionNode.innerHTML = suggestions.map((item) => `
      <button type="button" class="search-suggestion-item" data-search-value="${escapeHtml(item.value)}">
        <div class="search-suggestion-top">
          <span class="search-suggestion-title">${escapeHtml(item.title)}</span>
          <span class="search-suggestion-type">${escapeHtml(item.type)}</span>
        </div>
        <span class="search-suggestion-meta">${escapeHtml(item.subtitle)}</span>
      </button>
    `).join("");
    searchInput.setAttribute("aria-expanded", "true");
    suggestionNode.querySelectorAll("[data-search-value]").forEach((button) => {
      button.addEventListener("click", async () => {
        searchInput.value = button.dataset.searchValue || "";
        hideSearchSuggestions();
        state.activeCategory = "";
        await runCatalogSearch();
        document.getElementById("collection")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  function syncQuickFilterState() {
    const minValue = document.getElementById("catalogMinPrice")?.value || "";
    const maxValue = document.getElementById("catalogMaxPrice")?.value || "";
    const stockChecked = Boolean(document.getElementById("catalogInStock")?.checked);
    quickFilterButtons.forEach((button) => {
      const matchesPrice = (button.dataset.min || "") === minValue && (button.dataset.max || "") === maxValue;
      const matchesStock = button.dataset.stock === "true" && stockChecked;
      button.classList.toggle("is-active", matchesPrice || matchesStock);
    });
  }

  if (searchForm) {
    searchForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      hideSearchSuggestions();
      if (searchInput?.value.trim()) {
        state.activeCategory = "";
      }
      await runCatalogSearch();
      document.getElementById("collection")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
  if (searchInput) {
    searchInput.setAttribute("enterkeyhint", "search");
    searchInput.addEventListener("input", showSearchSuggestions);
    searchInput.addEventListener("focus", showSearchSuggestions);
    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") hideSearchSuggestions();
    });
  }
  if (sortSelect) sortSelect.addEventListener("change", runCatalogSearch);
  if (applyFiltersButton) applyFiltersButton.addEventListener("click", runCatalogSearch);
  quickFilterButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      const minNode = document.getElementById("catalogMinPrice");
      const maxNode = document.getElementById("catalogMaxPrice");
      const stockNode = document.getElementById("catalogInStock");
      if (minNode) minNode.value = button.dataset.min || "";
      if (maxNode) maxNode.value = button.dataset.max || "";
      if (stockNode) stockNode.checked = button.dataset.stock === "true";
      syncQuickFilterState();
      await runCatalogSearch();
    });
  });

  if (resetButton) {
    resetButton.addEventListener("click", () => {
      state.activeCategory = "";
      if (searchInput) searchInput.value = "";
      hideSearchSuggestions();
      if (sortSelect) sortSelect.value = "featured";
      const minNode = document.getElementById("catalogMinPrice");
      const maxNode = document.getElementById("catalogMaxPrice");
      const stockNode = document.getElementById("catalogInStock");
      if (minNode) minNode.value = "";
      if (maxNode) maxNode.value = "";
      if (stockNode) stockNode.checked = false;
      syncQuickFilterState();
      renderProductCollection("productGrid", payload.featured_products);
      const notFound = document.getElementById("notFound");
      if (notFound) {
        notFound.hidden = true;
        notFound.style.display = "none";
      }
      setStatus(document.getElementById("catalogMessage"), "Showing featured products.", "neutral");
    });
  }

  document.addEventListener("click", (event) => {
    if (!suggestionNode || !searchForm) return;
    if (searchForm.contains(event.target) || suggestionNode.contains(event.target)) return;
    hideSearchSuggestions();
  });

  syncQuickFilterState();
  if (usedFallback && loadMessage) {
    setStatus(catalogMessageNode, loadMessage, "error");
  } else if (!hasAnyHomeProducts(payload)) {
    setStatus(catalogMessageNode, loadMessage || "Catalog sync is still in progress. Products will appear shortly.", "error");
  }
}

async function renderProductPage() {
  const slug = new URLSearchParams(window.location.search).get("slug");
  const productView = document.getElementById("productView");
  const missingState = document.getElementById("missingProduct");
  if (!slug) {
    if (productView) productView.hidden = true;
    if (missingState) missingState.hidden = false;
    return;
  }

  try {
    await loadWishlistIds();
    const product = await apiFetch(`/products/${slug}`);
    state.currentProduct = product;
    state.productMap.set(product.id, product);
    if (productView) productView.hidden = false;
    if (missingState) missingState.hidden = true;

    document.title = `${product.name} - SwiftCart`;
    setImageSourceWithFallback(document.getElementById("productImage"), sanitizeUrl(product.image, "images/swift.png"), "images/swift.png");
    document.getElementById("productImage").alt = product.name;
    document.getElementById("productName").textContent = product.name;
    document.getElementById("productTag").textContent = product.tag;
    document.getElementById("productPrice").textContent = formatPrice(product.price);
    const productOriginalPrice = document.getElementById("productOriginalPrice");
    const productDiscount = document.getElementById("productDiscount");
    if (hasVisibleDiscount(product)) {
      productOriginalPrice.textContent = formatPrice(product.original_price);
      productDiscount.textContent = `${getVisibleDiscountPercent(product)}% off`;
      productOriginalPrice.hidden = false;
      productDiscount.hidden = false;
    } else {
      productOriginalPrice.textContent = "";
      productDiscount.textContent = "";
      productOriginalPrice.hidden = true;
      productDiscount.hidden = true;
    }
    document.getElementById("productRating").innerHTML = `${renderStars(product.rating)}<strong class="rating-value">${product.rating.toFixed(1)}</strong>`;
    document.getElementById("productReviews").textContent = `${product.reviews_count} reviews`;
    document.getElementById("productDescription").textContent = product.description;
    document.getElementById("deliveryNote").textContent = product.delivery_note;
    const productStockStatus = document.getElementById("productStockStatus");
    if (productStockStatus) {
      productStockStatus.innerHTML = buildStockStatusMarkup(product);
    }
    const addToCartButton = document.getElementById("addToCartButton");
    const buyNowButton = document.getElementById("buyNowButton");
    const isUnavailable = isProductOutOfStock(product);
    if (addToCartButton) {
      addToCartButton.disabled = isUnavailable;
      addToCartButton.textContent = isUnavailable ? "Out of Stock" : "Add to Cart";
    }
    if (buyNowButton) {
      buyNowButton.disabled = isUnavailable;
      buyNowButton.textContent = isUnavailable ? "Unavailable" : "Buy Now";
    }
    if (isUnavailable) {
      setStatus(document.getElementById("productFeedback"), "This product is currently out of stock.", "error");
    }

    const filteredHighlights = product.highlights.filter((item) => !/imported into catalog/i.test(String(item || "")));
    document.getElementById("productHighlights").innerHTML = filteredHighlights.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    document.getElementById("productSpecs").innerHTML = Object.entries(product.specifications)
      .map(([key, value]) => `<tr><td>${escapeHtml(key)}</td><td>${escapeHtml(value)}</td></tr>`)
      .join("");
    const specsPanel = document.getElementById("specificationsPanel");
    const specToggleButton = document.getElementById("specToggleButton");
    if (specToggleButton && specsPanel) {
      specToggleButton.addEventListener("click", () => {
        const willShow = specsPanel.hidden;
        specsPanel.hidden = !willShow;
        specToggleButton.textContent = willShow ? "Hide Full Specifications" : "Show Full Specifications";
      });
    }

    const reviewList = document.getElementById("reviewList");
    const currentUser = getStoredUser();
    reviewList.innerHTML = product.reviews.length
      ? product.reviews.map((review) => `
          <article class="review-card">
            <strong>${escapeHtml(review.title)}</strong>
            <span class="review-meta">${renderStars(review.rating)}<strong class="rating-value">${review.rating.toFixed(1)}</strong><span>by ${escapeHtml(review.author_name)}</span><span>${formatCompactDateTime(review.created_at)}</span></span>
            <p>${escapeHtml(review.comment)}</p>
            ${review.image ? `<img src="${escapeHtml(sanitizeUrl(review.image, "images/swift.png"))}" alt="${escapeHtml(review.title)}" class="review-image-card">` : ""}
            ${
              currentUser && review.author_user_id === currentUser.id
                ? `<div class="inline-actions"><button type="button" class="ghost-button delete-review-button" data-review-id="${review.id}">Delete My Review</button></div>`
                : ""
            }
          </article>
        `).join("")
      : "<p class=\"empty-copy\">No customer feedback has been shared for this product yet. Be the first verified shopper to leave a review.</p>";

    const reviewStarButtons = document.querySelectorAll(".review-star-button");
    const reviewRatingValue = document.getElementById("reviewRatingValue");
    const reviewImageInput = document.getElementById("reviewImageInput");
    const reviewImageData = document.getElementById("reviewImageData");
    const reviewImagePreview = document.getElementById("reviewImagePreview");

    function paintReviewStars(value) {
      reviewStarButtons.forEach((button) => {
        button.classList.toggle("active", Number(button.dataset.rating) <= value);
      });
    }

    paintReviewStars(Number(reviewRatingValue?.value || 0));
    reviewStarButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const value = Number(button.dataset.rating);
        if (reviewRatingValue) reviewRatingValue.value = String(value);
        paintReviewStars(value);
      });
    });

    reviewImageInput?.addEventListener("change", () => {
      const file = reviewImageInput.files?.[0];
      if (!file) {
        if (reviewImageData) reviewImageData.value = "";
        if (reviewImagePreview) reviewImagePreview.hidden = true;
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        if (reviewImageData) reviewImageData.value = String(reader.result || "");
        if (reviewImagePreview) {
          reviewImagePreview.src = String(reader.result || "");
          reviewImagePreview.hidden = false;
        }
      };
      reader.readAsDataURL(file);
    });

    renderProductCollection("relatedGrid", product.related_products);

    addToCartButton?.addEventListener("click", () => {
      if (isUnavailable) {
        setStatus(document.getElementById("productFeedback"), "This product is currently out of stock.", "error");
        return;
      }
      addProductToCart(product.id, 1);
      updateCartCount();
      setStatus(document.getElementById("productFeedback"), "Product added to cart.", "success");
    });

    const wishlistButton = document.getElementById("wishlistButton");
    if (wishlistButton) {
      wishlistButton.textContent = state.wishlistIds.has(product.id) ? "Saved in Wishlist" : "Add to Wishlist";
      wishlistButton.addEventListener("click", async () => {
        const user = getStoredUser();
        if (!user) {
          setStatus(document.getElementById("productFeedback"), "Login to save wishlist items.", "error");
          return;
        }
        try {
          await apiFetch(`/users/${user.id}/wishlist`, {
            method: "POST",
            body: JSON.stringify({ product_id: product.id })
          });
          state.wishlistIds.add(product.id);
          wishlistButton.textContent = "Saved in Wishlist";
          setStatus(document.getElementById("productFeedback"), "Added to wishlist.", "success");
        } catch (error) {
          setStatus(document.getElementById("productFeedback"), error.message, "error");
        }
      });
    }

    buyNowButton?.addEventListener("click", () => {
      if (isUnavailable) {
        setStatus(document.getElementById("productFeedback"), "This product is currently out of stock.", "error");
        return;
      }
      addProductToCart(product.id, 1);
      redirectToPage("Payment.html");
    });

    document.getElementById("deliveryCheckButton").addEventListener("click", () => {
      const pin = document.getElementById("pincodeInput").value.trim();
      if (!/^\d{6}$/.test(pin)) {
        setStatus(document.getElementById("deliveryMessage"), "Enter a valid 6-digit pincode.", "error");
        return;
      }
      const quick = pin.startsWith("56") || pin.startsWith("75");
      setStatus(
        document.getElementById("deliveryMessage"),
        quick ? "Delivery available in 1-3 business days." : "Delivery available in 3-6 business days.",
        "success"
      );
    });

    const savedPincodeButton = document.getElementById("useSavedPincodeButton");
    const savedPincodeLabel = document.getElementById("savedPincodeLabel");
    const defaultAddress = getDefaultAddress(currentUser);
    const pinInput = document.getElementById("pincodeInput");
    if (pinInput && defaultAddress?.pincode && !pinInput.value.trim()) {
      pinInput.value = defaultAddress.pincode;
    }
    if (savedPincodeLabel) {
      savedPincodeLabel.textContent = defaultAddress?.pincode ? `${defaultAddress.label || "Saved"} · ${defaultAddress.pincode}` : "No saved pincode yet";
    }
    if (savedPincodeButton) {
      savedPincodeButton.hidden = !defaultAddress?.pincode;
      savedPincodeButton.addEventListener("click", () => {
        if (!defaultAddress?.pincode) {
          setStatus(document.getElementById("deliveryMessage"), "Save an address on your account first to reuse its pincode here.", "error");
          return;
        }
        if (pinInput) pinInput.value = defaultAddress.pincode;
        setStatus(document.getElementById("deliveryMessage"), `Using saved pincode from ${defaultAddress.label || "your default address"}.`, "success");
      });
    }

    const reviewForm = document.getElementById("reviewForm");
    if (reviewForm) {
      bindAutoCapitalization([
        reviewForm.elements.author_name,
        reviewForm.elements.title
      ], "title");
      bindAutoCapitalization([reviewForm.elements.comment], "sentence");
      if (currentUser && reviewForm.elements.author_name && !reviewForm.elements.author_name.value) {
        reviewForm.elements.author_name.value = [currentUser.first_name, currentUser.last_name].filter(Boolean).join(" ").trim();
      }
      reviewForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(reviewForm).entries());
        if (currentUser) payload.user_id = currentUser.id;
        try {
          await apiFetch(`/products/${slug}/reviews`, {
            method: "POST",
            body: JSON.stringify(payload)
          });
          setStatus(document.getElementById("reviewStatus"), "Review submitted successfully. Refreshing...", "success");
          setTimeout(() => window.location.reload(), 500);
        } catch (error) {
          setStatus(document.getElementById("reviewStatus"), error.message, "error");
        }
      });
    }

    reviewList.querySelectorAll(".delete-review-button").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!currentUser) return;
        try {
          await apiFetch(`/products/${slug}/reviews/${button.dataset.reviewId}?user_id=${currentUser.id}`, {
            method: "DELETE"
          });
          setStatus(document.getElementById("reviewStatus"), "Your review was deleted successfully. Refreshing...", "success");
          setTimeout(() => window.location.reload(), 350);
        } catch (error) {
          setStatus(document.getElementById("reviewStatus"), error.message, "error");
        }
      });
    });
  } catch {
    if (productView) productView.hidden = true;
    if (missingState) missingState.hidden = false;
  }
}

function addProductToCart(productId, quantity) {
  const cart = getCart();
  const existing = cart.find((item) => item.product_id === productId);
  if (existing) {
    existing.quantity += quantity;
  } else {
    cart.push({ product_id: productId, quantity });
  }
  saveCart(cart);
}

async function loadProductsForCart() {
  const products = await apiFetch("/products");
  products.forEach((product) => state.productMap.set(product.id, product));
  return products;
}

async function renderCartPage() {
  await loadProductsForCart();
  const items = getCart()
    .map((item) => {
      const product = state.productMap.get(item.product_id);
      return product ? { ...product, quantity: item.quantity, total: product.price * item.quantity } : null;
    })
    .filter(Boolean);

  const emptyNode = document.getElementById("cartEmpty");
  const listNode = document.getElementById("cartItems");
  const subtotalNode = document.getElementById("cartSubtotal");
  const totalNode = document.getElementById("cartTotal");
  const savingsNode = document.getElementById("cartSavings");
  const summaryMetaNode = document.getElementById("cartSummaryMeta");
  const checkoutStatusNode = document.getElementById("cartCheckoutStatus");
  const checkoutButton = document.getElementById("cartCheckoutButton");
  const fixIssuesButton = document.getElementById("cartFixIssuesButton");
  const suggestionNode = document.getElementById("cartSuggestions");
  const summary = calculateCartSummary(items);

  if (!items.length) {
    if (emptyNode) {
      emptyNode.hidden = false;
      emptyNode.style.display = "grid";
    }
    if (listNode) listNode.innerHTML = "";
    if (subtotalNode) subtotalNode.textContent = formatPrice(0);
    if (totalNode) totalNode.textContent = formatPrice(0);
    if (savingsNode) savingsNode.textContent = formatPrice(0);
    if (summaryMetaNode) summaryMetaNode.innerHTML = "";
    if (checkoutStatusNode) setStatus(checkoutStatusNode, "Add products to your cart to continue to payment.", "neutral");
    if (checkoutButton) checkoutButton.disabled = true;
    if (fixIssuesButton) fixIssuesButton.disabled = true;
    if (suggestionNode) suggestionNode.innerHTML = "";
    return;
  }

  if (emptyNode) {
    emptyNode.hidden = true;
    emptyNode.style.display = "none";
  }
  listNode.innerHTML = items.map((item) => `
    <article class="cart-item">
      <img src="${escapeHtml(sanitizeUrl(item.image, "images/swift.png"))}" alt="${escapeHtml(item.name)}">
      <div class="cart-item-info">
        <h3>${escapeHtml(item.name)}</h3>
        <p>${escapeHtml(item.description)}</p>
        <div class="cart-stock-row">${buildStockStatusMarkup(item)}</div>
        <div class="cart-item-meta">
          <div class="quantity-controls">
            <button class="ghost-button qty-action" data-action="decrease" data-product-id="${item.id}" type="button">-</button>
            <span>Qty: ${item.quantity}</span>
            <button class="ghost-button qty-action" data-action="increase" data-product-id="${item.id}" type="button" ${item.quantity >= Number(item.stock || 0) ? "disabled" : ""}>+</button>
          </div>
          <strong>${formatPrice(item.total)}</strong>
        </div>
        <div class="inline-actions">
          <a class="product-link" href="${escapeHtml(buildProductHref(item.slug))}">View Product</a>
          <button class="ghost-button remove-cart-item" data-product-id="${item.id}" type="button">Remove</button>
        </div>
      </div>
    </article>
  `).join("");

  subtotalNode.textContent = formatPrice(summary.subtotal);
  totalNode.textContent = formatPrice(summary.subtotal + 50);
  if (savingsNode) savingsNode.textContent = formatPrice(summary.savings);
  if (summaryMetaNode) {
    summaryMetaNode.innerHTML = [
      `${summary.uniqueItems} listing${summary.uniqueItems === 1 ? "" : "s"}`,
      `${summary.itemCount} total item${summary.itemCount === 1 ? "" : "s"}`,
      summary.unavailableItems.length ? `${summary.unavailableItems.length} need attention` : "Ready for checkout"
    ].map((entry) => `<span class="summary-meta-chip">${escapeHtml(entry)}</span>`).join("");
  }
  if (checkoutStatusNode) {
    setStatus(
      checkoutStatusNode,
      summary.unavailableItems.length
        ? "Some items are out of stock or exceed available quantity. Fix them before checkout."
        : `You are saving ${formatPrice(summary.savings)} on this basket right now.`,
      summary.unavailableItems.length ? "error" : "success"
    );
  }
  if (checkoutButton) checkoutButton.disabled = summary.unavailableItems.length > 0;
  if (fixIssuesButton) fixIssuesButton.disabled = summary.unavailableItems.length === 0;

  listNode.querySelectorAll(".qty-action").forEach((button) => {
    button.addEventListener("click", () => {
      const productId = Number(button.dataset.productId);
      const current = getCart().find((entry) => entry.product_id === productId);
      if (!current) return;
      const product = state.productMap.get(productId);
      if (button.dataset.action === "increase" && current.quantity >= Number(product?.stock || 0)) {
        return;
      }
      const nextQuantity = button.dataset.action === "increase" ? current.quantity + 1 : current.quantity - 1;
      updateCartItemQuantity(productId, nextQuantity);
      updateCartCount();
      renderCartPage();
    });
  });

  listNode.querySelectorAll(".remove-cart-item").forEach((button) => {
    button.addEventListener("click", () => {
      removeCartItem(Number(button.dataset.productId));
      updateCartCount();
      renderCartPage();
    });
  });

  if (suggestionNode) {
    const categoryIds = new Set(items.map((item) => item.category.id));
    const inCartIds = new Set(items.map((item) => item.id));
    const primarySuggestions = Array.from(state.productMap.values())
      .filter((product) => !inCartIds.has(product.id) && categoryIds.has(product.category.id) && !isProductOutOfStock(product))
      .slice(0, 6);
    const suggestionIds = new Set(primarySuggestions.map((product) => product.id));
    const fallbackSuggestions = Array.from(state.productMap.values())
      .filter((product) => !inCartIds.has(product.id) && !suggestionIds.has(product.id) && !isProductOutOfStock(product))
      .sort((left, right) => right.rating - left.rating)
      .slice(0, Math.max(0, 6 - primarySuggestions.length));
    const suggestions = [...primarySuggestions, ...fallbackSuggestions];
    renderProductCollection("cartSuggestions", suggestions);
  }

  fixIssuesButton?.addEventListener("click", () => {
    const nextCart = getCart().flatMap((entry) => {
      const product = state.productMap.get(entry.product_id);
      if (!product || isProductOutOfStock(product)) return [];
      return [{ product_id: entry.product_id, quantity: Math.min(entry.quantity, Number(product.stock || 0)) }];
    });
    saveCart(nextCart);
    updateCartCount();
    renderCartPage();
  });

  checkoutButton?.addEventListener("click", () => {
    if (summary.unavailableItems.length) {
      setStatus(checkoutStatusNode, "Resolve cart issues before continuing to payment.", "error");
      return;
    }
    redirectToPage("Payment.html");
  });
}

async function renderPaymentPage() {
  await loadProductsForCart();
  const user = getStoredUser();
  let selectedAddressId = null;
  const items = getCart()
    .map((item) => {
      const product = state.productMap.get(item.product_id);
      return product ? { ...product, quantity: item.quantity, total: product.price * item.quantity } : null;
    })
    .filter(Boolean);

  const summaryList = document.getElementById("paymentItems");
  const subtotalNode = document.getElementById("paymentSubtotal");
  const totalNode = document.getElementById("paymentTotal");
  const savingsNode = document.getElementById("paymentSavings");
  const summaryMetaNode = document.getElementById("paymentSummaryMeta");
  const payButton = document.getElementById("payNowButton");
  const paymentStatus = document.getElementById("paymentStatus");
  const checkoutTrustList = document.getElementById("checkoutTrustList");
  const typeInputs = document.querySelectorAll("input[name='checkoutType']");
  const merchantFields = document.getElementById("merchantFields");
  const paymentMethodSelect = document.getElementById("paymentMethodSelect");
  const logoSlot = document.getElementById("paymentLogoCodeSlot");
  const paymentQrPanel = document.getElementById("paymentQrPanel");
  const savedAddressesNode = document.getElementById("savedDeliveryAddresses");
  const selectedAddressStatus = document.getElementById("selectedAddressStatus");
  const customLogoHtml = typeof window.SWIFTCART_PAYMENT_LOGO_HTML === "string" ? window.SWIFTCART_PAYMENT_LOGO_HTML : "";
  const summary = calculateCartSummary(items);

  if (logoSlot && customLogoHtml) {
    logoSlot.innerHTML = customLogoHtml;
  }

  if (checkoutTrustList) {
    checkoutTrustList.innerHTML = [
      "Saved addresses can be reused instantly.",
      "Live stock validation runs before order placement.",
      "UPI, card, banking, COD, and EMI flows are ready.",
      "Order tracking and cancellation remain available after checkout."
    ].map((entry) => `<span class="summary-meta-chip">${escapeHtml(entry)}</span>`).join("");
  }

  if (user) {
    const addresses = sortAddresses(user.addresses || []);
    const defaultAddress = getDefaultAddress(user);
    selectedAddressId = defaultAddress?.id || null;
    const fullName = [user.first_name, user.last_name].filter(Boolean).join(" ").trim();
    const nameNode = document.getElementById("billingName");
    const emailNode = document.getElementById("billingEmail");
    const mobileNode = document.getElementById("billingMobile");
    const streetNode = document.getElementById("billingStreet");
    const cityNode = document.getElementById("billingCity");
    const stateNode = document.getElementById("billingState");
    const pincodeNode = document.getElementById("billingPincode");
    if (nameNode && !nameNode.value) nameNode.value = fullName;
    if (emailNode && !emailNode.value) emailNode.value = user.email || "";
    if (mobileNode && !mobileNode.value) mobileNode.value = formatPhoneDisplay(user.mobile || "");
    fillAddressFields(defaultAddress, {
      street: streetNode,
      city: cityNode,
      state: stateNode,
      pincode: pincodeNode,
    });

    if (savedAddressesNode) {
      savedAddressesNode.innerHTML = addresses.length
        ? addresses.map((address) => `
            <article class="saved-delivery-address${address.id === selectedAddressId ? " is-selected" : ""}" data-address-id="${address.id}">
              <div class="saved-delivery-top">
                <strong class="saved-delivery-label">${escapeHtml(address.label || "Saved Address")}</strong>
                <span class="saved-delivery-chip${address.is_default ? " is-default" : ""}">${address.is_default ? "Default" : "Saved"}</span>
              </div>
              <div class="saved-delivery-meta">${escapeHtml(formatAddressSummary(address))}</div>
              <div class="saved-delivery-meta">${escapeHtml(address.landmark || "Ready to use for checkout")}</div>
            </article>
          `).join("")
        : "<p class=\"empty-copy\">Save a delivery address on your account to reuse it here.</p>";
      if (selectedAddressStatus && defaultAddress) {
        setStatus(selectedAddressStatus, `${defaultAddress.label || "Default address"} is selected for this order.`, "neutral");
      }
      savedAddressesNode.querySelectorAll("[data-address-id]").forEach((node) => {
        node.addEventListener("click", () => {
          const nextId = Number(node.dataset.addressId);
          const selectedAddress = addresses.find((item) => item.id === nextId);
          if (!selectedAddress) return;
          selectedAddressId = nextId;
          fillAddressFields(selectedAddress, {
            street: streetNode,
            city: cityNode,
            state: stateNode,
            pincode: pincodeNode,
          });
          savedAddressesNode.querySelectorAll(".saved-delivery-address").forEach((card) => {
            card.classList.toggle("is-selected", Number(card.dataset.addressId) === nextId);
          });
          setStatus(selectedAddressStatus, `${selectedAddress.label || "Saved address"} selected for this checkout.`, "success");
        });
      });
    }
  }

  function syncCheckoutType() {
    const selected = document.querySelector("input[name='checkoutType']:checked")?.value || "normal";
    if (merchantFields) merchantFields.hidden = selected !== "merchant";
  }

  function syncPaymentMode() {
    const method = paymentMethodSelect?.value || "UPI / Card";
    if (paymentQrPanel) {
      paymentQrPanel.hidden = !method.includes("UPI");
    }
  }

  typeInputs.forEach((input) => input.addEventListener("change", syncCheckoutType));
  syncCheckoutType();
  paymentMethodSelect?.addEventListener("change", syncPaymentMode);
  syncPaymentMode();

  if (!items.length) {
    summaryList.innerHTML = "<p class=\"empty-copy\">Your cart is empty. Add products before checkout.</p>";
    subtotalNode.textContent = formatPrice(0);
    totalNode.textContent = formatPrice(0);
    if (savingsNode) savingsNode.textContent = formatPrice(0);
    if (summaryMetaNode) summaryMetaNode.innerHTML = "";
    payButton.disabled = true;
    return;
  }

  const unavailableItems = items.filter((item) => isProductOutOfStock(item) || item.quantity > Number(item.stock || 0));
  summaryList.innerHTML = items.map((item) => `
    <div class="summary-item">
      <img src="${escapeHtml(sanitizeUrl(item.image, "images/swift.png"))}" alt="${escapeHtml(item.name)}">
      <div>
        <p>${escapeHtml(item.name)}</p>
        <small>Qty ${item.quantity}</small>
        <small>${escapeHtml(item.stock_status || "In Stock")}${Number(item.stock || 0) > 0 ? ` · ${item.stock} left` : ""}</small>
      </div>
      <strong>${formatPrice(item.total)}</strong>
    </div>
  `).join("");
  subtotalNode.textContent = formatPrice(summary.subtotal);
  totalNode.textContent = formatPrice(summary.subtotal + 50);
  if (savingsNode) savingsNode.textContent = formatPrice(summary.savings);
  if (summaryMetaNode) {
    summaryMetaNode.innerHTML = [
      `${summary.uniqueItems} listing${summary.uniqueItems === 1 ? "" : "s"}`,
      `${summary.itemCount} item${summary.itemCount === 1 ? "" : "s"}`,
      summary.savings > 0 ? `${formatPrice(summary.savings)} saved` : "Best live price applied"
    ].map((entry) => `<span class="summary-meta-chip">${escapeHtml(entry)}</span>`).join("");
  }
  if (unavailableItems.length) {
    payButton.disabled = true;
    setStatus(paymentStatus, "One or more items are out of stock or exceed the available stock. Update your cart to continue.", "error");
  } else {
    payButton.disabled = false;
    setStatus(paymentStatus, `Secure checkout ready. Current savings: ${formatPrice(summary.savings)}.`, "success");
  }

  payButton.addEventListener("click", async () => {
    if (!user) {
      setStatus(paymentStatus, "Please login before placing an order.", "error");
      return;
    }
    if (unavailableItems.length) {
      setStatus(paymentStatus, "Some items in this checkout are no longer available in the requested quantity.", "error");
      return;
    }

    const checkoutType = document.querySelector("input[name='checkoutType']:checked")?.value || "normal";
    const merchantProfile = {
      business_name: document.getElementById("merchantBusinessName")?.value.trim() || "",
      gstin: document.getElementById("merchantGstin")?.value.trim() || "",
      contact_role: document.getElementById("merchantContactRole")?.value.trim() || ""
    };

    if (checkoutType === "merchant" && (!merchantProfile.business_name || !merchantProfile.gstin)) {
      setStatus(paymentStatus, "Merchant checkout needs business name and GSTIN.", "error");
      return;
    }

    const requiredBilling = {
      name: document.getElementById("billingName")?.value.trim() || "",
      email: document.getElementById("billingEmail")?.value.trim() || "",
      mobile: normalizePhoneInput(document.getElementById("billingMobile")?.value || ""),
      street: document.getElementById("billingStreet")?.value.trim() || "",
      city: document.getElementById("billingCity")?.value.trim() || "",
      state: document.getElementById("billingState")?.value.trim() || "",
      pincode: document.getElementById("billingPincode")?.value.trim() || "",
    };
    if (Object.values(requiredBilling).some((value) => !String(value).trim())) {
      setStatus(paymentStatus, "Fill every billing and delivery field before placing the order.", "error");
      return;
    }
    if (!/^\d{6}$/.test(requiredBilling.pincode)) {
      setStatus(paymentStatus, "Enter a valid 6-digit delivery pincode.", "error");
      return;
    }
    if ((paymentMethodSelect?.value || "").includes("Cash on Delivery") && summary.subtotal > 50000) {
      setStatus(paymentStatus, "Cash on Delivery is disabled for orders above ₹50,000. Choose another payment method.", "error");
      return;
    }

    const payload = {
      user_id: user.id,
      items: getCart(),
      customer_type: checkoutType,
      merchant_profile: merchantProfile,
      shipping_address: {
        street: document.getElementById("billingStreet").value || getDefaultAddress(user)?.street || "",
        city: document.getElementById("billingCity").value || getDefaultAddress(user)?.city || "",
        state: document.getElementById("billingState").value || getDefaultAddress(user)?.state || "",
        pincode: document.getElementById("billingPincode").value || getDefaultAddress(user)?.pincode || "",
        address_id: selectedAddressId,
      },
      payment_method: paymentMethodSelect?.value || "UPI / Card"
    };

    try {
      payButton.disabled = true;
      const overlay = showPaymentProcessingOverlay();
      const response = await apiFetch("/orders/checkout", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      overlay.remove();
      saveCart([]);
      updateCartCount();
      setStatus(paymentStatus, `Order #${response.order.id} placed successfully.`, "success");
      setTimeout(() => {
        redirectToPage("Orders.html");
      }, 1000);
    } catch (error) {
      setStatus(paymentStatus, error.message, "error");
    } finally {
      document.getElementById("paymentProcessingOverlay")?.remove();
      payButton.disabled = false;
    }
  });
}

async function handleRegistration() {
  const form = document.getElementById("registerForm");
  if (!form) return;

  const otpStatus = document.getElementById("otpStatus");
  const registerStatus = document.getElementById("registerStatus");
  const sendOtpButton = document.getElementById("sendOtpButton");
  const verifyOtpButton = document.getElementById("verifyOtpButton");
  const otpSessionIdInput = document.getElementById("otpSessionId");
  const otpCodeInput = document.getElementById("otpCodeInput");
  const sellerFields = document.getElementById("sellerFields");

  bindAutoCapitalization([
    form.elements.first_name,
    form.elements.last_name,
    form.elements.city,
    form.elements.state,
    form.elements.landmark,
    form.elements.shop_name
  ], "title");
  bindAutoCapitalization([form.elements.street], "sentence");

  function syncAccountTypeUi() {
    const accountType = form.querySelector("input[name='account_type']:checked")?.value || "buyer";
    if (sellerFields) sellerFields.hidden = accountType !== "merchant" && accountType !== "seller";
  }

  form.querySelectorAll("input[name='account_type']").forEach((input) => {
    input.addEventListener("change", syncAccountTypeUi);
  });
  syncAccountTypeUi();

  function getOtpIdentity() {
    const formData = new FormData(form);
    return {
      email: String(formData.get("email") || "").trim(),
      mobile: normalizePhoneInput(formData.get("mobile")),
      purpose: "register"
    };
  }

  sendOtpButton?.addEventListener("click", async () => {
    const identity = getOtpIdentity();
    if (!identity.email || !identity.mobile) {
      setStatus(otpStatus, "Enter your email and mobile number first.", "error");
      return;
    }

    try {
      const response = await apiFetch("/auth/request-otp", {
        method: "POST",
        body: JSON.stringify(identity)
      });
      otpSessionIdInput.value = response.otp_session_id;
      state.registerOtpVerified = false;
      setStatus(
        otpStatus,
        response.otp_preview
          ? `OTP sent. Demo OTP for local testing: ${response.otp_preview}`
          : "OTP sent successfully. Check your verification channel and enter the code here.",
        "success"
      );
      startCooldown(sendOtpButton, 30, (remaining) => {
        sendOtpButton.textContent = remaining ? `Resend OTP in ${remaining}s` : "Send OTP";
      });
    } catch (error) {
      setStatus(otpStatus, error.message, "error");
    }
  });

  verifyOtpButton?.addEventListener("click", async () => {
    if (!otpSessionIdInput.value) {
      setStatus(otpStatus, "Request an OTP first.", "error");
      return;
    }
    if (!otpCodeInput.value.trim()) {
      setStatus(otpStatus, "Enter the 6-digit OTP.", "error");
      return;
    }
    try {
      await apiFetch("/auth/verify-otp", {
        method: "POST",
        body: JSON.stringify({
          otp_session_id: Number(otpSessionIdInput.value),
          otp_code: otpCodeInput.value.trim()
        })
      });
      state.registerOtpVerified = true;
      setStatus(otpStatus, "OTP verified successfully. You can create the account now.", "success");
    } catch (error) {
      state.registerOtpVerified = false;
      setStatus(otpStatus, error.message, "error");
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.mobile = normalizePhoneInput(payload.mobile);

    if (payload.password !== payload.confirm_password) {
      setStatus(registerStatus, "Passwords do not match.", "error");
      return;
    }
    if (!payload.otp_session_id || !state.registerOtpVerified) {
      setStatus(registerStatus, "Please send and verify the OTP before creating the account.", "error");
      return;
    }

    try {
      const response = await apiFetch("/auth/register", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      saveStoredUser(response.user);
      setStatus(registerStatus, "Account created successfully. Redirecting to your account...", "success");
      setTimeout(() => {
        redirectToPage(response.user.is_owner ? "Admin.html" : isMerchantUser(response.user) ? "Merchant.html" : "Account_Details.html");
      }, 900);
    } catch (error) {
      setStatus(registerStatus, error.message, "error");
    }
  });
}

async function handleLogin() {
  const form = document.getElementById("loginForm");
  if (!form) return;
  const loginStatusNode = document.getElementById("loginStatus");
  const sendLoginOtpButton = document.getElementById("sendLoginOtpButton");
  const verifyLoginOtpButton = document.getElementById("verifyLoginOtpButton");
  const loginOtpInput = document.getElementById("loginOtpInput");
  const loginOtpStatus = document.getElementById("loginOtpStatus");
  const loginEmail = document.getElementById("loginEmail");
  const loginMobile = document.getElementById("loginMobile");
  const loginAccountSelect = document.getElementById("loginAccountSelect");
  const loginLinkedAccountsBox = document.getElementById("loginLinkedAccountsBox");
  const recoveryEmail = document.getElementById("recoveryEmail");
  const recoveryMobile = document.getElementById("recoveryMobile");
  const sendRecoveryOtpButton = document.getElementById("sendRecoveryOtpButton");
  const verifyRecoveryOtpButton = document.getElementById("verifyRecoveryOtpButton");
  const recoveryOtpInput = document.getElementById("recoveryOtpInput");
  const recoveryNewPassword = document.getElementById("recoveryNewPassword");
  const recoveryConfirmPassword = document.getElementById("recoveryConfirmPassword");
  const recoveryStatus = document.getElementById("recoveryStatus");
  const recoveryAccountSelect = document.getElementById("recoveryAccountSelect");
  const recoveryLinkedAccountsBox = document.getElementById("recoveryLinkedAccountsBox");
  const forgotPasswordToggle = document.getElementById("forgotPasswordToggle");
  const recoveryPanel = document.getElementById("recoveryPanel");
  const captchaPrompt = document.getElementById("captchaPrompt");
  const captchaAnswer = document.getElementById("captchaAnswer");
  const captchaCheckbox = document.getElementById("captchaCheckbox");
  const refreshCaptchaButton = document.getElementById("refreshCaptchaButton");
  let captchaSessionId = "";
  const authFlashMessage = consumeAuthFlashMessage();
  if (authFlashMessage) {
    setStatus(loginStatusNode, authFlashMessage, "error");
  }

  const loadCaptcha = async () => {
    try {
      const response = await apiFetch("/auth/captcha");
      captchaSessionId = response.captcha_id;
      if (captchaPrompt) captchaPrompt.textContent = response.prompt;
      if (captchaAnswer) captchaAnswer.value = "";
      if (captchaCheckbox) captchaCheckbox.checked = false;
      if (!authFlashMessage) {
        setStatus(loginStatusNode, "", "neutral");
      }
    } catch (error) {
      if (captchaPrompt) captchaPrompt.textContent = "Verification unavailable. Refresh and try again.";
      setStatus(loginStatusNode, error.message, "error");
    }
  };

  const buildCaptchaPayload = () => ({
    captcha_id: captchaSessionId,
    captcha_answer: captchaAnswer?.value.trim() || ""
  });

  const ensureCaptchaReady = (statusNode) => {
    if (!captchaSessionId) {
      setStatus(statusNode, "Refresh the human verification challenge first.", "error");
      return false;
    }
    if (!captchaCheckbox?.checked) {
      setStatus(statusNode, "Confirm that you are a real shopper before continuing.", "error");
      return false;
    }
    if (!captchaAnswer?.value.trim()) {
      setStatus(statusNode, "Enter the human verification answer first.", "error");
      return false;
    }
    return true;
  };

  refreshCaptchaButton?.addEventListener("click", loadCaptcha);
  loginEmail?.addEventListener("input", () => setStatus(loginStatusNode, "", "neutral"));
  form.elements.password?.addEventListener("input", () => setStatus(loginStatusNode, "", "neutral"));
  captchaAnswer?.addEventListener("input", () => setStatus(loginStatusNode, "", "neutral"));
  captchaCheckbox?.addEventListener("change", () => setStatus(loginStatusNode, "", "neutral"));
  loadCaptcha();

  forgotPasswordToggle?.addEventListener("click", () => {
    if (!recoveryPanel) return;
    recoveryPanel.hidden = !recoveryPanel.hidden;
    forgotPasswordToggle.textContent = recoveryPanel.hidden ? "Forgot password?" : "Hide password recovery";
    if (!recoveryPanel.hidden) {
      recoveryPanel.scrollIntoView({ behavior: "smooth", block: "start" });
      recoveryEmail?.focus();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("loginStatus");
    if (!ensureCaptchaReady(status)) return;
    const payload = Object.fromEntries(new FormData(form).entries());
    Object.assign(payload, buildCaptchaPayload());

    try {
      const response = await apiFetch("/auth/login", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      saveStoredUser(response.user);
      setStatus(status, "Login successful. Redirecting...", "success");
      setTimeout(() => {
        redirectToPage(response.user.is_owner ? "Admin.html" : isMerchantUser(response.user) ? "Merchant.html" : "Account_Details.html");
      }, 700);
    } catch (error) {
      setStatus(status, error.message, "error");
      loadCaptcha();
    }
  });

  sendLoginOtpButton?.addEventListener("click", async () => {
    const email = loginEmail.value.trim();
    const mobile = normalizePhoneInput(loginMobile?.value) || "";
    if (!email && !mobile) {
      setStatus(loginOtpStatus, "Enter email or mobile number first.", "error");
      return;
    }
    if (!ensureCaptchaReady(loginOtpStatus)) return;

    try {
      const response = await apiFetch("/auth/request-otp", {
        method: "POST",
        body: JSON.stringify({
          email,
          mobile,
          purpose: "login",
          ...buildCaptchaPayload()
        })
      });
      state.loginOtpSessionId = response.otp_session_id;
      state.loginOtpAccounts = response.linked_accounts || [];
      if (loginAccountSelect && loginLinkedAccountsBox) {
        if (state.loginOtpAccounts.length > 1) {
          loginAccountSelect.innerHTML = state.loginOtpAccounts.map((account) => `
            <option value="${account.id}">${escapeHtml(`${account.full_name} · ${account.email} · ${account.unique_code}`)}</option>
          `).join("");
          loginLinkedAccountsBox.hidden = false;
        } else {
          loginLinkedAccountsBox.hidden = true;
          loginAccountSelect.innerHTML = "";
        }
      }
      setStatus(
        loginOtpStatus,
        response.otp_preview
          ? `Login OTP sent. Demo OTP for local testing: ${response.otp_preview}`
          : "Login OTP sent successfully. Check your verification channel and enter the code here.",
        "success"
      );
      loadCaptcha();
      startCooldown(sendLoginOtpButton, 30, (remaining) => {
        sendLoginOtpButton.textContent = remaining ? `Resend OTP in ${remaining}s` : "Send Login OTP";
      });
    } catch (error) {
      setStatus(loginOtpStatus, error.message, "error");
      loadCaptcha();
    }
  });

  verifyLoginOtpButton?.addEventListener("click", async () => {
    const email = loginEmail.value.trim();
    const mobile = normalizePhoneInput(loginMobile?.value) || "";
    if (!state.loginOtpSessionId) {
      setStatus(loginOtpStatus, "Request a login OTP first.", "error");
      return;
    }
    if (!loginOtpInput.value.trim()) {
      setStatus(loginOtpStatus, "Enter the OTP code.", "error");
      return;
    }

    try {
      await apiFetch("/auth/verify-otp", {
        method: "POST",
        body: JSON.stringify({
          otp_session_id: state.loginOtpSessionId,
          otp_code: loginOtpInput.value.trim()
        })
      });

      const response = await apiFetch("/auth/login-otp", {
        method: "POST",
        body: JSON.stringify({
          email,
          mobile,
          user_id: loginAccountSelect?.value ? Number(loginAccountSelect.value) : undefined,
          otp_session_id: state.loginOtpSessionId
        })
      });
      saveStoredUser(response.user);
      setStatus(loginOtpStatus, "OTP login successful. Redirecting...", "success");
      setTimeout(() => {
        redirectToPage(response.user.is_owner ? "Admin.html" : isMerchantUser(response.user) ? "Merchant.html" : "Account_Details.html");
      }, 700);
    } catch (error) {
      setStatus(loginOtpStatus, error.message, "error");
    }
  });

  sendRecoveryOtpButton?.addEventListener("click", async () => {
    const email = recoveryEmail?.value.trim() || "";
    const mobile = normalizePhoneInput(recoveryMobile?.value) || "";
    if (!email && !mobile) {
      setStatus(recoveryStatus, "Enter your recovery email or mobile number first.", "error");
      return;
    }
    if (!ensureCaptchaReady(recoveryStatus)) return;

    try {
      const response = await apiFetch("/auth/request-otp", {
        method: "POST",
        body: JSON.stringify({
          email,
          mobile,
          purpose: "recover",
          ...buildCaptchaPayload()
        })
      });
      state.recoveryOtpSessionId = response.otp_session_id;
      state.recoveryOtpAccounts = response.linked_accounts || [];
      if (recoveryAccountSelect && recoveryLinkedAccountsBox) {
        if (state.recoveryOtpAccounts.length > 1) {
          recoveryAccountSelect.innerHTML = state.recoveryOtpAccounts.map((account) => `
            <option value="${account.id}">${escapeHtml(`${account.full_name} · ${account.email} · ${account.unique_code}`)}</option>
          `).join("");
          recoveryLinkedAccountsBox.hidden = false;
        } else {
          recoveryLinkedAccountsBox.hidden = true;
          recoveryAccountSelect.innerHTML = "";
        }
      }
      setStatus(
        recoveryStatus,
        response.otp_preview
          ? `Recovery OTP sent. Demo OTP for local testing: ${response.otp_preview}`
          : "Recovery OTP sent successfully. Check your verification channel and enter the code here.",
        "success"
      );
      loadCaptcha();
      startCooldown(sendRecoveryOtpButton, 30, (remaining) => {
        sendRecoveryOtpButton.textContent = remaining ? `Resend OTP in ${remaining}s` : "Send Recovery OTP";
      });
    } catch (error) {
      setStatus(recoveryStatus, error.message, "error");
      loadCaptcha();
    }
  });

  verifyRecoveryOtpButton?.addEventListener("click", async () => {
    const email = recoveryEmail?.value.trim() || "";
    const mobile = normalizePhoneInput(recoveryMobile?.value) || "";
    if (!state.recoveryOtpSessionId) {
      setStatus(recoveryStatus, "Request a recovery OTP first.", "error");
      return;
    }
    if (!recoveryOtpInput?.value.trim()) {
      setStatus(recoveryStatus, "Enter the recovery OTP.", "error");
      return;
    }
    if (!recoveryNewPassword?.value || !recoveryConfirmPassword?.value) {
      setStatus(recoveryStatus, "Enter and confirm your new password.", "error");
      return;
    }

    try {
      await apiFetch("/auth/verify-otp", {
        method: "POST",
        body: JSON.stringify({
          otp_session_id: state.recoveryOtpSessionId,
          otp_code: recoveryOtpInput.value.trim()
        })
      });

      await apiFetch("/auth/reset-password-otp", {
        method: "POST",
        body: JSON.stringify({
          email,
          mobile,
          user_id: recoveryAccountSelect?.value ? Number(recoveryAccountSelect.value) : undefined,
          otp_session_id: state.recoveryOtpSessionId,
          new_password: recoveryNewPassword.value,
          confirm_password: recoveryConfirmPassword.value
        })
      });

      state.recoveryOtpSessionId = null;
      state.recoveryOtpAccounts = [];
      if (recoveryAccountSelect) recoveryAccountSelect.innerHTML = "";
      if (recoveryLinkedAccountsBox) recoveryLinkedAccountsBox.hidden = true;
      if (recoveryOtpInput) recoveryOtpInput.value = "";
      if (recoveryNewPassword) recoveryNewPassword.value = "";
      if (recoveryConfirmPassword) recoveryConfirmPassword.value = "";
      setStatus(recoveryStatus, "Password reset successful. You can now log in with the new password.", "success");
      if (forgotPasswordToggle) forgotPasswordToggle.textContent = "Forgot password?";
      if (recoveryPanel) recoveryPanel.hidden = true;
    } catch (error) {
      setStatus(recoveryStatus, error.message, "error");
    }
  });
}

async function renderAccountPage() {
  const user = getStoredUser();
  if (!user) {
    redirectToPage("Login.html");
    return;
  }

  let profile = mergedProfileData(user, null);
  let profileLoadError = "";
  try {
    profile = mergedProfileData(user, await apiFetch(`/users/${user.id}/profile`));
  } catch (error) {
    profileLoadError = error.message || "Profile details could not be refreshed.";
  }
  saveStoredUser(profile);
  syncUserUi();
  const photoPrefs = loadProfilePhotoPrefs(profile.id);

  document.querySelectorAll("[data-profile-name]").forEach((node) => { node.textContent = profile.full_name || profile.first_name || "Guest"; });
  document.querySelectorAll("[data-profile-first]").forEach((node) => { node.value = profile.first_name; });
  document.querySelectorAll("[data-profile-last]").forEach((node) => { node.value = profile.last_name; });
  document.querySelectorAll("[data-profile-email]").forEach((node) => { node.value = profile.email; });
  document.querySelectorAll("[data-profile-mobile]").forEach((node) => { node.value = formatPhoneDisplay(profile.mobile); });
  document.querySelectorAll("[data-profile-code]").forEach((node) => { node.value = profile.unique_code || ""; });
  document.querySelectorAll("[data-profile-joined]").forEach((node) => { node.value = formatCompactDateTime(profile.created_at); });
  document.querySelectorAll("[data-profile-last-login]").forEach((node) => { node.value = formatCompactDateTime(profile.last_login_at); });
  document.querySelectorAll("[data-profile-password-updated]").forEach((node) => { node.value = formatCompactDateTime(profile.password_changed_at); });
  document.querySelectorAll("[data-profile-last-device]").forEach((node) => { node.value = profile.last_login_device || "Not captured yet"; });
  document.querySelectorAll("[data-profile-last-browser]").forEach((node) => {
    node.value = [profile.last_login_browser, profile.last_login_platform].filter(Boolean).join(" on ") || "Not captured yet";
  });
  document.querySelectorAll("[data-profile-last-method]").forEach((node) => {
    node.value = profile.last_login_method ? toTitleCase(String(profile.last_login_method).replaceAll("_", " ")) : "Not captured yet";
  });
  document.querySelectorAll("[data-profile-last-ip]").forEach((node) => { node.value = profile.last_login_ip || "Not captured yet"; });
  document.querySelectorAll("[data-profile-role]").forEach((node) => {
    node.value = isMerchantUser(profile) ? "Merchant / Seller" : profile.is_owner ? "Owner" : "Normal Buyer";
  });
  document.querySelectorAll("[data-profile-shop]").forEach((node) => {
    node.value = profile.shop_name || "";
    node.closest(".card")?.classList.toggle("seller-card-active", Boolean(profile.shop_name || profile.gstin));
  });
  document.querySelectorAll("[data-profile-gstin]").forEach((node) => {
    node.value = profile.gstin || "";
  });
  document.querySelectorAll("[data-profile-avatar]").forEach((node) => {
    setImageSourceWithFallback(node, profile.profile_image, "images/swift.png");
  });
  const avatarStage = document.getElementById("profileAvatarStage");
  const shapeSelect = document.getElementById("profileShapeSelect");
  const zoomRange = document.getElementById("profileZoomRange");
  const focusRange = document.getElementById("profileFocusRange");
  const zoomValue = document.getElementById("profileZoomValue");
  const focusValue = document.getElementById("profileFocusValue");
  const removeProfilePhotoButton = document.getElementById("removeProfilePhotoButton");
  const profileImageInput = document.getElementById("profileImageInput");
  const profileFileName = document.getElementById("profileFileName");
  const applyPhotoPrefs = () => {
    const shape = shapeSelect?.value || photoPrefs.shape || "circle";
    const zoom = zoomRange?.value || String(photoPrefs.zoom || 1);
    const focus = focusRange?.value || String(photoPrefs.focus || 50);
    if (zoomValue) zoomValue.textContent = `${Math.round(Number(zoom) * 100)}%`;
    if (focusValue) focusValue.textContent = `${focus}%`;
    if (avatarStage) {
      avatarStage.classList.remove("profile-shape-circle", "profile-shape-rounded", "profile-shape-square");
      avatarStage.classList.add(`profile-shape-${shape}`);
      avatarStage.style.setProperty("--profile-zoom", String(zoom));
      avatarStage.style.setProperty("--profile-focus", `${focus}%`);
    }
    document.querySelectorAll("[data-profile-avatar]").forEach((node) => {
      if (!(node instanceof HTMLImageElement)) return;
      node.style.setProperty("--profile-zoom", String(zoom));
      node.style.setProperty("--profile-focus", `${focus}%`);
    });
    saveProfilePhotoPrefs(profile.id, { shape, zoom: Number(zoom), focus: Number(focus) });
  };
  if (shapeSelect && photoPrefs.shape) shapeSelect.value = photoPrefs.shape;
  if (zoomRange && photoPrefs.zoom) zoomRange.value = String(photoPrefs.zoom);
  if (focusRange && photoPrefs.focus) focusRange.value = String(photoPrefs.focus);
  shapeSelect?.addEventListener("change", applyPhotoPrefs);
  zoomRange?.addEventListener("input", applyPhotoPrefs);
  focusRange?.addEventListener("input", applyPhotoPrefs);
  applyPhotoPrefs();

  document.querySelectorAll("[data-owner-only]").forEach((node) => {
    node.hidden = !profile.is_owner;
  });
  document.querySelectorAll("[data-merchant-only]").forEach((node) => {
    node.hidden = !isMerchantUser(profile);
  });

  document.getElementById("logoutButton")?.addEventListener("click", () => {
    logoutCurrentUser();
  });

  const passwordForm = document.getElementById("passwordChangeForm");
  const passwordStatus = document.getElementById("passwordChangeStatus");
  const profileForm = document.getElementById("profileUpdateForm");
  const profileStatus = document.getElementById("profileUpdateStatus");
  const addressForm = document.getElementById("addressUpdateForm");
  const addressStatus = document.getElementById("addressStatus");
  const savedAddressesList = document.getElementById("savedAddressesList");
  const addressRecordId = document.getElementById("addressRecordId");
  const addressLabelInput = document.getElementById("addressLabel");
  const addressDefaultInput = document.getElementById("addressIsDefault");
  const createAddressButton = document.getElementById("createAddressButton");
  const addressResetButton = document.getElementById("addressResetButton");
  const profileImageForm = document.getElementById("profileImageForm");
  const profileImageStatus = document.getElementById("profileImageStatus");
  const profileSaveShortcut = document.getElementById("profileSaveShortcut");

  if (profileLoadError) {
    setStatus(profileStatus, `Loaded saved account details. Live profile refresh failed: ${profileLoadError}`, "error");
  }

  bindAutoCapitalization([
    profileForm?.elements?.first_name,
    profileForm?.elements?.last_name,
    document.querySelector("[data-profile-shop]")
  ], "title");
  bindAutoCapitalization([
    addressForm?.elements?.label,
    addressForm?.elements?.city,
    addressForm?.elements?.state,
    addressForm?.elements?.landmark
  ], "title");
  bindAutoCapitalization([addressForm?.elements?.street], "sentence");

  if (profileForm) profileForm.onsubmit = async (event) => {
    event.preventDefault();
    const emailField = document.querySelector("[data-profile-email]");
    const mobileField = document.querySelector("[data-profile-mobile]");
    const payload = {
      first_name: profileForm.elements.first_name?.value || "",
      last_name: profileForm.elements.last_name?.value || "",
      email: emailField?.value || "",
      mobile: mobileField?.value || "",
      shop_name: document.querySelector("[data-profile-shop]")?.value || "",
      gstin: document.querySelector("[data-profile-gstin]")?.value || ""
    };
    payload.mobile = normalizePhoneInput(payload.mobile);
    if (!payload.first_name.trim() || !payload.last_name.trim()) {
      setStatus(profileStatus, "Enter both first name and last name before saving.", "error");
      return;
    }
    if (!payload.email.trim()) {
      setStatus(profileStatus, "Enter an email address before saving.", "error");
      return;
    }
    if (!payload.mobile.trim()) {
      setStatus(profileStatus, "Enter a mobile number with country code before saving.", "error");
      return;
    }
    try {
      const response = await apiFetch(`/users/${profile.id}/profile`, {
        method: "PUT",
        body: JSON.stringify(payload)
      });
      saveStoredUser(response.user);
      setStatus(profileStatus, response.message, "success");
      setTimeout(() => {
        renderAccountPage();
      }, 250);
    } catch (error) {
      setStatus(profileStatus, error.message, "error");
    }
  };
  if (profileSaveShortcut) {
    profileSaveShortcut.onclick = () => profileForm?.requestSubmit();
  }

  const populateAddressForm = (address) => {
    if (addressRecordId) addressRecordId.value = address?.id ? String(address.id) : "";
    if (addressLabelInput) addressLabelInput.value = address?.label || "";
    if (addressDefaultInput) addressDefaultInput.checked = Boolean(address?.is_default);
    fillAddressFields(address, {
      city: addressForm?.elements?.city,
      state: addressForm?.elements?.state,
      pincode: addressForm?.elements?.pincode,
      landmark: addressForm?.elements?.landmark,
      street: addressForm?.elements?.street,
    });
  };

  const renderAddressCards = (currentProfile) => {
    if (!savedAddressesList) return;
    const addresses = sortAddresses(currentProfile.addresses || []);
    if (!addresses.length) {
      savedAddressesList.innerHTML = "<p class=\"empty-copy\">No saved addresses yet. Add your first delivery address here.</p>";
      populateAddressForm(null);
      return;
    }

    savedAddressesList.innerHTML = addresses.map((address) => `
      <article class="saved-address-card${address.is_default ? " is-default" : ""}" data-address-id="${address.id}">
        <div class="saved-address-badges">
          <span class="saved-address-pill">${escapeHtml(address.label || "Saved Address")}</span>
          ${address.is_default ? `<span class="saved-address-pill is-default">Default Delivery Address</span>` : ""}
        </div>
        <div class="saved-address-text">${escapeHtml(formatAddressSummary(address))}</div>
        <div class="saved-address-text">${escapeHtml(address.landmark || "Ready for checkout and delivery")}</div>
        <div class="saved-address-actions">
          <button type="button" class="ghost-button inline-button" data-address-edit="${address.id}">Edit</button>
          <button type="button" class="ghost-button inline-button" data-address-default="${address.id}" ${address.is_default ? "disabled" : ""}>Use as Default</button>
          <button type="button" class="ghost-button inline-button" data-address-delete="${address.id}">Delete</button>
        </div>
      </article>
    `).join("");

    savedAddressesList.querySelectorAll("[data-address-edit]").forEach((button) => {
      button.addEventListener("click", () => {
        const address = addresses.find((item) => item.id === Number(button.dataset.addressEdit));
        populateAddressForm(address || null);
        addressForm?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    });

    savedAddressesList.querySelectorAll("[data-address-default]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          const response = await apiFetch(`/users/${profile.id}/addresses/${button.dataset.addressDefault}/default`, {
            method: "POST"
          });
          saveStoredUser(response.user);
          setStatus(addressStatus, response.message, "success");
          setTimeout(() => renderAccountPage(), 200);
        } catch (error) {
          setStatus(addressStatus, error.message, "error");
        }
      });
    });

    savedAddressesList.querySelectorAll("[data-address-delete]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          const response = await apiFetch(`/users/${profile.id}/addresses/${button.dataset.addressDelete}`, {
            method: "DELETE"
          });
          saveStoredUser(response.user);
          setStatus(addressStatus, response.message, "success");
          setTimeout(() => renderAccountPage(), 200);
        } catch (error) {
          setStatus(addressStatus, error.message, "error");
        }
      });
    });
  };

  populateAddressForm(getDefaultAddress(profile));
  renderAddressCards(profile);

  if (createAddressButton) createAddressButton.onclick = () => {
    populateAddressForm({
      label: "New Address",
      city: "",
      state: "",
      pincode: "",
      landmark: "",
      street: "",
      is_default: !(profile.addresses || []).length,
    });
    addressForm?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  if (addressResetButton) addressResetButton.onclick = () => {
    populateAddressForm(getDefaultAddress(getStoredUser() || profile));
    setStatus(addressStatus, "Address form reset to your current default delivery address.", "neutral");
  };

  if (addressForm) addressForm.onsubmit = async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(addressForm).entries());
    payload.is_default = Boolean(addressDefaultInput?.checked);
    try {
      const addressId = Number(addressRecordId?.value || 0);
      const endpoint = addressId ? `/users/${profile.id}/addresses/${addressId}` : `/users/${profile.id}/addresses`;
      const method = addressId ? "PUT" : "POST";
      const response = await apiFetch(endpoint, {
        method,
        body: JSON.stringify(payload)
      });
      saveStoredUser(response.user);
      setStatus(addressStatus, response.message, "success");
      setTimeout(() => {
        renderAccountPage();
      }, 250);
    } catch (error) {
      setStatus(addressStatus, error.message, "error");
    }
  };

  if (passwordForm) passwordForm.onsubmit = async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(passwordForm).entries());
    if (!payload.current_password || !payload.new_password || !payload.confirm_password) {
      setStatus(passwordStatus, "Fill current password, new password, and confirm password to continue.", "error");
      return;
    }
    try {
      const response = await apiFetch(`/users/${profile.id}/change-password`, {
        method: "POST",
        body: JSON.stringify(payload)
      });
      passwordForm.reset();
      saveStoredUser({ ...profile, ...response.user });
      setStatus(passwordStatus, response.message, "success");
      setTimeout(() => {
        renderAccountPage();
      }, 300);
    } catch (error) {
      setStatus(passwordStatus, error.message, "error");
    }
  };

  if (profileImageForm) profileImageForm.onsubmit = async (event) => {
    event.preventDefault();
    const imageInput = document.getElementById("profileImageInput");
    const file = imageInput?.files?.[0];
    if (!file) {
      setStatus(profileImageStatus, "Choose an image before uploading.", "error");
      return;
    }

    try {
      const payload = new FormData();
      payload.append("image", file);
      const response = await apiFetch(`/users/${profile.id}/profile-image`, {
        method: "POST",
        body: payload
      });
      saveStoredUser(response.user);
      syncUserUi();
      document.querySelectorAll("[data-profile-avatar]").forEach((node) => {
        setImageSourceWithFallback(node, response.user.profile_image, "images/swift.png");
      });
      profileImageForm.reset();
      if (profileFileName) profileFileName.textContent = "No file selected";
      setStatus(profileImageStatus, response.message, "success");
    } catch (error) {
      setStatus(profileImageStatus, error.message, "error");
    }
  };

  profileImageInput?.addEventListener("change", () => {
    const file = profileImageInput.files?.[0];
    if (profileFileName) profileFileName.textContent = file?.name || "No file selected";
    if (!file) {
      document.querySelectorAll("[data-profile-avatar]").forEach((node) => {
        setImageSourceWithFallback(node, profile.profile_image, "images/swift.png");
      });
      return;
    }
    const previewUrl = URL.createObjectURL(file);
    document.querySelectorAll("[data-profile-avatar]").forEach((node) => {
      setImageSourceWithFallback(node, previewUrl, "images/swift.png");
    });
  });

  removeProfilePhotoButton?.addEventListener("click", async () => {
    try {
      const response = await apiFetch(`/users/${profile.id}/profile-image`, {
        method: "DELETE"
      });
      if (shapeSelect) shapeSelect.value = "circle";
      if (zoomRange) zoomRange.value = "1";
      if (focusRange) focusRange.value = "50";
      saveProfilePhotoPrefs(profile.id, { shape: "circle", zoom: 1, focus: 50 });
      applyPhotoPrefs();
      saveStoredUser(response.user);
      syncUserUi();
      document.querySelectorAll("[data-profile-avatar]").forEach((node) => {
        setImageSourceWithFallback(node, "images/swift.png", "images/swift.png");
      });
      if (profileFileName) profileFileName.textContent = "No file selected";
      setStatus(profileImageStatus, "Profile photo removed. Default SwiftCart photo restored.", "success");
    } catch (error) {
      setStatus(profileImageStatus, error.message, "error");
    }
  });
}

async function renderOrdersPage() {
  const user = getStoredUser();
  const container = document.getElementById("ordersList");
  const statsNode = document.getElementById("orderStats");
  const searchInput = document.getElementById("orderSearchInput");
  const statusFilter = document.getElementById("orderStatusFilter");
  const ordersStatus = document.getElementById("ordersStatus");
  if (!container) return;
  if (!user) {
    container.innerHTML = "<p class=\"empty-copy\">Login to view your orders.</p>";
    return;
  }

  let orders = [];
  try {
    orders = await apiFetch(`/users/${user.id}/orders`);
  } catch (error) {
    if (statsNode) statsNode.innerHTML = "";
    container.innerHTML = "<p class=\"empty-copy\">We could not load your orders right now. Please refresh in a moment.</p>";
    setStatus(ordersStatus, error.message || "Order history could not be loaded.", "error");
    return;
  }
  if (statsNode) {
    const delivered = orders.filter((order) => order.status === "Delivered").length;
    const active = orders.filter((order) => !["Cancelled", "Delivered"].includes(order.status)).length;
    const cancelled = orders.filter((order) => order.status === "Cancelled").length;
    statsNode.innerHTML = [
      ["Total Orders", orders.length],
      ["Active", active],
      ["Delivered", delivered],
      ["Cancelled", cancelled]
    ].map(([label, value]) => `
      <article class="marketplace-stat-card compact">
        <strong>${value}</strong>
        <span>${label}</span>
      </article>
    `).join("");
  }

  const drawOrders = () => {
    const query = String(searchInput?.value || "").trim().toLowerCase();
    const selectedStatus = statusFilter?.value || "all";
    const filteredOrders = orders.filter((order) => {
      const statusMatches = selectedStatus === "all" || order.status === selectedStatus;
      const searchBlob = [
        `order ${order.id}`,
        order.status,
        order.customer?.full_name,
        ...order.items.map((item) => item.name)
      ].join(" ").toLowerCase();
      const queryMatches = !query || searchBlob.includes(query);
      return statusMatches && queryMatches;
    });

    container.innerHTML = filteredOrders.length
      ? filteredOrders.map((order) => `
        <article class="order-card">
          <div class="order-card-top">
            <div>
              <strong>Order #${order.id}</strong>
              <p class="order-meta-copy">Placed on ${formatCompactDateTime(order.created_at)}</p>
            </div>
            <span class="order-status-pill${order.status === "Partially Cancelled" ? " is-partial" : order.status === "Cancelled" ? " is-cancelled" : ""}">${order.status}</span>
          </div>
          <p class="order-delivery-copy">${getOrderDeliveryCopy(order)}</p>
          <div class="order-items-list">
            ${order.items.map((item) => renderOrderLineItem(order, item)).join("")}
          </div>
          ${renderOrderTimeline(order)}
          ${order.cancel_reason ? `<p class="order-cancel-note"><strong>Cancellation reason:</strong> ${escapeHtml(order.cancel_reason)}</p>` : ""}
          <div class="summary-row">
            <span>${order.items.length} product${order.items.length === 1 ? "" : "s"} in this order for ${escapeHtml(order.customer?.full_name || "Customer")}</span>
            <strong>${formatPrice(order.total_amount)}</strong>
          </div>
        </article>
      `).join("")
      : `<p class="empty-copy">${orders.length ? "No orders match the current search or filter." : "No orders yet. Place your first order from the catalog."}</p>`;

    if (ordersStatus) {
      setStatus(
        ordersStatus,
        filteredOrders.length === orders.length
          ? `Showing all ${orders.length} order${orders.length === 1 ? "" : "s"}.`
          : `Showing ${filteredOrders.length} of ${orders.length} orders.`,
        filteredOrders.length ? "success" : "neutral"
      );
    }

    container.querySelectorAll(".order-item-cancel-form").forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const reason = String(new FormData(form).get("reason") || "").trim();
        const statusNode = form.querySelector(".order-cancel-status");
        if (reason.split(/\s+/).filter(Boolean).length < 10) {
          setStatus(statusNode, "Please enter at least 10 words for the cancellation reason.", "error");
          return;
        }
        try {
          await apiFetch(`/orders/${form.dataset.orderId}/items/${form.dataset.orderItemId}/cancel`, {
            method: "POST",
            body: JSON.stringify({
              user_id: user.id,
              reason
            })
          });
          setStatus(statusNode, "Product cancelled successfully. Refreshing order history...", "success");
          setTimeout(() => {
            renderOrdersPage();
          }, 250);
        } catch (error) {
          setStatus(statusNode, error.message, "error");
        }
      });
    });
  };

  if (searchInput) searchInput.oninput = drawOrders;
  if (statusFilter) statusFilter.onchange = drawOrders;
  drawOrders();
}

async function renderWishlistPage() {
  const user = getStoredUser();
  const container = document.getElementById("wishlistList");
  const status = document.getElementById("wishlistStatus");
  if (!container) return;
  if (!user) {
    container.innerHTML = "<p class=\"empty-copy\">Login to view your wishlist.</p>";
    return;
  }

  const wishlist = await apiFetch(`/users/${user.id}/wishlist`);
  if (!wishlist.length) {
    container.innerHTML = "<p class=\"empty-copy\">No wishlist items yet. Save products from any product page.</p>";
    return;
  }

  container.innerHTML = wishlist.map((item) => `
    <article class="cart-item">
      <img src="${escapeHtml(sanitizeUrl(item.image, "images/swift.png"))}" alt="${escapeHtml(item.name)}">
      <div class="cart-item-info">
        <h3>${escapeHtml(item.name)}</h3>
        <p>${escapeHtml(item.description)}</p>
        <div class="cart-item-meta">
          <strong>${formatPrice(item.price)}</strong>
          <div class="inline-actions">
            <a class="product-link" href="${escapeHtml(buildProductHref(item.slug))}">View</a>
            <button class="ghost-button wishlist-remove" data-product-id="${item.id}" type="button">Remove</button>
          </div>
        </div>
      </div>
    </article>
  `).join("");

  container.querySelectorAll(".wishlist-remove").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await apiFetch(`/users/${user.id}/wishlist/${button.dataset.productId}`, { method: "DELETE" });
        setStatus(status, "Removed from wishlist.", "success");
        renderWishlistPage();
      } catch (error) {
        setStatus(status, error.message, "error");
      }
    });
  });
}

async function renderMerchantPage() {
  const user = getStoredUser();
  if (!isMerchantUser(user)) {
    redirectToPage("Login.html");
    return;
  }

  document.getElementById("merchantLogoutButton")?.addEventListener("click", () => {
    logoutCurrentUser();
  });

  const [dashboard, catalog] = await Promise.all([
    apiFetch(`/merchant/dashboard?user_id=${encodeURIComponent(user.id)}`),
    apiFetch(`/merchant/products?user_id=${encodeURIComponent(user.id)}`)
  ]);

  const statsNode = document.getElementById("merchantStats");
  const tableNode = document.getElementById("merchantProductTable");
  const merchantNode = document.getElementById("merchantIdentity");
  const categorySelect = document.getElementById("merchantCategorySelect");
  const form = document.getElementById("merchantProductForm");
  const status = document.getElementById("merchantStatus");
  const hiddenId = document.getElementById("merchantProductId");

  bindAutoCapitalization([
    form?.elements?.name,
    form?.elements?.tag
  ], "title");
  bindAutoCapitalization([form?.elements?.description], "sentence");

  statsNode.innerHTML = Object.entries(dashboard.totals).map(([label, value]) => `
    <article class="stat-card">
      <strong>${label === "revenue" ? formatPrice(value) : value}</strong>
      <span>${label.replaceAll("_", " ")}</span>
    </article>
  `).join("");

  if (merchantNode) {
    merchantNode.innerHTML = `
      <article class="stat-card">
        <strong>${escapeHtml(dashboard.merchant.shop_name || dashboard.merchant.full_name)}</strong>
        <span>${escapeHtml(dashboard.merchant.email)}${dashboard.merchant.gstin ? ` · ${escapeHtml(dashboard.merchant.gstin)}` : ""}</span>
      </article>
    `;
  }

  categorySelect.innerHTML = catalog.categories.map((category) => `
    <option value="${category.id}">${escapeHtml(category.name)}</option>
  `).join("");

  tableNode.innerHTML = catalog.products.length
    ? catalog.products.map((product) => `
        <article class="admin-row">
          <div>
            <strong>${escapeHtml(product.name)}</strong>
            <p>${escapeHtml(product.category.name)} · ${escapeHtml(product.tag)} · Stock ${product.stock}</p>
          </div>
          <div class="admin-actions">
            <span>${formatPrice(product.price)}</span>
            <button class="ghost-button merchant-edit" data-product-id="${product.id}" type="button">Edit</button>
          </div>
        </article>
      `).join("")
    : "<p class=\"empty-copy\">No merchant listings yet. Add your first product above.</p>";

  tableNode.querySelectorAll(".merchant-edit").forEach((button) => {
    button.addEventListener("click", () => {
      const product = catalog.products.find((item) => item.id === Number(button.dataset.productId));
      if (!product) return;
      hiddenId.value = product.id;
      form.elements.name.value = product.name;
      form.elements.slug.value = product.slug;
      form.elements.category_id.value = product.category.id;
      form.elements.image.value = product.image;
      form.elements.price.value = product.price;
      form.elements.original_price.value = product.original_price;
      form.elements.stock.value = product.stock;
      form.elements.tag.value = product.tag;
      form.elements.description.value = product.description;
      form.elements.highlights.value = product.highlights.join("|");
      form.elements.specifications.value = Object.entries(product.specifications).map(([k, v]) => `${k}=${v}`).join("|");
      form.elements.featured.checked = Boolean(product.featured);
      form.elements.deal_of_the_day.checked = Boolean(product.deal_of_the_day);
      setStatus(status, `Editing ${product.name}`, "neutral");
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    data.featured = form.elements.featured.checked;
    data.deal_of_the_day = form.elements.deal_of_the_day.checked;

    try {
      if (hiddenId.value) {
        await apiFetch(`/merchant/products/${hiddenId.value}?user_id=${encodeURIComponent(user.id)}`, {
          method: "PUT",
          body: JSON.stringify(data)
        });
        setStatus(status, "Product updated successfully.", "success");
      } else {
        await apiFetch(`/merchant/products?user_id=${encodeURIComponent(user.id)}`, {
          method: "POST",
          body: JSON.stringify(data)
        });
        setStatus(status, "Product created successfully.", "success");
      }
      form.reset();
      hiddenId.value = "";
      renderMerchantPage();
    } catch (error) {
      setStatus(status, error.message, "error");
    }
  }, { once: true });
}

function buildAdminRowActions(actions) {
  return actions.map((action) => `
    <button class="ghost-button owner-inline-action" type="button" data-owner-action="${escapeHtml(action.type)}" data-owner-value="${escapeHtml(action.value)}">
      ${escapeHtml(action.label)}
    </button>
  `).join("");
}

function getProfilePhotoPrefsKey(userId) {
  return `swiftcart-profile-photo-prefs-${userId}`;
}

function loadProfilePhotoPrefs(userId) {
  try {
    return JSON.parse(localStorage.getItem(getProfilePhotoPrefsKey(userId)) || "{}");
  } catch {
    return {};
  }
}

function saveProfilePhotoPrefs(userId, prefs) {
  localStorage.setItem(getProfilePhotoPrefsKey(userId), JSON.stringify(prefs));
}

function bindOwnerActionButtons(scope, handlers) {
  if (!scope) return;
  scope.querySelectorAll("[data-owner-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.ownerAction || "";
      const value = button.dataset.ownerValue || "";
      if (handlers[action]) handlers[action](value);
    });
  });
}

async function renderAdminPage() {
  const user = getStoredUser();
  if (!isOwnerUser(user)) {
    redirectToPage("Login.html");
    return;
  }

  if (!state.adminExpandedSections) {
    state.adminExpandedSections = { ...DEFAULT_ADMIN_EXPANDED_SECTIONS };
  }

  document.getElementById("adminLogoutButton")?.addEventListener("click", () => {
    logoutCurrentUser();
  });
  const status = document.getElementById("adminStatus");
  setStatus(status, "Loading owner dashboard…", "neutral");

  const [dashboardResult, catalogResult, dbOverviewResult] = await Promise.allSettled([
    apiFetch(`/admin/dashboard${buildOwnerQuery(user)}`),
    apiFetch(`/admin/products${buildOwnerQuery(user)}`),
    apiFetch(`/admin/database/overview${buildOwnerQuery(user)}`)
  ]);

  const dashboard = dashboardResult.status === "fulfilled"
    ? normalizeAdminDashboardPayload(dashboardResult.value, user)
    : buildEmptyAdminDashboard(user);
  const catalog = catalogResult.status === "fulfilled"
    ? normalizeAdminCatalogPayload(catalogResult.value)
    : normalizeAdminCatalogPayload();
  const dbOverview = dbOverviewResult.status === "fulfilled"
    ? normalizeAdminDbOverview(dbOverviewResult.value)
    : normalizeAdminDbOverview();

  const failedSections = [];
  if (dashboardResult.status === "rejected") failedSections.push(`analytics: ${dashboardResult.reason?.message || "Request failed"}`);
  if (catalogResult.status === "rejected") failedSections.push(`catalog: ${catalogResult.reason?.message || "Request failed"}`);
  if (dbOverviewResult.status === "rejected") failedSections.push(`database: ${dbOverviewResult.reason?.message || "Request failed"}`);
  if (failedSections.length) {
    setStatus(status, `Loaded partial owner dashboard. ${failedSections.join(" · ")}`, "error");
  } else {
    setStatus(
      status,
      `Owner dashboard updated. ${dashboard.totals.products} products, ${dashboard.totals.orders} orders, and ${dashboard.totals.users} users loaded.`,
      "success"
    );
  }

  const statsNode = document.getElementById("adminStats");
  const tableNode = document.getElementById("adminProductTable");
  const usersNode = document.getElementById("adminUsersTable");
  const ordersNode = document.getElementById("adminOrdersTable");
  const reviewsNode = document.getElementById("adminReviewsTable");
  const linkedAccountsNode = document.getElementById("adminLinkedAccountsTable");
  const changesNode = document.getElementById("adminChangesTable");
  const codesNode = document.getElementById("adminCodesTable");
  const dbTablesNode = document.getElementById("adminDbTablesList");
  const chatsNode = document.getElementById("adminChatsTable");
  const ownerNode = document.getElementById("ownerIdentity");
  const growthCardsNode = document.getElementById("adminGrowthCards");
  const growthTimelineNode = document.getElementById("adminGrowthTimeline");
  const hourlyTimelineNode = document.getElementById("adminHourlyTimeline");
  const revenueChartNode = document.getElementById("adminRevenueChart");
  const orderLineChartNode = document.getElementById("adminOrderLineChart");
  const cancelledChartNode = document.getElementById("adminCancelledChart");
  const categoryChartNode = document.getElementById("adminCategoryChart");
  const categoryPerformanceNode = document.getElementById("adminCategoryPerformance");
  const inventorySummaryNode = document.getElementById("adminInventorySummary");
  const bankOffersNode = document.getElementById("adminBankOffersTable");
  const activeDiscountsNode = document.getElementById("adminActiveDiscountsTable");
  const productsToggleButton = document.getElementById("adminProductsToggle");
  const usersToggleButton = document.getElementById("adminUsersToggle");
  const codesToggleButton = document.getElementById("adminCodesToggle");
  const bankOffersToggleButton = document.getElementById("adminBankOffersToggle");
  const ordersToggleButton = document.getElementById("adminOrdersToggle");
  const reviewsToggleButton = document.getElementById("adminReviewsToggle");
  const linkedToggleButton = document.getElementById("adminLinkedToggle");
  const changesToggleButton = document.getElementById("adminChangesToggle");
  const chatsToggleButton = document.getElementById("adminChatsToggle");
  const dbTablesToggleButton = document.getElementById("adminDbTablesToggle");
  const categorySelect = document.getElementById("adminCategorySelect");
  const discountCategorySelect = document.getElementById("adminDiscountCategorySelect");
  const discountPercentInput = document.getElementById("adminDiscountPercent");
  const discountDurationInput = document.getElementById("adminDiscountDuration");
  const discountSecondaryInput = document.getElementById("adminDiscountSecondary");
  const applyCategoryDiscountButton = document.getElementById("adminApplyCategoryDiscount");
  const removeCategoryDiscountButton = document.getElementById("adminRemoveCategoryDiscount");
  const secondaryCategoriesSelect = document.getElementById("adminSecondaryCategoriesSelect");
  const createCategoryButton = document.getElementById("adminCreateCategoryButton");
  const newCategoryNameInput = document.getElementById("adminNewCategoryName");
  const form = document.getElementById("adminProductForm");
  const hiddenId = document.getElementById("adminProductId");
  const imageInput = document.getElementById("adminImageInput");
  const imageFileInput = document.getElementById("adminImageFile");
  const imagePreview = document.getElementById("adminImagePreview");
  const imageUploadStatus = document.getElementById("adminImageUploadStatus");
  const dbPathNode = document.getElementById("adminDatabasePath");
  const dbTableSelect = document.getElementById("adminDbTableSelect");
  const dbRefreshButton = document.getElementById("adminDbRefreshButton");
  const dbTableInfo = document.getElementById("adminDbTableInfo");
  const dbPreview = document.getElementById("adminDbPreview");
  const dbQueryForm = document.getElementById("adminDbQueryForm");
  const dbQueryStatus = document.getElementById("adminDbQueryStatus");
  const dbQueryResult = document.getElementById("adminDbQueryResult");
  const dbQueryInput = document.getElementById("adminDbQuery");
  const sectionLimit = 5;

  const queueOwnerSql = (sql, statusMessage) => {
    if (dbQueryInput) dbQueryInput.value = sql;
    if (dbQueryStatus) setStatus(dbQueryStatus, statusMessage, "success");
    document.getElementById("adminDbQuery")?.scrollIntoView({ behavior: "smooth", block: "center" });
    dbQueryInput?.focus();
  };

  if (statsNode) {
    statsNode.innerHTML = Object.entries(dashboard.totals).map(([label, value]) => `
      <article class="stat-card">
        <strong>${value}</strong>
        <span>${label.replaceAll("_", " ")}</span>
      </article>
    `).join("");
  }

  if (ownerNode) {
    ownerNode.innerHTML = `
      <article class="stat-card">
        <strong>${dashboard.owner.full_name}</strong>
        <span>${dashboard.owner.email} · Code ${dashboard.owner.unique_code}</span>
        <span>Joined ${formatDateTime(dashboard.owner.created_at)}</span>
      </article>
    `;
  }

  if (growthCardsNode) {
    growthCardsNode.innerHTML = [
      ["Users (7 days)", dashboard.growth.users_last_7_days],
      ["Users (30 days)", dashboard.growth.users_last_30_days],
      ["Orders (7 days)", dashboard.growth.orders_last_7_days],
      ["Orders (30 days)", dashboard.growth.orders_last_30_days],
      ["Revenue (7 days)", formatPrice(dashboard.growth.revenue_last_7_days)],
      ["Revenue (30 days)", formatPrice(dashboard.growth.revenue_last_30_days)],
      ["Merchant Accounts", dashboard.growth.merchant_accounts],
      ["Cancelled Orders", dashboard.totals.cancelled_orders],
      ["AI Chats", dashboard.totals.chat_messages]
    ].map(([label, value]) => `
      <article class="stat-card">
        <strong>${value}</strong>
        <span>${label}</span>
      </article>
    `).join("");
  }

  if (growthTimelineNode) {
    growthTimelineNode.innerHTML = dashboard.order_activity.length
      ? renderAnalyticsBars(
          dashboard.order_activity,
          (entry) => entry.label,
          (entry) => entry.orders,
          (entry) => `${entry.orders} orders · ${formatPrice(entry.revenue)}`
        )
      : "<p class=\"empty-copy\">Order growth data is not available yet.</p>";
  }

  if (hourlyTimelineNode) {
    const activeHours = dashboard.hourly_activity.filter((entry) => entry.orders > 0);
    hourlyTimelineNode.innerHTML = activeHours.length
      ? renderAnalyticsBars(
          activeHours,
          (entry) => entry.hour,
          (entry) => entry.orders,
          (entry) => `${entry.orders} orders`
        )
      : "<p class=\"empty-copy\">No hourly order data yet.</p>";
  }

  if (revenueChartNode) {
    revenueChartNode.innerHTML = renderLineChart("Finance trend", dashboard.finance_series, "#22c55e", (value) => formatPrice(value));
  }
  if (orderLineChartNode) {
    orderLineChartNode.innerHTML = renderLineChart("Order trend", dashboard.order_series, "#2563eb", (value) => `${value} orders`);
  }
  if (cancelledChartNode) {
    cancelledChartNode.innerHTML = renderLineChart("Cancellation trend", dashboard.cancelled_series, "#ef4444", (value) => `${value} cancelled`);
  }
  if (categoryChartNode) {
    const activeCategoryPerformance = dashboard.category_performance.filter((entry) => entry.products > 0);
    categoryChartNode.innerHTML = activeCategoryPerformance.length
      ? renderAnalyticsBars(
          activeCategoryPerformance.slice(0, 8),
          (entry) => entry.category_name,
          (entry) => entry.ordered_units,
          (entry) => `${entry.ordered_units} units · ${entry.cancelled_units} cancelled`
        )
      : "<p class=\"empty-copy\">No category performance data yet.</p>";
  }
  if (categoryPerformanceNode) {
    const listedCategories = dashboard.category_performance.filter((entry) => entry.products > 0);
    categoryPerformanceNode.innerHTML = listedCategories.length
      ? listedCategories.map((entry) => `
          <article class="admin-row">
            <div>
              <strong>${entry.category_name}</strong>
              <p>${entry.products} listed products</p>
              <p>${entry.in_stock_products} in stock · ${entry.out_of_stock_products} out of stock · ${entry.low_stock_products} low stock</p>
              <p>${entry.ordered_units} ordered units · ${entry.cancelled_units} cancelled units</p>
            </div>
            <div class="admin-actions">
              <strong>${formatPrice(entry.revenue)}</strong>
              ${buildAdminRowActions([
                { type: "inspect-category", value: entry.category_name, label: "Inspect" }
              ])}
            </div>
          </article>
        `).join("")
      : "<p class=\"empty-copy\">No listed category performance data yet.</p>";
  }

  if (inventorySummaryNode) {
    inventorySummaryNode.innerHTML = [
      { label: "Seller Listed Products", value: dashboard.inventory?.seller_listed_products ?? 0, note: "Products created by merchant accounts" },
      { label: "Platform Managed Products", value: dashboard.inventory?.platform_managed_products ?? 0, note: "Products managed directly by the owner catalog" },
      { label: "Discounted Products", value: dashboard.inventory?.discounted_products ?? 0, note: "Products currently showing a lower live price" },
      { label: "Out of Stock", value: dashboard.totals.out_of_stock_products ?? 0, note: "Listings customers cannot purchase right now" },
      { label: "Low Stock", value: dashboard.totals.low_stock_products ?? 0, note: "Listings that need replenishment soon" }
    ].map((entry) => `
      <article class="admin-row">
        <div>
          <strong>${entry.label}</strong>
          <p>${entry.note}</p>
        </div>
        <div class="admin-actions">
          <strong>${entry.value}</strong>
        </div>
      </article>
    `).join("");
  }

  if (bankOffersNode) {
    const visibleOffers = isSectionExpanded("bankOffers") ? dashboard.bank_offers : dashboard.bank_offers.slice(0, sectionLimit);
    bankOffersNode.innerHTML = dashboard.bank_offers.length
      ? visibleOffers.map((offer) => `
          <article class="admin-row">
            <div>
              <strong>${offer.bank_name}</strong>
              <p>${offer.category_name}</p>
              <p>${offer.discount_percent}% instant discount up to ${formatPrice(offer.max_discount)}</p>
            </div>
            <div class="admin-actions">
              <span>Min order ${formatPrice(offer.minimum_order_value)}</span>
              ${buildAdminRowActions([
                { type: "inspect-category", value: offer.category_name, label: "Open Category" }
              ])}
            </div>
          </article>
        `).join("")
      : "<p class=\"empty-copy\">No bank offers generated yet.</p>";
    if (bankOffersToggleButton) {
      bankOffersToggleButton.hidden = dashboard.bank_offers.length <= sectionLimit;
      bankOffersToggleButton.textContent = isSectionExpanded("bankOffers") ? "Show Less" : `Show More (${dashboard.bank_offers.length - sectionLimit})`;
      bankOffersToggleButton.onclick = () => {
        setSectionExpanded("bankOffers", !isSectionExpanded("bankOffers"));
        renderAdminPage();
      };
    }
  }

  if (activeDiscountsNode) {
    activeDiscountsNode.innerHTML = dashboard.active_category_discounts?.length
      ? dashboard.active_category_discounts.map((discount) => `
          <article class="admin-row">
            <div class="discount-summary">
              <strong>${escapeHtml(discount.category_name)}</strong>
              <p>${discount.discount_percent}% off · ${discount.affected_products} product(s) updated</p>
              <p>Expires on ${formatCompactDateTime(discount.expires_at)}</p>
            </div>
            <div class="admin-actions">
              <span class="discount-chip${formatRemainingDuration(discount.expires_at) === "Expired" ? " is-warning" : ""}">${formatRemainingDuration(discount.expires_at)}</span>
              <span>${discount.include_secondary ? "Primary + secondary category" : "Primary category only"}</span>
              <button
                class="ghost-button admin-discount-remove"
                type="button"
                data-category-id="${discount.category_id}"
                data-include-secondary="${discount.include_secondary ? "true" : "false"}"
              >
                Remove Discount
              </button>
            </div>
          </article>
        `).join("")
      : "<p class=\"empty-copy\">No active category discounts right now.</p>";
  }

  if (dbPathNode) {
    dbPathNode.textContent = `Database file: ${dbOverview.database_path}`;
  }

  if (dbTableSelect) {
    dbTableSelect.innerHTML = dbOverview.tables.length
      ? dbOverview.tables.map((table) => `
          <option value="${table.name}">${table.name} (${table.rows} rows)</option>
        `).join("")
      : `<option value="">No tables available</option>`;
  }

  if (categorySelect) {
    categorySelect.innerHTML = catalog.categories.length
      ? catalog.categories.map((category) => `
          <option value="${category.id}">${category.name}</option>
        `).join("")
      : `<option value="">No categories available</option>`;
  }
  if (discountCategorySelect) {
    const discountCategories = dashboard.category_performance
      .filter((entry) => entry.products > 0)
      .map((entry) => catalog.categories.find((category) => category.id === entry.category_id))
      .filter(Boolean);
    discountCategorySelect.innerHTML = `<option value="">Select category for discount</option>${discountCategories.map((category) => `
      <option value="${category.id}">${category.name}</option>
    `).join("")}`;
  }
  if (secondaryCategoriesSelect) {
    secondaryCategoriesSelect.innerHTML = catalog.categories.map((category) => `
      <option value="${category.name}">${category.name}</option>
    `).join("");
  }

  if (createCategoryButton) {
    createCategoryButton.onclick = async () => {
      const name = newCategoryNameInput?.value.trim() || "";
      if (!name) {
        setStatus(status, "Enter a category name first.", "error");
        return;
      }
      try {
        const response = await apiFetch(`/admin/categories${buildOwnerQuery(user)}`, {
          method: "POST",
          body: JSON.stringify({ name })
        });
        if (newCategoryNameInput) newCategoryNameInput.value = "";
        setStatus(status, response.message, "success");
        renderAdminPage();
      } catch (error) {
        setStatus(status, error.message, "error");
      }
    };
  }

  if (applyCategoryDiscountButton) {
    applyCategoryDiscountButton.onclick = async () => {
      const categoryId = discountCategorySelect?.value;
      const discountPercent = Number(discountPercentInput?.value || 0);
      const durationHours = Number(discountDurationInput?.value || 24);
      const includeSecondary = Boolean(discountSecondaryInput?.checked);
      if (!categoryId) {
        setStatus(status, "Choose a category for the discount first.", "error");
        return;
      }
      if (!discountPercent || discountPercent < 1 || discountPercent > 99) {
        setStatus(status, "Enter a discount between 1 and 99 percent.", "error");
        return;
      }
      if (!durationHours || durationHours < 1 || durationHours > 720) {
        setStatus(status, "Enter a discount timer between 1 and 720 hours.", "error");
        return;
      }
      try {
        const response = await apiFetch(`/admin/category-discount${buildOwnerQuery(user)}`, {
          method: "POST",
          body: JSON.stringify({
            category_id: Number(categoryId),
            discount_percent: discountPercent,
            duration_hours: durationHours,
            include_secondary: includeSecondary
          })
        });
        setStatus(status, response.message, "success");
        if (discountPercentInput) discountPercentInput.value = "";
        if (discountDurationInput) discountDurationInput.value = "24";
        renderAdminPage();
      } catch (error) {
        setStatus(status, error.message, "error");
      }
    };
  }

  if (removeCategoryDiscountButton) {
    removeCategoryDiscountButton.onclick = async () => {
      const categoryId = discountCategorySelect?.value;
      const includeSecondary = Boolean(discountSecondaryInput?.checked);
      if (!categoryId) {
        setStatus(status, "Choose a category before removing a discount.", "error");
        return;
      }
      try {
        const response = await apiFetch(`/admin/category-discount/remove${buildOwnerQuery(user)}`, {
          method: "POST",
          body: JSON.stringify({
            category_id: Number(categoryId),
            include_secondary: includeSecondary
          })
        });
        setStatus(status, response.message, "success");
        if (discountPercentInput) discountPercentInput.value = "";
        if (discountDurationInput) discountDurationInput.value = "24";
        renderAdminPage();
      } catch (error) {
        setStatus(status, error.message, "error");
      }
    };
  }

  activeDiscountsNode?.querySelectorAll(".admin-discount-remove").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const response = await apiFetch(`/admin/category-discount/remove${buildOwnerQuery(user)}`, {
          method: "POST",
          body: JSON.stringify({
            category_id: Number(button.dataset.categoryId),
            include_secondary: button.dataset.includeSecondary === "true"
          })
        });
        setStatus(status, response.message, "success");
        renderAdminPage();
      } catch (error) {
        setStatus(status, error.message, "error");
      }
    });
  });

  bindAutoCapitalization([
    form?.elements?.name,
    form?.elements?.tag,
    newCategoryNameInput
  ], "title");
  bindAutoCapitalization([form?.elements?.description], "sentence");

  if (imageFileInput) {
    imageFileInput.onchange = async () => {
      const file = imageFileInput.files?.[0];
      if (!file) {
        if (imageInput) imageInput.value = "";
        if (imagePreview) {
          imagePreview.hidden = true;
          imagePreview.removeAttribute("src");
        }
        setStatus(imageUploadStatus, "", "neutral");
        return;
      }
      if (imagePreview) {
        imagePreview.src = URL.createObjectURL(file);
        imagePreview.hidden = false;
      }
      try {
        const payload = new FormData();
        payload.append("image", file);
        const response = await apiFetch(`/admin/uploads/product-image${buildOwnerQuery(user)}`, {
          method: "POST",
          body: payload
        });
        if (imageInput) imageInput.value = response.image;
        setStatus(imageUploadStatus, response.message, "success");
      } catch (error) {
        if (imageInput) imageInput.value = "";
        setStatus(imageUploadStatus, error.message, "error");
      }
    };
  }

  const visibleProducts = isSectionExpanded("products") ? catalog.products : catalog.products.slice(0, sectionLimit);
  if (tableNode) {
    tableNode.innerHTML = catalog.products.length
      ? visibleProducts.map((product) => `
          <article class="admin-row">
            <div>
              <strong>${escapeHtml(product.name)}</strong>
              <p>Product ID ${product.id} · ${escapeHtml(product.category.name)}${product.secondary_categories?.length ? ` · ${escapeHtml(product.secondary_categories.join(", "))}` : ""} · ${escapeHtml(product.tag)}${product.seller_shop_name ? ` · Seller ${escapeHtml(product.seller_shop_name)}` : ""}</p>
              <p>${buildStockStatusMarkup(product)}${hasVisibleDiscount(product) ? ` · ${formatPrice(product.price)} from ${formatPrice(product.original_price)}` : ` · ${formatPrice(product.price)}`}</p>
              <p class="admin-rating-row">${renderStars(product.rating)}<strong class="rating-value">${product.rating.toFixed(1)}</strong><span>${product.reviews_count} customer ratings</span></p>
            </div>
            <div class="admin-actions">
              <div class="stock-control-group">
                <span class="stock-badge">Stock ${product.stock}</span>
                <button class="ghost-button owner-stock-adjust" data-product-id="${product.id}" data-stock="${product.stock}" data-stock-change="-1" type="button">-1</button>
                <button class="ghost-button owner-stock-adjust" data-product-id="${product.id}" data-stock="${product.stock}" data-stock-change="1" type="button">+1</button>
              </div>
              <button class="ghost-button admin-edit" data-product-id="${product.id}" type="button">Edit</button>
              <button class="ghost-button admin-delete-product" data-product-id="${product.id}" type="button">Delete</button>
              <button class="ghost-button owner-edit-product" data-product-id="${product.id}" type="button">Control</button>
            </div>
          </article>
        `).join("")
      : "<p class=\"empty-copy\">Catalog products are not available yet.</p>";
  }
  if (productsToggleButton) {
    productsToggleButton.hidden = catalog.products.length <= 5;
    productsToggleButton.textContent = isSectionExpanded("products") ? "Show Less" : `Show More (${catalog.products.length - 5})`;
    productsToggleButton.onclick = () => {
      setSectionExpanded("products", !isSectionExpanded("products"));
      renderAdminPage();
    };
  }

  if (usersNode) {
    const visibleUsers = isSectionExpanded("users") ? dashboard.users : dashboard.users.slice(0, sectionLimit);
    usersNode.innerHTML = dashboard.users.length
      ? visibleUsers.map((member) => `
          <article class="admin-row">
            <div>
              <strong>${escapeHtml(member.full_name)}</strong>
              <p>${escapeHtml(member.email)} · ${escapeHtml(formatPhoneDisplay(member.mobile))} · ${escapeHtml(member.account_type)}${member.shop_name ? ` · ${escapeHtml(member.shop_name)}` : ""}</p>
              <p>Code ${member.unique_code} · Joined ${formatCompactDateTime(member.created_at)} · Last login ${formatCompactDateTime(member.last_login_at)}</p>
              <p>Device ${escapeHtml(member.last_login_device || "Not captured yet")} · ${escapeHtml(member.last_login_browser || "Unknown browser")} on ${escapeHtml(member.last_login_platform || "Unknown platform")} · ${escapeHtml(member.last_login_method ? member.last_login_method.replaceAll("_", " ") : "Unknown method")}</p>
              <p>Last IP ${escapeHtml(member.last_login_ip || "Not captured yet")}</p>
              <p>${member.is_banned ? `Banned on ${formatCompactDateTime(member.banned_at)}${member.ban_reason ? ` · ${escapeHtml(member.ban_reason)}` : ""}` : "Account is active and allowed to shop."}</p>
              <p>Password updated ${formatCompactDateTime(member.password_changed_at)} · Password history is protected server-side.</p>
              <p class="admin-sensitive-copy">Plaintext passwords are not stored and password hashes are not exposed in the browser.</p>
              <p class="admin-sensitive-copy">Owner can edit user data, but the unique code is locked.</p>
              ${member.address ? `<p>${escapeHtml(`${member.address.street}, ${member.address.city}, ${member.address.state} ${member.address.pincode}`)}</p>` : ""}
            </div>
            <div class="admin-actions">
              <span>${member.is_owner ? "Owner" : member.is_banned ? "Banned" : isMerchantUser(member) ? "Merchant" : "Customer"}</span>
              ${buildAdminRowActions([
                { type: "edit-user", value: String(member.id), label: "Edit Data" },
                { type: "inspect-user", value: String(member.id), label: "Inspect" },
                ...(member.is_owner ? [] : [member.is_banned ? { type: "unban-user", value: String(member.id), label: "Unban" } : { type: "ban-user", value: String(member.id), label: "Ban" }]),
                ...(member.is_owner ? [] : [{ type: "delete-user", value: String(member.id), label: "Delete" }])
              ])}
            </div>
          </article>
        `).join("")
      : "<p class=\"empty-copy\">No user data available.</p>";
    if (usersToggleButton) {
      usersToggleButton.hidden = dashboard.users.length <= sectionLimit;
      usersToggleButton.textContent = isSectionExpanded("users") ? "Show Less" : `Show More (${dashboard.users.length - sectionLimit})`;
      usersToggleButton.onclick = () => {
        setSectionExpanded("users", !isSectionExpanded("users"));
        renderAdminPage();
      };
    }
  }

  if (codesNode) {
    const visibleCodes = isSectionExpanded("codes") ? dashboard.users : dashboard.users.slice(0, sectionLimit);
    codesNode.innerHTML = dashboard.users.length
      ? visibleCodes.map((member) => `
          <article class="identity-code-card">
            <strong>${escapeHtml(member.unique_code)}</strong>
            <p>${escapeHtml(member.full_name)}</p>
            <span>${escapeHtml(member.email)}</span>
          </article>
        `).join("")
      : "<p class=\"empty-copy\">No unique IDs available.</p>";
    if (codesToggleButton) {
      codesToggleButton.hidden = dashboard.users.length <= sectionLimit;
      codesToggleButton.textContent = isSectionExpanded("codes") ? "Show Less" : `Show More (${dashboard.users.length - sectionLimit})`;
      codesToggleButton.onclick = () => {
        setSectionExpanded("codes", !isSectionExpanded("codes"));
        renderAdminPage();
      };
    }
  }

  if (ordersNode) {
    const visibleOrders = isSectionExpanded("orders") ? dashboard.orders : dashboard.orders.slice(0, sectionLimit);
    ordersNode.innerHTML = dashboard.orders.length
      ? visibleOrders.map((order) => `
          <article class="admin-row">
            <div>
              <strong>Order #${order.id}</strong>
              <p>${escapeHtml(order.customer.full_name)} · ${escapeHtml(order.customer.email)}${order.customer.shop_name ? ` · ${escapeHtml(order.customer.shop_name)}` : ""}</p>
              <p>${escapeHtml(order.items.map((item) => `${item.name} x${item.quantity}`).join(", "))}</p>
              <p>Ordered on ${order.created_date} at ${order.created_time}</p>
            </div>
            <div class="admin-actions">
              <span>${order.status}</span>
              <strong>${formatPrice(order.total_amount)}</strong>
              ${buildAdminRowActions([
                { type: "edit-order", value: String(order.id), label: "Edit Data" },
                { type: "inspect-order", value: String(order.id), label: "Inspect" },
                { type: "delete-order", value: String(order.id), label: "Delete" }
              ])}
            </div>
          </article>
        `).join("")
      : "<p class=\"empty-copy\">No orders available.</p>";
    if (ordersToggleButton) {
      ordersToggleButton.hidden = dashboard.orders.length <= sectionLimit;
      ordersToggleButton.textContent = isSectionExpanded("orders") ? "Show Less" : `Show More (${dashboard.orders.length - sectionLimit})`;
      ordersToggleButton.onclick = () => {
        setSectionExpanded("orders", !isSectionExpanded("orders"));
        renderAdminPage();
      };
    }
  }

  if (reviewsNode) {
    const visibleReviews = isSectionExpanded("reviews") ? dashboard.reviews : dashboard.reviews.slice(0, sectionLimit);
    reviewsNode.innerHTML = dashboard.reviews.length
      ? visibleReviews.map((review) => `
          <article class="admin-row review-row">
            <div>
              <strong>${escapeHtml(review.title)}</strong>
              <p>${escapeHtml(review.product_name)} · by ${escapeHtml(review.author_name)}</p>
              <p class="admin-rating-row">${renderStars(review.rating)}<strong class="rating-value">${Number(review.rating).toFixed(1)}</strong><span>${formatCompactDateTime(review.created_at)}</span></p>
              <p>${escapeHtml(review.comment)}</p>
              ${review.image ? `<img class="admin-review-image" src="${escapeHtml(sanitizeUrl(review.image, "images/swift.png"))}" alt="${escapeHtml(review.title)}">` : ""}
            </div>
            <div class="admin-actions">
              <a class="product-link" href="${escapeHtml(buildProductHref(review.product_slug))}">Open Product</a>
              ${buildAdminRowActions([
                { type: "edit-review", value: String(review.id), label: "Edit Data" },
                { type: "inspect-review", value: String(review.id), label: "Inspect" },
                { type: "delete-review", value: String(review.id), label: "Delete" }
              ])}
            </div>
          </article>
        `).join("")
      : "<p class=\"empty-copy\">No customer reviews available yet.</p>";
    if (reviewsToggleButton) {
      reviewsToggleButton.hidden = dashboard.reviews.length <= sectionLimit;
      reviewsToggleButton.textContent = isSectionExpanded("reviews") ? "Show Less" : `Show More (${dashboard.reviews.length - sectionLimit})`;
      reviewsToggleButton.onclick = () => {
        setSectionExpanded("reviews", !isSectionExpanded("reviews"));
        renderAdminPage();
      };
    }
  }

  if (linkedAccountsNode) {
    const visibleLinked = isSectionExpanded("linked") ? dashboard.linked_mobile_accounts : dashboard.linked_mobile_accounts.slice(0, sectionLimit);
    linkedAccountsNode.innerHTML = dashboard.linked_mobile_accounts.length
      ? visibleLinked.map((group) => `
          <article class="admin-row linked-account-card">
            <div class="linked-account-copy">
              <strong>${escapeHtml(formatPhoneDisplay(group.mobile))}</strong>
              <p>${group.count} accounts linked to this number</p>
              <div class="linked-account-chips">
                ${group.accounts.map((account) => `<span>${escapeHtml(`${account.full_name} · ${account.email} · ${account.unique_code}`)}</span>`).join("")}
              </div>
            </div>
            <div class="admin-actions">
              ${buildAdminRowActions([
                { type: "inspect-mobile", value: group.mobile, label: "Inspect" },
                { type: "edit-mobile", value: group.mobile, label: "Edit Data" }
              ])}
            </div>
          </article>
        `).join("")
      : "<p class=\"empty-copy\">No duplicate mobile number links detected.</p>";
    if (linkedToggleButton) {
      linkedToggleButton.hidden = dashboard.linked_mobile_accounts.length <= sectionLimit;
      linkedToggleButton.textContent = isSectionExpanded("linked") ? "Show Less" : `Show More (${dashboard.linked_mobile_accounts.length - sectionLimit})`;
      linkedToggleButton.onclick = () => {
        setSectionExpanded("linked", !isSectionExpanded("linked"));
        renderAdminPage();
      };
    }
  }

  if (changesNode) {
    const visibleChanges = isSectionExpanded("changes") ? dashboard.user_change_logs : dashboard.user_change_logs.slice(0, sectionLimit);
    changesNode.innerHTML = dashboard.user_change_logs.length
      ? visibleChanges.map((change) => `
          <article class="admin-row">
            <div>
              <strong>${escapeHtml(change.user?.full_name || "Unknown User")}</strong>
              <p>${escapeHtml(change.user?.email || "No email")} · ${escapeHtml(change.user?.unique_code || "")}</p>
              <p>${escapeHtml(change.field_name.replaceAll("_", " "))} changed by ${escapeHtml(change.changed_by)} on ${formatCompactDateTime(change.created_at)}</p>
              <p>Previous: ${escapeHtml(change.old_value || "Empty")}</p>
              <p>Updated: ${escapeHtml(change.new_value || "Empty")}</p>
            </div>
            <div class="admin-actions">
              ${change.user ? buildAdminRowActions([{ type: "inspect-user", value: String(change.user.id), label: "Open User" }]) : ""}
            </div>
          </article>
        `).join("")
      : "<p class=\"empty-copy\">No user data changes recorded yet.</p>";
    if (changesToggleButton) {
      changesToggleButton.hidden = dashboard.user_change_logs.length <= sectionLimit;
      changesToggleButton.textContent = isSectionExpanded("changes") ? "Show Less" : `Show More (${dashboard.user_change_logs.length - sectionLimit})`;
      changesToggleButton.onclick = () => {
        setSectionExpanded("changes", !isSectionExpanded("changes"));
        renderAdminPage();
      };
    }
  }

  if (chatsNode) {
    const chatGroups = buildAdminChatGroups(dashboard.chat_messages);
    const visibleChats = isSectionExpanded("chats") ? chatGroups : chatGroups.slice(0, sectionLimit);
    chatsNode.innerHTML = chatGroups.length
      ? visibleChats.map((group) => `
          <article class="admin-chat-card">
            <div class="admin-chat-head">
              <div>
                <strong>${escapeHtml(group.user ? `${group.user.full_name} (${group.user.unique_code})` : "Guest visitor")}</strong>
                <p>${escapeHtml(group.user ? `${group.user.email} · ${group.user.account_type}` : "No account linked")}${group.page ? ` · Page ${escapeHtml(group.page)}` : ""}</p>
              </div>
              <div class="admin-actions">
                ${group.user ? buildAdminRowActions([{ type: "inspect-user", value: String(group.user.id), label: "Open User" }]) : ""}
                ${buildAdminRowActions([
                  { type: "inspect-chat", value: `${group.user?.id || 0}::${group.page || ""}`, label: "Inspect Chat" },
                  { type: "delete-chat", value: `${group.user?.id || 0}::${group.page || ""}`, label: "Delete" }
                ])}
              </div>
            </div>
            <div class="admin-chat-transcript">
              ${group.messages.map((chat) => `
                <article class="admin-chat-bubble ${chat.role === "user" ? "user" : "assistant"}">
                  <span class="admin-chat-role">${chat.role === "user" ? "Customer" : "SwiftCart AI"}</span>
                  <p>${escapeHtml(chat.message)}</p>
                  <div class="admin-chat-meta">
                    <span>${escapeHtml(chat.intent || "general")}</span>
                    <span>${formatCompactDateTime(chat.created_at)}</span>
                  </div>
                </article>
              `).join("")}
            </div>
          </article>
        `).join("")
      : "<p class=\"empty-copy\">No AI chat logs are stored yet.</p>";
    if (chatsToggleButton) {
      chatsToggleButton.hidden = chatGroups.length <= sectionLimit;
      chatsToggleButton.textContent = isSectionExpanded("chats") ? "Show Less" : `Show More (${chatGroups.length - sectionLimit})`;
      chatsToggleButton.onclick = () => {
        setSectionExpanded("chats", !isSectionExpanded("chats"));
        renderAdminPage();
      };
    }
  }

  if (dbTablesNode) {
    const visibleTables = isSectionExpanded("tables") ? dbOverview.tables : dbOverview.tables.slice(0, sectionLimit);
    dbTablesNode.innerHTML = dbOverview.tables.length
      ? visibleTables.map((table) => `
          <article class="admin-row">
            <div>
              <strong>${table.name}</strong>
              <p>${table.rows} rows available in this table</p>
            </div>
            <div class="admin-actions">
              ${buildAdminRowActions([
                { type: "preview-table", value: table.name, label: "Preview" },
                { type: "edit-table", value: table.name, label: "Edit Data" }
              ])}
            </div>
          </article>
        `).join("")
      : "<p class=\"empty-copy\">Database table metadata is not available yet.</p>";
    if (dbTablesToggleButton) {
      dbTablesToggleButton.hidden = dbOverview.tables.length <= sectionLimit;
      dbTablesToggleButton.textContent = isSectionExpanded("tables") ? "Show Less" : `Show More (${dbOverview.tables.length - sectionLimit})`;
      dbTablesToggleButton.onclick = () => {
        setSectionExpanded("tables", !isSectionExpanded("tables"));
        renderAdminPage();
      };
    }
  }

  async function loadOwnerDatabaseTable() {
    const tableName = dbTableSelect?.value;
    if (!tableName) {
      setStatus(dbTableInfo, "No table selected.", dbOverview.tables.length ? "error" : "neutral");
      renderDatabaseTable(dbPreview, [], []);
      return;
    }
    try {
      const payload = await apiFetch(`/admin/database/table/${encodeURIComponent(tableName)}${buildOwnerQuery(user)}&limit=50`);
      setStatus(dbTableInfo, `Showing ${payload.rows.length} of ${payload.total_rows} rows from ${payload.table}.`, "success");
      renderDatabaseTable(dbPreview, payload.columns, payload.rows);
    } catch (error) {
      setStatus(dbTableInfo, error.message, "error");
      renderDatabaseTable(dbPreview, [], []);
    }
  }

  if (dbRefreshButton) dbRefreshButton.onclick = loadOwnerDatabaseTable;
  if (dbTableSelect) dbTableSelect.onchange = loadOwnerDatabaseTable;
  await loadOwnerDatabaseTable();

  if (dbQueryForm) dbQueryForm.onsubmit = async (event) => {
    event.preventDefault();
    try {
      const result = await apiFetch(`/admin/database/query${buildOwnerQuery(user)}`, {
        method: "POST",
        body: JSON.stringify({ sql: dbQueryInput?.value || "" })
      });
      setStatus(
        dbQueryStatus,
        result.columns.length
          ? `${result.operation} returned ${result.rows.length} rows.`
          : `${result.operation} affected ${result.affected_rows} rows.`,
        "success"
      );
      renderDatabaseTable(dbQueryResult, result.columns, result.rows);
      if (!result.columns.length && dbTableSelect?.value) {
        await loadOwnerDatabaseTable();
      }
    } catch (error) {
      setStatus(dbQueryStatus, error.message, "error");
      renderDatabaseTable(dbQueryResult, [], []);
    }
  };

  tableNode.querySelectorAll(".admin-edit").forEach((button) => {
    button.addEventListener("click", () => {
      const product = catalog.products.find((item) => item.id === Number(button.dataset.productId));
      if (!product) return;
      hiddenId.value = product.id;
      form.elements.name.value = product.name;
      form.elements.slug.value = product.slug;
      form.elements.category_id.value = product.category.id;
      form.elements.image.value = product.image;
      if (secondaryCategoriesSelect) {
        const selectedCategories = new Set(product.secondary_categories || []);
        Array.from(secondaryCategoriesSelect.options).forEach((option) => {
          option.selected = selectedCategories.has(option.value);
        });
      }
      if (imagePreview) {
        imagePreview.src = product.image;
        imagePreview.hidden = false;
      }
      form.elements.price.value = product.price;
      form.elements.original_price.value = product.original_price;
      form.elements.stock.value = product.stock;
      form.elements.tag.value = product.tag;
      form.elements.description.value = product.description;
      form.elements.highlights.value = product.highlights.join("|");
      form.elements.specifications.value = Object.entries(product.specifications).map(([k, v]) => `${k}=${v}`).join("|");
      form.elements.featured.checked = Boolean(product.featured);
      form.elements.deal_of_the_day.checked = Boolean(product.deal_of_the_day);
      setStatus(status, `Editing ${product.name}`, "neutral");
    });
  });
  tableNode.querySelectorAll(".owner-edit-product").forEach((button) => {
    button.addEventListener("click", () => {
      queueOwnerSql(
        `UPDATE products SET price = price WHERE id = ${Number(button.dataset.productId)};`,
        "Product update template loaded in the database editor."
      );
    });
  });
  tableNode.querySelectorAll(".admin-delete-product").forEach((button) => {
    button.addEventListener("click", async () => {
      const productId = Number(button.dataset.productId);
      try {
        const response = await apiFetch(`/admin/products/${productId}${buildOwnerQuery(user)}`, {
          method: "DELETE"
        });
        setStatus(status, response.message, "success");
        renderAdminPage();
      } catch (error) {
        setStatus(status, error.message, "error");
      }
    });
  });
  tableNode.querySelectorAll(".owner-stock-adjust").forEach((button) => {
    button.addEventListener("click", async () => {
      const productId = Number(button.dataset.productId);
      const currentStock = Number(button.dataset.stock);
      const delta = Number(button.dataset.stockChange);
      const nextStock = Math.max(0, currentStock + delta);
      try {
        await apiFetch(`/admin/products/${productId}${buildOwnerQuery(user)}`, {
          method: "PUT",
          body: JSON.stringify({ stock: nextStock })
        });
        setStatus(status, `Stock updated to ${nextStock}.`, "success");
        renderAdminPage();
      } catch (error) {
        setStatus(status, error.message, "error");
      }
    });
  });

  const ownerActionHandlers = {
    "edit-user": (value) => queueOwnerSql(`UPDATE users SET first_name = first_name WHERE id = ${Number(value)};`, "User update template loaded."),
    "inspect-user": (value) => queueOwnerSql(`SELECT * FROM users WHERE id = ${Number(value)};`, "User inspection query loaded."),
    "ban-user": async (value) => {
      const member = dashboard.users.find((item) => item.id === Number(value));
      if (!member || member.is_owner) {
        setStatus(status, "The owner account cannot be banned.", "error");
        return;
      }
      const reason = window.prompt(`Reason for banning ${member.full_name}?`, member.ban_reason || "Policy or trust violation.");
      if (reason === null) return;
      try {
        const response = await apiFetch(`/admin/users/${Number(value)}/ban${buildOwnerQuery(user)}`, {
          method: "POST",
          body: JSON.stringify({ reason })
        });
        setStatus(status, response.message, "success");
        renderAdminPage();
      } catch (error) {
        setStatus(status, error.message, "error");
      }
    },
    "unban-user": async (value) => {
      try {
        const response = await apiFetch(`/admin/users/${Number(value)}/unban${buildOwnerQuery(user)}`, {
          method: "POST"
        });
        setStatus(status, response.message, "success");
        renderAdminPage();
      } catch (error) {
        setStatus(status, error.message, "error");
      }
    },
    "delete-user": (value) => {
      const member = dashboard.users.find((item) => item.id === Number(value));
      if (member?.is_owner) {
        setStatus(status, "The owner account is locked and cannot be deleted.", "error");
        return;
      }
      queueOwnerSql(`DELETE FROM users WHERE id = ${Number(value)};`, "User delete query loaded.");
    },
    "edit-order": (value) => queueOwnerSql(`UPDATE orders SET status = status WHERE id = ${Number(value)};`, "Order update template loaded."),
    "inspect-order": (value) => queueOwnerSql(`SELECT * FROM orders WHERE id = ${Number(value)};`, "Order inspection query loaded."),
    "delete-order": (value) => queueOwnerSql(`DELETE FROM orders WHERE id = ${Number(value)};`, "Order delete query loaded."),
    "edit-review": (value) => queueOwnerSql(`UPDATE reviews SET comment = comment WHERE id = ${Number(value)};`, "Review update template loaded."),
    "inspect-review": (value) => queueOwnerSql(`SELECT * FROM reviews WHERE id = ${Number(value)};`, "Review inspection query loaded."),
    "delete-review": (value) => queueOwnerSql(`DELETE FROM reviews WHERE id = ${Number(value)};`, "Review delete query loaded."),
    "inspect-mobile": (value) => queueOwnerSql(`SELECT * FROM users WHERE mobile = '${String(value).replaceAll("'", "''")}';`, "Linked-account inspection query loaded."),
    "edit-mobile": (value) => queueOwnerSql(`UPDATE users SET mobile = mobile WHERE mobile = '${String(value).replaceAll("'", "''")}';`, "Linked-account update template loaded."),
    "inspect-chat": (value) => {
      const [userIdRaw, pageRaw] = String(value).split("::");
      const userId = Number(userIdRaw);
      const pageClause = pageRaw ? ` AND page = '${pageRaw.replaceAll("'", "''")}'` : "";
      const userClause = userId > 0 ? `user_id = ${userId}` : "user_id IS NULL";
      queueOwnerSql(`SELECT * FROM chat_messages WHERE ${userClause}${pageClause} ORDER BY created_at DESC LIMIT 50;`, "Chat log query loaded.");
    },
    "delete-chat": (value) => {
      const [userIdRaw, pageRaw] = String(value).split("::");
      const userId = Number(userIdRaw);
      const pageClause = pageRaw ? ` AND page = '${pageRaw.replaceAll("'", "''")}'` : "";
      const userClause = userId > 0 ? `user_id = ${userId}` : "user_id IS NULL";
      queueOwnerSql(`DELETE FROM chat_messages WHERE ${userClause}${pageClause};`, "Chat delete query loaded.");
    },
    "preview-table": async (value) => {
      if (dbTableSelect) dbTableSelect.value = value;
      await loadOwnerDatabaseTable();
      dbPreview?.scrollIntoView({ behavior: "smooth", block: "center" });
    },
    "edit-table": (value) => queueOwnerSql(`SELECT * FROM ${value} LIMIT 20;`, "Table query loaded in the database editor."),
    "inspect-category": (value) => queueOwnerSql(`SELECT products.id, products.name, products.price, products.stock FROM products JOIN categories ON categories.id = products.category_id WHERE categories.name = '${String(value).replaceAll("'", "''")}' LIMIT 50;`, "Category inspection query loaded.")
  };
  bindOwnerActionButtons(usersNode, ownerActionHandlers);
  bindOwnerActionButtons(ordersNode, ownerActionHandlers);
  bindOwnerActionButtons(reviewsNode, ownerActionHandlers);
  bindOwnerActionButtons(linkedAccountsNode, ownerActionHandlers);
  bindOwnerActionButtons(changesNode, ownerActionHandlers);
  bindOwnerActionButtons(bankOffersNode, ownerActionHandlers);
  bindOwnerActionButtons(dbTablesNode, ownerActionHandlers);
  bindOwnerActionButtons(categoryPerformanceNode, ownerActionHandlers);
  bindOwnerActionButtons(chatsNode, ownerActionHandlers);

  bindDisclosureButton("adminFinanceDisclosure", "adminFinancePanel", "finance");
  bindDisclosureButton("adminCategoryDisclosure", "adminCategoryPanel", "category");
  bindDisclosureButton("adminBankOffersDisclosure", "adminBankOffersPanel", "bankOffers");
  bindDisclosureButton("adminProductsDisclosure", "adminProductsPanel", "products");
  bindDisclosureButton("adminUsersDisclosure", "adminUsersPanel", "users");
  bindDisclosureButton("adminCodesDisclosure", "adminCodesPanel", "codes");
  bindDisclosureButton("adminOrdersDisclosure", "adminOrdersPanel", "orders");
  bindDisclosureButton("adminReviewsDisclosure", "adminReviewsPanel", "reviews");
  bindDisclosureButton("adminLinkedDisclosure", "adminLinkedPanel", "linked");
  bindDisclosureButton("adminChangesDisclosure", "adminChangesPanel", "changes");
  bindDisclosureButton("adminChatsDisclosure", "adminChatsPanel", "chats");
  bindDisclosureButton("adminDatabaseDisclosure", "adminDatabasePanel", "database");

  if (imageInput) {
    imageInput.oninput = () => {
      const value = imageInput.value.trim();
      if (!imagePreview) return;
      if (!value) {
        imagePreview.hidden = true;
        imagePreview.removeAttribute("src");
        return;
      }
      imagePreview.src = value;
      imagePreview.hidden = false;
    };
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    data.featured = form.elements.featured.checked;
    data.deal_of_the_day = form.elements.deal_of_the_day.checked;
    data.secondary_categories = secondaryCategoriesSelect
      ? Array.from(secondaryCategoriesSelect.selectedOptions).map((option) => option.value)
      : [];

    try {
      if (hiddenId.value) {
        await apiFetch(`/admin/products/${hiddenId.value}${buildOwnerQuery(user)}`, {
          method: "PUT",
          body: JSON.stringify(data)
        });
        setStatus(status, "Product updated successfully.", "success");
      } else {
        await apiFetch(`/admin/products${buildOwnerQuery(user)}`, {
          method: "POST",
          body: JSON.stringify(data)
        });
        setStatus(status, "Product created successfully.", "success");
      }
      form.reset();
      hiddenId.value = "";
      if (secondaryCategoriesSelect) {
        Array.from(secondaryCategoriesSelect.options).forEach((option) => {
          option.selected = false;
        });
      }
      if (imagePreview) {
        imagePreview.hidden = true;
        imagePreview.removeAttribute("src");
      }
      renderAdminPage();
    } catch (error) {
      setStatus(status, error.message, "error");
    }
  }, { once: true });
}

document.addEventListener("DOMContentLoaded", async () => {
  decorateSharedFooters();
  updateCartCount();
  syncUserUi();
  initChatbotWidget();

  const page = document.body.dataset.page;
  if (!guardProtectedPage(page)) return;
  try {
    if (page === "home") await renderHomePage();
    if (page === "product") await renderProductPage();
    if (page === "cart") await renderCartPage();
    if (page === "payment") await renderPaymentPage();
    if (page === "register") await handleRegistration();
    if (page === "login") await handleLogin();
    if (page === "account") await renderAccountPage();
    if (page === "merchant") await renderMerchantPage();
    if (page === "orders") await renderOrdersPage();
    if (page === "wishlist") await renderWishlistPage();
    if (page === "admin") await renderAdminPage();
  } catch (error) {
    const statusNode = getPageStatusNode(page);
    setStatus(statusNode, error.message, "error");
  }
});
