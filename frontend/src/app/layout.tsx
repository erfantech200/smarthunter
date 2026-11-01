import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Trade Desk",
  description: "Private FX & commodities research desk",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#0a0a0a", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-dvh flex flex-col">
        <main className="flex-1 mx-auto w-full max-w-5xl p-4">{children}</main>
        <footer className="border-t border-neutral-800 p-3 text-center text-xs text-neutral-500">
          Decision support only. Not financial advice.
        </footer>
      </body>
    </html>
  );
}
