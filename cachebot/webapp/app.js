(() => {
  const tg = window.Telegram?.WebApp;
  const logEl = document.getElementById("log");
  const statDeals = document.getElementById("statDeals");
  const statBalance = document.getElementById("statBalance");
  const statStatus = document.getElementById("statStatus");
  const userBadge = document.getElementById("userBadge");
  const themeToggle = document.getElementById("themeToggle");
  const checkAuthBtn = document.getElementById("checkAuth");
  const openMenuBtn = document.getElementById("openMenu");

  const state = {
    user: null,
    initData: "",
  };

  const log = (message, type = "info") => {
    if (!logEl) return;
    const line = document.createElement("div");
    line.className = `log-line ${type}`;
    line.textContent = message;
    logEl.prepend(line);
  };

  const applyTheme = (theme) => {
    document.documentElement.dataset.theme = theme;
    if (tg) {
      try {
        tg.setHeaderColor(theme === "dark" ? "#0e0f13" : "#f6f3ee");
        tg.setBackgroundColor(theme === "dark" ? "#0e0f13" : "#f6f3ee");
      } catch (err) {
        // Ignore if WebApp methods are unavailable.
      }
    }
  };

  const detectTheme = () => {
    if (tg?.colorScheme) return tg.colorScheme;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  };

  const setAuthState = (user) => {
    state.user = user;
    if (user?.username) {
      userBadge.textContent = `@${user.username}`;
    } else if (user?.first_name) {
      userBadge.textContent = user.first_name;
    } else {
      userBadge.textContent = "Гость";
    }
    statStatus.textContent = user ? "Готов" : "Ожидание";
  };

  const fetchMe = async () => {
    if (!state.initData) {
      log("initData не найден. Откройте WebApp из Telegram.", "error");
      return null;
    }
    try {
      const res = await fetch("/api/me", {
        method: "GET",
        headers: {
          "X-Telegram-Init-Data": state.initData,
        },
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const payload = await res.json();
      return payload.user || null;
    } catch (err) {
      log(`Ошибка авторизации: ${err.message}`, "error");
      return null;
    }
  };

  const initTelegram = async () => {
    if (tg) {
      tg.ready();
      tg.expand();
      state.initData = tg.initData || "";
      applyTheme(detectTheme());
    } else {
      applyTheme(detectTheme());
      log("WebApp API не найден. Проверьте запуск через Telegram.", "warn");
    }
    setAuthState(null);
  };

  themeToggle?.addEventListener("click", () => {
    const current = document.documentElement.dataset.theme || "light";
    applyTheme(current === "light" ? "dark" : "light");
  });

  checkAuthBtn?.addEventListener("click", async () => {
    log("Проверяем авторизацию...");
    const user = await fetchMe();
    if (user) {
      setAuthState(user);
      log(`Готово. Пользователь: ${user.username || user.first_name || user.id}`);
    }
  });

  openMenuBtn?.addEventListener("click", () => {
    log("Разделы мини‑аппа будут здесь. Подключаем API.");
  });

  initTelegram();
})();
