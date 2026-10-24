import type { Metadata } from "next";
import { IBM_Plex_Mono, Public_Sans } from "next/font/google";
import "./globals.css";

// Public Sans: the U.S. Web Design System typeface. Hound's output is evidence for law enforcement and exchanges, so it
// speaks in the register those readers already trust. Plex Mono only for addresses and hashes (real code-like data).
const display = Public_Sans({ variable: "--font-display", subsets: ["latin"], weight: ["600", "700", "800"] });
const body = Public_Sans({ variable: "--font-body", subsets: ["latin"], weight: ["400", "500", "600", "700"] });
const mono = IBM_Plex_Mono({ variable: "--font-mono", subsets: ["latin"], weight: ["400", "500"] });

export const metadata: Metadata = {
  title: "Hound",
  description: "Follow a scam victim's money to where it sits, and find everyone else still paying.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
