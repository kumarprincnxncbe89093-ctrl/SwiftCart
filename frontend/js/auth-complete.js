(function () {
  const params = new URLSearchParams(window.location.search);
  const token = String(params.get("token") || "").trim();
  const encodedUser = String(params.get("user") || "").trim();
  const redirectTarget = String(params.get("redirect") || "/").trim() || "/";
  const error = String(params.get("error") || "").trim();

  const normalizeBase64 = (value) => {
    const remainder = value.length % 4;
    return remainder ? `${value}${"=".repeat(4 - remainder)}` : value;
  };

  try {
    if (token && encodedUser) {
      const user = JSON.parse(atob(normalizeBase64(encodedUser).replaceAll("-", "+").replaceAll("_", "/")));
      user.auth_token = token;
      localStorage.setItem("swiftcart-token", token);
      localStorage.setItem("swiftcart-user", JSON.stringify(user));
      window.location.replace(redirectTarget.startsWith("/") ? redirectTarget : "/");
      return;
    }
  } catch (_error) {
    // Fall through to the login page when the bridge payload is invalid.
  }

  const next = error
    ? `/login?error=${encodeURIComponent(error)}`
    : "/login?error=We%20could%20not%20complete%20your%20login.%20Please%20try%20again.";
  window.location.replace(next);
})();
