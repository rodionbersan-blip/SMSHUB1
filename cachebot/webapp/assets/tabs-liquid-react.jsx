import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import LiquidGlass from "liquid-glass-react";

function TabsLiquidMenu() {
  const navRef = useRef(null);
  const [glassSize, setGlassSize] = useState({ width: 920, height: 182 });

  useLayoutEffect(() => {
    const syncSize = () => {
      const node = navRef.current;
      if (!node) return;
      const rect = node.getBoundingClientRect();
      const width = Math.max(280, Math.round(rect.width));
      const height = Math.max(120, Math.round(rect.height));
      setGlassSize((prev) => {
        if (prev.width === width && prev.height === height) return prev;
        return { width, height };
      });
    };

    syncSize();
    const node = navRef.current;
    if (!node) return;

    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(syncSize) : null;
    observer?.observe(node);
    window.addEventListener("resize", syncSize);

    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", syncSize);
    };
  }, []);

  useEffect(() => {
    document.documentElement.classList.add("tabs-liquid-react-enabled");
    return () => document.documentElement.classList.remove("tabs-liquid-react-enabled");
  }, []);

  return (
    <LiquidGlass
      mode="shader"
      displacementScale={70}
      blurAmount={0.08}
      saturation={135}
      aberrationIntensity={2}
      elasticity={0.2}
      cornerRadius={28}
      padding="6px 10px"
      glassSize={glassSize}
      className="tabs-liquid-shell"
      style={{ width: "100%" }}
    >
      <nav ref={navRef} className="tabs tabs--liquid-react">
        <button className="tab nav-btn with-icon" data-view="p2p" type="button">
          <span className="nav-icon">
            <img src="/app/assets/p2p-icon.png" alt="" />
          </span>
          P2P
        </button>
        <button className="tab nav-btn with-icon" data-view="deals" type="button">
          <span className="nav-icon">
            <img src="/app/assets/deals-icon.png" alt="" />
          </span>
          Сделки
        </button>
        <button className="tab nav-btn with-icon" data-view="support" type="button">
          <span className="nav-icon">
            <img className="support-nav-icon" src="/app/assets/support-icon-request.png?v=1" alt="" />
          </span>
          Помощь
        </button>
        <span className="tabs-break" aria-hidden="true"></span>
        <button className="tab nav-btn with-icon" data-view="disputes" id="disputesTab" type="button">
          <span className="nav-icon">
            <img src="/app/assets/moderation-icon.png?v=1" alt="" />
          </span>
          Модерация
        </button>
        <button className="tab nav-btn with-icon" data-view="admin" id="adminTab" type="button">
          <span className="nav-icon">
            <img className="admin-nav-icon" src="/app/assets/admin-icon-request.png?v=1" alt="" />
          </span>
          Админ
        </button>
        <button
          className="tab nav-btn with-icon merchant-sell-nav"
          data-view="merchant-sell"
          id="merchantSellNav"
          type="button"
        >
          <span className="nav-icon">
            <img src="/app/assets/p2p-icon.png" alt="" />
          </span>
          <span className="nav-label">Продать Мерчанту</span>
        </button>
      </nav>
    </LiquidGlass>
  );
}

(function mountTabsLiquidReact() {
  const mountNode = document.getElementById("tabsReactMount");
  if (!mountNode) return;
  try {
    const root = createRoot(mountNode);
    flushSync(() => {
      root.render(<TabsLiquidMenu />);
    });
  } catch (error) {
    console.error("tabs-liquid-react mount failed", error);
  }
})();
