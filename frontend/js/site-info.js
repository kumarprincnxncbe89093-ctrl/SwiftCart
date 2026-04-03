document.addEventListener("DOMContentLoaded", async () => {
  const setText = (selector, value) => {
    if (!value) return;
    document.querySelectorAll(selector).forEach((node) => {
      node.textContent = value;
    });
  };

  const setLink = (wrapSelector, linkSelector, value, prefix) => {
    const wrapNodes = document.querySelectorAll(wrapSelector);
    const linkNodes = document.querySelectorAll(linkSelector);
    if (!wrapNodes.length && !linkNodes.length) return Boolean(value);
    if (!value) {
      wrapNodes.forEach((node) => {
        node.hidden = true;
      });
      return false;
    }
    linkNodes.forEach((node) => {
      node.textContent = value;
      node.href = `${prefix}${value}`;
    });
    wrapNodes.forEach((node) => {
      node.hidden = false;
    });
    return true;
  };

  try {
    const response = await fetch("/api/site-profile", {
      headers: { Accept: "application/json" }
    });
    if (!response.ok) return;

    const profile = await response.json();
    setText("[data-site-legal-name]", profile.legal_name || "SwiftCart");
    setText("[data-site-business-address]", profile.business_address || "Bengaluru, Karnataka, India");
    setText("[data-site-support-hours]", profile.support_hours || "Monday to Saturday, 10:00 AM to 6:00 PM IST");

    const hasEmail = setLink(
      "[data-site-support-email-wrap]",
      "[data-site-support-email-link]",
      String(profile.support_email || "").trim(),
      "mailto:"
    );
    const hasPhone = setLink(
      "[data-site-support-phone-wrap]",
      "[data-site-support-phone-link]",
      String(profile.support_phone || "").trim(),
      "tel:"
    );

    if (hasEmail || hasPhone) {
      document.querySelectorAll("[data-site-contact-fallback]").forEach((node) => {
        node.hidden = true;
      });
    }
  } catch (_error) {
    // Public trust pages should still render even if site profile data is unavailable.
  }
});
