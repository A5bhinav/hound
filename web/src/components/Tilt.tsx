"use client";

import { useEffect, useRef } from "react";

/** Leans its child a few degrees toward the cursor, eased, so the hero feels alive. Still for reduced motion
 *  and for touch screens (no hover). Writes --tx / --ty (-1..1) that the CSS turns into rotation. */
export default function Tilt({ className, children }: { className?: string; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !window.matchMedia("(hover: hover)").matches) return;
    let goal = { x: 0, y: 0 };
    const now = { x: 0, y: 0 };
    let frame = 0;
    const step = () => {
      now.x += (goal.x - now.x) * 0.08;
      now.y += (goal.y - now.y) * 0.08;
      el.style.setProperty("--tx", now.x.toFixed(4));
      el.style.setProperty("--ty", now.y.toFixed(4));
      frame = Math.abs(goal.x - now.x) + Math.abs(goal.y - now.y) > 0.001 ? requestAnimationFrame(step) : 0;
    };
    const kick = () => {
      if (!frame) frame = requestAnimationFrame(step);
    };
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      goal = {
        x: Math.max(-1, Math.min(1, (e.clientX - cx) / (window.innerWidth / 2))),
        y: Math.max(-1, Math.min(1, (e.clientY - cy) / (window.innerHeight / 2))),
      };
      kick();
    };
    const leave = () => {
      goal = { x: 0, y: 0 };
      kick();
    };
    window.addEventListener("pointermove", move, { passive: true });
    document.addEventListener("pointerleave", leave);
    return () => {
      window.removeEventListener("pointermove", move);
      document.removeEventListener("pointerleave", leave);
      cancelAnimationFrame(frame);
    };
  }, []);
  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}
