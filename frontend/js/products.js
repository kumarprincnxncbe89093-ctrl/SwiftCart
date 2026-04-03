const RAILWAY_API_ORIGIN = "https://web-production-00035.up.railway.app";
const API_BASE = new URL(
  "/api",
  window.location.protocol === "file:" ? RAILWAY_API_ORIGIN : window.location.origin
).toString().replace(/\/$/, "");
const STORAGE_KEYS = {
  cart: "swiftcart-cart",
  user: "swiftcart-user",
  token: "swiftcart-token"
};

const EXTRA_SHOWCASE_IMAGES = [
  "images/51+CE3ghnzL._AC_SY400_.jpg",
  "images/512JQ+6XadL._AC_SY400_.jpg",
  "images/51CJ3LiSy1L._AC_UL640_QL65_.jpg",
  "images/51VvhX76PjL._AC_UL640_QL65_.jpg",
  "images/61AAr-lfB9L._AC_UL640_QL65_.jpg",
  "images/61QZbqAUvKL._AC_UL640_QL65_.jpg",
  "images/61VW43-uP4L._AC_UL640_QL65_.jpg",
  "images/61hxYIGjEKL._AC_UL640_QL65_.jpg",
  "images/61isZzWRP5L._AC_UL640_QL65_.jpg",
  "images/71+CsirvJ2L._AC_SY400_.jpg",
  "images/711DIM8DgKL._AC_SY400_.jpg",
  "images/715OgXyABFL._AC_UL640_QL65_.jpg",
  "images/71E8rpjp2TL._AC_UL640_QL65_.jpg",
  "images/71SiaxOfrxL._AC_UL640_QL65_.jpg",
  "images/71cXQm1s52L._AC_UL640_QL65_.jpg",
  "images/71eX66ytH+L._AC_UY436_QL65_.jpg",
  "images/81Qs8j6kD2L._AC_SY400_.jpg",
  "images/81hauo1yiwL._AC_UL640_QL65_.jpg",
  "images/91KpYmTpylL._AC_SY400_.jpg"
];

function formatPrice(value) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0
  }).format(Number(value) || 0);
}

function getStoredUser() {
  return JSON.parse(localStorage.getItem(STORAGE_KEYS.user) || "null");
}

function saveStoredUser(user, token = "") {
  if (!user) {
    localStorage.removeItem(STORAGE_KEYS.user);
    localStorage.removeItem(STORAGE_KEYS.token);
    return;
  }
  const existingUser = getStoredUser();
  const normalizedToken = String(token || user.auth_token || localStorage.getItem(STORAGE_KEYS.token) || "").trim();
  const normalizedUser = {
    ...(existingUser?.auth_token && !user.auth_token ? { auth_token: existingUser.auth_token } : {}),
    ...user,
  };
  if (normalizedToken) {
    normalizedUser.auth_token = normalizedToken;
    localStorage.setItem(STORAGE_KEYS.token, normalizedToken);
  }
  localStorage.setItem(STORAGE_KEYS.user, JSON.stringify(normalizedUser));
}

function getAuthToken() {
  return String(localStorage.getItem(STORAGE_KEYS.token) || getStoredUser()?.auth_token || "").trim();
}

function getLoginPagePath() {
  return "/login";
}

function getCart() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEYS.cart) || "[]");
    return Array.isArray(raw)
      ? raw
          .map((item) => ({
            product_id: Number(item.product_id),
            quantity: Math.max(1, Number(item.quantity) || 1)
          }))
          .filter((item) => Number.isFinite(item.product_id) && item.product_id > 0)
      : [];
  } catch {
    return [];
  }
}

function saveCart(cart) {
  const normalized = Array.isArray(cart)
    ? cart
        .map((item) => ({
          product_id: Number(item.product_id),
          quantity: Math.max(1, Number(item.quantity) || 1)
        }))
        .filter((item) => Number.isFinite(item.product_id) && item.product_id > 0)
    : [];
  localStorage.setItem(STORAGE_KEYS.cart, JSON.stringify(normalized));
}

function redirectToPage(path) {
  window.location.replace(path);
}

function logoutCurrentUser() {
  const currentUser = getStoredUser();
  if (currentUser?.id) {
    sessionStorage.removeItem(`swiftcart-chat-history:${currentUser.id}`);
    sessionStorage.removeItem(`swiftcart-chat-closed-at:${currentUser.id}`);
  }
  document.querySelector(".chatbot-shell")?.remove();
  saveStoredUser(null);
  sessionStorage.setItem("swiftcart-last-logout", String(Date.now()));
  redirectToPage(getLoginPagePath());
}

function setAuthFlashMessage(message) {
  if (!message) return;
  sessionStorage.setItem("swiftcart-auth-message", String(message));
}

function consumeAuthFlashMessage() {
  const message = sessionStorage.getItem("swiftcart-auth-message") || "";
  if (message) {
    sessionStorage.removeItem("swiftcart-auth-message");
  }
  return message;
}

function updateCartItemQuantity(productId, quantity) {
  const cart = getCart();
  const item = cart.find((entry) => entry.product_id === productId);
  if (!item) return;
  item.quantity = quantity;
  const nextCart = cart.filter((entry) => entry.quantity > 0);
  saveCart(nextCart);
}

function removeCartItem(productId) {
  const cart = getCart().filter((entry) => entry.product_id !== productId);
  saveCart(cart);
}

async function apiFetch(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const authToken = getAuthToken();
  const storedUser = getStoredUser();
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...(options.headers || {})
    },
    ...options
  });

  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }

  if (!response.ok) {
    if (response.status === 401 && (authToken || storedUser?.id)) {
      setAuthFlashMessage(data?.message || "Your session has expired. Please login again.");
      saveStoredUser(null);
      if (!window.location.pathname.toLowerCase().endsWith("/login") && !window.location.pathname.toLowerCase().endsWith("login.html")) {
        redirectToPage(getLoginPagePath());
      }
    }
    if (data?.force_logout) {
      setAuthFlashMessage(data?.message || "Your session is no longer active.");
      saveStoredUser(null);
      if (!window.location.pathname.toLowerCase().endsWith("/login") && !window.location.pathname.toLowerCase().endsWith("login.html")) {
        redirectToPage(getLoginPagePath());
      }
    }
    throw new Error(data?.message || "Request failed");
  }

  return data;
}
