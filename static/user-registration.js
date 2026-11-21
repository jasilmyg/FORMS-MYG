(function () {
  "use strict";

  var API_URL = "/api/user-registration";
  var CHECK_MOBILE_URL = "/api/user-registration/check-mobile";
  var form = document.getElementById("regForm");
  var submitBtn = document.getElementById("submitBtn");
  var hint = document.getElementById("submitHint");
  var formAlert = document.getElementById("formAlert");
  var formView = document.getElementById("formView");
  var successView = document.getElementById("successView");

  var MOBILE_RE = /^[6-9]\d{9}$/;
  var NAME_RE = /^[A-Za-z][A-Za-z .'\-]{1,99}$/;
  var PLACE_RE = /^[A-Za-z0-9][A-Za-z0-9 .,'\-\/()]{1,99}$/;
  var GENDERS = ["Male", "Female", "Other", "Prefer not to say"];

  var els = {
    fullName: document.getElementById("fullName"),
    mobile: document.getElementById("mobile"),
    gender: document.getElementById("gender"),
    age: document.getElementById("age"),
    place: document.getElementById("place"),
    terms: document.getElementById("terms")
  };

  var touched = {};
  var submitting = false;
  var duplicateMobiles = {};
  var mobileCheckTimer = null;
  var mobileCheckController = null;

  /* ── validators: return an error string, or "" when valid ── */
  var validators = {
    fullName: function (v) {
      v = v.replace(/\s+/g, " ").trim();
      if (!v) return "Full name is required.";
      if (!NAME_RE.test(v)) return "Enter a valid name (letters only, 2-100 characters).";
      return "";
    },
    mobile: function (v) {
      if (!v) return "Mobile number is required.";
      if (!/^\d+$/.test(v)) return "Mobile number can contain digits only.";
      if (v.length !== 10) return "Mobile number must be exactly 10 digits.";
      if (!MOBILE_RE.test(v)) return "Enter a valid mobile number starting with 6, 7, 8 or 9.";
      if (duplicateMobiles[v]) return "This mobile number is already registered.";
      return "";
    },
    gender: function (v) {
      if (!v) return "Please select your gender.";
      if (GENDERS.indexOf(v) === -1) return "Please select a valid option.";
      return "";
    },
    age: function (v) {
      v = String(v).trim();
      if (!v) return "Age is required.";
      if (!/^\d{1,3}$/.test(v)) return "Enter a valid whole number for age.";
      var n = parseInt(v, 10);
      if (n < 1 || n > 120) return "Age must be between 1 and 120.";
      return "";
    },
    place: function (v) {
      v = v.replace(/\s+/g, " ").trim();
      if (!v) return "Place is required.";
      if (!PLACE_RE.test(v)) return "Enter a valid place (2-100 characters).";
      return "";
    },
    terms: function (checked) {
      return checked ? "" : "You must accept the Terms and Conditions and Privacy Policy.";
    }
  };

  function valueOf(name) {
    return name === "terms" ? els.terms.checked : els[name].value;
  }

  function setFieldState(name, message) {
    var wrap = form.querySelector('[data-field="' + name + '"]');
    var errEl = document.getElementById(name + "-error");
    var input = els[name];
    if (message) {
      wrap.classList.add("invalid");
      wrap.classList.remove("valid");
      errEl.textContent = message;
      input.setAttribute("aria-invalid", "true");
    } else {
      wrap.classList.remove("invalid");
      if (name !== "terms" && valueOf(name)) wrap.classList.add("valid");
      errEl.textContent = "";
      input.removeAttribute("aria-invalid");
    }
  }

  function checkField(name, show) {
    var msg = validators[name](valueOf(name));
    if (show) setFieldState(name, msg);
    return !msg;
  }

  function isFormValid(show) {
    var ok = true;
    Object.keys(els).forEach(function (n) {
      if (!checkField(n, show || touched[n])) ok = false;
    });
    return ok;
  }

  function refreshButton() {
    var ok = Object.keys(els).every(function (n) { return !validators[n](valueOf(n)); });
    submitBtn.disabled = !ok || submitting;
    hint.classList.toggle("hide", ok);
  }

  /* ── input restrictions ── */
  els.mobile.addEventListener("input", function () {
    var v = els.mobile.value.replace(/[\s\-]/g, "");
    // allow pasting +91XXXXXXXXXX / 91XXXXXXXXXX / 0XXXXXXXXXX
    if (/^\+91\d{10}$/.test(v)) v = v.slice(3);
    else if (/^91\d{10}$/.test(v)) v = v.slice(2);
    else if (/^0\d{10}$/.test(v)) v = v.slice(1);
    els.mobile.value = v.replace(/\D/g, "").slice(0, 10);
  });

  els.age.addEventListener("keydown", function (e) {
    if (["e", "E", "+", "-", ".", ","].indexOf(e.key) !== -1) e.preventDefault();
  });
  els.age.addEventListener("input", function () {
    var v = els.age.value.replace(/\D/g, "").slice(0, 3);
    if (els.age.value !== v) els.age.value = v;
  });

  /* ── live duplicate mobile check ── */
  function scheduleMobileCheck(mobile) {
    clearTimeout(mobileCheckTimer);
    if (mobileCheckController) {
      mobileCheckController.abort();
      mobileCheckController = null;
    }
    if (!MOBILE_RE.test(mobile) || duplicateMobiles[mobile]) return;

    mobileCheckTimer = setTimeout(function () {
      mobileCheckController = new AbortController();
      fetch(CHECK_MOBILE_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ mobile: mobile }),
        signal: mobileCheckController.signal
      })
        .then(function (res) { return res.ok ? res.json() : {}; })
        .then(function (body) {
          if (body && body.exists) {
            duplicateMobiles[mobile] = true;
            if (els.mobile.value === mobile) {
              touched.mobile = true;
              setFieldState("mobile", body.message || "This mobile number is already registered.");
              refreshButton();
            }
          }
        })
        .catch(function () { /* ignore abort/network hiccups; server still enforces on submit */ });
    }, 250);
  }

  /* ── live validation ── */
  Object.keys(els).forEach(function (name) {
    function onEdit() {
      touched[name] = true;
      checkField(name, true);
      hideAlert();
      refreshButton();
      if (name === "mobile") scheduleMobileCheck(els.mobile.value);
    }
    if (name === "gender" || name === "terms") {
      els[name].addEventListener("change", onEdit);
    } else {
      els[name].addEventListener("input", onEdit);
      els[name].addEventListener("change", onEdit);
    }
    els[name].addEventListener("blur", function () {
      touched[name] = true;
      checkField(name, true);
      refreshButton();
      if (name === "mobile") scheduleMobileCheck(els.mobile.value);
    });
  });

  /* ── UI helpers ── */
  var toastTimer;
  function toast(msg, type) {
    var t = document.getElementById("toast");
    t.textContent = msg;
    t.className = "toast show " + (type || "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.className = "toast"; }, 4500);
  }

  function showAlert(msg) {
    formAlert.textContent = msg;
    formAlert.hidden = false;
  }
  function hideAlert() { formAlert.hidden = true; }

  function setLoading(on) {
    submitting = on;
    submitBtn.classList.toggle("loading", on);
    submitBtn.querySelector(".btn-label").textContent = on ? "Submitting…" : "Submit";
    submitBtn.setAttribute("aria-busy", on ? "true" : "false");
    Object.keys(els).forEach(function (n) { els[n].disabled = on; });
    refreshButton();
  }

  /* ── submit ── */
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (submitting) return;                      // prevent double submissions
    hideAlert();

    if (!isFormValid(true)) {
      var firstBad = form.querySelector(".invalid input, .invalid select");
      if (firstBad) firstBad.focus();
      return;
    }

    var payload = {
      fullName: els.fullName.value.replace(/\s+/g, " ").trim(),
      mobile: els.mobile.value,
      gender: els.gender.value,
      age: els.age.value.trim(),
      place: els.place.value.replace(/\s+/g, " ").trim(),
      terms: els.terms.checked,
      website: document.getElementById("website").value   // honeypot
    };

    setLoading(true);

    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 20000);

    fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          return { status: res.status, ok: res.ok, body: body };
        });
      })
      .then(function (r) {
        if (r.ok && r.body.success) {
          duplicateMobiles[payload.mobile] = true;
          showSuccess(r.body);
          return;
        }
        if (r.status === 409) {
          duplicateMobiles[payload.mobile] = true;
        }
        setLoading(false);
        if (r.body && r.body.errors) {
          Object.keys(r.body.errors).forEach(function (k) {
            if (els[k]) { touched[k] = true; setFieldState(k, r.body.errors[k]); }
          });
          var bad = form.querySelector(".invalid input, .invalid select");
          if (bad) bad.focus();
        }
        refreshButton();
        var msg = (r.body && r.body.message) || "Something went wrong. Please try again.";
        showAlert(msg);
        toast(msg, "error");
      })
      .catch(function (err) {
        setLoading(false);
        var msg = err && err.name === "AbortError"
          ? "The request timed out. Please check your connection and try again."
          : "Unable to reach the server. Please check your connection and try again.";
        showAlert(msg);
        toast(msg, "error");
      })
      .then(function () { clearTimeout(timer); });
  });

  function showSuccess(body) {
    document.getElementById("successMsg").textContent = body.message || "Registration completed successfully.";
    formView.hidden = true;
    successView.hidden = false;
    successView.focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
    toast("Registration successful!", "ok");
  }

  document.getElementById("againBtn").addEventListener("click", function () {
    form.reset();
    touched = {};
    hideAlert();
    Object.keys(els).forEach(function (n) { setFieldState(n, ""); form.querySelector('[data-field="' + n + '"]').classList.remove("valid"); });
    setLoading(false);
    successView.hidden = true;
    formView.hidden = false;
    els.fullName.focus();
  });

  /* ── Terms / Privacy dialogs ── */
  document.querySelectorAll("[data-modal]").forEach(function (a) {
    a.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      var dlg = document.getElementById(a.getAttribute("data-modal"));
      if (dlg && dlg.showModal) dlg.showModal();
    });
  });
  document.querySelectorAll("dialog").forEach(function (dlg) {
    dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
    var close = dlg.querySelector("[data-close]");
    if (close) close.addEventListener("click", function () { dlg.close(); });
  });

  refreshButton();
})();
