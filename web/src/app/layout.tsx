import type { Metadata } from "next";
import { IBM_Plex_Mono, Manrope } from "next/font/google";
import "./globals.css";

// Manrope: a round geometric sans for big calm headlines and readable body text. Plex Mono for addresses and hashes.
const display = Manrope({ variable: "--font-display", subsets: ["latin"], weight: ["600", "700", "800"] });
const body = Manrope({ variable: "--font-body", subsets: ["latin"], weight: ["400", "500", "600", "700"] });
const mono = IBM_Plex_Mono({ variable: "--font-mono", subsets: ["latin"], weight: ["400", "500"] });

export const metadata: Metadata = {
  title: "Hound",
  description: "Follow a scam victim's money to where it sits, and find everyone else still paying.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" data-scroll-behavior="smooth" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
