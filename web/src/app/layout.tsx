import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";

// IBM Plex Sans for everything: a plain, engineered face that reads as a security product, not a crypto app.
// Plex Mono (same family) for addresses and hashes, so evidence and interface look like one system.
const display = IBM_Plex_Sans({ variable: "--font-display", subsets: ["latin"], weight: ["600", "700"] });
const body = IBM_Plex_Sans({ variable: "--font-body", subsets: ["latin"], weight: ["400", "500", "600", "700"] });
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
