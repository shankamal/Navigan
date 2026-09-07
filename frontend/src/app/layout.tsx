import type { Metadata } from "next";
import "@fontsource/open-sans/400.css";
import "@fontsource/open-sans/600.css";
import "@fontsource/open-sans/700.css";
import "./globals.css";
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
