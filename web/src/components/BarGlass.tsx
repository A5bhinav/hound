"use client";

import { useEffect } from "react";

/** The top bar is see-through at the top of the page (like the hero design) and gets a dark glass
 *  backing once content scrolls under it. */
export default function BarGlass() {
  useEffect(() => {
    const bar = document.querySelector<HTMLElement>(".bar");
    if (!bar) return;
    const set = () => {
      if (window.scrollY > 8) bar.dataset.stuck = "";
      else delete bar.dataset.stuck;
    };
    set();
    window.addEventListener("scroll", set, { passive: true });
    return () => window.removeEventListener("scroll", set);
  }, []);
  return null;
}
