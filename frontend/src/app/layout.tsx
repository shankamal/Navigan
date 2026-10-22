import type { Metadata } from "next";
import "@fontsource/geist-sans/400.css";
import "@fontsource/geist-sans/500.css";
import "@fontsource/geist-sans/600.css";
import "@fontsource/geist-sans/700.css";
import "./globals.css";
import "./navigan-theme.css";
import "./workspace-standards.css";
import { Providers } from "./providers";
export const metadata: Metadata = {
  title: {
    default: "Navigan | Container Management",
    template: "%s | Navigan",
  },
  description: "Multi-cloud customer onboarding and governance.",
  robots: { index: false, follow: false },
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

